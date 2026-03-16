from dataclasses import dataclass

@dataclass
class BackupConfig:
    """Configuration parameters for the backup process."""
    progress_file: str = "progress.json"
    file_list: str = "file_list.txt"
    android_root: str = "/sdcard/"
    local_backup_dir: str = "android_backup"
    
    # ADB command timeouts (in seconds)
    adb_timeout_short: int = 5
    adb_timeout_medium: int = 60
    adb_timeout_long: int = 300
