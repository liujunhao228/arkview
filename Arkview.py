# -*- coding: utf-8 -*-
"""
Archived Image Viewer: Scans directories for ZIP archives containing only image files
and provides a browser with preview and viewing capabilities.
"""

# --- Standard Library Imports ---
import io
import os
import platform
import queue
import re
import subprocess
import threading
import zipfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import (Any, Callable, Dict, List, Optional, Tuple, Union)

# --- Third-Party Imports ---
import tkinter as tk
from tkinter import (Checkbutton, BooleanVar, Frame, Label, Menu, Toplevel,
                     filedialog, messagebox)
from tkinter import ttk
from tkinter.ttk import PanedWindow, Progressbar

# --- Pillow Dependency ---
try:
    from PIL import Image, ImageTk, ImageOps, UnidentifiedImageError
except ImportError as e:
    messagebox.showerror(
        "Dependency Missing",
        f"Pillow library is required:\n{str(e)}\n'pip install Pillow'"
    )
    exit(1)

# --- Drag & Drop Dependency (Optional) ---
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_ENABLED = True
except ImportError:
    print(
        "INFO: Optional library `tkinterdnd2` not found.\n"
        "Install using: `pip install tkinterdnd2`\n"
        "Drag and drop functionality will be disabled."
    )
    # Define dummy classes/variables for graceful fallback
    class TkinterDnD:
        @staticmethod
        def Tk(*args, **kwargs): return tk.Tk(*args, **kwargs)
        # Add ThemedTk fallback if using ttkthemes
        # @staticmethod
        # def ThemedTk(*args, **kwargs): return ThemedTk(*args, **kwargs) # Assuming ThemedTk is imported

    DND_FILES = None
    DND_ENABLED = False

# --- Configuration Constants ---
CONFIG: Dict[str, Any] = {
    # Files & Formats
    "IMAGE_EXTENSIONS": {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.ico'},
    # Performance & Cache
    "THUMBNAIL_SIZE": (280, 280),
    "PERFORMANCE_THUMBNAIL_SIZE": (180, 180),
    "BATCH_UPDATE_INTERVAL": 5, # UI update frequency during scan
    "MAX_THUMBNAIL_LOAD_SIZE": 10 * 1024 * 1024, # 10 MB
    "PERFORMANCE_MAX_THUMBNAIL_LOAD_SIZE": 3 * 1024 * 1024, # 3 MB
    "MAX_VIEWER_LOAD_SIZE": 100 * 1024 * 1024, # 100 MB
    "PERFORMANCE_MAX_VIEWER_LOAD_SIZE": 30 * 1024 * 1024, # 30 MB
    "CACHE_MAX_ITEMS_NORMAL": 50, # Increased cache size
    "CACHE_MAX_ITEMS_PERFORMANCE": 25, # Smaller cache in performance mode
    "PRELOAD_VIEWER_NEIGHBORS_NORMAL": 2, # Preload +/- 2 images in viewer (normal)
    "PRELOAD_VIEWER_NEIGHBORS_PERFORMANCE": 1, # Preload +/- 1 image in viewer (performance)
    "PRELOAD_NEXT_THUMBNAIL": True, # Preload next thumbnail in preview (normal mode only)
    # UI & Behavior
    "WINDOW_SIZE": "1050x750",
    "VIEWER_ZOOM_FACTOR": 1.2,
    "VIEWER_MAX_ZOOM": 10.0,
    "VIEWER_MIN_ZOOM": 0.1,
    "PREVIEW_UPDATE_DELAY": 250, # ms delay before updating preview on selection change
    "THREAD_POOL_WORKERS": min(8, (os.cpu_count() or 1) + 4), # Thread pool size
    "APP_VERSION": "3.9 - Optimized",
}

# --- Helper Functions ---

def format_size(size_bytes: int) -> str:
    """Formats byte size into a human-readable string (KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.1f} GB"

def format_datetime(timestamp: float) -> str:
    """Formats a timestamp into a YYYY-MM-DD HH:MM:SS string."""
    try:
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, OSError, TypeError):
        # Handle potential invalid timestamps gracefully
        return "N/A"

def parse_human_size(size_str: str) -> Optional[int]:
    """
    Parses human-readable size string (KB, MB, GB, or bytes) into bytes.
    Returns None for empty string, -1 for parse error.
    """
    size_str = size_str.strip().upper()
    if not size_str:
        return None
    # Regex supports optional space and B suffix
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT])?B?$', size_str)
    if not match:
        # Allow plain numbers as bytes
        if size_str.isdigit():
             return int(size_str)
        return -1 # Indicate parsing error

    value = float(match.group(1))
    unit = match.group(2)

    multipliers = {'G': 1024**3, 'M': 1024**2, 'K': 1024, None: 1}
    multiplier = multipliers.get(unit, 1) # Default to 1 (bytes) if no unit

    return int(value * multiplier)


# --- LRU Cache ---
class LRUCache:
    """Simple Least Recently Used (LRU) cache for Image objects."""
    def __init__(self, capacity: int):
        self.cache = OrderedDict()
        self.capacity = capacity
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Optional[Image.Image]:
        """Retrieves an item from the cache, marking it as recently used."""
        with self._lock:
            if key not in self.cache:
                return None
            else:
                self.cache.move_to_end(key)
                # Return a copy to prevent modification of the cached object?
                # For PIL Images, maybe not strictly necessary if only read,
                # but safer if transformations happen outside the cache put.
                # return self.cache[key].copy()
                return self.cache[key]

    def put(self, key: tuple, value: Image.Image):
        """Adds an item to the cache, potentially evicting the least used."""
        if not isinstance(value, Image.Image):
            print(f"Cache Warning: Attempted to cache non-Image object for key {key}")
            return
        with self._lock:
            # Ensure the image data is loaded before caching
            try:
                value.load()
            except Exception as e:
                print(f"Cache Warning: Failed to load image data before caching key {key}: {e}")
                return # Don't cache potentially broken images

            if key in self.cache:
                # Update existing item and move to end
                self.cache[key] = value
                self.cache.move_to_end(key)
            else:
                # Evict oldest if capacity reached
                if len(self.cache) >= self.capacity:
                    self.cache.popitem(last=False)
                # Add new item
                self.cache[key] = value

    def clear(self):
        """Removes all items from the cache."""
        with self._lock:
            self.cache.clear()

    def resize(self, new_capacity: int):
        """Changes the cache capacity, evicting items if needed."""
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

# --- ZIP File Manager ---
class ZipFileManager:
    """Manages opening and closing of ZipFile objects to avoid resource leaks."""
    def __init__(self):
        self._open_files: Dict[str, zipfile.ZipFile] = {}
        self._lock = threading.Lock() # Thread-safe access to the dictionary

    def get_zipfile(self, path: str) -> Optional[zipfile.ZipFile]:
        """Gets or opens a ZipFile object for the given path."""
        abs_path = os.path.abspath(path)
        with self._lock:
            if abs_path in self._open_files:
                # TODO: Add a check here? What if the file was closed externally?
                # For now, assume it's still valid if in the dict.
                return self._open_files[abs_path]
            try:
                # Ensure the file still exists before trying to open
                if not os.path.exists(abs_path):
                     print(f"ZipManager Warning: File not found at {abs_path}")
                     return None
                zf = zipfile.ZipFile(path, 'r')
                self._open_files[abs_path] = zf
                return zf
            except FileNotFoundError:
                print(f"ZipManager Error: File not found when opening {path}")
                # Remove if it was somehow added previously but now gone
                if abs_path in self._open_files: del self._open_files[abs_path]
                return None
            except (zipfile.BadZipFile, IsADirectoryError, PermissionError) as e:
                print(f"ZipManager Error: Failed to open {path}: {e}")
                # Remove if it was somehow added previously but now invalid
                if abs_path in self._open_files: del self._open_files[abs_path]
                return None
            except Exception as e: # Catch other potential errors
                print(f"ZipManager Error: Unexpected error opening {path}: {e}")
                if abs_path in self._open_files: del self._open_files[abs_path]
                return None

    def close_zipfile(self, path: str):
        """Closes the ZipFile object for the given path."""
        abs_path = os.path.abspath(path)
        with self._lock:
            if abs_path in self._open_files:
                try:
                    self._open_files[abs_path].close()
                except Exception as e:
                    # Log error but continue cleanup
                    print(f"ZipManager Warning: Error closing {path}: {e}")
                # Always remove from dictionary after attempting close
                del self._open_files[abs_path]

    def close_all(self):
        """Closes all managed ZipFile objects."""
        with self._lock:
            # Iterate over a copy of keys to allow modification during iteration
            keys_to_close = list(self._open_files.keys())
            for abs_path in keys_to_close:
                try:
                    self._open_files[abs_path].close()
                except Exception as e:
                    print(f"ZipManager Warning: Error closing {abs_path} during close_all: {e}")
                # Remove from dict even if closing failed
                del self._open_files[abs_path]
            # Verify the dictionary is empty
            # assert not self._open_files, "ZipManager dictionary not empty after close_all"


# --- Core Logic: ZIP Scanner ---
class ZipScanner:
    """Provides static methods for analyzing ZIP files."""

    _image_extensions = CONFIG["IMAGE_EXTENSIONS"]

    @staticmethod
    def is_image_file(filename: str) -> bool:
        """Checks if a filename corresponds to a supported image extension."""
        if not filename or filename.endswith('/'): # Ignore directories
            return False
        # Efficiently get extension and check membership
        _root, ext = os.path.splitext(filename)
        return ext.lower() in ZipScanner._image_extensions

    @staticmethod
    def analyze_zip(zip_path: str) -> Tuple[bool, Optional[List[str]], Optional[float], Optional[int], int]:
        """
        Analyzes a ZIP file to determine if it contains *only* image files.

        Returns:
            Tuple[bool, Optional[List[str]], Optional[float], Optional[int], int]:
            - is_valid (bool): True if the ZIP exists, is readable, contains at least one file,
                               and all files are recognized images.
            - image_members (Optional[List[str]]): List of image filenames if valid, else None.
            - mod_time (Optional[float]): Modification timestamp of the ZIP file, or None if error.
            - file_size (Optional[int]): Size of the ZIP file in bytes, or None if error.
            - image_count (int): Number of image files found (even if other files exist).
        """
        mod_time: Optional[float] = None
        file_size: Optional[int] = None
        image_count: int = 0
        all_image_members: List[str] = []
        is_valid: bool = False

        try:
            # 1. Check existence and get basic stats
            if not os.path.exists(zip_path):
                # Return early if file doesn't exist
                return False, None, None, None, 0
            stat_result = os.stat(zip_path)
            mod_time = stat_result.st_mtime
            file_size = stat_result.st_size

            # 2. Open and read ZIP contents
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                member_list = zip_ref.infolist()

                if not member_list: # Empty ZIP file
                    return False, None, mod_time, file_size, 0

                contains_only_images: bool = True
                has_at_least_one_file: bool = False

                for member_info in member_list:
                    if member_info.is_dir():
                        continue # Skip directories explicitly

                    has_at_least_one_file = True
                    filename = member_info.filename

                    # Handle potential encoding issues in filenames
                    # Sometimes filenames are not standard UTF-8
                    # Let's try to decode defensively, but this might not be perfect
                    try:
                        # Attempt default decoding (often cp437 or utf-8)
                        _ = filename.encode('cp437').decode('utf-8', errors='ignore')
                    except Exception:
                        # If decoding fails, we might skip or flag the file
                        # For simplicity here, we continue processing based on the raw filename
                        pass

                    if ZipScanner.is_image_file(filename):
                        image_count += 1
                        all_image_members.append(filename)
                    else:
                        # Found a non-image file
                        contains_only_images = False
                        # No need to collect image members if not purely images
                        all_image_members = []
                        break # Stop checking further members

                # Determine validity based on findings
                is_valid = has_at_least_one_file and contains_only_images

        except (zipfile.BadZipFile, FileNotFoundError, IsADirectoryError) as e:
            # Known file/ZIP related errors
            print(f"Analysis Info: Skipping {os.path.basename(zip_path)} - {type(e).__name__}: {e}")
            return False, None, mod_time, file_size, image_count # Return partial info if possible
        except PermissionError as e:
             print(f"Analysis Info: Skipping {os.path.basename(zip_path)} due to Permission Error.")
             return False, None, mod_time, file_size, image_count
        except OSError as e:
            # Catch potential OS errors during stat or file access
            print(f"Analysis Error: OS error processing {os.path.basename(zip_path)}: {e}")
            return False, None, mod_time, file_size, image_count
        except Exception as e:
            # Catch any other unexpected errors
            print(f"Analysis Error: Unexpected error analyzing {os.path.basename(zip_path)}: {type(e).__name__} - {e}")
            return False, None, mod_time, file_size, image_count

        # Return the final analysis result
        return is_valid, all_image_members if is_valid else None, mod_time, file_size, image_count


# --- Background Image Loader ---
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
        self.data = data # Can be PIL Image or PhotoImage depending on context
        self.error_message = error_message
        self.cache_key = cache_key # Used to match result to request

def load_image_data_async(
    zip_path: str,
    member_name: str,
    max_load_size: int,
    target_size: Optional[Tuple[int, int]], # Target size for thumbnailing, None for full image
    result_queue: queue.Queue,
    cache: LRUCache,
    cache_key: tuple,
    zip_manager: ZipFileManager,
    performance_mode: bool,
    force_reload: bool = False
):
    """
    Asynchronously loads image data from a ZIP archive member.

    Handles caching, size limits, and thumbnail generation. Puts a LoadResult
    object into the result_queue upon completion or error.
    """
    # 1. Check Cache (unless forced reload)
    if not force_reload:
        cached_image = cache.get(cache_key)
        if cached_image is not None:
            try:
                # We have the full image in cache, process it for the request
                img_to_process = cached_image.copy() # Work on a copy
                if target_size: # Need a thumbnail
                    resampling_method = (
                        Image.Resampling.NEAREST if performance_mode
                        else Image.Resampling.LANCZOS
                    )
                    img_to_process.thumbnail(target_size, resampling_method)
                # Put the processed (or original if no target_size) image in result
                result_queue.put(LoadResult(success=True, data=img_to_process, cache_key=cache_key))
                return # Success from cache
            except Exception as e:
                print(f"Async Load Warning: Error processing cached image for {cache_key}: {e}")
                # Fall through to reload if processing fails

    # 2. Access ZIP file
    zf = zip_manager.get_zipfile(zip_path)
    if zf is None:
        result_queue.put(LoadResult(success=False, error_message="Cannot open ZIP", cache_key=cache_key))
        return

    # 3. Load Image Data
    try:
        member_info = zf.getinfo(member_name)

        # Check size constraints before reading
        if member_info.file_size == 0:
            result_queue.put(LoadResult(success=False, error_message="Image file empty", cache_key=cache_key))
            return
        if member_info.file_size > max_load_size:
            err_msg = f"Too large ({format_size(member_info.file_size)} > {format_size(max_load_size)})"
            result_queue.put(LoadResult(success=False, error_message=err_msg, cache_key=cache_key))
            return

        # Read data and open with Pillow
        image_data = zf.read(member_name)
        with io.BytesIO(image_data) as image_stream:
            # Use ImageOps.exif_transpose to handle rotation metadata
            img = ImageOps.exif_transpose(Image.open(image_stream))
            # Ensure image data is fully loaded from the stream
            img.load()

        # 4. Cache the full loaded image (before potential thumbnailing)
        cache.put(cache_key, img.copy()) # Cache a copy

        # 5. Process for the specific request (thumbnail or full)
        img_to_return = img # Start with the full image
        if target_size:
            resampling_method = (
                Image.Resampling.NEAREST if performance_mode
                else Image.Resampling.LANCZOS
            )
            # Create thumbnail from the loaded image (use thumbnail method for aspect ratio)
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
        # Catch other Pillow errors or unexpected issues
        print(f"Async Load Error: Failed processing {cache_key}: {type(e).__name__} - {e}")
        result_queue.put(LoadResult(success=False, error_message=f"Load error: {type(e).__name__}", cache_key=cache_key))


# --- Settings Dialog ---
class SettingsDialog(Toplevel):
    """Dialog window for application settings."""
    def __init__(self, master, current_settings: Dict[str, Any]):
        super().__init__(master)
        self.title("Settings")
        self.resizable(False, False)
        self.transient(master) # Keep on top of master
        self.grab_set() # Modal behavior

        self.settings = current_settings
        # Work on a copy to allow cancellation
        self.result_settings = current_settings.copy()

        # Variables linked to Checkbuttons
        self.performance_mode_var = BooleanVar(
            value=self.result_settings.get('performance_mode', False)
        )
        self.viewer_enabled_var = BooleanVar(
            value=self.result_settings.get('viewer_enabled', True)
        )
        self.preload_thumb_var = BooleanVar(
            value=self.result_settings.get('preload_next_thumbnail', CONFIG['PRELOAD_NEXT_THUMBNAIL'])
        )

        # --- UI Setup ---
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Performance Mode Checkbutton
        perf_check = ttk.Checkbutton(
            main_frame,
            text="Performance Mode (Faster, Lower Quality)",
            variable=self.performance_mode_var,
            command=self._update_dependent_settings # Update related options visually
        )
        perf_check.pack(anchor=tk.W, pady=5)

        # Viewer Enabled Checkbutton
        viewer_check = ttk.Checkbutton(
            main_frame,
            text="Enable Multi-Image Viewer (Click Preview)",
            variable=self.viewer_enabled_var
        )
        viewer_check.pack(anchor=tk.W, pady=5)

        # Preload Thumbnail Checkbutton
        self.preload_thumb_check = ttk.Checkbutton(
            main_frame,
            text="Preload Next Thumbnail (in Preview)",
            variable=self.preload_thumb_var
        )
        self.preload_thumb_check.pack(anchor=tk.W, pady=5)

        # Button Frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(15, 0))

        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok)
        ok_button.pack(side=tk.RIGHT, padx=(5, 0))

        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        # --- Initial State & Positioning ---
        self._update_dependent_settings() # Set initial state of dependent options
        self.update_idletasks() # Ensure window size is calculated

        # Center the dialog over the master window
        master_x = master.winfo_x()
        master_y = master.winfo_y()
        master_w = master.winfo_width()
        master_h = master.winfo_height()
        dialog_w = self.winfo_width()
        dialog_h = self.winfo_height()
        center_x = master_x + (master_w // 2) - (dialog_w // 2)
        center_y = master_y + (master_h // 2) - (dialog_h // 2)
        self.geometry(f"+{center_x}+{center_y}")

        # Handle window close button (like Cancel)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Wait for the dialog to close
        self.wait_window(self)

    def _update_dependent_settings(self):
        """Enable/disable settings based on performance mode."""
        is_performance = self.performance_mode_var.get()
        # Preloading next thumbnail is disabled in performance mode
        self.preload_thumb_check.config(state=tk.DISABLED if is_performance else tk.NORMAL)
        if is_performance:
            self.preload_thumb_var.set(False) # Ensure it's off if disabled

    def _on_ok(self):
        """Apply settings and close dialog."""
        self.settings['performance_mode'] = self.performance_mode_var.get()
        self.settings['viewer_enabled'] = self.viewer_enabled_var.get()
        # Only apply preload setting if not in performance mode
        if not self.settings['performance_mode']:
             self.settings['preload_next_thumbnail'] = self.preload_thumb_var.get()
        else:
             self.settings['preload_next_thumbnail'] = False # Force off

        self.destroy()

    def _on_cancel(self):
        """Discard changes and close dialog."""
        # No need to revert self.settings, as we worked on result_settings
        self.destroy()

# --- Image Viewer Window ---
class ImageViewerWindow(Toplevel):
    """Window for viewing multiple images from a ZIP archive."""
    def __init__(
        self,
        master, # The main application window instance
        zip_path: str,
        image_members: List[str],
        initial_index: int,
        settings: Dict[str, Any],
        cache: LRUCache,
        result_queue: queue.Queue,
        thread_pool: ThreadPoolExecutor,
        zip_manager: ZipFileManager
    ):
        super().__init__(master)
        self.master_app = master # Reference to the main app if needed
        self.zip_path = zip_path
        self.image_members = image_members
        self.current_index = initial_index
        self.settings = settings # App settings (performance mode etc.)
        self.cache = cache # Shared image cache
        self.result_queue = result_queue # Queue for async load results
        self.thread_pool = thread_pool # Shared thread pool
        self.zip_manager = zip_manager # Shared zip manager

        # State variables
        self.current_pil_image: Optional[Image.Image] = None # Full resolution loaded image
        self._current_photo_image: Optional[ImageTk.PhotoImage] = None # Displayed image
        self.zoom_factor: float = 1.0
        self.fit_to_window: bool = True
        self._is_loading: bool = False
        self._is_fullscreen: bool = False
        self._current_load_future: Optional[concurrent.futures.Future] = None
        self._resize_job_id: Optional[str] = None # For debouncing resize events

        # --- Window Setup ---
        self.title(f"View: {os.path.basename(zip_path)}")
        self.geometry("800x600")
        self.minsize(400, 300)

        self._setup_ui()
        self._setup_bindings()

        # Make modal and focus
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._close_viewer)

        # Load initial image shortly after UI is setup
        self.after(50, lambda: self.load_image(self.current_index))
        self.after(100, self.focus_force)


    def _setup_ui(self):
        """Creates and packs the UI widgets."""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Top Control Bar ---
        top_frame = ttk.Frame(main_frame, padding=5)
        top_frame.pack(fill=tk.X)

        self.prev_button = ttk.Button(top_frame, text="< Prev", command=self._show_prev, width=8)
        self.prev_button.pack(side=tk.LEFT)

        self.image_info_label = ttk.Label(top_frame, text="Image 1 / X", anchor=tk.CENTER)
        self.image_info_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        self.next_button = ttk.Button(top_frame, text="Next >", command=self._show_next, width=8)
        self.next_button.pack(side=tk.RIGHT)

        # --- Image Display Area ---
        # Use a standard tk.Label for background color control if ttk style is tricky
        self.image_label = tk.Label(main_frame, background="darkgrey", anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Status Bar (Initially Hidden) ---
        self.status_frame = ttk.Frame(main_frame, padding=(5, 2))
        # status_frame is packed/unpacked dynamically in _show/_hide_loading

        self.progress_bar = Progressbar(self.status_frame, mode='indeterminate', maximum=100)
        # progress_bar is packed/unpacked with status_frame

        self.status_label = ttk.Label(self.status_frame, text="", anchor=tk.W)
        # status_label is packed/unpacked with status_frame

    def _setup_bindings(self):
        """Sets up keyboard and mouse event bindings."""
        # Navigation
        self.bind("<Left>", self._handle_keypress)
        self.bind("<Right>", self._handle_keypress)
        self.bind("<Prior>", self._handle_keypress) # Page Up
        self.bind("<Next>", self._handle_keypress)  # Page Down

        # Window Control
        self.bind("<Escape>", self._handle_keypress)
        self.bind("<F11>", self._toggle_fullscreen)
        self.bind("<Configure>", self._on_resize) # Window resize

        # Image Control
        # Mouse Wheel Zoom (Platform dependent)
        if platform.system() == "Linux":
            self.bind("<Button-4>", self._on_zoom) # Scroll Up
            self.bind("<Button-5>", self._on_zoom) # Scroll Down
        else: # Windows, macOS
            self.bind("<MouseWheel>", self._on_zoom)

        self.bind("<f>", self._handle_keypress) # Toggle fit
        self.bind("<F>", self._handle_keypress) # Toggle fit (Shift+f)
        self.bind("+", self._handle_keypress)   # Zoom In (Numpad + or =)
        self.bind("=", self._handle_keypress)   # Zoom In
        self.bind("-", self._handle_keypress)   # Zoom Out (Numpad - or -)
        self.bind("_", self._handle_keypress)   # Zoom Out (Shift+-)


    def _handle_keypress(self, event):
        """Handles keyboard shortcuts."""
        key = event.keysym.lower()
        # Allow essential keys even when loading
        essential_keys = {"escape", "f11", "f"}
        if self._is_loading and key not in essential_keys:
            return

        if key in ("left", "prior"): # Prior is Page Up
            self._show_prev()
        elif key in ("right", "next"): # Next is Page Down
            self._show_next()
        elif key == "escape":
            if self._is_fullscreen:
                self._toggle_fullscreen(force_state=False) # Exit fullscreen first
            else:
                self._close_viewer() # Close if not fullscreen
        elif key == "f":
            self._toggle_fit()
        elif key == "f11":
            self._toggle_fullscreen()
        elif key in ("plus", "equal"): # '+' or '=' for zoom in
             self._zoom_in()
        elif key in ("minus", "underscore"): # '-' or '_' for zoom out
             self._zoom_out()

    def _zoom_in(self):
        """Zooms the image in."""
        if not self.current_pil_image or self._is_loading: return
        new_zoom = min(CONFIG["VIEWER_MAX_ZOOM"], self.zoom_factor * CONFIG["VIEWER_ZOOM_FACTOR"])
        if new_zoom != self.zoom_factor:
             self.zoom_factor = new_zoom
             self.fit_to_window = False # Manual zoom disables fit
             self._render_image()


    def _zoom_out(self):
        """Zooms the image out."""
        if not self.current_pil_image or self._is_loading: return
        new_zoom = max(CONFIG["VIEWER_MIN_ZOOM"], self.zoom_factor / CONFIG["VIEWER_ZOOM_FACTOR"])
        if new_zoom != self.zoom_factor:
             self.zoom_factor = new_zoom
             self.fit_to_window = False # Manual zoom disables fit
             self._render_image()


    def _toggle_fullscreen(self, event=None, force_state: Optional[bool] = None):
        """Toggles or sets the fullscreen state."""
        if force_state is not None:
            self._is_fullscreen = force_state
        else:
            self._is_fullscreen = not self._is_fullscreen

        # Update window attribute for fullscreen
        self.attributes("-fullscreen", self._is_fullscreen)

        # Optional: Hide/show controls in fullscreen? (More complex UI change)
        # if self._is_fullscreen:
        #     self.top_frame.pack_forget()
        # else:
        #     self.top_frame.pack(fill=tk.X)

        # Re-render image after potential layout change from fullscreen toggle
        self.after(50, self._render_image) # Short delay might be needed

    def _on_resize(self, event=None):
        """Handles window resize events with debouncing."""
        # Debounce resize events to avoid excessive rendering calls
        if self._resize_job_id:
            self.after_cancel(self._resize_job_id)
        # Schedule the actual resize logic after a short delay
        self._resize_job_id = self.after(150, self._apply_resize)

    def _apply_resize(self):
        """Applies adjustments needed after window resize."""
        self._resize_job_id = None # Clear the job ID
        # Re-render the image only if fitting to window and an image exists
        if self.fit_to_window and self.current_pil_image and self.winfo_exists():
            self._render_image()

    def _on_zoom(self, event):
        """Handles mouse wheel zoom."""
        if not self.current_pil_image or self._is_loading:
            return

        factor = CONFIG["VIEWER_ZOOM_FACTOR"]
        min_zoom = CONFIG["VIEWER_MIN_ZOOM"]
        max_zoom = CONFIG["VIEWER_MAX_ZOOM"]

        # Determine zoom direction based on event properties
        delta = 0
        if event.num == 4: delta = 1   # Linux scroll up
        elif event.num == 5: delta = -1 # Linux scroll down
        elif hasattr(event, 'delta'): delta = event.delta # Windows/macOS

        if delta > 0: # Zoom In
            new_zoom = self.zoom_factor * factor
        elif delta < 0: # Zoom Out
            new_zoom = self.zoom_factor / factor
        else:
            return # No scroll detected

        # Clamp zoom factor within limits
        self.zoom_factor = max(min_zoom, min(max_zoom, new_zoom))

        # Manual zoom disables 'fit to window'
        if self.fit_to_window:
            self.fit_to_window = False

        # Re-render the image with the new zoom factor
        self._render_image()

    def _toggle_fit(self, event=None):
        """Toggles 'fit to window' mode."""
        if not self.current_pil_image or self._is_loading:
            return
        self.fit_to_window = not self.fit_to_window
        if self.fit_to_window:
            # Reset zoom factor when fitting
            self.zoom_factor = 1.0
        self._render_image() # Re-render based on new mode

    def _update_ui_state(self):
        """Updates labels, button states based on current index and loading status."""
        if not self.winfo_exists(): return

        total = len(self.image_members)
        current_num = self.current_index + 1

        # Update title/info label
        if 0 <= self.current_index < total:
             member_name = os.path.basename(self.image_members[self.current_index])
             self.image_info_label.config(text=f"Image {current_num} / {total} ({member_name})")
        else:
             self.image_info_label.config(text=f"Image {current_num} / {total}")

        # Update button states
        prev_state = tk.NORMAL if self.current_index > 0 and not self._is_loading else tk.DISABLED
        next_state = tk.NORMAL if self.current_index < total - 1 and not self._is_loading else tk.DISABLED
        self.prev_button.config(state=prev_state)
        self.next_button.config(state=next_state)

    def _show_loading(self, message="Loading..."):
        """Displays the loading indicator and message."""
        if not self.winfo_exists(): return
        self._is_loading = True

        # Configure and display status bar elements
        self.status_label.config(text=message)
        self.progress_bar.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0, 5))
        self.status_label.pack(fill=tk.X, side=tk.LEFT)
        self.status_frame.pack(fill=tk.X, side=tk.BOTTOM) # Show the status bar
        self.progress_bar.start(10) # Start indeterminate animation

        # Disable navigation while loading
        self._update_ui_state()
        self.update_idletasks() # Ensure UI updates immediately

    def _hide_loading(self):
        """Hides the loading indicator."""
        if not self.winfo_exists(): return
        self._is_loading = False

        # Stop progress bar and hide status bar
        self.progress_bar.stop()
        self.status_frame.pack_forget()

        # Re-enable navigation
        self._update_ui_state()

    def load_image(self, index: int, force_reload: bool = False):
        """
        Initiates loading of the image at the specified index.
        Handles caching and submits the load task to the thread pool.
        """
        if self._is_loading and not force_reload:
            print("Load cancelled: Already loading.")
            return # Avoid concurrent loads unless forced
        if not (0 <= index < len(self.image_members)):
            print(f"Load cancelled: Index {index} out of bounds (0-{len(self.image_members)-1})")
            return # Index out of bounds

        self.current_index = index
        member_name = self.image_members[index]
        cache_key = (self.zip_path, member_name)

        # Reset view state for the new image
        self.fit_to_window = True
        self.zoom_factor = 1.0
        self.current_pil_image = None # Clear previous image data
        self._current_photo_image = None # Clear previous Tkinter image object
        self.image_label.config(image=None, text="") # Clear display

        # --- Check Cache ---
        if not force_reload:
            cached_image = self.cache.get(cache_key)
            if cached_image is not None:
                self.current_pil_image = cached_image.copy() # Use a copy from cache
                self._render_image() # Render immediately
                self._update_ui_state()
                self._pre_load_neighbors() # Preload neighbors after displaying current
                return # Loaded from cache, done.

        # --- Load Asynchronously ---
        self._show_loading(f"Loading {os.path.basename(member_name)}...")

        perf_mode = self.settings.get('performance_mode', False)
        max_load_size = (
            CONFIG["PERFORMANCE_MAX_VIEWER_LOAD_SIZE"] if perf_mode
            else CONFIG["MAX_VIEWER_LOAD_SIZE"]
        )

        # Cancel previous future if any
        if self._current_load_future and not self._current_load_future.done():
             self._current_load_future.cancel()

        # Submit new load task
        self._current_load_future = self.thread_pool.submit(
            load_image_data_async,
            self.zip_path,
            member_name,
            max_load_size,
            None, # Load full image for viewer (None target_size)
            self.result_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            perf_mode,
            force_reload # Pass force_reload flag
        )

    def handle_load_result(self, result: LoadResult):
        """Processes the result from the asynchronous load task."""
        if not self.winfo_exists(): return # Window closed

        # Check if the result is for the currently expected image
        try:
            expected_key = (self.zip_path, self.image_members[self.current_index])
        except IndexError:
             return # Index might have changed rapidly

        if result.cache_key != expected_key:
            # This result is for a previous/cancelled load request, ignore it
            return

        self._hide_loading() # Hide progress bar

        if result.success and isinstance(result.data, Image.Image):
            # Successfully loaded the image
            self.current_pil_image = result.data # Store the full PIL image
            self._render_image() # Display the loaded image
        else:
            # Failed to load
            self.current_pil_image = None
            self._current_photo_image = None
            error_msg = result.error_message or "Unknown load error"
            self.image_label.config(image=None, text=f"Cannot Load:\n{error_msg}")
            self.image_label.image = None # Ensure reference is cleared

        self._update_ui_state() # Update buttons etc.
        self._pre_load_neighbors() # Preload neighbors after current image is handled

    def _render_image(self):
        """Renders the current_pil_image onto the image_label, applying zoom/fit."""
        if not self.winfo_exists(): return
        if not self.current_pil_image:
            # No image data, ensure label is clear or shows error message
            if not self._is_loading: # Don't clear loading message
                 self.image_label.config(image=None, text="" if self.current_pil_image is None else self.image_label.cget("text"))
            self.image_label.image = None
            self._current_photo_image = None
            return

        # Get container dimensions (wait if not ready)
        label_w = self.image_label.winfo_width()
        label_h = self.image_label.winfo_height()
        if label_w <= 1 or label_h <= 1: # Widget not yet sized
            self.after(50, self._render_image) # Retry shortly
            return

        try:
            img_to_render: Image.Image = self.current_pil_image
            target_w, target_h = img_to_render.width, img_to_render.height

            # Determine resampling quality
            perf_mode = self.settings.get('performance_mode', False)
            resampling = (Image.Resampling.NEAREST if perf_mode
                          else Image.Resampling.LANCZOS)

            # Calculate display size based on fit or zoom
            if self.fit_to_window:
                img_aspect = target_w / target_h
                label_aspect = label_w / label_h
                # Fit within label bounds while maintaining aspect ratio
                if img_aspect > label_aspect: # Image wider than label area
                    display_w = label_w
                    display_h = int(display_w / img_aspect)
                else: # Image taller than label area
                    display_h = label_h
                    display_w = int(display_h * img_aspect)
            else: # Apply zoom factor
                display_w = int(target_w * self.zoom_factor)
                display_h = int(target_h * self.zoom_factor)

            # Ensure minimum size of 1x1
            display_w = max(1, display_w)
            display_h = max(1, display_h)

            # Resize the image if necessary
            # Only resize if displayed size is different from original *and* smaller for thumbnailing
            # or if zoom is not 1.0
            final_image = img_to_render
            if (display_w != target_w or display_h != target_h):
                # Use thumbnail for downscaling (preserves aspect ratio better within bounds)
                # Use resize for upscaling or specific zoom
                if self.fit_to_window and (display_w < target_w or display_h < target_h):
                    final_image = img_to_render.copy() # Work on a copy
                    final_image.thumbnail((display_w, display_h), resampling)
                elif not self.fit_to_window:
                    final_image = img_to_render.resize((display_w, display_h), resampling)

            # Convert PIL image to Tkinter PhotoImage
            self._current_photo_image = ImageTk.PhotoImage(final_image)

            # Update the label
            self.image_label.config(image=self._current_photo_image, text="") # Clear any previous text
            self.image_label.image = self._current_photo_image # Keep reference

        except Exception as e:
            print(f"Viewer Render Error: {type(e).__name__} - {e}")
            # Display error message on the label
            self.image_label.config(image=None, text=f"Render Error:\n{type(e).__name__}")
            self.image_label.image = None
            self._current_photo_image = None

    def _pre_load_neighbors(self):
        """Submits asynchronous load tasks for neighboring images."""
        if self._is_loading or not self.winfo_exists():
            return # Don't preload if already loading or window closed

        perf_mode = self.settings.get('performance_mode', False)
        preload_depth = (CONFIG["PRELOAD_VIEWER_NEIGHBORS_PERFORMANCE"] if perf_mode
                         else CONFIG["PRELOAD_VIEWER_NEIGHBORS_NORMAL"])
        max_load_size = (
            CONFIG["PERFORMANCE_MAX_VIEWER_LOAD_SIZE"] if perf_mode
            else CONFIG["MAX_VIEWER_LOAD_SIZE"]
        )

        indices_to_preload = []
        # Prioritize next images, then previous
        for i in range(1, preload_depth + 1):
            indices_to_preload.append(self.current_index + i)
        for i in range(1, preload_depth + 1):
             indices_to_preload.append(self.current_index - i)

        queued_count = 0
        max_preload_tasks = 3 # Limit concurrent preloads further if needed

        for index in indices_to_preload:
            if 0 <= index < len(self.image_members):
                member_name = self.image_members[index]
                cache_key = (self.zip_path, member_name)

                # Check if not already cached and not currently being loaded by this viewer
                # (Note: another viewer or preview might be loading it)
                if cache_key not in self.cache:
                     # Check if a future for this key is already pending (less critical check)
                    is_already_pending = False
                    # (Could track pending futures more formally if needed)

                    if not is_already_pending and queued_count < max_preload_tasks:
                        # Submit preload task (load full image for viewer cache)
                        self.thread_pool.submit(
                            load_image_data_async,
                            self.zip_path,
                            member_name,
                            max_load_size,
                            None, # Preload full image
                            self.result_queue, # Use main queue, result ignored unless navigated to
                            self.cache,
                            cache_key,
                            self.zip_manager,
                            perf_mode,
                            False # Don't force reload for preloads
                        )
                        queued_count += 1


    def _show_next(self):
        """Navigates to the next image."""
        if not self._is_loading and self.current_index < len(self.image_members) - 1:
            self.load_image(self.current_index + 1)

    def _show_prev(self):
        """Navigates to the previous image."""
        if not self._is_loading and self.current_index > 0:
            self.load_image(self.current_index - 1)

    def _close_viewer(self):
        """Cleans up resources and closes the viewer window."""
        print("Closing image viewer...")
        # Cancel any pending resize job
        if self._resize_job_id:
            self.after_cancel(self._resize_job_id)
            self._resize_job_id = None

        # Cancel any pending load future
        if self._current_load_future and not self._current_load_future.done():
            self._current_load_future.cancel()
            self._current_load_future = None

        # Clear image references to help garbage collection
        self.current_pil_image = None
        self._current_photo_image = None
        if hasattr(self.image_label, 'image'): # Check if attribute exists
            self.image_label.config(image='')
            self.image_label.image = None

        # Release grab and destroy window
        self.grab_release()
        self.destroy()


# --- Image Preview Panel ---
class ImagePreview(ttk.Frame):
    """Panel to display a thumbnail preview of the selected ZIP's first image."""
    def __init__(
        self,
        master, # Parent widget (likely the main PanedWindow)
        settings: Dict[str, Any],
        cache: LRUCache,
        result_queue: queue.Queue,
        thread_pool: ThreadPoolExecutor,
        zip_manager: ZipFileManager,
        **kwargs
    ):
        super().__init__(master, **kwargs)
        self.settings = settings
        self.cache = cache
        self.result_queue = result_queue
        self.thread_pool = thread_pool
        self.zip_manager = zip_manager
        self.master_app = master.winfo_toplevel() # Get the root Tk window

        # State
        self._current_zip_path: Optional[str] = None
        self._current_image_members: List[str] = []
        self._current_thumb_index: int = 0 # Index of the currently displayed/loading thumb
        self._current_thumb_photo: Optional[ImageTk.PhotoImage] = None
        self._current_load_future: Optional[concurrent.futures.Future] = None
        self._is_loading_thumb: bool = False

        self._setup_ui()

    def _setup_ui(self):
        """Creates the widgets for the preview panel."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1) # Allow preview frame to expand

        self.title_label = ttk.Label(self, text="Image Preview:")
        self.title_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=(0, 2))

        # Frame to hold the preview label, providing a border
        preview_frame = ttk.Frame(self, relief=tk.SUNKEN, borderwidth=1)
        preview_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0, 5))
        preview_frame.grid_rowconfigure(0, weight=1)
        preview_frame.grid_columnconfigure(0, weight=1)

        # Label to display the thumbnail
        self.preview_label = ttk.Label(
            preview_frame,
            text="Select a ZIP file on the left",
            anchor=tk.CENTER,
            background="lightgrey", # Default background
            cursor="hand2" # Indicate clickability
        )
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        # Bind click to open viewer (if enabled)
        self.preview_label.bind("<Button-1>", self._open_image_viewer)

        # Progress bar (initially hidden)
        self.progressbar = Progressbar(self, orient=tk.HORIZONTAL, mode='indeterminate', maximum=100)
        # self.progressbar.grid(...) is done in _show/_hide_thumb_loading

        # --- Set initial size based on largest possible thumbnail ---
        max_thumb_w = max(CONFIG["THUMBNAIL_SIZE"][0], CONFIG["PERFORMANCE_THUMBNAIL_SIZE"][0])
        max_thumb_h = max(CONFIG["THUMBNAIL_SIZE"][1], CONFIG["PERFORMANCE_THUMBNAIL_SIZE"][1])
        # Add padding/border/label height estimate
        estimated_height = max_thumb_h + self.title_label.winfo_reqheight() + 20
        estimated_width = max_thumb_w + 20
        self.config(width=estimated_width, height=estimated_height)
        self.pack_propagate(False) # Prevent frame from shrinking to label size

    def update_preview(self, zip_path: Optional[str], image_members: List[str]):
        """
        Updates the preview panel to show the first image from the given ZIP.
        Clears the preview if zip_path is None or image_members is empty.
        """
        # Cancel any ongoing load for the previous selection
        if self._current_load_future and not self._current_load_future.done():
             self._current_load_future.cancel()
             self._hide_thumb_loading() # Ensure loading indicator is removed

        self._current_zip_path = zip_path
        self._current_image_members = image_members
        self._current_thumb_index = 0 # Reset to first image

        if not zip_path or not image_members:
            self._clear_preview("No images found" if zip_path else "Select a ZIP file")
            self.title_label.config(text="Image Preview:")
            return

        # Update title
        num_images = len(image_members)
        img_text = "image" if num_images == 1 else "images"
        self.title_label.config(text=f"Preview (1 / {num_images} {img_text}):")

        # Load the thumbnail for the first image
        self.load_thumbnail(0)

    def _show_thumb_loading(self):
        """Displays the loading indicator for the thumbnail."""
        if not self.winfo_exists(): return
        self._is_loading_thumb = True

        # Clear previous image/text, show loading text
        self.preview_label.config(image=None, text="Loading thumbnail...")
        self.preview_label.image = None
        self._current_thumb_photo = None

        # Show and start progress bar
        self.progressbar.grid(row=2, column=0, sticky=tk.EW, padx=5, pady=(2, 0))
        self.progressbar.start(10)
        self.update_idletasks()

    def _hide_thumb_loading(self):
        """Hides the loading indicator."""
        if not self.winfo_exists(): return
        self._is_loading_thumb = False

        # Stop and hide progress bar
        self.progressbar.stop()
        self.progressbar.grid_forget()

    def load_thumbnail(self, index: int, force_reload: bool = False):
        """Initiates loading of the thumbnail for the image at the given index."""
        if self._is_loading_thumb and not force_reload:
            return # Avoid concurrent loads unless forced
        if not self._current_zip_path or not (0 <= index < len(self._current_image_members)):
            self._clear_preview("Invalid image index" if self._current_zip_path else "No ZIP selected")
            return

        self._current_thumb_index = index
        member_name = self._current_image_members[index]
        cache_key = (self._current_zip_path, member_name)

        perf_mode = self.settings.get('performance_mode', False)
        thumb_size = (CONFIG["PERFORMANCE_THUMBNAIL_SIZE"] if perf_mode
                      else CONFIG["THUMBNAIL_SIZE"])
        max_load_size = (CONFIG["PERFORMANCE_MAX_THUMBNAIL_LOAD_SIZE"] if perf_mode
                         else CONFIG["MAX_THUMBNAIL_LOAD_SIZE"])

        # --- Check Cache ---
        # We need the *full* image from cache to create the *correct size* thumbnail
        if not force_reload:
            cached_full_image = self.cache.get(cache_key)
            if cached_full_image is not None:
                # Create thumbnail from cached full image
                self._display_pil_thumbnail(cached_full_image, thumb_size)
                # Potentially preload next thumbnail (after current one is displayed)
                self._maybe_preload_next_thumbnail(index + 1)
                return # Loaded from cache

        # --- Load Asynchronously ---
        self._show_thumb_loading()

        if self._current_load_future and not self._current_load_future.done():
             self._current_load_future.cancel()

        self._current_load_future = self.thread_pool.submit(
            load_image_data_async,
            self._current_zip_path,
            member_name,
            max_load_size,
            thumb_size, # Request thumbnail size directly
            self.result_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            perf_mode,
            force_reload
        )

    def handle_thumbnail_result(self, result: LoadResult):
        """Processes the result of an asynchronous thumbnail load."""
        if not self.winfo_exists(): return # Window closed

        # Check if the result matches the *currently expected* thumbnail
        if not self._current_zip_path or not self._current_image_members: return
        try:
            expected_key = (self._current_zip_path, self._current_image_members[self._current_thumb_index])
        except IndexError:
            return # Index changed before result arrived

        if result.cache_key != expected_key:
            # Result is for a different/older request, ignore
            return

        self._hide_thumb_loading() # Hide progress bar

        if result.success and isinstance(result.data, Image.Image):
            # The async function already returned a thumbnailed image
            # Convert directly to PhotoImage
            try:
                self._current_thumb_photo = ImageTk.PhotoImage(result.data)
                self.preview_label.config(image=self._current_thumb_photo, text="")
                self.preview_label.image = self._current_thumb_photo
                # Update title label to reflect the current index
                num_images = len(self._current_image_members)
                img_text = "image" if num_images == 1 else "images"
                self.title_label.config(text=f"Preview ({self._current_thumb_index + 1} / {num_images} {img_text}):")
                 # Potentially preload next thumbnail
                self._maybe_preload_next_thumbnail(self._current_thumb_index + 1)
            except Exception as e:
                print(f"Preview Error: Creating PhotoImage failed: {e}")
                self._show_message(f"Display error:\n{type(e).__name__}")
                self.preview_label.image = None
                self._current_thumb_photo = None
        else:
            # Load failed
            self._show_message(f"Cannot load thumb:\n{result.error_message}")

    def _display_pil_thumbnail(self, pil_image: Image.Image, target_thumb_size: Tuple[int, int]):
        """
        Creates and displays a thumbnail from a given PIL Image.
        Assumes pil_image is the full-resolution image.
        """
        if not self.winfo_exists(): return

        try:
            # Create a thumbnail copy respecting aspect ratio
            img_copy = pil_image.copy()
            perf_mode = self.settings.get('performance_mode', False)
            resampling = (Image.Resampling.NEAREST if perf_mode
                          else Image.Resampling.LANCZOS)
            img_copy.thumbnail(target_thumb_size, resampling)

            # Convert to Tkinter PhotoImage
            self._current_thumb_photo = ImageTk.PhotoImage(img_copy)

            # Update the preview label
            self.preview_label.config(image=self._current_thumb_photo, text="")
            self.preview_label.image = self._current_thumb_photo # Keep reference

            # Update title label
            num_images = len(self._current_image_members)
            img_text = "image" if num_images == 1 else "images"
            self.title_label.config(text=f"Preview ({self._current_thumb_index + 1} / {num_images} {img_text}):")

        except Exception as e:
            print(f"Preview Error: Displaying PIL thumbnail failed: {e}")
            self._show_message(f"Display error:\n{type(e).__name__}")
            self.preview_label.image = None
            self._current_thumb_photo = None

    def _maybe_preload_next_thumbnail(self, next_index: int):
        """Preloads the next thumbnail if conditions are met."""
        if not self.winfo_exists() or self._is_loading_thumb:
            return
        # Check settings: enabled globally and not in performance mode
        if not self.settings.get('preload_next_thumbnail', False) or self.settings.get('performance_mode', False):
             return
        # Check if next index is valid
        if not self._current_zip_path or not (0 <= next_index < len(self._current_image_members)):
            return

        next_member_name = self._current_image_members[next_index]
        next_cache_key = (self._current_zip_path, next_member_name)

        # Check if already cached
        if next_cache_key in self.cache:
            return

        # --- Submit preload task ---
        # print(f"Preloading next thumbnail: {next_member_name}") # Debug
        perf_mode = self.settings.get('performance_mode', False) # Re-check just in case
        thumb_size = (CONFIG["PERFORMANCE_THUMBNAIL_SIZE"] if perf_mode
                      else CONFIG["THUMBNAIL_SIZE"])
        max_load_size = (CONFIG["PERFORMANCE_MAX_THUMBNAIL_LOAD_SIZE"] if perf_mode
                         else CONFIG["MAX_THUMBNAIL_LOAD_SIZE"])

        # Submit preload task (result goes to main queue but typically ignored unless needed)
        self.thread_pool.submit(
            load_image_data_async,
            self._current_zip_path,
            next_member_name,
            max_load_size,
            thumb_size, # Request thumbnail size
            self.result_queue,
            self.cache,
            next_cache_key,
            self.zip_manager,
            perf_mode,
            False # Don't force reload
        )


    def _open_image_viewer(self, event=None):
        """Opens the multi-image viewer window."""
        # Check if viewer is enabled in settings
        if not self.settings.get('viewer_enabled', True):
            messagebox.showinfo("Viewer Disabled", "The multi-image viewer is disabled in Settings.", parent=self)
            return

        # Check if we have valid data to show
        if not self._current_zip_path or not self._current_image_members:
            messagebox.showwarning("No Image Selected", "Cannot open viewer: No ZIP file or images selected.", parent=self)
            return

        # Check if still loading the *current* thumbnail (might be confusing to open viewer)
        if self._is_loading_thumb:
            messagebox.showinfo("Loading", "Please wait for the current thumbnail to load before opening the viewer.", parent=self)
            return

        # Open the viewer window
        ImageViewerWindow(
            self.master_app, # Pass the main Tk root window
            self._current_zip_path,
            self._current_image_members,
            self._current_thumb_index, # Start viewer at the currently previewed image
            self.settings,
            self.cache,
            self.result_queue,
            self.thread_pool,
            self.zip_manager
        )

    def _show_message(self, text: str):
        """Displays a text message in the preview area."""
        if not self.winfo_exists(): return
        # Clear any image and set the text
        self.preview_label.config(image='', text=text)
        self.preview_label.image = None
        self._current_thumb_photo = None
         # Reset title if showing a general message
        if "Select a ZIP" in text or "No images" in text:
             self.title_label.config(text="Image Preview:")


    def _clear_preview(self, message: str = "Select a ZIP file on the left"):
        """Clears the preview area and resets state."""
        if self._current_load_future and not self._current_load_future.done():
             self._current_load_future.cancel()
        self._hide_thumb_loading() # Ensure progress bar is hidden
        self._show_message(message) # Display the provided message

        # Reset internal state
        self._current_zip_path = None
        self._current_image_members = []
        self._current_thumb_index = 0
        self._current_thumb_photo = None
        self.title_label.config(text="Image Preview:")


# --- Filter Frame UI ---
class FilterFrame(ttk.LabelFrame):
    """Frame containing filtering options."""
    def __init__(self, master, apply_callback: Callable, clear_callback: Callable, **kwargs):
        super().__init__(master, text="Filters", padding="5", **kwargs)
        self.apply_callback = apply_callback
        self.clear_callback = clear_callback

        # --- Filter Variables ---
        self.min_size_var = tk.StringVar()
        self.max_size_var = tk.StringVar()
        self.min_count_var = tk.StringVar()
        self.max_count_var = tk.StringVar()

        # --- Layout ---
        row = 0
        # Size Filter
        ttk.Label(self, text="Size:").grid(row=row, column=0, sticky=tk.W, padx=(0, 2), pady=2)
        ttk.Entry(self, textvariable=self.min_size_var, width=8).grid(row=row, column=1, sticky=tk.EW, pady=2)
        ttk.Label(self, text="-").grid(row=row, column=2, padx=2, pady=2)
        ttk.Entry(self, textvariable=self.max_size_var, width=8).grid(row=row, column=3, sticky=tk.EW, pady=2)
        ttk.Label(self, text="(e.g., 500K, 10M)").grid(row=row, column=4, sticky=tk.W, padx=(2, 10), pady=2) # Example format

        # Image Count Filter
        ttk.Label(self, text="Images:").grid(row=row, column=5, sticky=tk.W, padx=(10, 2), pady=2)
        ttk.Entry(self, textvariable=self.min_count_var, width=5).grid(row=row, column=6, sticky=tk.EW, pady=2)
        ttk.Label(self, text="-").grid(row=row, column=7, padx=2, pady=2)
        ttk.Entry(self, textvariable=self.max_count_var, width=5).grid(row=row, column=8, sticky=tk.EW, pady=2)

        # Buttons (Aligned Right)
        self.grid_columnconfigure(9, weight=1) # Push buttons to the right
        button_frame = ttk.Frame(self)
        button_frame.grid(row=row, column=10, sticky=tk.E, padx=(10, 0), pady=2)

        self.apply_button = ttk.Button(button_frame, text="Apply", command=self.apply_callback, width=7)
        self.apply_button.pack(side=tk.LEFT, padx=(0, 2))

        self.clear_button = ttk.Button(button_frame, text="Clear", command=self.clear_callback, width=7)
        self.clear_button.pack(side=tk.LEFT)

    def get_filter_values(self) -> Optional[Dict[str, Optional[int]]]:
        """Parses entry fields and returns filter criteria, or None on error."""
        values: Dict[str, Optional[int]] = {
            "min_size": None, "max_size": None,
            "min_count": None, "max_count": None
        }
        error_messages = []

        try:
            # Parse Sizes
            min_s = parse_human_size(self.min_size_var.get())
            max_s = parse_human_size(self.max_size_var.get())
            if min_s == -1: error_messages.append("Invalid minimum size format.")
            if max_s == -1: error_messages.append("Invalid maximum size format.")
            values["min_size"] = min_s if min_s != -1 else None
            values["max_size"] = max_s if max_s != -1 else None

            # Parse Counts
            min_c_str = self.min_count_var.get().strip()
            max_c_str = self.max_count_var.get().strip()
            if min_c_str:
                if not min_c_str.isdigit(): error_messages.append("Minimum count must be a number.")
                else: values["min_count"] = int(min_c_str)
            if max_c_str:
                 if not max_c_str.isdigit(): error_messages.append("Maximum count must be a number.")
                 else: values["max_count"] = int(max_c_str)

            # Validate Ranges
            if values["min_size"] is not None and values["min_size"] < 0:
                 error_messages.append("Minimum size cannot be negative.")
            if values["max_size"] is not None and values["max_size"] < 0:
                 error_messages.append("Maximum size cannot be negative.")
            if values["min_count"] is not None and values["min_count"] < 0:
                 error_messages.append("Minimum count cannot be negative.")
            if values["max_count"] is not None and values["max_count"] < 0:
                 error_messages.append("Maximum count cannot be negative.")

            if (values["min_size"] is not None and values["max_size"] is not None and
                    values["min_size"] > values["max_size"]):
                error_messages.append("Minimum size cannot be greater than maximum size.")
            if (values["min_count"] is not None and values["max_count"] is not None and
                    values["min_count"] > values["max_count"]):
                 error_messages.append("Minimum count cannot be greater than maximum count.")

            if error_messages:
                messagebox.showerror("Filter Error", "\n".join(error_messages), parent=self)
                return None
            else:
                return values

        except ValueError: # Catch potential int() conversion errors (though isdigit checks help)
            messagebox.showerror("Filter Error", "Invalid numeric value entered.", parent=self)
            return None

    def clear_entries(self):
        """Clears all filter input fields."""
        self.min_size_var.set("")
        self.max_size_var.set("")
        self.min_count_var.set("")
        self.max_count_var.set("")

    def set_children_state(self, new_state: str):
        """Sets the state ('normal' or 'disabled') for interactive child widgets."""
        valid_states = {'normal', 'disabled', 'readonly'}
        if new_state not in valid_states:
            print(f"Warning: Invalid state '{new_state}' passed to set_children_state.")
            return

        # Iterate through direct children
        for child in self.winfo_children():
            # Handle nested frames (like the button frame)
            if isinstance(child, (ttk.Frame, tk.Frame)):
                 for sub_child in child.winfo_children():
                    try:
                         # Check if the widget supports the 'state' option
                         if 'state' in sub_child.configure():
                             sub_child.config(state=new_state)
                    except tk.TclError:
                         # Ignore widgets without a 'state' option (like Labels in the sub-frame)
                         pass
            else:
                 # Handle direct children (Entries, Buttons, etc.)
                try:
                     if 'state' in child.configure():
                         child.config(state=new_state)
                except tk.TclError:
                     # Ignore widgets without 'state' (like Labels)
                     pass


# --- Main Application ---
class MainApplication(ttk.Frame):
    """Main application window and logic."""

    # Type alias for the result of ZipScanner.analyze_zip
    AnalysisResult = Tuple[bool, Optional[List[str]], Optional[float], Optional[int], int]

    def __init__(self, master: Union[tk.Tk, TkinterDnD.Tk]):
        super().__init__(master, padding="5")
        self.master = master # The root Tk window (potentially DnD enabled)

        # --- Core Components ---
        self.app_settings: Dict[str, Any] = {
            'performance_mode': False,
            'viewer_enabled': True,
            'preload_next_thumbnail': CONFIG['PRELOAD_NEXT_THUMBNAIL'],
        }
        self.image_cache: LRUCache = self._create_cache() # Initialize with correct size
        self.zip_manager: ZipFileManager = ZipFileManager()
        self.load_result_queue = queue.Queue() # For image load results
        self.thread_pool = ThreadPoolExecutor(max_workers=CONFIG["THREAD_POOL_WORKERS"])

        # --- State Variables ---
        self.stop_scan_event = threading.Event()
        self.current_scan_thread: Optional[threading.Thread] = None
        # Stores {zip_path: (image_members, basename, mod_time, size_bytes, image_count)}
        self.found_zip_details: Dict[str, Tuple[List[str], str, float, int, int]] = {}
        # Metadata Cache: {zip_path: (mod_time, AnalysisResult)}
        self.metadata_cache: Dict[str, Tuple[float, MainApplication.AnalysisResult]] = {}
        # Treeview sorting state
        self._sort_column: str = "Name"
        self._sort_reverse: bool = False
        # Preview update debounce timer ID
        self.preview_job_id: Optional[str] = None
        # Filter state
        self.filter_criteria: Dict[str, Optional[int]] = {
            "min_size": None, "max_size": None, "min_count": None, "max_count": None
        }
        self.is_filtered: bool = False

        # --- Window Setup ---
        self.master.title(f"Zip Image Finder v{CONFIG['APP_VERSION']}")
        self.master.geometry(CONFIG["WINDOW_SIZE"])
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.pack(fill=tk.BOTH, expand=True)

        # --- Initialize UI ---
        self._setup_ui()

        # --- Setup Drag & Drop (if available) ---
        if DND_ENABLED and hasattr(self.master, 'drop_target_register'):
            try:
                 # Register the main frame or the listbox/treeview for dropping
                 self.master.drop_target_register(DND_FILES)
                 self.master.dnd_bind('<<Drop>>', self._handle_drop)
                 self.update_status("Ready. Drag & drop folders here to scan.")
            except Exception as e:
                 print(f"Error setting up DND: {e}")
                 self.update_status("Ready. (DND setup failed)")
        else:
            self.update_status("Ready. (Drag & Drop disabled - tkinterdnd2 not found)")

        # Start the queue processor loop
        self.master.after(100, self._process_load_queue)

    def _create_cache(self) -> LRUCache:
        """Creates the LRUCache with size based on settings."""
        is_perf = self.app_settings.get('performance_mode', False)
        capacity = (CONFIG['CACHE_MAX_ITEMS_PERFORMANCE'] if is_perf
                    else CONFIG['CACHE_MAX_ITEMS_NORMAL'])
        print(f"Initializing cache with capacity: {capacity} (Performance Mode: {is_perf})")
        return LRUCache(capacity)

    def _update_cache_capacity(self):
        """Resizes the cache based on current performance mode setting."""
        is_perf = self.app_settings.get('performance_mode', False)
        new_capacity = (CONFIG['CACHE_MAX_ITEMS_PERFORMANCE'] if is_perf
                        else CONFIG['CACHE_MAX_ITEMS_NORMAL'])
        old_capacity = self.image_cache.capacity
        if new_capacity != old_capacity:
            print(f"Resizing cache capacity from {old_capacity} to {new_capacity} (Performance Mode: {is_perf})")
            self.image_cache.resize(new_capacity)
            self.update_status(f"Cache capacity set to {new_capacity}.")

    def _setup_ui(self):
        """Creates and arranges all UI elements."""
        # --- Top: Directory Selection ---
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(top_frame, text="Target Directory:").pack(side=tk.LEFT, padx=(0, 5))
        self.dir_entry_var = tk.StringVar()
        self.dir_entry = ttk.Entry(top_frame, textvariable=self.dir_entry_var, width=60)
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.dir_entry.bind("<Return>", lambda e: self.start_scan()) # Scan on Enter
        self.browse_button = ttk.Button(top_frame, text="Browse...", command=self.browse_directory)
        self.browse_button.pack(side=tk.LEFT, padx=(5, 0))

        # --- Filter Frame ---
        self.filter_frame = FilterFrame(self, apply_callback=self._apply_filter, clear_callback=self._clear_filter)
        self.filter_frame.pack(fill=tk.X, pady=5)

        # --- Action Buttons ---
        action_frame = ttk.Frame(self)
        action_frame.pack(fill=tk.X, pady=5)
        self.scan_button = ttk.Button(action_frame, text="Scan Folder", command=self.start_scan)
        self.scan_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(action_frame, text="Stop Scan", command=self.stop_scan, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(5, 0))
        self.export_button = ttk.Button(action_frame, text="Export List", command=self.export_list, state=tk.DISABLED)
        self.export_button.pack(side=tk.LEFT, padx=(5, 0))
        # Spacer to push right-side buttons
        ttk.Frame(action_frame).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.clear_cache_button = ttk.Button(action_frame, text="Clear Cache", command=self.clear_image_cache)
        self.clear_cache_button.pack(side=tk.LEFT, padx=(5, 0))
        self.settings_button = ttk.Button(action_frame, text="Settings", command=self.open_settings_dialog)
        self.settings_button.pack(side=tk.LEFT, padx=(5, 0))


        # --- Main Paned Window (List | Preview) ---
        main_pane = PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, pady=5)

        # --- Left Pane: Treeview List ---
        list_frame = ttk.Frame(main_pane)
        main_pane.add(list_frame, weight=3) # Give list more initial space

        # Label above the list (reference stored to update text)
        self.list_label = ttk.Label(list_frame, text="Found ZIP Archives:")
        self.list_label.pack(anchor=tk.W, padx=5)

        tree_frame = ttk.Frame(list_frame) # Frame to hold tree and scrollbar
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 0), padx=5)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("Name", "Date Modified", "Size", "Image Count"),
            show="headings", # Hide the default first empty column
            selectmode=tk.BROWSE # Only allow single selection
        )
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure Treeview Columns & Headings
        col_widths = {"Name": 300, "Date Modified": 140, "Size": 90, "Image Count": 80}
        col_anchors = {"Name": tk.W, "Date Modified": tk.W, "Size": tk.E, "Image Count": tk.E}
        for col, text in {"Name": "Name", "Date Modified": "Modified", "Size": "Size", "Image Count": "Images"}.items():
             self.tree.heading(col, text=text, anchor=col_anchors[col],
                               command=lambda c=col: self.sort_treeview_column(c, False))
             self.tree.column(col, width=col_widths[col], anchor=col_anchors[col], stretch=(col=="Name")) # Only stretch Name

        # Scrollbar for Treeview
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.config(yscrollcommand=scrollbar.set)

        # Treeview Bindings
        self.tree.bind('<<TreeviewSelect>>', self.on_treeview_select)
        self.tree.bind('<Button-3>', self.show_context_menu) # Right-click
        self.tree.bind('<Button-2>', self.show_context_menu) # Middle-click (some platforms)
        # Consider adding Enter key binding to open viewer or file
        self.tree.bind('<Return>', self._on_tree_return)


        # --- Right Pane: Image Preview ---
        self.preview_panel = ImagePreview(
            main_pane, # Parent is the paned window
            settings=self.app_settings,
            cache=self.image_cache,
            result_queue=self.load_result_queue,
            thread_pool=self.thread_pool,
            zip_manager=self.zip_manager
        )
        main_pane.add(self.preview_panel, weight=1) # Give preview less initial space

        # --- Status Bar ---
        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=3)
        self.status_label.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 0))
        # Initial status message set after DND setup

        # Apply initial sort indicator
        self.update_sort_indicator()


    def _process_load_queue(self):
        """Periodically checks and processes results from the image load queue."""
        try:
            while True: # Process all available results non-blockingly
                result: LoadResult = self.load_result_queue.get_nowait()

                # Identify the target for this result (viewer or preview)
                target_viewer = self._find_viewer_for_result(result)

                if target_viewer and target_viewer.winfo_exists():
                     # Route result to the specific viewer window
                    target_viewer.handle_load_result(result)
                elif self._is_result_for_preview(result):
                    # Route result to the preview panel
                    self.preview_panel.handle_thumbnail_result(result)
                # else:
                    # Result is likely for a closed viewer or an old preview request, discard.
                    # print(f"Discarding result for key: {result.cache_key}") # Debug

        except queue.Empty:
            # Queue is empty, nothing more to process right now
            pass
        except Exception as e:
            # Log errors during queue processing
            print(f"Error processing load queue: {type(e).__name__} - {e}")
        finally:
            # Reschedule the check if the window still exists
            if self.master.winfo_exists():
                self.master.after(100, self._process_load_queue) # Check again in 100ms

    def _find_viewer_for_result(self, result: LoadResult) -> Optional[ImageViewerWindow]:
        """Finds an active ImageViewerWindow that expects this result."""
        if not result.cache_key: return None
        # Iterate through Toplevel windows that are children of the main window
        for win in self.master.winfo_children():
            if isinstance(win, ImageViewerWindow) and win.winfo_exists():
                try:
                    # Check if the viewer's current expected key matches the result's key
                    viewer_expected_key = (win.zip_path, win.image_members[win.current_index])
                    if viewer_expected_key == result.cache_key:
                        return win
                except IndexError:
                    # Viewer's state might have changed, ignore if index is invalid
                    continue
                except Exception as e:
                     print(f"Error checking viewer window state: {e}")
                     continue # Skip problematic window
        return None # No matching active viewer found

    def _is_result_for_preview(self, result: LoadResult) -> bool:
        """Checks if the result corresponds to the current preview panel request."""
        if not result.cache_key or not self.preview_panel.winfo_exists():
            return False
        if not self.preview_panel._current_zip_path or not self.preview_panel._current_image_members:
             return False

        try:
            # Check if the preview panel's expected key matches the result's key
            preview_expected_key = (
                self.preview_panel._current_zip_path,
                self.preview_panel._current_image_members[self.preview_panel._current_thumb_index]
            )
            return preview_expected_key == result.cache_key
        except IndexError:
            # Preview state might have changed rapidly
            return False
        except Exception as e:
             print(f"Error checking preview panel state: {e}")
             return False


    def clear_image_cache(self):
        """Clears the image cache and updates status/preview."""
        num_items = len(self.image_cache)
        self.image_cache.clear()
        self.update_status(f"Image cache cleared ({num_items} items removed).")

        # Force reload the current preview/viewer if something is selected/open
        focused_item_id = self.tree.focus()
        if focused_item_id:
            # Trigger reload for the selected item's preview
            self.on_treeview_select(None, force_update=True) # Force immediate update/reload

        # Force reload for any open viewers (more complex, maybe just notify user)
        viewers_found = 0
        for win in self.master.winfo_children():
             if isinstance(win, ImageViewerWindow) and win.winfo_exists():
                 viewers_found += 1
                 win.load_image(win.current_index, force_reload=True)
        if viewers_found > 0:
             self.update_status(f"Image cache cleared. Reloading content in {viewers_found} viewer(s).")


    def on_treeview_select(self, event: Optional[tk.Event] = None, force_update: bool = False):
        """Handles selection changes in the Treeview with debouncing."""
        # Cancel any previously scheduled preview update
        if self.preview_job_id:
            self.master.after_cancel(self.preview_job_id)
            self.preview_job_id = None

        selected_items = self.tree.selection()
        if not selected_items:
            # Nothing selected, clear the preview
            self.preview_panel.update_preview(None, [])
            return

        focused_item_id = selected_items[0] # Get the single selected item IID (zip_path)

        # Schedule the actual update action after a delay, unless forced
        if force_update:
            self._update_preview_action(focused_item_id)
        else:
            self.preview_job_id = self.master.after(
                CONFIG["PREVIEW_UPDATE_DELAY"],
                self._update_preview_action,
                focused_item_id
            )

    def _update_preview_action(self, item_id: str):
        """The actual action to update the preview panel, called after delay."""
        self.preview_job_id = None # Clear the timer ID
        if not self.master.winfo_exists(): return # App closed

        # Verify the item is still selected (user might have clicked elsewhere quickly)
        current_selection = self.tree.selection()
        if not current_selection or current_selection[0] != item_id:
            return # Selection changed, do nothing

        # Get data for the selected item and update the preview panel
        if item_id in self.found_zip_details:
            image_members, _, _, _, _ = self.found_zip_details[item_id]
            self.preview_panel.update_preview(item_id, image_members)
        else:
            # Should not happen if tree is in sync with found_zip_details
            print(f"Preview Warning: Data for selected item '{item_id}' not found.")
            self.preview_panel.update_preview(None, [])

    def _on_tree_return(self, event: Optional[tk.Event] = None):
        """Handles Enter key press on the Treeview selection."""
        focused_item_id = self.tree.focus()
        if not focused_item_id: return

        # Open the image viewer if enabled and possible
        if (focused_item_id in self.found_zip_details and
                self.found_zip_details[focused_item_id][0] and # Has image members
                self.app_settings.get('viewer_enabled', True)):
            self.preview_panel._open_image_viewer() # Use preview panel's method
        else:
            # Fallback: try opening the file externally
            self.open_zip_file()


    # --- Filter Methods ---
    def _apply_filter(self):
        """Applies the current filter criteria to the Treeview."""
        filter_values = self.filter_frame.get_filter_values()
        if filter_values is None: return # Error during parsing

        self.filter_criteria = filter_values
        # Determine if any filter is active
        self.is_filtered = any(v is not None for v in filter_values.values())

        # --- Re-populate Treeview based on filters ---
        self.tree.delete(*self.tree.get_children()) # Clear existing items
        self.preview_panel._clear_preview() # Clear preview as selection is lost

        filtered_count = 0
        total_count = len(self.found_zip_details)

        for zip_path, data in self.found_zip_details.items():
            img_list, basename, mod_time, size_bytes, img_count = data

            # Apply filters
            passes = True
            if self.filter_criteria["min_size"] is not None and size_bytes < self.filter_criteria["min_size"]:
                passes = False
            if passes and self.filter_criteria["max_size"] is not None and size_bytes > self.filter_criteria["max_size"]:
                passes = False
            if passes and self.filter_criteria["min_count"] is not None and img_count < self.filter_criteria["min_count"]:
                passes = False
            if passes and self.filter_criteria["max_count"] is not None and img_count > self.filter_criteria["max_count"]:
                passes = False

            if passes:
                filtered_count += 1
                display_mod = format_datetime(mod_time)
                display_size = format_size(size_bytes)
                self.tree.insert('', tk.END, iid=zip_path, values=(basename, display_mod, display_size, str(img_count)))

        # --- Update UI ---
        # Re-apply sorting to the filtered list
        if filtered_count > 0:
            self.sort_treeview_column(self._sort_column, self._sort_reverse, force_apply=True)

        # Update list label and status
        if self.is_filtered:
            self.list_label.config(text=f"Filtered Results ({filtered_count} / {total_count}):")
            self.update_status(f"Filter applied. Showing {filtered_count} of {total_count} items.")
        else:
            self.list_label.config(text=f"Found ZIP Archives ({total_count}):") # Show total count even if not filtered
            self.update_status(f"Filter cleared. Showing {total_count} items.")

        # Update export button state based on whether items are visible
        self.export_button.config(state=tk.NORMAL if filtered_count > 0 else tk.DISABLED)

    def _clear_filter(self):
        """Clears filter entries and reapplies (showing all items)."""
        self.filter_frame.clear_entries()
        # Re-calling apply_filter with empty entries effectively clears the filter
        self._apply_filter()

    # --- Drag & Drop Handling ---
    def _handle_drop(self, event):
        """Handles files/folders dropped onto the application window."""
        if not DND_ENABLED: return

        raw_data = event.data
        print(f"DND Raw Data: {raw_data}") # Debug

        # Parsing DND data can be tricky (spaces, braces, multiple files)
        # This is a basic attempt, might need refinement based on TkinterDnD/OS specifics
        try:
            # Remove potential surrounding braces
            if raw_data.startswith('{') and raw_data.endswith('}'):
                # Handle paths with spaces inside braces: split carefully
                # This requires more robust parsing, maybe regex or specific library
                # For now, assume simple space separation after removing braces
                 paths_str = raw_data[1:-1]
                 # TODO: Improve parsing for paths with spaces if '{path one} {path two}' format is used
                 potential_paths = paths_str.split() # Basic split, fails on spaces within paths
            else:
                # Assume space-separated list without braces
                potential_paths = raw_data.split()

            # Find the first valid directory among dropped items
            first_valid_dir = None
            for path in potential_paths:
                # Simple clean-up attempt (might remove valid chars if path has escapes)
                cleaned_path = path.strip()
                if cleaned_path and os.path.exists(cleaned_path) and os.path.isdir(cleaned_path):
                    first_valid_dir = cleaned_path
                    break # Use the first directory found

            if first_valid_dir:
                self.update_status(f"Detected drop: {os.path.basename(first_valid_dir)}")
                # Check if a scan is already running
                if self.current_scan_thread and self.current_scan_thread.is_alive():
                    messagebox.showwarning("Scan in Progress",
                                           "A scan is already running. Please wait or stop it first.",
                                           parent=self)
                    return

                # Set the directory and start scanning after a short delay
                self.dir_entry_var.set(first_valid_dir)
                self.after(100, self.start_scan) # Use 'after' to avoid issues within event handler

            else:
                self.update_status("Drop detected, but no valid directory found.")
                messagebox.showwarning("Invalid Drop",
                                       "Please drop a single folder containing ZIP files.",
                                       parent=self)
        except Exception as e:
            print(f"Error processing drop event: {e}")
            self.update_status("Error processing dropped item(s).")

    # --- Other Methods ---
    def open_settings_dialog(self):
        """Opens the settings dialog and updates cache/preview if settings change."""
        # Store state before opening dialog
        old_perf_mode = self.app_settings.get('performance_mode', False)

        # Open the dialog (it's modal, code pauses here)
        SettingsDialog(self.master, self.app_settings)

        # Settings might have changed, check and apply
        new_perf_mode = self.app_settings.get('performance_mode', False)

        # Update cache capacity if performance mode changed
        if old_perf_mode != new_perf_mode:
            self._update_cache_capacity()
            # Force reload of current preview if performance mode changed quality
            focused_item_id = self.tree.focus()
            if focused_item_id:
                 self.on_treeview_select(None, force_update=True)

        # Update viewer setting status (no immediate action needed, checked on click/key)
        viewer_enabled = self.app_settings.get('viewer_enabled', True)
        self.update_status(f"Settings updated. Viewer: {'Enabled' if viewer_enabled else 'Disabled'}.")


    def browse_directory(self):
        """Opens a dialog to select a directory."""
        # Suggest initial directory based on current entry or CWD
        initial_dir = self.dir_entry_var.get() or os.getcwd()
        directory = filedialog.askdirectory(
            title="Select Folder Containing ZIP Archives",
            initialdir=initial_dir,
            parent=self.master # Ensure dialog is parented correctly
        )
        if directory:
            self.dir_entry_var.set(directory)
            self.update_status(f"Directory selected: {directory}")
            # Clear previous results when a new directory is chosen manually
            self.clear_results_and_scan_state()


    def clear_results_and_scan_state(self):
        """Clears results, treeview, caches, filters, and resets UI state."""
        # Stop any active scan first
        if self.current_scan_thread and self.current_scan_thread.is_alive():
            self.stop_scan()
            # Need to wait briefly for thread to potentially acknowledge stop?
            # This is tricky. Best practice might be to disable clear while scanning.
            # For now, proceed assuming stop_scan works quickly enough.

        # Clear Treeview
        self.tree.delete(*self.tree.get_children())

        # Clear Data Stores
        self.found_zip_details.clear()
        self.metadata_cache.clear()
        # Don't clear image cache here, use dedicated button/setting change

        # Clear Preview
        self.preview_panel._clear_preview("Select a ZIP file on the left")

        # Clear Filters
        self.filter_frame.clear_entries()
        self.is_filtered = False
        self.filter_criteria = {k: None for k in self.filter_criteria}

        # Reset Sorting
        self._sort_column = "Name"
        self._sort_reverse = False
        self.update_sort_indicator()

        # Reset Labels and Buttons
        self.list_label.config(text="Found ZIP Archives:")
        self.export_button.config(state=tk.DISABLED)
        # Ensure scan/stop buttons are in correct idle state
        self.scan_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.browse_button.config(state=tk.NORMAL)
        self.filter_frame.set_children_state(tk.NORMAL)
        self.settings_button.config(state=tk.NORMAL)
        self.clear_cache_button.config(state=tk.NORMAL)


        self.update_status("Results, cache, and filters cleared.")

    def update_status(self, message: str):
        """Updates the status bar message safely from any thread."""
        # Use 'after' to ensure UI update happens in the main thread
        if self.master.winfo_exists():
            self.master.after(0, lambda: self.status_var.set(message))

    def add_result(
        self,
        zip_path: str,
        image_members: List[str],
        basename: str,
        mod_time: float,
        size: int,
        image_count: int
    ):
        """
        Adds a validated ZIP file result to the internal store and potentially
        to the Treeview if it passes the current filter. Scheduled via `after`.
        """
        def _add_task():
            if not self.master.winfo_exists(): return

            # 1. Store the full details regardless of filter
            self.found_zip_details[zip_path] = (
                image_members, basename, mod_time, size, image_count
            )

            # 2. Check against current filter criteria
            passes_filter = True
            if self.is_filtered:
                if self.filter_criteria["min_size"] is not None and size < self.filter_criteria["min_size"]:
                    passes_filter = False
                if passes_filter and self.filter_criteria["max_size"] is not None and size > self.filter_criteria["max_size"]:
                    passes_filter = False
                if passes_filter and self.filter_criteria["min_count"] is not None and image_count < self.filter_criteria["min_count"]:
                    passes_filter = False
                if passes_filter and self.filter_criteria["max_count"] is not None and image_count > self.filter_criteria["max_count"]:
                    passes_filter = False

            # 3. Insert into Treeview if passes filter (or if not filtering)
            if passes_filter:
                display_mod = format_datetime(mod_time)
                display_size = format_size(size)
                try:
                     self.tree.insert('', tk.END, iid=zip_path, values=(basename, display_mod, display_size, str(image_count)))
                except tk.TclError as e:
                     # Could happen if item already exists due to race condition/bug
                     print(f"Warning: Failed to insert item {zip_path} into tree: {e}")


            # 4. Enable export button if any item is visible in the tree
            if self.tree.get_children() and self.export_button['state'] == tk.DISABLED:
                self.export_button.config(state=tk.NORMAL)

        # Schedule the task to run in the main thread
        if self.master.winfo_exists():
            self.master.after(0, _add_task)


    def scan_complete(self, message: str):
        """Actions to perform when the scan finishes or is stopped."""
        def _complete_task():
            if not self.master.winfo_exists(): return

            # Update status bar with final message
            self.update_status(message)

            # Apply final sort to the (potentially filtered) treeview
            if self.tree.get_children():
                self.sort_treeview_column(self._sort_column, self._sort_reverse, force_apply=True)

            # Update list label to reflect final counts (considering filters)
            total_found = len(self.found_zip_details)
            visible_count = len(self.tree.get_children())
            if self.is_filtered:
                self.list_label.config(text=f"Filtered Results ({visible_count} / {total_found}):")
            else:
                self.list_label.config(text=f"Found ZIP Archives ({total_found}):")


            # Re-enable UI elements
            self.scan_button.config(state=tk.NORMAL)
            self.browse_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED) # Scan finished/stopped
            self.settings_button.config(state=tk.NORMAL)
            self.clear_cache_button.config(state=tk.NORMAL)
            # Re-enable filter frame controls
            self.filter_frame.set_children_state(tk.NORMAL)
            # Enable export only if items are visible
            self.export_button.config(state=tk.NORMAL if visible_count > 0 else tk.DISABLED)
            # Re-enable treeview interaction (if it was disabled)
            # self.tree.config(state=tk.NORMAL) # If state was changed

            # Clear the reference to the finished thread
            self.current_scan_thread = None

        # Schedule the task for the main thread
        if self.master.winfo_exists():
            self.master.after(0, _complete_task)


    def start_scan(self):
        """Initiates the directory scanning process."""
        directory = self.dir_entry_var.get()
        if not directory:
            messagebox.showerror("Input Error", "Please select a directory first.", parent=self)
            return
        if not os.path.isdir(directory):
             messagebox.showerror("Input Error", f"The specified path is not a valid directory:\n{directory}", parent=self)
             return
        if self.current_scan_thread and self.current_scan_thread.is_alive():
            messagebox.showwarning("Scan Active", "A scan is already in progress.", parent=self)
            return

        # --- Prepare for Scan ---
        self.clear_results_and_scan_state() # Clear previous data/state
        self.update_status("Initializing scan...")

        # Disable UI elements during scan
        self.scan_button.config(state=tk.DISABLED)
        self.browse_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL) # Enable stop button
        self.export_button.config(state=tk.DISABLED)
        self.settings_button.config(state=tk.DISABLED)
        self.clear_cache_button.config(state=tk.DISABLED)
        # Disable filter frame controls
        self.filter_frame.set_children_state(tk.DISABLED)
        # Optionally disable treeview interaction (prevents selection changes during async adds)
        # self.tree.config(state=tk.DISABLED)


        # --- Start Scan Thread ---
        self.stop_scan_event.clear() # Reset stop flag
        self.current_scan_thread = threading.Thread(
            target=self._run_scan_task, # Target the actual scanning function
            args=(directory,),
            daemon=True # Allow app to exit even if thread hangs (though cleanup is better)
        )
        self.current_scan_thread.start()

    def _run_scan_task(self, directory: str):
        """The actual scanning logic executed in a separate thread."""
        found_count: int = 0
        processed_count: int = 0
        cache_hits: int = 0
        error_files: List[str] = [] # Store basenames of files causing errors

        try:
            self.update_status("Scanning directory for .zip files...")
            zip_files: List[str] = []
            # Use scandir for potentially better performance on large directories
            try:
                with os.scandir(directory) as it:
                    for entry in it:
                        # Check stop flag periodically
                        if self.stop_scan_event.is_set(): break
                        # Check if it's a file and ends with .zip (case-insensitive)
                        if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith('.zip'):
                            zip_files.append(entry.path)
            except PermissionError:
                self.scan_complete("Scan Error: Permission denied reading directory contents.")
                return
            except FileNotFoundError:
                 self.scan_complete("Scan Error: Target directory not found.")
                 return
            except OSError as e:
                 self.scan_complete(f"Scan Error: OS error listing directory: {e}")
                 return

            # Check if stopped during directory listing
            if self.stop_scan_event.is_set():
                self.scan_complete("Scan stopped by user during directory listing.")
                return

            total_zips = len(zip_files)
            if total_zips == 0:
                self.scan_complete("Scan Complete: No .zip files found in the directory.")
                return

            self.update_status(f"Found {total_zips} .zip files. Analyzing contents...")

            # --- Analyze each ZIP file ---
            for idx, zip_path in enumerate(zip_files):
                if self.stop_scan_event.is_set(): break # Check stop flag before processing each file

                processed_count += 1
                basename = os.path.basename(zip_path)

                # Update status periodically
                if idx % CONFIG["BATCH_UPDATE_INTERVAL"] == 0 or idx == total_zips - 1:
                    self.update_status(f"Processing ({processed_count}/{total_zips}): {basename}")

                # --- Metadata Cache Logic ---
                analysis_result: Optional[MainApplication.AnalysisResult] = None
                current_mod_time: Optional[float] = None
                try:
                    # Get current mod time safely
                    if os.path.exists(zip_path): # Re-check existence
                        current_mod_time = os.stat(zip_path).st_mtime
                    else:
                        print(f"Scan Info: File disappeared during scan: {basename}")
                        continue # Skip file that vanished
                except (OSError, PermissionError) as e:
                     print(f"Scan Warning: Cannot get status for {basename}: {e}")
                     error_files.append(f"{basename} (stat failed)")
                     continue # Skip file if stat fails

                # Check cache if mod time is available
                if current_mod_time is not None and zip_path in self.metadata_cache:
                    cached_mod_time, cached_result = self.metadata_cache[zip_path]
                    # Use cache only if modification time matches exactly
                    if cached_mod_time == current_mod_time:
                        analysis_result = cached_result
                        cache_hits += 1
                    # else: Cache is stale, needs re-analysis

                # --- Perform Analysis (if not cached or stale) ---
                if analysis_result is None:
                    analysis_result = ZipScanner.analyze_zip(zip_path)
                    # Update cache if analysis provided a mod time and result
                    # Use the mod_time obtained *during analysis* if available, otherwise use the one we got earlier
                    mod_time_from_analysis = analysis_result[2]
                    effective_mod_time = mod_time_from_analysis if mod_time_from_analysis is not None else current_mod_time

                    if effective_mod_time is not None:
                         self.metadata_cache[zip_path] = (effective_mod_time, analysis_result)

                # --- Process Analysis Result ---
                is_valid, image_members, mod_time_res, file_size, image_count = analysis_result

                if is_valid and image_members is not None and mod_time_res is not None and file_size is not None:
                    # Valid ZIP containing only images
                    found_count += 1
                    self.add_result(zip_path, image_members, basename, mod_time_res, file_size, image_count)
                elif file_size is None and mod_time_res is None:
                     # Analysis likely failed early (file not found, bad zip etc.)
                     # Error logged within analyze_zip or during stat
                     if f"{basename} (stat failed)" not in error_files: # Avoid double listing
                         error_files.append(f"{basename} (analysis failed)")
                # else: File exists but is invalid (e.g., contains non-images, empty, etc.)
                # No error message needed here, it's just not a match.

            # --- Finalize Scan ---
            if self.stop_scan_event.is_set():
                final_message = f"Scan stopped by user. Processed {processed_count}/{total_zips} files."
            else:
                final_message = f"Scan Complete. Found {found_count} valid image archives."
                if cache_hits > 0:
                    final_message += f" ({cache_hits} loaded from metadata cache)"
                if error_files:
                    final_message += f" Skipped/failed {len(error_files)} files."
                    # Optionally list errored files:
                    # print("Files with errors:", error_files)

            self.scan_complete(final_message)

        except Exception as e:
            # Catch unexpected errors in the scan loop itself
            print(f"FATAL SCAN ERROR: {type(e).__name__} - {e}")
            import traceback
            traceback.print_exc()
            self.scan_complete(f"Scan failed due to an unexpected error: {e}")

    def stop_scan(self):
        """Signals the scanning thread to stop."""
        if self.current_scan_thread and self.current_scan_thread.is_alive():
            self.update_status("Stopping scan request sent...")
            self.stop_scan_event.set()
            self.stop_button.config(state=tk.DISABLED) # Disable button after click
            # The scan thread will check the event and call scan_complete
        else:
            self.update_status("No scan is currently running.")
            self.stop_button.config(state=tk.DISABLED) # Ensure it's disabled


    def sort_treeview_column(self, column: str, reverse: bool, force_apply: bool = False):
        """Sorts the Treeview items based on the selected column."""
        # Determine sort direction
        if not force_apply and column == self._sort_column:
            # Toggle direction if clicking the same column again
            new_reverse = not self._sort_reverse
        else:
            # Default to ascending when changing columns or forcing apply
            new_reverse = reverse # Use provided reverse only when forced or different col

        # --- Define Sort Key Function ---
        # Default tuple for missing items (shouldn't happen in normal operation)
        default_tuple = ([], '', 0.0, 0, 0)
        try:
            if column == "Size":        # Sort by size_bytes (index 3)
                key_func = lambda iid: self.found_zip_details.get(iid, default_tuple)[3]
            elif column == "Date Modified": # Sort by mod_time (float, index 2)
                key_func = lambda iid: self.found_zip_details.get(iid, default_tuple)[2]
            elif column == "Image Count": # Sort by image_count (int, index 4)
                key_func = lambda iid: self.found_zip_details.get(iid, default_tuple)[4]
            else: # Default to Name (index 1), case-insensitive
                key_func = lambda iid: self.found_zip_details.get(iid, default_tuple)[1].lower()

            # Get list of *currently visible* item IDs from the tree
            item_ids = list(self.tree.get_children('')) # Pass '' for root items

            # Sort the list of IDs using the key function
            item_ids.sort(key=key_func, reverse=new_reverse)

            # Reorder items in the treeview according to the sorted list
            for idx, item_id in enumerate(item_ids):
                self.tree.move(item_id, '', idx) # Move item to new index under root ('')

            # Update internal sort state
            self._sort_column = column
            self._sort_reverse = new_reverse

            # Update visual indicator in column header
            self.update_sort_indicator()

        except KeyError as e:
             print(f"Sorting Error: Key {e} not found in found_zip_details. Tree might be out of sync.")
             messagebox.showerror("Sort Error", f"Data mismatch during sorting. Please rescan or clear.", parent=self)
        except Exception as e:
            print(f"Sorting Error: Unexpected error - {type(e).__name__}: {e}")
            messagebox.showerror("Sort Error", f"An unexpected error occurred during sorting: {e}", parent=self)


    def update_sort_indicator(self):
        """Adds/Removes sort arrows (▲▼) in the Treeview column headers."""
        up_arrow = ' ▲'
        down_arrow = ' ▼'
        try:
            for col in ("Name", "Date Modified", "Size", "Image Count"):
                current_heading = self.tree.heading(col) # Get current heading options
                current_text = current_heading.get("text", "")

                # Remove any existing arrow
                text_without_arrow = current_text.replace(up_arrow, "").replace(down_arrow, "")

                # Add the correct arrow if this is the sorted column
                new_text = text_without_arrow
                if col == self._sort_column:
                    new_text += down_arrow if self._sort_reverse else up_arrow

                # Update the heading text only if it changed
                if new_text != current_text:
                     self.tree.heading(col, text=new_text)
        except tk.TclError as e:
            # Can happen if the treeview is destroyed during update
            print(f"Sort Indicator Warning: TclError - {e}")
        except Exception as e:
             print(f"Sort Indicator Error: Unexpected - {type(e).__name__} - {e}")


    def export_list(self):
        """Exports the *currently visible* list of ZIP file paths to a text file."""
        # Get IDs (paths) of items currently shown in the tree
        items_to_export = self.tree.get_children('')

        if not items_to_export:
            messagebox.showinfo("Export Empty", "There are no items currently visible in the list to export.", parent=self)
            return

        # Ask user for save location
        initial_filename = "image_zip_list"
        if self.is_filtered: initial_filename += "_filtered"
        initial_filename += ".txt"

        filepath = filedialog.asksaveasfilename(
            title="Export Visible List As",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            initialfile=initial_filename,
            parent=self.master
        )

        if not filepath: return # User cancelled

        # Write the list to the file
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                for item_id in items_to_export:
                    # Write the full path (which is the item ID)
                    f.write(item_id + '\n')
            self.update_status(f"List exported successfully to {os.path.basename(filepath)}")
            messagebox.showinfo("Export Successful", f"{len(items_to_export)} file paths exported to:\n{filepath}", parent=self)
        except OSError as e:
            messagebox.showerror("Export Error", f"Failed to write to file:\n{e}", parent=self)
            self.update_status("Export failed: Could not write file.")
        except Exception as e:
             messagebox.showerror("Export Error", f"An unexpected error occurred during export:\n{e}", parent=self)
             self.update_status("Export failed: Unexpected error.")

    # --- Context Menu Methods ---

    def show_context_menu(self, event: tk.Event):
        """Displays a context menu for the selected Treeview item."""
        # Identify the item under the cursor
        item_id = self.tree.identify_row(event.y)
        if not item_id: return # Clicked outside any item

        # Select the item under the cursor if it wasn't already selected
        if item_id not in self.tree.selection():
             self.tree.selection_set(item_id)
             self.tree.focus(item_id) # Also set focus

        # Ensure we have data for this item
        if item_id not in self.found_zip_details:
            print(f"Context Menu Warning: No data for item {item_id}")
            return

        zip_path = item_id # The item ID is the full path
        has_images = bool(self.found_zip_details[zip_path][0]) # Check if image list is not empty
        viewer_enabled = self.app_settings.get('viewer_enabled', True)

        # Create the menu
        context_menu = Menu(self.master, tearoff=0)

        # View Images Command
        if has_images:
            if viewer_enabled:
                 context_menu.add_command(label="View Images...",
                                         command=self.preview_panel._open_image_viewer)
            else:
                 context_menu.add_command(label="View Images... (Disabled)", state=tk.DISABLED)
        else:
            # Should not happen for valid items, but handle defensively
            context_menu.add_command(label="View Images... (No Images)", state=tk.DISABLED)

        context_menu.add_separator()

        # Open File / Folder Commands
        context_menu.add_command(label="Open File Location", command=self.open_containing_folder)
        # Add command to open the zip file itself with default application
        context_menu.add_command(label="Open ZIP File", command=self.open_zip_file)

        context_menu.add_separator()

        # Copy Path Command
        context_menu.add_command(label="Copy Full Path", command=self.copy_selected_paths)

        # Display the menu at the cursor position
        try:
             context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            # Ensure the menu is properly destroyed after use
             context_menu.grab_release()


    def get_focused_zip_path(self) -> Optional[str]:
        """Returns the full path of the currently focused item in the Treeview."""
        focused_item_id = self.tree.focus() # Returns the item ID (which is the path)
        # Check if the focused item is one we know about (sanity check)
        if focused_item_id and focused_item_id in self.found_zip_details:
            return focused_item_id
        return None

    def get_selected_zip_paths(self) -> List[str]:
        """Returns a list containing the path(s) of selected items (currently single selection)."""
        # Treeview is in BROWSE mode, so selection() returns tuple of one item or empty tuple
        selected_ids = self.tree.selection()
        if selected_ids:
            # Validate the selected item exists in our data
            if selected_ids[0] in self.found_zip_details:
                 return list(selected_ids)
            else:
                 print(f"Selection Warning: Selected item {selected_ids[0]} not in known details.")
                 return []
        return []


    def open_zip_file(self):
        """Opens the selected ZIP file using the system's default application."""
        zip_filepath = self.get_focused_zip_path()
        if not zip_filepath:
             messagebox.showwarning("Action Failed", "No ZIP file selected.", parent=self)
             return
        if not os.path.exists(zip_filepath):
            messagebox.showerror("Error", f"File not found:\n{zip_filepath}", parent=self)
            return

        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(zip_filepath) # Preferred method on Windows
            elif system == "Darwin": # macOS
                subprocess.run(['open', zip_filepath], check=True)
            else: # Linux and other POSIX-like systems
                subprocess.run(['xdg-open', zip_filepath], check=True)
        except FileNotFoundError:
             # This can happen if the helper utility (open, xdg-open) isn't found,
             # or if there's no default application associated with .zip files.
             messagebox.showerror("Error", "Could not find a program to open the ZIP file.", parent=self)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file:\n{e}\nPath: {zip_filepath}", parent=self)


    def open_containing_folder(self):
        """打开包含选中 ZIP 文件的文件夹，并尝试选中该文件。"""
        zip_filepath = self.get_focused_zip_path()
        if not zip_filepath:
            return

        if not os.path.exists(zip_filepath):
            messagebox.showerror("错误", f"文件不存在:\n{zip_filepath}", parent=self.master)
            self._remove_missing_item(zip_filepath)
            return

        folder_path = os.path.dirname(zip_filepath)

        try:
            system = platform.system()
            if system == "Windows":
                # 使用 Windows API 更稳定的方式打开资源管理器并选中文件
                import ctypes
                ctypes.windll.shell32.ShellExecuteW(
                    None, "open", "explorer", f'/select,"{os.path.normpath(zip_filepath)}"', None, 1)
            elif system == "Darwin":
                subprocess.run(['open', '-R', zip_filepath], check=True)
            else:
                subprocess.run(['xdg-open', folder_path], check=True)
        except Exception as e:
            messagebox.showerror("错误", f"打开文件夹时发生错误: {str(e)}", parent=self.master)


    def copy_selected_paths(self):
        """Copies the full path of the selected ZIP file to the clipboard."""
        # Currently supports single selection only due to BROWSE mode
        zip_filepaths = self.get_selected_zip_paths()
        if not zip_filepaths:
            messagebox.showwarning("Action Failed", "No ZIP file selected to copy.", parent=self)
            return

        try:
            clipboard_text = zip_filepaths[0] # Get the single selected path
            self.master.clipboard_clear()
            self.master.clipboard_append(clipboard_text)
            self.update_status(f"Path copied to clipboard: ...{os.path.basename(clipboard_text)}")
        except tk.TclError as e:
            # Might happen if clipboard access is restricted or fails
            messagebox.showerror("Clipboard Error", f"Could not access system clipboard:\n{e}", parent=self)
            self.update_status("Failed to copy path to clipboard.")
        except Exception as e:
             messagebox.showerror("Copy Error", f"An unexpected error occurred while copying:\n{e}", parent=self)
             self.update_status("Failed to copy path: Unexpected error.")

    # --- Application Lifecycle ---

    def on_closing(self):
        """Handles the application window closing event."""
        # Check if scan is running
        if self.current_scan_thread and self.current_scan_thread.is_alive():
            if messagebox.askyesno("Confirm Exit", "A scan is currently in progress. Stop scan and exit?", parent=self):
                self.stop_scan() # Signal the scan thread to stop
                # Give the thread a moment to potentially finish or acknowledge stop
                # before forcing shutdown. This is not guaranteed.
                self.master.after(200, self._shutdown_resources_and_destroy)
            else:
                return # User cancelled exit, do nothing
        else:
            # No scan running, proceed directly to shutdown
            self._shutdown_resources_and_destroy()

    def _shutdown_resources_and_destroy(self):
        """Cleans up resources like threads and file handles before exiting."""
        print("Shutting down application...")
        self.update_status("Shutting down...")

        # 1. Cancel pending UI tasks (like preview updates)
        if self.preview_job_id:
            try:
                self.master.after_cancel(self.preview_job_id)
                self.preview_job_id = None
            except tk.TclError: pass # Ignore if already cancelled/invalid

        # 2. Signal any running scan thread to stop (if not already done)
        if self.current_scan_thread and self.current_scan_thread.is_alive():
             print("Signaling active scan thread to stop during shutdown...")
             self.stop_scan_event.set()
             # Optional: Wait a very short time for thread to potentially exit cleanly
             # self.current_scan_thread.join(timeout=0.5) # Timeout in seconds


        # 3. Shutdown thread pool
        print("Shutting down thread pool...")
        # For Python 3.9+, cancel_futures=True is safer
        cancel_futures_flag = True if platform.python_version_tuple() >= ('3', '9') else False
        # Set wait=False to not block UI, although ideally threads finish quickly
        self.thread_pool.shutdown(wait=False, cancel_futures=cancel_futures_flag)

        # 4. Close managed ZIP files
        print("Closing open ZIP files...")
        self.zip_manager.close_all()

        # 5. Destroy the main window
        if self.master.winfo_exists():
            print("Destroying main window.")
            self.master.destroy()

        print("Shutdown complete.")


# --- Application Entry Point ---
if __name__ == "__main__":
    # Attempt DPI awareness on Windows for sharper UI elements
    try:
        from ctypes import windll
        # Functions might vary: SetProcessDpiAwareness, SetProcessDPIAware
        try:
             windll.shcore.SetProcessDpiAwareness(1) # Newer Windows versions
        except (AttributeError, OSError):
             try:
                 windll.user32.SetProcessDPIAware() # Older Windows versions
             except (AttributeError, OSError):
                 print("DPI Awareness: Could not set DPI awareness.")
    except (ImportError, AttributeError, OSError):
        # Not on Windows or ctypes unavailable
        pass

    # Create the root window (TkinterDnD enabled if available)
    # If TkinterDnD is used, TkinterDnD.Tk() creates the root window.
    # Otherwise, use standard tk.Tk().
    root = TkinterDnD.Tk() if DND_ENABLED else tk.Tk()

    # Create the main application frame within the root window
    app = MainApplication(master=root)

    # Start the Tkinter main event loop
    root.mainloop()