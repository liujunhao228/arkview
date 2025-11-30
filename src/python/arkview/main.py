"""
Main Arkview Application - Hybrid Rust-Python Architecture
"""

import os
import platform
import queue
import re
import subprocess
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageTk
from tkinter import filedialog, messagebox, Menu
from tkinter.scrolledtext import ScrolledText
import ttkbootstrap as ttk
from ttkbootstrap import Style

from .core import (
    ZipScanner, ZipFileManager, LRUCache, load_image_data_async,
    LoadResult, _format_size, RUST_AVAILABLE
)
from .ui import (
    SettingsDialog, ImageViewerWindow, DND_ENABLED, TkinterDnD, DND_FILES, format_datetime
)
from .gallery import GalleryView


CONFIG: Dict[str, Any] = {
    "IMAGE_EXTENSIONS": {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.ico'},
    "THUMBNAIL_SIZE": (280, 280),
    "PERFORMANCE_THUMBNAIL_SIZE": (180, 180),
    "GALLERY_THUMB_SIZE": (220, 220),
    "GALLERY_PREVIEW_SIZE": (480, 480),
    "BATCH_SCAN_SIZE": 50,  # Number of files to scan in one batch
    "BATCH_UPDATE_INTERVAL": 20,  # UI update interval (number of files)
    "MAX_THUMBNAIL_LOAD_SIZE": 10 * 1024 * 1024,
    "PERFORMANCE_MAX_THUMBNAIL_LOAD_SIZE": 3 * 1024 * 1024,
    "MAX_VIEWER_LOAD_SIZE": 100 * 1024 * 1024,
    "PERFORMANCE_MAX_VIEWER_LOAD_SIZE": 30 * 1024 * 1024,
    "CACHE_MAX_ITEMS_NORMAL": 50,
    "CACHE_MAX_ITEMS_PERFORMANCE": 25,
    "PRELOAD_VIEWER_NEIGHBORS_NORMAL": 2,
    "PRELOAD_VIEWER_NEIGHBORS_PERFORMANCE": 1,
    "PRELOAD_NEXT_THUMBNAIL": True,
    "WINDOW_SIZE": "1050x750",
    "VIEWER_ZOOM_FACTOR": 1.2,
    "VIEWER_MAX_ZOOM": 10.0,
    "VIEWER_MIN_ZOOM": 0.1,
    "PREVIEW_UPDATE_DELAY": 250,
    "THREAD_POOL_WORKERS": min(8, (os.cpu_count() or 1) + 4),
    "APP_VERSION": "4.0 - Rust-Python Hybrid",
}


def parse_human_size(size_str: str) -> Optional[int]:
    """Parses human-readable size string into bytes."""
    size_str = size_str.strip().upper()
    if not size_str:
        return None
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT])?B?$', size_str)
    if not match:
        if size_str.isdigit():
            return int(size_str)
        return -1

    value = float(match.group(1))
    unit = match.group(2)

    multipliers = {'G': 1024**3, 'M': 1024**2, 'K': 1024, None: 1}
    multiplier = multipliers.get(unit, 1)

    return int(value * multiplier)


class MainApp:
    """Main Arkview Application."""
    def __init__(self, root):
        self.root = root
        self.root.title(f"Arkview {CONFIG['APP_VERSION']}")
        self.root.geometry(CONFIG["WINDOW_SIZE"])
        self.root.minsize(600, 400)

        self.zip_scanner = ZipScanner()
        self.zip_manager = ZipFileManager()
        self.cache = LRUCache(CONFIG["CACHE_MAX_ITEMS_NORMAL"])
        self.preview_queue: queue.Queue = queue.Queue()
        self.thread_pool = ThreadPoolExecutor(max_workers=CONFIG["THREAD_POOL_WORKERS"])

        self.app_settings: Dict[str, Any] = {
            'performance_mode': False,
            'viewer_enabled': True,
            'preload_next_thumbnail': CONFIG['PRELOAD_NEXT_THUMBNAIL'],
            'max_thumbnail_size': CONFIG['MAX_THUMBNAIL_LOAD_SIZE'],
        }

        self.zip_files: Dict[str, Tuple[Optional[List[str]], float, int, int]] = {}
        self.current_selected_zip: Optional[str] = None
        self.current_preview_index: Optional[int] = None
        self.current_preview_members: Optional[List[str]] = None
        self.current_preview_cache_key: Optional[Tuple[str, str]] = None
        self.current_preview_future = None

        self.scan_thread = None
        self.scan_stop_event = threading.Event()

        self.current_view = "explorer"  # "explorer" or "gallery"
        self.gallery_widget: Optional[GalleryView] = None

        self._setup_ui()
        self._setup_menu()
        self._setup_drag_drop()
        self._setup_keyboard_shortcuts()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        if RUST_AVAILABLE:
            self.root.title(f"{self.root.title()} [Rust Accelerated]")

    def _setup_ui(self):
        """Setup the main UI."""
        # View switcher at the top
        view_switch_frame = ttk.Frame(self.root, padding=(8, 5))
        view_switch_frame.pack(fill=tk.X, side=tk.TOP)

        view_label = ttk.Label(view_switch_frame, text="View:", font=("", 10, "bold"))
        view_label.pack(side=tk.LEFT, padx=(0, 10))

        self.explorer_view_button = ttk.Button(
            view_switch_frame,
            text="📋 Resource Explorer",
            command=lambda: self._switch_view("explorer"),
            bootstyle="primary",
            width=18
        )
        self.explorer_view_button.pack(side=tk.LEFT, padx=(0, 5))

        self.gallery_view_button = ttk.Button(
            view_switch_frame,
            text="🎞️ Gallery",
            command=lambda: self._switch_view("gallery"),
            bootstyle="secondary-outline",
            width=15
        )
        self.gallery_view_button.pack(side=tk.LEFT)

        # Container for switchable views
        self.views_container = ttk.Frame(self.root)
        self.views_container.pack(fill=tk.BOTH, expand=True)

        # === RESOURCE EXPLORER VIEW ===
        self.explorer_view_frame = ttk.Frame(self.views_container)
        
        main_frame = ttk.Panedwindow(self.explorer_view_frame, orient=tk.HORIZONTAL)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # --- Left Panel: ZIP File List ---
        left_frame = ttk.Frame(main_frame, padding=5)
        main_frame.add(left_frame, weight=1)

        left_label = ttk.Label(left_frame, text="📦 Archives", font=("", 11, "bold"))
        left_label.pack(fill=tk.X, pady=(0, 8))

        list_container = ttk.Frame(left_frame)
        list_container.pack(fill=tk.BOTH, expand=True)

        self.zip_listbox = tk.Listbox(
            list_container, 
            activestyle='none',
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            bg="#1f2123",
            fg="#f8f9fa",
            selectbackground="#00bc8c",
            selectforeground="#101214",
            font=("Segoe UI", 10)
        )
        self.zip_listbox.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        left_scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=self.zip_listbox.yview)
        left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.zip_listbox.config(yscrollcommand=left_scrollbar.set, highlightbackground="#2f3336")

        self.zip_listbox.bind("<<ListboxSelect>>", self._on_zip_selected)

        # --- Right Panel: Preview and Details ---
        right_frame = ttk.Frame(main_frame, padding=5)
        main_frame.add(right_frame, weight=1)

        right_label = ttk.Label(right_frame, text="🖼️  Preview", font=("", 11, "bold"))
        right_label.pack(fill=tk.X, pady=(0, 8))

        # Preview navigation controls
        preview_nav_frame = ttk.Frame(right_frame)
        preview_nav_frame.pack(fill=tk.X, pady=(0, 8))

        self.preview_prev_button = ttk.Button(
            preview_nav_frame, 
            text="◀ Prev", 
            command=self._preview_prev, 
            width=10,
            bootstyle="secondary-outline"
        )
        self.preview_prev_button.pack(side=tk.LEFT, padx=(0, 5))
        self.preview_prev_button.config(state=tk.DISABLED)

        self.preview_info_label = ttk.Label(
            preview_nav_frame, text="", anchor=tk.CENTER, font=("", 9)
        )
        self.preview_info_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        self.preview_next_button = ttk.Button(
            preview_nav_frame, 
            text="Next ▶", 
            command=self._preview_next, 
            width=10,
            bootstyle="secondary-outline"
        )
        self.preview_next_button.pack(side=tk.RIGHT, padx=(5, 0))
        self.preview_next_button.config(state=tk.DISABLED)

        preview_container = ttk.Frame(right_frame, relief=tk.FLAT, borderwidth=1)
        preview_container.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self.preview_label = tk.Label(
            preview_container,
            background="#2a2d2e",
            height=15,
            text="Select a ZIP file",
            anchor=tk.CENTER,
            cursor="hand2",
            fg="#ffffff",
            font=("", 10)
        )
        self.preview_label.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.preview_label.bind("<Button-1>", lambda event: self._open_viewer())
        self.preview_label.bind("<MouseWheel>", self._on_preview_scroll)
        if platform.system() == "Linux":
            self.preview_label.bind("<Button-4>", self._on_preview_scroll)
            self.preview_label.bind("<Button-5>", self._on_preview_scroll)

        self._reset_preview()

        # --- Details Panel ---
        details_frame = ttk.Labelframe(right_frame, text="ℹ️  Details", padding=8)
        details_frame.pack(fill=tk.X)

        self.details_text = ScrolledText(
            details_frame, width=40, height=8, state=tk.DISABLED
        )
        self.details_text.pack(fill=tk.BOTH, expand=True)

        # === GALLERY VIEW ===
        self.gallery_view_frame = ttk.Frame(self.views_container)
        self.gallery_widget = GalleryView(
            self.gallery_view_frame,
            self.zip_files,
            self.app_settings,
            self.cache,
            self.thread_pool,
            self.zip_manager,
            CONFIG,
            self._ensure_members_loaded,
            self._on_gallery_selection,
            self._open_viewer_from_gallery
        )
        self.gallery_widget.pack(fill=tk.BOTH, expand=True)

        # --- Bottom Control Panel ---
        bottom_frame = ttk.Frame(self.root, padding=(8, 5))
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)

        button_container = ttk.Frame(bottom_frame)
        button_container.pack(side=tk.LEFT)

        scan_button = ttk.Button(
            button_container, 
            text="📁 Scan Directory", 
            command=self._scan_directory,
            bootstyle="primary",
            width=16
        )
        scan_button.pack(side=tk.LEFT, padx=(0, 5))

        view_button = ttk.Button(
            button_container, 
            text="👁️ View", 
            command=self._open_viewer,
            bootstyle="success",
            width=10
        )
        view_button.pack(side=tk.LEFT, padx=(0, 5))

        clear_button = ttk.Button(
            button_container, 
            text="🗑️ Clear", 
            command=self._clear_list,
            bootstyle="warning-outline",
            width=10
        )
        clear_button.pack(side=tk.LEFT, padx=(0, 5))

        settings_button = ttk.Button(
            button_container, 
            text="⚙️ Settings", 
            command=self._show_settings,
            bootstyle="secondary-outline",
            width=12
        )
        settings_button.pack(side=tk.LEFT)

        status_container = ttk.Frame(bottom_frame)
        status_container.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        self.status_label = ttk.Label(
            status_container, 
            text="Ready", 
            font=("", 9),
            anchor=tk.E
        )
        self.status_label.pack(side=tk.RIGHT, padx=(5, 0))

        self._update_view_buttons()
        self._update_view_visibility()

    def _setup_menu(self):
        """Setup the menu bar."""
        menubar = Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Scan Directory", command=self._scan_directory)
        file_menu.add_command(label="Add ZIP File", command=self._add_zip_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_closing)

        view_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Settings", command=self._show_settings)
        view_menu.add_command(label="Clear List", command=self._clear_list)

        help_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self._show_about)

    def _setup_drag_drop(self):
        """Setup drag and drop if available."""
        if DND_ENABLED:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_drop)

    def _on_drop(self, event):
        """Handle dropped files."""
        files = self.root.tk.splitlist(event.data)
        for file_path in files:
            file_path = file_path.strip('{}')
            if file_path.lower().endswith('.zip'):
                self._add_zip_entry(file_path)

    def _setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts."""
        self.root.bind("<Control-g>", lambda e: self._switch_view("gallery"))
        self.root.bind("<Control-e>", lambda e: self._switch_view("explorer"))
        self.root.bind("<Tab>", self._handle_tab_switch)
        
        # Gallery navigation keys
        self.root.bind("<Left>", self._handle_gallery_key)
        self.root.bind("<Right>", self._handle_gallery_key)
        self.root.bind("<Up>", self._handle_gallery_key)
        self.root.bind("<Down>", self._handle_gallery_key)
        self.root.bind("<space>", self._handle_gallery_key)
        self.root.bind("<Return>", self._handle_gallery_key)
        self.root.bind("<Escape>", self._handle_gallery_key)
        self.root.bind("<Home>", self._handle_gallery_key)
        self.root.bind("<End>", self._handle_gallery_key)


    def _handle_tab_switch(self, event):
        """Handle Tab key to switch views."""
        if self.current_view == "explorer":
            self._switch_view("gallery")
        else:
            self._switch_view("explorer")
        return "break"

    def _switch_view(self, view: str):
        """Switch between explorer and gallery views."""
        if view not in ["explorer", "gallery"]:
            return

        if self.current_view == view:
            return

        self.current_view = view
        self._update_view_buttons()
        self._update_view_visibility()

        if view == "gallery" and self.gallery_widget:
            self.gallery_widget.populate()

    def _update_view_buttons(self):
        """Update view button styles based on current view."""
        if self.current_view == "explorer":
            self.explorer_view_button.config(bootstyle="primary")
            self.gallery_view_button.config(bootstyle="secondary-outline")
        else:
            self.explorer_view_button.config(bootstyle="secondary-outline")
            self.gallery_view_button.config(bootstyle="primary")

    def _update_view_visibility(self):
        """Update view visibility based on current view."""
        if self.current_view == "explorer":
            self.gallery_view_frame.pack_forget()
            self.explorer_view_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.explorer_view_frame.pack_forget()
            self.gallery_view_frame.pack(fill=tk.BOTH, expand=True)

    def _refresh_gallery(self):
        """Refresh gallery view if visible."""
        if self.gallery_widget and self.current_view == "gallery":
            self.gallery_widget.populate()

    def _handle_gallery_key(self, event):
        """Forward navigation keys to gallery when active."""
        if self.current_view != "gallery" or not self.gallery_widget:
            return
        result = self.gallery_widget.handle_keypress(event)
        if result == "break":
            return "break"

    def _scan_directory(self):
        """Scan a directory for ZIP files."""
        directory = filedialog.askdirectory(title="Select Directory to Scan")
        if not directory:
            return

        self.status_label.config(text="Scanning...")
        self.scan_stop_event.clear()
        self.scan_thread = threading.Thread(
            target=self._scan_directory_worker,
            args=(directory,),
            daemon=True
        )
        self.scan_thread.start()

    def _scan_directory_worker(self, directory: str):
        """Worker thread for scanning a directory with batch processing."""
        try:
            zip_files = [str(p) for p in Path(directory).glob("**/*.zip")]
            total_files = len(zip_files)

            if total_files == 0:
                self._run_on_main_thread(self.status_label.config, text="No ZIP files found")
                return

            batch_size = max(1, CONFIG["BATCH_SCAN_SIZE"])
            ui_update_interval = max(1, CONFIG["BATCH_UPDATE_INTERVAL"])
            pending_entries: List[Tuple[str, Optional[List[str]], Optional[float], Optional[int], Optional[int]]] = []
            processed = 0
            valid_found = 0

            def flush_pending():
                if not pending_entries:
                    return
                batch = pending_entries.copy()
                pending_entries.clear()
                self._run_on_main_thread(self._add_zip_entries_bulk, batch)

            for start in range(0, total_files, batch_size):
                if self.scan_stop_event.is_set():
                    break

                batch_paths = zip_files[start:start + batch_size]
                try:
                    batch_results = self.zip_scanner.batch_analyze_zips(batch_paths, collect_members=False)
                except Exception as e:
                    self._run_on_main_thread(messagebox.showerror, "Error", f"Scan error: {e}")
                    self._run_on_main_thread(self.status_label.config, text="Scan failed")
                    return

                for zip_path, is_valid, members, mod_time, file_size, image_count in batch_results:
                    processed += 1
                    if is_valid:
                        pending_entries.append((zip_path, members, mod_time, file_size, image_count))
                        valid_found += 1

                if len(pending_entries) >= batch_size:
                    flush_pending()

                if processed % ui_update_interval == 0 or processed >= total_files:
                    self._run_on_main_thread(
                        self.status_label.config,
                        text=f"Scanning... {processed}/{total_files} files processed"
                    )

            flush_pending()

            final_message = (
                "Scan canceled" if self.scan_stop_event.is_set()
                else f"Found {valid_found} valid archives (of {processed} scanned)"
            )
            self._run_on_main_thread(self.status_label.config, text=final_message)
        except Exception as e:
            self._run_on_main_thread(messagebox.showerror, "Error", f"Scan error: {e}")
            self._run_on_main_thread(self.status_label.config, text="Scan failed")

    def _add_zip_file(self):
        """Add a single ZIP file."""
        file_path = filedialog.askopenfilename(
            title="Select ZIP File",
            filetypes=[("ZIP Files", "*.zip"), ("All Files", "*.*")]
        )
        if file_path:
            self._analyze_and_add(file_path)

    def _analyze_and_add(self, zip_path: str):
        """Analyze and add a ZIP file."""
        is_valid, members, mod_time, file_size, image_count = self.zip_scanner.analyze_zip(zip_path)

        if is_valid and members:
            self._add_zip_entry(zip_path, members, mod_time, file_size)
        else:
            messagebox.showwarning(
                "Not Valid",
                f"'{os.path.basename(zip_path)}' does not contain only images."
            )

    def _add_zip_entry(
        self,
        zip_path: str,
        members: Optional[List[str]] = None,
        mod_time: Optional[float] = None,
        file_size: Optional[int] = None,
        image_count: Optional[int] = None
    ):
        """Add a ZIP file to the list."""
        self._add_zip_entries_bulk([(zip_path, members, mod_time, file_size, image_count)])

    def _add_zip_entries_bulk(self, entries: List[Tuple[str, Optional[List[str]], Optional[float], Optional[int], Optional[int]]]):
        """Add multiple ZIP files to the list in a batch (more efficient)."""
        if not entries:
            return
        
        display_items = []
        for zip_path, members, mod_time, file_size, image_count in entries:
            if zip_path in self.zip_files:
                continue
            
            resolved_members = members
            resolved_mod_time = mod_time
            resolved_file_size = file_size
            resolved_image_count = image_count

            if resolved_members is None and resolved_image_count is None:
                is_valid, resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count = self.zip_scanner.analyze_zip(zip_path)
                if not is_valid or not resolved_members:
                    continue
            elif resolved_members is None and (resolved_mod_time is None or resolved_file_size is None):
                # Need complete metadata for display
                is_valid, resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count = self.zip_scanner.analyze_zip(zip_path)
                if not is_valid:
                    continue

            if resolved_image_count is None:
                resolved_image_count = len(resolved_members) if resolved_members else 0

            entry_mod_time = resolved_mod_time or 0
            entry_file_size = resolved_file_size or 0

            self.zip_files[zip_path] = (resolved_members, entry_mod_time, entry_file_size, resolved_image_count)

            display_text = os.path.basename(zip_path)
            if entry_file_size:
                display_text += f" ({_format_size(entry_file_size)})"
            display_items.append(display_text)
        
        if display_items:
            self.zip_listbox.insert(tk.END, *display_items)

        self._refresh_gallery()

    def _run_on_main_thread(self, func: Callable, *args, **kwargs):
        """Execute function on main thread (thread-safe UI update)."""
        self.root.after(0, partial(func, *args, **kwargs))

    def _on_zip_selected(self, event):
        """Handle ZIP file selection."""
        selection = self.zip_listbox.curselection()
        if not selection:
            self._reset_preview()
            return

        index = selection[0]
        zip_entries = list(self.zip_files.keys())
        if index >= len(zip_entries):
            self._reset_preview()
            return

        zip_path = zip_entries[index]
        self.current_selected_zip = zip_path

        entry = self.zip_files[zip_path]
        members, mod_time, file_size, image_count = entry

        if members is None:
            members = self._ensure_members_loaded(zip_path)
            if not members:
                self._reset_preview("No images found")
                return
            members, mod_time, file_size, image_count = self.zip_files[zip_path]

        if not members:
            self._reset_preview("No images found")
            return

        self._update_details(zip_path, mod_time, file_size, image_count)
        self._load_preview(zip_path, members, 0)

    def _ensure_members_loaded(self, zip_path: str) -> Optional[List[str]]:
        """Ensure members list is loaded for a ZIP file."""
        entry = self.zip_files.get(zip_path)
        if not entry:
            return None

        members, mod_time, file_size, image_count = entry
        if members is not None:
            return members

        is_valid, members, mod_time, file_size, image_count = self.zip_scanner.analyze_zip(zip_path)
        if is_valid and members:
            self.zip_files[zip_path] = (members, mod_time or 0, file_size or 0, len(members))
            return members
        return None

    def _update_details(self, zip_path: str, mod_time: float, file_size: int, image_count: int):
        """Update the details panel."""
        details = f"Archive: {os.path.basename(zip_path)}\n"
        details += f"Images: {image_count}\n"
        details += f"Size: {_format_size(file_size)}\n"
        if mod_time:
            details += f"Modified: {format_datetime(mod_time)}\n"

        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete(1.0, tk.END)
        self.details_text.insert(tk.END, details)
        self.details_text.config(state=tk.DISABLED)

    def _load_preview(self, zip_path: str, members: List[str], index: int):
        """Load preview image."""
        if not members or index >= len(members) or index < 0:
            return

        if self.current_preview_future and not self.current_preview_future.done():
            self.current_preview_future.cancel()
        while True:
            try:
                self.preview_queue.get_nowait()
            except queue.Empty:
                break

        self.current_preview_index = index
        self.current_preview_members = members
        cache_key = (zip_path, members[index])
        self.current_preview_cache_key = cache_key

        # Update preview info label
        self.preview_info_label.config(text=f"Image {index + 1} / {len(members)}")

        # Update navigation button states
        self.preview_prev_button.config(state=tk.NORMAL if index > 0 else tk.DISABLED)
        self.preview_next_button.config(state=tk.NORMAL if index < len(members) - 1 else tk.DISABLED)

        target_size = (
            CONFIG["PERFORMANCE_THUMBNAIL_SIZE"] if self.app_settings['performance_mode']
            else CONFIG["THUMBNAIL_SIZE"]
        )

        self.preview_label.config(image='', text="Loading preview...")
        self.preview_label.image = None

        self.current_preview_future = self.thread_pool.submit(
            load_image_data_async,
            zip_path,
            members[index],
            self.app_settings['max_thumbnail_size'],
            target_size,
            self.preview_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.app_settings['performance_mode']
        )

        self.root.after(20, self._check_preview_result)

    def _check_preview_result(self):
        """Check if preview image is ready."""
        expected_key = getattr(self, 'current_preview_cache_key', None)
        if expected_key is None:
            return

        try:
            while True:
                result = self.preview_queue.get_nowait()
                if result.cache_key != expected_key:
                    continue

                if result.success and result.data:
                    photo = ImageTk.PhotoImage(result.data)
                    self.preview_label.config(image=photo, text="")
                    self.preview_label.image = photo
                else:
                    message = result.error_message or "Preview failed"
                    self.preview_label.config(image='', text=f"Error: {message}")
                    self.preview_label.image = None
                self.current_preview_future = None
                return
        except queue.Empty:
            if self.current_preview_future and not self.current_preview_future.done():
                self.root.after(20, self._check_preview_result)

    def _reset_preview(self, message: str = "Select a ZIP file"):
        if self.current_preview_future and not self.current_preview_future.done():
            self.current_preview_future.cancel()
        self.current_preview_future = None
        self.current_preview_members = None
        self.current_preview_index = None
        self.current_preview_cache_key = None

        # Drain any pending preview results
        while True:
            try:
                self.preview_queue.get_nowait()
            except queue.Empty:
                break

        self.preview_label.config(image='', text=message)
        self.preview_label.image = None
        self.preview_info_label.config(text='')
        self.preview_prev_button.config(state=tk.DISABLED)
        self.preview_next_button.config(state=tk.DISABLED)

    def _on_preview_scroll(self, event):
        if not self.current_preview_members:
            return
        if platform.system() == "Linux":
            delta = 1 if event.num == 4 else -1
        else:
            delta = 1 if event.delta > 0 else -1
        if delta > 0:
            self._preview_prev()
        else:
            self._preview_next()

    def _preview_prev(self):
        if not self.current_selected_zip or not self.current_preview_members:
            return
        new_index = (self.current_preview_index or 0) - 1
        if new_index >= 0:
            self._load_preview(self.current_selected_zip, self.current_preview_members, new_index)

    def _preview_next(self):
        if not self.current_selected_zip or not self.current_preview_members:
            return
        current_index = self.current_preview_index or 0
        if current_index + 1 < len(self.current_preview_members):
            self._load_preview(self.current_selected_zip, self.current_preview_members, current_index + 1)

    def _open_viewer(self):
        """Open the multi-image viewer."""
        if not self.current_selected_zip:
            messagebox.showwarning("No Selection", "Please select an archive first.")
            return

        if not self.app_settings.get('viewer_enabled', True):
            messagebox.showinfo("Disabled", "Multi-image viewer is disabled in settings.")
            return

        zip_path = self.current_selected_zip
        entry = self.zip_files.get(zip_path)
        if not entry:
            messagebox.showwarning("Missing Entry", "Selected archive is no longer available.")
            return

        members = entry[0]
        if members is None:
            members = self._ensure_members_loaded(zip_path)
            if not members:
                messagebox.showerror("Error", "Unable to load archive contents.")
                return

        index = self.current_preview_index or 0

        viewer_queue = queue.Queue()
        ImageViewerWindow(
            self.root,
            zip_path,
            members,
            index,
            self.app_settings,
            self.cache,
            viewer_queue,
            self.thread_pool,
            self.zip_manager
        )

    def _open_viewer_from_gallery(self, zip_path: str, members: List[str], index: int):
        """Open viewer when triggered from gallery view."""
        if not self.app_settings.get('viewer_enabled', True):
            messagebox.showinfo("Disabled", "Multi-image viewer is disabled in settings.")
            return
        
        viewer_queue = queue.Queue()
        ImageViewerWindow(
            self.root,
            zip_path,
            members,
            index,
            self.app_settings,
            self.cache,
            viewer_queue,
            self.thread_pool,
            self.zip_manager
        )

    def _on_gallery_selection(self, zip_path: str, members: List[str], index: int):
        """Handle selection change in gallery view."""
        self.current_selected_zip = zip_path
        self.current_preview_members = members
        self.current_preview_index = index

        entry = self.zip_files.get(zip_path)
        if entry:
            _, mod_time, file_size, image_count = entry
            self._update_details(zip_path, mod_time, file_size, image_count)

    def _show_settings(self):
        """Show settings dialog."""
        SettingsDialog(self.root, self.app_settings)

        if self.app_settings.get('performance_mode'):
            new_capacity = CONFIG["CACHE_MAX_ITEMS_PERFORMANCE"]
        else:
            new_capacity = CONFIG["CACHE_MAX_ITEMS_NORMAL"]

        self.cache.resize(new_capacity)

    def _clear_list(self):
        """Clear the ZIP file list."""
        self.zip_listbox.delete(0, tk.END)
        self.zip_files.clear()
        self.current_selected_zip = None
        self._reset_preview()
        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete(1.0, tk.END)
        self.details_text.config(state=tk.DISABLED)

    def _show_about(self):
        """Show about dialog."""
        about_text = f"""Arkview {CONFIG['APP_VERSION']}
High-Performance Archived Image Viewer

Hybrid Rust-Python Architecture
{f'Rust Acceleration: Enabled' if RUST_AVAILABLE else 'Rust Acceleration: Not Available'}

Archive browsing and image preview utility.
BSD-2-Clause License"""
        messagebox.showinfo("About Arkview", about_text)

    def _on_closing(self):
        """Handle application closing."""
        self.scan_stop_event.set()
        self.zip_manager.close_all()
        self.thread_pool.shutdown(wait=False)
        self.root.destroy()


def main():
    """Main entry point."""
    if DND_ENABLED:
        root = TkinterDnD.Tk()
        style = Style(theme="darkly", master=root)
        style.configure('.', font=("Segoe UI", 10))
    else:
        root = ttk.Window(themename="darkly")
        root.style.configure('.', font=("Segoe UI", 10))

    app = MainApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
