import subprocess
import logging
from typing import List, Optional

logger = logging.getLogger("adb_backup")

class ADBClient:
    """Handles all communication with the Android Debug Bridge (ADB)."""
    
    def __init__(self, short_timeout: int = 5, medium_timeout: int = 60, long_timeout: int = 300):
        self.short_timeout = short_timeout
        self.medium_timeout = medium_timeout
        self.long_timeout = long_timeout

    def _run(self, cmd: List[str], timeout: int) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=timeout)

    def is_connected(self) -> bool:
        """Check if an ADB device is successfully connected."""
        try:
            result = self._run(['adb', 'devices'], timeout=self.short_timeout)
            if result.returncode != 0:
                logger.error("ADB command failed")
                return False
            
            lines = result.stdout.strip().splitlines()
            if len(lines) <= 1 or "device" not in result.stdout:
                logger.error("No ADB device connected")
                return False
                
            return True
        except subprocess.TimeoutExpired:
            logger.error("ADB connection check timed out")
            return False
        except Exception as e:
            logger.error(f"ADB connection error: {e}")
            return False

    def list_files(self, path: str) -> List[str]:
        """Retrieve a list of all files in the given directory on the device."""
        try:
            cmd = ['adb', 'shell', f'find "{path}" -type f 2>/dev/null | sort']
            result = self._run(cmd, timeout=self.medium_timeout)
            if result.returncode != 0:
                logger.error(f"Failed to list files: {result.stderr}")
                return []
            
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return []

    def get_file_size(self, path: str) -> Optional[int]:
        """Obtain the precise byte size of a specified file on the device."""
        try:
            cmd = ['adb', 'shell', f'stat -c %s "{path}"']
            result = self._run(cmd, timeout=self.short_timeout)
            if result.returncode == 0 and result.stdout.strip().isdigit():
                return int(result.stdout.strip())
            return None
        except Exception as e:
            logger.error(f"Error getting file size for {path}: {e}")
            return None

    def pull_file(self, android_path: str, local_path: str) -> bool:
        """Download a file from the device to the local file system."""
        try:
            cmd = ['adb', 'pull', android_path, local_path]
            result = self._run(cmd, timeout=self.long_timeout)
            
            if result.returncode != 0:
                logger.error(f"Failed to pull {android_path}: {result.stderr}")
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.error(f"Pull command timed out for {android_path}")
            return False
        except Exception as e:
            logger.error(f"Error pulling file {android_path}: {e}")
            return False
