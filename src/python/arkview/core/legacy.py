"""
Legacy components for Arkview core layer.
"""

import io
import os
import threading
from typing import Optional, List, Tuple, Union
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict

from PIL import Image, ImageOps, UnidentifiedImageError

# Qt imports for signals
from PySide6.QtCore import QObject, Signal

try:
    from .. import arkview_core
    RUST_AVAILABLE = True
    ZipScannerRust = arkview_core.ZipScanner
    ImageProcessorRust = arkview_core.ImageProcessor
except ImportError:
    RUST_AVAILABLE = False
    ZipScannerRust = None
    ImageProcessorRust = None

# Import LRUCache from external module instead of using redundant implementation
from .cache import LRUCache


class LegacyZipFileManager:
    """Manages opening and closing of ZipFile objects to avoid resource leaks."""
    def __init__(self, max_open_files: int = 10):
        self._open_files: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self._max_open_files = max_open_files
        if RUST_AVAILABLE:
            self.image_processor = ImageProcessorRust()

    def get_zipfile(self, path: str):
        """Gets or opens a ZipFile object for the given path."""
        import zipfile
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
        abs_path = os.path.abspath(path)
        with self._lock:
            if abs_path in self._open_files:
                try:
                    zf = self._open_files.pop(abs_path)
                    zf.close()
                except Exception as e:
                    print(f"ZipManager Warning: Error closing {path}: {e}")

    def close_all(self):
        with self._lock:
            while self._open_files:
                abs_path, zf = self._open_files.popitem(last=False)
                try:
                    zf.close()
                except Exception as e:
                    print(f"ZipManager Warning: Error closing {abs_path} during close_all: {e}")