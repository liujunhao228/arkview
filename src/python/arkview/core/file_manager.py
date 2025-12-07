"""
File manager for Arkview core layer.
Handles opening and closing of ZipFile objects to avoid resource leaks.
"""

import os
import threading
import zipfile
from typing import Optional, OrderedDict
from collections import OrderedDict as CollectionsOrderedDict


class ZipFileManager:
    """Manages opening and closing of ZipFile objects to avoid resource leaks."""
    
    def __init__(self, max_open_files: int = 10):
        self._open_files: OrderedDict = CollectionsOrderedDict()
        self._lock = threading.Lock()
        self._max_open_files = max_open_files

    def get_zipfile(self, path: str) -> Optional[zipfile.ZipFile]:
        """Gets or opens a ZipFile object for the given path."""
        abs_path = os.path.abspath(path)
        with self._lock:
            if abs_path in self._open_files:
                zf = self._open_files.pop(abs_path)
                # Move to end to mark as most recently used
                self._open_files[abs_path] = zf
                return zf
            try:
                if not os.path.exists(abs_path):
                    print(f"ZipManager Warning: File not found at {abs_path}")
                    return None
                zf = zipfile.ZipFile(path, 'r')
                self._open_files[abs_path] = zf

                # Enforce LRU capacity
                if len(self._open_files) > self._max_open_files:
                    oldest_path, oldest_zf = self._open_files.popitem(last=False)
                    try:
                        oldest_zf.close()
                    except Exception as e:
                        print(f"ZipManager Warning: Error closing {oldest_path} during eviction: {e}")

                return zf
            except (FileNotFoundError, zipfile.BadZipFile, IsADirectoryError, PermissionError) as e:
                print(f"ZipManager Error: Failed to open {path}: {e}")
                if abs_path in self._open_files:
                    del self._open_files[abs_path]
                return None
            except Exception as e:
                print(f"ZipManager Error: Unexpected error opening {path}: {e}")
                if abs_path in self._open_files:
                    del self._open_files[abs_path]
                return None

    def close_zipfile(self, path: str):
        """Close a specific zipfile."""
        abs_path = os.path.abspath(path)
        with self._lock:
            if abs_path in self._open_files:
                try:
                    zf = self._open_files.pop(abs_path)
                    zf.close()
                except Exception as e:
                    print(f"ZipManager Warning: Error closing {path}: {e}")

    def close_all(self):
        """Close all open zipfiles."""
        with self._lock:
            while self._open_files:
                abs_path, zf = self._open_files.popitem(last=False)
                try:
                    zf.close()
                except Exception as e:
                    print(f"ZipManager Warning: Error closing {abs_path} during close_all: {e}")