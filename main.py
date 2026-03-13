#!/usr/bin/env python3

import os
import sys
import subprocess
import json
import logging
import time
import hashlib
from pathlib import Path
import threading

# Global variables for hotkey
is_paused = False

def hotkey_listener():
    global is_paused
    if os.name == 'nt':
        import msvcrt
        while True:
            try:
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key.lower() == b'p':
                        is_paused = not is_paused
                        if is_paused:
                            print("\n[Hotkey 'p' pressed] Pausing after the current file finishes...", flush=True)
                        else:
                            print("\n[Hotkey 'p' pressed] Resuming...", flush=True)
                time.sleep(0.1)
            except Exception:
                pass
    else:
        import tty, termios, select, atexit
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            
            def restore_tty():
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except Exception:
                    pass
            
            atexit.register(restore_tty)
            tty.setcbreak(fd)
            
            while True:
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    key = sys.stdin.read(1)
                    if key.lower() == 'p':
                        is_paused = not is_paused
                        if is_paused:
                            print("\n[Hotkey 'p' pressed] Pausing after the current file finishes...", flush=True)
                        else:
                            print("\n[Hotkey 'p' pressed] Resuming...", flush=True)
        except Exception:
            pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("backup.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Constants
PROGRESS_FILE = "progress.json"
FILE_LIST = "file_list.txt"
ANDROID_ROOT = "/sdcard/"  # Default Android storage path
LOCAL_BACKUP_DIR = "android_backup"

def check_adb_connection():
    """Check if ADB is connected to a device."""
    try:
        result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, encoding='utf-8', timeout=5)
        if result.returncode != 0:
            logging.error("ADB command failed")
            return False
        
        lines = result.stdout.strip().splitlines()
        if len(lines) <= 1 or "device" not in result.stdout:
            logging.error("No ADB device connected")
            return False
            
        logging.info("ADB device connected")
        return True
    except subprocess.TimeoutExpired:
        logging.error("ADB command timed out")
        return False
    except Exception as e:
        logging.error(f"ADB connection error: {str(e)}")
        return False

def get_all_files_from_device(path=ANDROID_ROOT):
    """Get a list of all files from the Android device."""
    try:
        logging.info(f"Listing all files from {path}")
        cmd = ['adb', 'shell', f'find "{path}" -type f 2>/dev/null | sort']
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=60)
        if result.returncode != 0:
            logging.error(f"Failed to list files: {result.stderr}")
            return []
        
        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        
        # Save file list to disk
        with open(FILE_LIST, 'w', encoding='utf-8') as f:
            for file in files:
                f.write(f"{file}\n")
        
        logging.info(f"Found {len(files)} files on device")
        return files
    except subprocess.TimeoutExpired:
        logging.error("File listing timed out")
        return []
    except Exception as e:
        logging.error(f"Error listing files: {str(e)}")
        return []

def create_local_directory_structure(files):
    """Create the local directory structure to match the Android device."""
    logging.info("Creating local directory structure")
    created_dirs = set()
    
    for file_path in files:
        # Convert Android path to local path
        # Use normpath to convert slashes to local OS format (e.g. \ on Windows)
        rel_path = file_path.lstrip('/')
        local_dir = os.path.normpath(os.path.join(LOCAL_BACKUP_DIR, os.path.dirname(rel_path)))
        
        if local_dir not in created_dirs:
            try:
                os.makedirs(local_dir, exist_ok=True)
                created_dirs.add(local_dir)
            except Exception as e:
                logging.error(f"Failed to create directory {local_dir}: {str(e)}")
    
    logging.info(f"Created {len(created_dirs)} directories")

def load_progress():
    """Load the progress of backed up files."""
    if not os.path.exists(PROGRESS_FILE):
        logging.info(f"No progress file found, starting fresh")
        return {}
    
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            progress = json.load(f)
            logging.info(f"Loaded progress for {len(progress)} files")
            return progress
    except json.JSONDecodeError:
        logging.error(f"Progress file is corrupted, creating new one")
        return {}
    except Exception as e:
        logging.error(f"Error loading progress file: {str(e)}")
        return {}

def save_progress(progress):
    """Save the progress of backed up files."""
    try:
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(progress, f)
    except Exception as e:
        logging.error(f"Error saving progress file: {str(e)}")

def get_file_size_on_device(file_path):
    """Get the size of a file on the Android device."""
    try:
        cmd = ['adb', 'shell', f'stat -c %s "{file_path}"']
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=5)
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip())
        return None
    except subprocess.TimeoutExpired:
        logging.error(f"Command timed out while getting size for {file_path}")
        return None
    except Exception as e:
        logging.error(f"Error getting file size for {file_path}: {str(e)}")
        return None

def file_needs_backup(android_path, local_path, progress):
    """Check if a file needs to be backed up."""
    # If file is marked as completed in progress and exists locally
    if android_path in progress and os.path.exists(local_path):
        try:
            local_size = os.path.getsize(local_path)
            device_size = get_file_size_on_device(android_path)
            
            # If sizes match, file is likely already backed up correctly
            if local_size == device_size and device_size is not None:
                return False
            
            # If file exists but is corrupted or incomplete, delete it for fresh download
            logging.info(f"File size mismatch for {android_path}. Local: {local_size}, Device: {device_size}")
            os.remove(local_path)
            logging.info(f"Removed incomplete/corrupted file: {local_path}")
        except Exception as e:
            logging.error(f"Error checking file {android_path}: {str(e)}")
    
    return True

def pull_file(android_path, local_path):
    """Pull a file from the Android device to local storage."""
    try:
        logging.info(f"Pulling file: {android_path}")
        cmd = ['adb', 'pull', android_path, local_path]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=300)  # 5 minute timeout
        
        if result.returncode != 0:
            logging.error(f"Failed to pull {android_path}: {result.stderr}")
            return False
            
        # Verify the file was pulled correctly
        if not os.path.exists(local_path):
            logging.error(f"Pull reported success but file {local_path} doesn't exist")
            return False
            
        logging.info(f"Successfully pulled {android_path}")
        return True
    except subprocess.TimeoutExpired:
        logging.error(f"Pull command timed out for {android_path}")
        # Clean up potentially partial file
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
                logging.info(f"Removed partial file after timeout: {local_path}")
            except Exception:
                pass
        return False
    except Exception as e:
        logging.error(f"Error pulling file {android_path}: {str(e)}")
        return False

def update_progress_bar(current, total, bar_length=50):
    """Display a progress bar in the terminal."""
    progress = min(1.0, current / total) if total > 0 else 0
    arrow = '=' * int(round(progress * bar_length))
    spaces = ' ' * (bar_length - len(arrow))
    
    sys.stdout.write(f'\r[{arrow}{spaces}] {current}/{total} files ({int(progress*100)}%)')
    sys.stdout.flush()

def main():
    """Main backup function."""
    logging.info(f"Starting Android backup")
    
    # Start hotkey listener thread
    print("Initializing hotkey listener... Press 'p' at any time to pause/resume backup.")
    listener_thread = threading.Thread(target=hotkey_listener, daemon=True)
    listener_thread.start()
    
    # Check ADB connection
    if not check_adb_connection():
        logging.error("ADB connection failed. Exiting.")
        return
    
    # Create backup directory if it doesn't exist
    os.makedirs(LOCAL_BACKUP_DIR, exist_ok=True)
    
    # Get all files from Android device
    android_files = get_all_files_from_device()
    if not android_files:
        logging.error("No files found on device or error listing files. Exiting.")
        return
    
    # Create local directory structure
    create_local_directory_structure(android_files)
    
    # Load progress
    progress = load_progress()
    
    # Start backup process
    total_files = len(android_files)
    processed_files = 0
    successful_files = 0
    skipped_files = 0
    failed_files = 0
    
    logging.info(f"Starting backup of {total_files} files")
    
    try:
        for android_path in android_files:
            # Check if paused by hotkey
            if is_paused:
                print("\nYour device is ready to eject.")
                logging.info("Backup paused by hotkey.")
                
                # Wait until user resumes
                while is_paused:
                    time.sleep(0.5)
                
                print("\nWaiting for ADB device to reconnect...")
                logging.info("Backup resumed by hotkey. Waiting for device...")
                
                # Silently wait for ADB without spamming logs
                while True:
                    result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 and "device" in result.stdout and len(result.stdout.strip().splitlines()) > 1:
                        break
                    time.sleep(2)
                
                print("Device connected. Continuing backup...")
                logging.info("ADB device reconnected. Resuming backup.")
                
            # Convert Android path to local path
            # Use normpath to ensure correct slash direction for the local OS
            rel_path = android_path.lstrip('/')
            local_path = os.path.normpath(os.path.join(LOCAL_BACKUP_DIR, rel_path))
            
            # Periodically check if ADB connection is still alive
            if processed_files % 10 == 0 and processed_files > 0:
                if not check_adb_connection():
                    logging.error("ADB connection lost during backup")
                    break
            
            # Check if file needs backup
            if not file_needs_backup(android_path, local_path, progress):
                logging.info(f"Skipping already backed up file: {android_path}")
                processed_files += 1
                skipped_files += 1
                update_progress_bar(processed_files, total_files)
                continue
            
            # Pull file from device
            success = pull_file(android_path, local_path)
            
            if success:
                # Mark as completed in progress
                progress[android_path] = {
                    "completed": True,
                    "timestamp": time.time(),
                    "local_path": local_path
                }
                save_progress(progress)
                logging.info(f"Successfully backed up: {android_path}")
                successful_files += 1
            else:
                logging.error(f"Failed to back up: {android_path}")
                failed_files += 1
            
            processed_files += 1
            update_progress_bar(processed_files, total_files)
    
    except KeyboardInterrupt:
        logging.info("Backup interrupted by user")
        print("\nBackup interrupted by user.")
    except Exception as e:
        logging.error(f"Unexpected error during backup: {str(e)}")
        print(f"\nUnexpected error: {str(e)}")
    
    # Final stats
    print("\nBackup process completed.")
    print(f"Total files: {total_files}")
    print(f"Successfully backed up: {successful_files}")
    print(f"Skipped (already backed up): {skipped_files}")
    print(f"Failed: {failed_files}")
    
    logging.info(f"Backup completed. Success: {successful_files}, Skipped: {skipped_files}, Failed: {failed_files}")

if __name__ == "__main__":
    main()
