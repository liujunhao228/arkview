"""
Core module integrating Rust backend with Python frontend.
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
    from . import arkview_core
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




class LoadResult:
    """Data class to hold the result of an asynchronous image load."""
    def __init__(
        self,
        success: bool,
        data: Optional[Image.Image] = None,
        error_message: str = "",
        cache_key: Optional[tuple] = None
    ):
        self.success = success
        self.data = data
        self.error_message = error_message
        self.cache_key = cache_key


class ImageLoaderSignals(QObject):
    """Custom signals for image loading operations."""
    image_loaded = Signal(object)  # Signal carrying LoadResult object


def async_load_image_from_zip(
    zf,
    member_name: str,
    target_size: Optional[Tuple[int, int]],
    cache: LRUCache,
    cache_key: tuple,
    signals: Optional['ImageLoaderSignals'] = None,
    performance_mode: bool = False
):
    """
    Asynchronously loads an image from a ZIP file member.
    Can emit signals if provided, otherwise returns the result directly.
    """
    try:
        # Check cache first
        cached_img = cache.get(cache_key)
        if cached_img is not None:
            if signals is not None:
                signals.image_loaded.emit(cached_img)
                return
            else:
                return cached_img

        image_data = zf.read(member_name)
        with io.BytesIO(image_data) as image_stream:
            img = ImageOps.exif_transpose(Image.open(image_stream))
            img.load()

        # Cache the original loaded image
        cache.put(cache_key, img)

        # Prepare display image
        if target_size:
            resampling_method = (
                Image.Resampling.NEAREST if performance_mode
                else Image.Resampling.LANCZOS
            )
            img_thumb = img.copy()
            img_thumb.thumbnail(target_size, resampling_method)
            result = LoadResult(success=True, data=img_thumb, cache_key=cache_key)
        else:
            result = LoadResult(success=True, data=img, cache_key=cache_key)
        
        if signals is not None:
            signals.image_loaded.emit(result)
            return
        else:
            return result

    except KeyError:
        result = LoadResult(success=False, error_message=f"Member '{member_name}' not found", cache_key=cache_key)
        if signals is not None:
            signals.image_loaded.emit(result)
            return
        else:
            return result
    except UnidentifiedImageError:
        result = LoadResult(success=False, error_message="Invalid image format", cache_key=cache_key)
        if signals is not None:
            signals.image_loaded.emit(result)
            return
        else:
            return result
    except Image.DecompressionBombError:
        result = LoadResult(success=False, error_message="Decompression Bomb", cache_key=cache_key)
        if signals is not None:
            signals.image_loaded.emit(result)
            return
        else:
            return result
    except MemoryError:
        result = LoadResult(success=False, error_message="Out of memory", cache_key=cache_key)
        if signals is not None:
            signals.image_loaded.emit(result)
            return
        else:
            return result
    except Exception as e:
        print(f"Async Load Error: Failed processing {cache_key}: {type(e).__name__} - {e}")
        result = LoadResult(success=False, error_message=f"Load error: {type(e).__name__}", cache_key=cache_key)
        if signals is not None:
            signals.image_loaded.emit(result)
            return
        else:
            return result