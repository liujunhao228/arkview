"""
ZIP service implementation for Arkview.
Handles scanning and analysis of ZIP archives.
"""

import os
import traceback
import zipfile
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QObject, Signal

from ..core.models import ZipFileInfo
from ..core.file_manager import ZipFileManager
try:
    from ..core import arkview_core
    RUST_AVAILABLE = True
    ZipScannerRust = arkview_core.ZipScanner
except ImportError:
    RUST_AVAILABLE = False
    ZipScannerRust = None


class ZipService(QObject):
    """Service for handling ZIP archive scanning and analysis operations."""
    
    # Signals for async operations
    scanCompleted = Signal(list)  # List[ZipFileInfo]
    scanProgress = Signal(int, int)  # current, total
    scanError = Signal(str, str)  # path, error_message
    
    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.zip_manager = ZipFileManager()
        if RUST_AVAILABLE:
            self.zip_scanner = ZipScannerRust()
        else:
            self.zip_scanner = None

    def get_zipfile(self, zip_path: str) -> Optional[zipfile.ZipFile]:
        """Get a ZipFile object, opening it if necessary.
        
        This is an adapter method that forwards to the internal zip_manager.
        """
        return self.zip_manager.get_zip(zip_path)
    
    def analyze_zip(self, zip_path: str, collect_members: bool = True) -> Tuple[bool, Optional[List[str]], Optional[float], Optional[int], int]:
        """
        Analyze a ZIP file to determine if it contains only image files.
        Uses Rust for performance when available.
        """
        if RUST_AVAILABLE and self.zip_scanner:
            try:
                return self.zip_scanner.analyze_zip(zip_path, collect_members)
            except Exception as e:
                print(f"Rust scanner error for {zip_path}: {type(e).__name__} - {e}")
                # Fall back to Python implementation if Rust fails
                pass

        # Fallback to pure Python if Rust not available or failed
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

                    if self._is_image_file(filename):
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
        try:
            from ..core import arkview_core
            return arkview_core.is_image_file(filename)
        except ImportError:
            # Fallback to Python implementation if Rust extension is not available
            from ..core.models import ImageExtensions
            return ImageExtensions.is_image_file(filename)