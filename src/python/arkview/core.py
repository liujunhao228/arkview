"""
Core module integrating Rust backend with Python frontend.
"""

import io
import os
import threading
import queue
from typing import Optional, List, Tuple, Union
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict

from PIL import Image, ImageOps, UnidentifiedImageError, ImageTk

try:
    from . import arkview_core
    RUST_AVAILABLE = True
    ZipScannerRust = arkview_core.ZipScanner
    ImageProcessorRust = arkview_core.ImageProcessor
except ImportError:
    RUST_AVAILABLE = False
    ZipScannerRust = None
    ImageProcessorRust = None


class LRUCache:
    """Simple Least Recently Used (LRU) cache for Image objects."""
    def __init__(self, capacity: int):
        self.cache = OrderedDict()
        self.capacity = capacity
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Optional[Image.Image]:
        with self._lock:
            if key not in self.cache:
                return None
            else:
                self.cache.move_to_end(key)
                return self.cache[key]

    def put(self, key: tuple, value: Image.Image):
        if not isinstance(value, Image.Image):
            print(f"Cache Warning: Attempted to cache non-Image object for key {key}")
            return
        with self._lock:
            try:
                value.load()
            except Exception as e:
                print(f"Cache Warning: Failed to load image data before caching key {key}: {e}")
                return

            if key in self.cache:
                self.cache[key] = value
                self.cache.move_to_end(key)
            else:
                if len(self.cache) >= self.capacity:
                    self.cache.popitem(last=False)
                self.cache[key] = value

    def clear(self):
        with self._lock:
            self.cache.clear()

    def resize(self, new_capacity: int):
        if new_capacity <= 0:
            raise ValueError("Cache capacity must be positive.")
        with self._lock:
            self.capacity = new_capacity
            while len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self.cache)

    def __contains__(self, key: tuple) -> bool:
        with self._lock:
            return key in self.cache


class ZipFileManager:
    """Manages opening and closing of ZipFile objects to avoid resource leaks."""
    def __init__(self):
        self._open_files: dict = {}
        self._lock = threading.Lock()
        if RUST_AVAILABLE:
            self.image_processor = ImageProcessorRust()

    def get_zipfile(self, path: str):
        """Gets or opens a ZipFile object for the given path."""
        import zipfile
        abs_path = os.path.abspath(path)
        with self._lock:
            if abs_path in self._open_files:
                return self._open_files[abs_path]
            try:
                if not os.path.exists(abs_path):
                    print(f"ZipManager Warning: File not found at {abs_path}")
                    return None
                zf = zipfile.ZipFile(path, 'r')
                self._open_files[abs_path] = zf
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
                    self._open_files[abs_path].close()
                except Exception as e:
                    print(f"ZipManager Warning: Error closing {path}: {e}")
                del self._open_files[abs_path]

    def close_all(self):
        with self._lock:
            keys_to_close = list(self._open_files.keys())
            for abs_path in keys_to_close:
                try:
                    self._open_files[abs_path].close()
                except Exception as e:
                    print(f"ZipManager Warning: Error closing {abs_path} during close_all: {e}")
                del self._open_files[abs_path]


class ZipScanner:
    """ZIP file analysis with Rust acceleration."""
    def __init__(self):
        self.rust_scanner = ZipScannerRust() if RUST_AVAILABLE else None

    def analyze_zip(self, zip_path: str) -> Tuple[bool, Optional[List[str]], Optional[float], Optional[int], int]:
        """
        Analyzes a ZIP file to determine if it contains *only* image files.
        Uses Rust for performance.
        """
        if RUST_AVAILABLE and self.rust_scanner:
            return self.rust_scanner.analyze_zip(zip_path)
        
        # Fallback to pure Python if Rust not available
        import zipfile
        mod_time: Optional[float] = None
        file_size: Optional[int] = None
        image_count: int = 0
        all_image_members: List[str] = []
        is_valid: bool = False

        try:
            if not os.path.exists(zip_path):
                return False, None, None, None, 0
            stat_result = os.stat(zip_path)
            mod_time = stat_result.st_mtime
            file_size = stat_result.st_size

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                member_list = zip_ref.infolist()

                if not member_list:
                    return False, None, mod_time, file_size, 0

                contains_only_images: bool = True
                has_at_least_one_file: bool = False

                for member_info in member_list:
                    if member_info.is_dir():
                        continue

                    has_at_least_one_file = True
                    filename = member_info.filename

                    if self._is_image_file(filename):
                        image_count += 1
                        all_image_members.append(filename)
                    else:
                        contains_only_images = False
                        all_image_members = []
                        break

                is_valid = has_at_least_one_file and contains_only_images

        except Exception as e:
            print(f"Analysis Error: {type(e).__name__} - {e}")
            return False, None, mod_time, file_size, image_count

        return is_valid, all_image_members if is_valid else None, mod_time, file_size, image_count

    @staticmethod
    def _is_image_file(filename: str) -> bool:
        IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.ico'}
        if not filename or filename.endswith('/'):
            return False
        _root, ext = os.path.splitext(filename)
        return ext.lower() in IMAGE_EXTENSIONS


class LoadResult:
    """Data class to hold the result of an asynchronous image load."""
    def __init__(
        self,
        success: bool,
        data: Optional[Union[Image.Image, ImageTk.PhotoImage]] = None,
        error_message: str = "",
        cache_key: Optional[tuple] = None
    ):
        self.success = success
        self.data = data
        self.error_message = error_message
        self.cache_key = cache_key


def load_image_data_async(
    zip_path: str,
    member_name: str,
    max_load_size: int,
    target_size: Optional[Tuple[int, int]],
    result_queue: queue.Queue,
    cache: LRUCache,
    cache_key: tuple,
    zip_manager: ZipFileManager,
    performance_mode: bool,
    force_reload: bool = False
):
    """
    Asynchronously loads image data from a ZIP archive member.
    """
    if not force_reload:
        cached_image = cache.get(cache_key)
        if cached_image is not None:
            try:
                img_to_process = cached_image.copy()
                if target_size:
                    resampling_method = (
                        Image.Resampling.NEAREST if performance_mode
                        else Image.Resampling.LANCZOS
                    )
                    img_to_process.thumbnail(target_size, resampling_method)
                result_queue.put(LoadResult(success=True, data=img_to_process, cache_key=cache_key))
                return
            except Exception as e:
                print(f"Async Load Warning: Error processing cached image for {cache_key}: {e}")

    zf = zip_manager.get_zipfile(zip_path)
    if zf is None:
        result_queue.put(LoadResult(success=False, error_message="Cannot open ZIP", cache_key=cache_key))
        return

    try:
        member_info = zf.getinfo(member_name)

        if member_info.file_size == 0:
            result_queue.put(LoadResult(success=False, error_message="Image file empty", cache_key=cache_key))
            return
        if member_info.file_size > max_load_size:
            err_msg = f"Too large ({_format_size(member_info.file_size)} > {_format_size(max_load_size)})"
            result_queue.put(LoadResult(success=False, error_message=err_msg, cache_key=cache_key))
            return

        image_data = zf.read(member_name)
        with io.BytesIO(image_data) as image_stream:
            img = ImageOps.exif_transpose(Image.open(image_stream))
            img.load()

        cache.put(cache_key, img.copy())

        img_to_return = img
        if target_size:
            resampling_method = (
                Image.Resampling.NEAREST if performance_mode
                else Image.Resampling.LANCZOS
            )
            img_thumb = img.copy()
            img_thumb.thumbnail(target_size, resampling_method)
            img_to_return = img_thumb

        result_queue.put(LoadResult(success=True, data=img_to_return, cache_key=cache_key))

    except KeyError:
        result_queue.put(LoadResult(success=False, error_message=f"Member '{member_name}' not found", cache_key=cache_key))
    except UnidentifiedImageError:
        result_queue.put(LoadResult(success=False, error_message="Invalid image format", cache_key=cache_key))
    except Image.DecompressionBombError:
        result_queue.put(LoadResult(success=False, error_message="Decompression Bomb", cache_key=cache_key))
    except MemoryError:
        result_queue.put(LoadResult(success=False, error_message="Out of memory", cache_key=cache_key))
    except Exception as e:
        print(f"Async Load Error: Failed processing {cache_key}: {type(e).__name__} - {e}")
        result_queue.put(LoadResult(success=False, error_message=f"Load error: {type(e).__name__}", cache_key=cache_key))


def _format_size(size_bytes: int) -> str:
    """Formats byte size into a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.1f} GB"
