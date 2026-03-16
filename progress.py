import json
import os
import logging
import time
from typing import Dict, Any

logger = logging.getLogger("adb_backup")

class ProgressTracker:
    """Manages the persistence and retrieval of backup state."""
    
    def __init__(self, progress_file: str):
        self.progress_file = progress_file
        self._state: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        """Safely load the existing progress from disk."""
        if not os.path.exists(self.progress_file):
            return {}
        try:
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Progress file is corrupted; starting fresh")
            return {}
        except Exception as e:
            logger.error(f"Failed to load progress file: {e}")
            return {}

    def save(self) -> None:
        """Persist the current tracking state to disk."""
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self._state, f)
        except Exception as e:
            logger.error(f"Failed to save progress file: {e}")

    def is_completed(self, android_path: str) -> bool:
        """Check if a particular file has already been successfully backed up."""
        return self._state.get(android_path, {}).get("completed", False)

    def mark_completed(self, android_path: str, local_path: str) -> None:
        """Record a file as successfully copied."""
        self._state[android_path] = {
            "completed": True,
            "timestamp": time.time(),
            "local_path": local_path
        }
        self.save()
