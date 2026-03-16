#!/usr/bin/env python3

import logging
import sys

from config import BackupConfig
from adb import ADBClient
from progress import ProgressTracker
from backup import BackupOrchestrator

def setup_logger(log_file: str = "backup.log") -> logging.Logger:
    """
    Configures a dual-channel logging system:
    - Detailed debug/info logs are streamed cleanly to a file.
    - Important errors surface to the console without interrupting the progress bar.
    """
    logger = logging.getLogger("adb_backup")
    logger.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # Restrict console to WARNING and above to preserve stdout cursor integrity
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.WARNING)
    stream_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    
    return logger

def main() -> None:
    # 1. Bootstrap the environment
    logger = setup_logger()
    logger.info("Starting ADB Backup Sequence")
    
    # 2. Inject dependencies
    config = BackupConfig()
    
    client = ADBClient(
        short_timeout=config.adb_timeout_short,
        medium_timeout=config.adb_timeout_medium,
        long_timeout=config.adb_timeout_long
    )
    
    tracker = ProgressTracker(config.progress_file)
    
    # 3. Mount and execute orchestrator
    orchestrator = BackupOrchestrator(config, client, tracker)
    orchestrator.run()

if __name__ == "__main__":
    main()
