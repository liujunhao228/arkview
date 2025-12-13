"""
File manager implementation for Arkview core layer.
Manages opening and closing of ZipFile objects to avoid resource leaks.
"""

import os
import threading
import zipfile
from collections import OrderedDict
from typing import Optional, Dict
try:
    from .. import arkview_core
    RUST_AVAILABLE = True
    ZipScannerRust = arkview_core.ZipScanner
except ImportError:
    RUST_AVAILABLE = False
    ZipScannerRust = None


class ZipFileManager:
    """Manages opening and closing of ZipFile objects to avoid resource leaks."""
    def __init__(self, max_open_files: int = 10):
        self._open_files: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self._max_open_files = max_open_files
        if RUST_AVAILABLE:
            self.image_processor = arkview_core.ImageProcessor()

    def get_zip(self, zip_path: str) -> Optional[zipfile.ZipFile]:
        """Get a ZipFile object, opening it if necessary."""
        with self._lock:
            if zip_path in self._open_files:
                # Move to end (most recently used)
                self._open_files.move_to_end(zip_path)
                return self._open_files[zip_path]
            
            # Check if we need to close oldest files
            while len(self._open_files) >= self._max_open_files:
                # Remove least recently used
                oldest_path, oldest_file = self._open_files.popitem(last=False)
                try:
                    oldest_file.close()
                except Exception:
                    pass  # Ignore errors when closing
            
            try:
                zip_file = zipfile.ZipFile(zip_path, 'r')
                self._open_files[zip_path] = zip_file
                return zip_file
            except Exception:
                return None

    def release_zip(self, zip_path: str):
        """Explicitly release a zip file."""
        with self._lock:
            if zip_path in self._open_files:
                zip_file = self._open_files.pop(zip_path)
                try:
                    zip_file.close()
                except Exception:
                    pass  # Ignore errors when closing

    def clear(self):
        """Close all open zip files."""
        with self._lock:
            for zip_file in self._open_files.values():
                try:
                    zip_file.close()
                except Exception:
                    pass  # Ignore errors when closing
            self._open_files.clear()