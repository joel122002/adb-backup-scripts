import os
import logging
import sys
import msvcrt
import threading
import time
from typing import List

from config import BackupConfig
from adb import ADBClient
from progress import ProgressTracker

logger = logging.getLogger("adb_backup")

class ProgressBar:
    """A minimal, clean terminal progress bar."""
    
    @staticmethod
    def update(current: int, total: int, bar_length: int = 50) -> None:
        progress = min(1.0, current / total) if total > 0 else 0
        arrow = '=' * int(round(progress * bar_length))
        spaces = ' ' * (bar_length - len(arrow))
        
        sys.stdout.write(f'\r[{arrow}{spaces}] {current}/{total} files ({int(progress * 100)}%)')
        sys.stdout.flush()

class BackupOrchestrator:
    """Orchestrates the entire ADB backup lifecycle."""
    
    def __init__(self, config: BackupConfig, client: ADBClient, tracker: ProgressTracker):
        self.config = config
        self.client = client
        self.tracker = tracker
        self._pause_event = threading.Event()
        self._stop_event = threading.Event()

    def _keyboard_listener(self) -> None:
        """Daemon thread that continuously listens for the 'p' hotkey to toggle pause state."""
        while not self._stop_event.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key.lower() == b'p':
                    # Toggle the pause event
                    if self._pause_event.is_set():
                        # We are currently paused; user pressed 'p' to resume
                        logger.info("Backup resume triggered by user via 'p' key")
                        self._pause_event.clear()
                    else:
                        # We are currently running; user pressed 'p' to pause
                        logger.info("Backup pause triggered by user via 'p' key")
                        self._pause_event.set()
                elif key == b'\x03': # Ctrl+C
                    # Allow Ctrl+C to propagate to the main thread via standard OS interrupts
                    pass
            time.sleep(0.1) # Prevent CPU pegging

    def _save_file_list(self, files: List[str]) -> None:
        try:
            with open(self.config.file_list, 'w', encoding='utf-8') as f:
                for file_path in files:
                    f.write(f"{file_path}\n")
        except Exception as e:
            logger.error(f"Error saving file list: {e}")

    def _create_directories(self, files: List[str]) -> None:
        logger.info("Building local directory replication")
        created_dirs = set()
        
        for file_path in files:
            rel_path = file_path.lstrip('/')
            local_dir = os.path.normpath(os.path.join(self.config.local_backup_dir, os.path.dirname(rel_path)))
            
            if local_dir not in created_dirs:
                try:
                    os.makedirs(local_dir, exist_ok=True)
                    created_dirs.add(local_dir)
                except Exception as e:
                    logger.error(f"Failed to create directory {local_dir}: {e}")
        
        logger.info(f"Replicated {len(created_dirs)} directories")

    def _needs_backup(self, android_path: str, local_path: str) -> bool:
        if self.tracker.is_completed(android_path) and os.path.exists(local_path):
            try:
                local_size = os.path.getsize(local_path)
                device_size = self.client.get_file_size(android_path)
                
                if local_size == device_size and device_size is not None:
                    return False
                
                logger.info(f"Size mismatch: {android_path} (Local: {local_size}, Device: {device_size})")
                os.remove(local_path)
                logger.info(f"Purged incomplete file payload: {local_path}")
            except Exception as e:
                logger.error(f"File validation failure for {android_path}: {e}")
                
        return True

    def run(self) -> None:
        logger.info("Initializing backup agent.")
        
        if not self.client.is_connected():
            logger.error("No active ADB connection found. Aborting.")
            return

        os.makedirs(self.config.local_backup_dir, exist_ok=True)
        
        android_files = self.client.list_files(self.config.android_root)
        if not android_files:
            logger.warning("No target files located on the device.")
            return

        self._save_file_list(android_files)
        logger.info(f"Discovered {len(android_files)} total targets")
        
        self._create_directories(android_files)
        
        total = len(android_files)
        stats = {"processed": 0, "success": 0, "skipped": 0, "failed": 0}
        
        logger.info(f"Commencing continuous backup of {total} targets")
        print(f"Starting backup of {total} files...\n")
        print("Press 'p' at any time to softly pause the backup.")
        
        # Start keyboard listener daemon
        listener_thread = threading.Thread(target=self._keyboard_listener, daemon=True)
        listener_thread.start()
        
        while stats["processed"] < total:
            try:
                # Obey pause flag nicely before we pull the next file from the array 
                if self._pause_event.is_set():
                    print("\n\nThe file that was in progress is now copied.")
                    print("You can now successfully unplug your phone.")
                    print("Press 'p' again to resume backup or Ctrl+C to abort.")
                    
                    # Spin-wait until the user presses 'p' again to clear the flag
                    while self._pause_event.is_set() and not self._stop_event.is_set():
                        time.sleep(0.1)
                        
                    if not self._stop_event.is_set():
                        print("\nResuming backup...")
                
                path = android_files[stats["processed"]]
                rel_path = path.lstrip('/')
                local_path = os.path.normpath(os.path.join(self.config.local_backup_dir, rel_path))
                
                # Revalidate health of device connection periodically
                if stats["processed"] > 0 and stats["processed"] % 10 == 0:
                    if not self.client.is_connected():
                        logger.error("ADB connection severed during transmission. Halting.")
                        print("\nConnection lost to the device.")
                        break
                
                if not self._needs_backup(path, local_path):
                    stats["skipped"] += 1
                else:
                    logger.debug(f"Pulling file: {path}")
                    if self.client.pull_file(path, local_path) and os.path.exists(local_path):
                        self.tracker.mark_completed(path, local_path)
                        stats["success"] += 1
                    else:
                        logger.error(f"Transmission failure: {path}")
                        if os.path.exists(local_path):
                            try: os.remove(local_path)
                            except OSError: pass
                        stats["failed"] += 1
                
                stats["processed"] += 1
                ProgressBar.update(stats["processed"], total)
                                
            except KeyboardInterrupt:
                print("\n\nBackup fully aborted by user.")
                logger.info("Process forcefully interrupted by the user")
                break
            except Exception as e:
                print(f"\n\nAn unexpected anomaly occurred: {e}")
                logger.error(f"Unhandled exception in backup loop: {e}", exc_info=True)
                break
        
        # Cleanup
        self._stop_event.set()
        listener_thread.join(timeout=1.0)
            
        print("\n\n--- Session Summary ---")
        for metric, count in stats.items():
            print(f"{metric.capitalize():<12}: {count}")
            
        logger.info(f"Backup session concluded. Telemetry: {stats}")
