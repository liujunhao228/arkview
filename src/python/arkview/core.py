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


class ZipScanner:
    """ZIP file analysis with Rust acceleration."""
    def __init__(self):
        self.rust_scanner = ZipScannerRust() if RUST_AVAILABLE else None

    def analyze_zip(
        self,
        zip_path: str,
        collect_members: bool = True
    ) -> Tuple[bool, Optional[List[str]], Optional[float], Optional[int], int]:
        """
        Analyzes a ZIP file to determine if it contains *only* image files.
        Uses Rust for performance.
        """
        if RUST_AVAILABLE and self.rust_scanner:
            try:
                return self.rust_scanner.analyze_zip(zip_path, collect_members)
            except Exception as e:
                print(f"Rust scanner error for {zip_path}: {type(e).__name__} - {e}")
                # Fall back to Python implementation if Rust fails
                pass

        # Fallback to pure Python if Rust not available or failed
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

            # Check for potentially huge files to avoid hanging
            if file_size > 500 * 1024 * 1024:  # 500MB limit
                return False, None, mod_time, file_size, 0

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                member_list = zip_ref.infolist()

                # Check for potentially huge number of entries to avoid hanging
                if len(member_list) > 10000:
                    return False, None, mod_time, file_size, 0

                if not member_list:
                    return False, None, mod_time, file_size, 0

                contains_only_images: bool = True
                has_at_least_one_file: bool = False

                # Limit processing to first 1000 entries to avoid hanging
                limit = min(len(member_list), 1000)
                for i in range(limit):
                    member_info = member_list[i]
                    if member_info.is_dir():
                        continue

                    has_at_least_one_file = True
                    filename = member_info.filename

                    if _is_image_file(filename):
                        image_count += 1
                        if collect_members:
                            all_image_members.append(filename)
                    else:
                        contains_only_images = False
                        all_image_members = []
                        break

                # If we reached the limit without finding non-image files,
                # check if there are more entries that weren't processed
                if limit == 1000 and len(member_list) > 1000:
                    return False, None, mod_time, file_size, image_count

                is_valid = has_at_least_one_file and contains_only_images

        except zipfile.BadZipFile:
            print(f"Bad ZIP file: {zip_path}")
            return False, None, mod_time, file_size, image_count
        except zipfile.LargeZipFile:
            print(f"ZIP file too large: {zip_path}")
            return False, None, mod_time, file_size, image_count
        except PermissionError:
            print(f"Permission denied accessing: {zip_path}")
            return False, None, mod_time, file_size, image_count
        except Exception as e:
            print(f"Analysis Error: {type(e).__name__} - {e}")
            return False, None, mod_time, file_size, image_count

        return is_valid, all_image_members if (is_valid and collect_members) else None, mod_time, file_size, image_count

    def analyze_zip_with_timeout(
        self,
        zip_path: str,
        collect_members: bool = True,
        timeout: int = 30  # 30 seconds timeout
    ) -> Tuple[bool, Optional[List[str]], Optional[float], Optional[int], int]:
        """
        Analyzes a ZIP file with timeout protection using threading for cross-platform compatibility.
        """
        import threading

        # Result container
        result_container = {'type': None, 'data': None}
        result_lock = threading.Lock()
        result_event = threading.Event()

        def target():
            try:
                result = self.analyze_zip(zip_path, collect_members)
                with result_lock:
                    result_container['type'] = 'success'
                    result_container['data'] = result
                result_event.set()
            except Exception as e:
                with result_lock:
                    result_container['type'] = 'error'
                    result_container['data'] = (type(e).__name__, str(e))
                result_event.set()

        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        completed = result_event.wait(timeout)

        if not completed:
            # Thread is still running, meaning it timed out
            print(f"Timeout analyzing {zip_path}")
            return False, None, None, None, 0
        else:
            with result_lock:
                result_type = result_container['type']
                result_data = result_container['data']
            
            if result_type == 'success':
                return result_data
            else:
                print(f"Error analyzing {zip_path}: {result_data[0]} - {result_data[1]}")
                return False, None, None, None, 0

    def batch_analyze_zips(
        self,
        zip_paths: List[str],
        collect_members: bool = True
    ) -> List[Tuple[str, bool, Optional[List[str]], Optional[float], Optional[int], int]]:
        """
        Batch analyzes multiple ZIP files in parallel using Rust.
        Returns list of (zip_path, is_valid, members, mod_time, file_size, image_count) tuples.
        """
        if RUST_AVAILABLE and self.rust_scanner:
            try:
                # For better interruption handling, we might want to process in smaller batches
                # if we're concerned about hanging in Rust code
                return self.rust_scanner.batch_analyze_zips(zip_paths, collect_members)
            except Exception as e:
                print(f"Batch analysis error, falling back to sequential: {e}")

        # Fallback: sequential processing with interruption support
        results = []
        for zip_path in zip_paths:
            is_valid, members, mod_time, file_size, image_count = self.analyze_zip(zip_path, collect_members)
            results.append((zip_path, is_valid, members, mod_time, file_size, image_count))
        return results

    @staticmethod
    def _is_image_file(filename: str) -> bool:
        """Check if a file is an image based on its extension."""
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.ico'}
        _, ext = os.path.splitext(filename.lower())
        return ext in image_extensions


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