#!/usr/bin/env python3

import argparse
import os
import sys
import tempfile
from pathlib import Path


def create_hardlink(link_path: Path, existing_path: Path):
    """
    Create a hard link.

    link_path     = new directory entry
    existing_path = existing file
    """
    os.link(existing_path, link_path)


def get_device(path: Path):
    """
    Return the filesystem device containing the path.

    Hard links can only be created within the same filesystem.
    """
    return path.stat().st_dev


def ensure_same_filesystem(path1: Path, path2: Path):
    """
    Verify that two paths are on the same filesystem/device.
    """
    if get_device(path1) != get_device(path2):
        raise RuntimeError(
            "\n"
            "N and O are on different filesystems.\n\n"
            f"N: {path1}\n"
            f"O: {path2}\n\n"
            "Hard links cannot cross filesystems.\n"
            "Put both directories on the same filesystem."
        )


def is_symlink(path: Path) -> bool:
    """
    Don't follow symbolic links.
    """
    return path.is_symlink()


def same_file(path1: Path, path2: Path) -> bool:
    """
    Check whether two paths refer to the same underlying file.
    """
    try:
        return os.path.samefile(path1, path2)
    except (FileNotFoundError, OSError):
        return False


def replace_with_hardlink(source: Path, destination: Path):
    """
    Replace destination with a hard link to source.

    A temporary hard link is created first so that we don't destroy
    the existing destination until the new hard link has succeeded.
    """

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Nothing to do if destination already points to the same file.
    if destination.exists() and same_file(source, destination):
        return False

    # Create temporary file in the destination directory.
    fd, temp_name = tempfile.mkstemp(
        prefix=".backup_link_",
        dir=destination.parent,
    )

    os.close(fd)

    temp_path = Path(temp_name)

    try:
        # mkstemp creates a real file. Remove it before creating
        # the hard link using the same filename.
        temp_path.unlink()

        # Create hard link.
        create_hardlink(
            temp_path,
            source,
        )

        # Replace destination with the new hard link.
        os.replace(
            temp_path,
            destination,
        )

        return True

    except Exception:

        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass

        raise


def merge_backup(
    new_backup: Path,
    old_backup: Path,
    dry_run: bool = False,
):
    new_backup = new_backup.resolve()
    old_backup = old_backup.resolve()

    print()
    print("=" * 70)
    print("BACKUP MERGE")
    print("=" * 70)

    print(f"New backup : {new_backup}")
    print(f"Mega backup: {old_backup}")
    print(f"Dry run    : {dry_run}")

    print("=" * 70)
    print()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    if not new_backup.exists():
        raise FileNotFoundError(
            f"New backup does not exist: {new_backup}"
        )

    if not new_backup.is_dir():
        raise NotADirectoryError(
            f"New backup is not a directory: {new_backup}"
        )

    if new_backup == old_backup:
        raise ValueError(
            "N and O cannot be the same directory."
        )

    # Create O if it doesn't exist.
    if not old_backup.exists():

        print(f"Creating: {old_backup}")

        if not dry_run:
            old_backup.mkdir(
                parents=True,
                exist_ok=True,
            )

    elif not old_backup.is_dir():

        raise NotADirectoryError(
            f"Old backup is not a directory: {old_backup}"
        )

    # Hard links require both directories to be on the same filesystem.
    if not dry_run:
        ensure_same_filesystem(
            new_backup,
            old_backup,
        )

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    new_files = 0
    updated_files = 0
    unchanged_files = 0
    skipped_symlinks = 0
    errors = 0

    # ------------------------------------------------------------------
    # Walk N
    # ------------------------------------------------------------------

    for root, dirs, files in os.walk(
        new_backup,
        topdown=True,
        followlinks=False,
    ):

        root_path = Path(root)

        # --------------------------------------------------------------
        # Don't traverse symlinked directories
        # --------------------------------------------------------------

        safe_dirs = []

        for dirname in dirs:

            directory = root_path / dirname

            if is_symlink(directory):

                print(f"[SKIP]    Symlink directory: {directory}")

                skipped_symlinks += 1

            else:

                safe_dirs.append(dirname)

        dirs[:] = safe_dirs

        # --------------------------------------------------------------
        # Process files
        # --------------------------------------------------------------

        for filename in files:

            source = root_path / filename

            # Don't process symlinked files.
            if is_symlink(source):

                print(f"[SKIP]    Symlink: {source}")

                skipped_symlinks += 1

                continue

            try:

                relative_path = source.relative_to(
                    new_backup
                )

                destination = (
                    old_backup / relative_path
                )

                # ======================================================
                # FILE DOES NOT EXIST IN O
                # ======================================================

                if not destination.exists():

                    print(
                        f"[NEW]     {relative_path}"
                    )

                    if not dry_run:

                        destination.parent.mkdir(
                            parents=True,
                            exist_ok=True,
                        )

                        create_hardlink(
                            destination,
                            source,
                        )

                    new_files += 1

                # ======================================================
                # FILE EXISTS IN O
                # ======================================================

                else:

                    # If O contains a directory where N contains
                    # a file, this is a conflict.
                    if destination.is_dir():

                        raise RuntimeError(
                            "Destination is a directory but "
                            f"source is a file: {destination}"
                        )

                    # Already points to same underlying file.
                    if same_file(
                        source,
                        destination,
                    ):

                        print(
                            f"[SAME]    {relative_path}"
                        )

                        unchanged_files += 1

                    # Different file -> replace with hardlink.
                    else:

                        print(
                            f"[UPDATE]  {relative_path}"
                        )

                        if not dry_run:

                            replace_with_hardlink(
                                source,
                                destination,
                            )

                        updated_files += 1

            except Exception as e:

                errors += 1

                print(
                    f"[ERROR]   {source}"
                )

                print(
                    f"          {e}"
                )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    print()
    print("=" * 70)
    print("MERGE COMPLETE")
    print("=" * 70)

    print(
        f"New files linked       : {new_files}"
    )

    print(
        f"Existing files updated : {updated_files}"
    )

    print(
        f"Already identical      : {unchanged_files}"
    )

    print(
        f"Skipped symlinks       : {skipped_symlinks}"
    )

    print(
        f"Errors                 : {errors}"
    )

    print()

    print(
        "Files existing only in O were left untouched."
    )

    print(
        "Nothing was deleted from N."
    )

    if dry_run:

        print()
        print(
            "DRY RUN: No changes were made."
        )

    if errors:

        print()
        print(
            "WARNING: Errors occurred."
        )

        print(
            "Do NOT delete N until the errors are resolved."
        )

    print(
        "=" * 70
    )

    print()


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Merge a new backup into a mega backup "
            "using hard links."
        )
    )

    parser.add_argument(
        "new_backup",
        help="New backup directory (N)",
    )

    parser.add_argument(
        "old_backup",
        help="Mega/old backup directory (O)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show what would happen without "
            "making any changes."
        ),
    )

    args = parser.parse_args()

    try:

        merge_backup(
            Path(args.new_backup),
            Path(args.old_backup),
            dry_run=args.dry_run,
        )

    except KeyboardInterrupt:

        print()
        print("Interrupted.")

        sys.exit(130)

    except Exception as e:

        print()
        print("=" * 70)
        print("FATAL ERROR")
        print("=" * 70)
        print(e)
        print("=" * 70)

        sys.exit(1)


if __name__ == "__main__":
    main()