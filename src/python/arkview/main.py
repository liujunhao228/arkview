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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageTk
from tkinter import Menu, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk
from tkinter.ttk import PanedWindow

from .core import (
    ZipScanner, ZipFileManager, LRUCache, load_image_data_async,
    LoadResult, _format_size, RUST_AVAILABLE
)
from .ui import (
    SettingsDialog, ImageViewerWindow, DND_ENABLED, TkinterDnD, DND_FILES, format_datetime
)


CONFIG: Dict[str, Any] = {
    "IMAGE_EXTENSIONS": {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.ico'},
    "THUMBNAIL_SIZE": (280, 280),
    "PERFORMANCE_THUMBNAIL_SIZE": (180, 180),
    "BATCH_UPDATE_INTERVAL": 5,
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
        self.result_queue: queue.Queue = queue.Queue()
        self.thread_pool = ThreadPoolExecutor(max_workers=CONFIG["THREAD_POOL_WORKERS"])

        self.app_settings: Dict[str, Any] = {
            'performance_mode': False,
            'viewer_enabled': True,
            'preload_next_thumbnail': CONFIG['PRELOAD_NEXT_THUMBNAIL'],
            'max_thumbnail_size': CONFIG['MAX_THUMBNAIL_LOAD_SIZE'],
        }

        self.zip_files: Dict[str, Tuple[List[str], float, int]] = {}
        self.current_selected_zip: Optional[str] = None
        self.current_preview_index: Optional[int] = None
        self.current_preview_future = None

        self.scan_thread = None
        self.scan_stop_event = threading.Event()

        self._setup_ui()
        self._setup_menu()
        self._setup_drag_drop()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        if RUST_AVAILABLE:
            self.root.title(f"{self.root.title()} [Rust Accelerated]")

    def _setup_ui(self):
        """Setup the main UI."""
        main_frame = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Left Panel: ZIP File List ---
        left_frame = ttk.Frame(main_frame)
        main_frame.add(left_frame, weight=1)

        left_label = ttk.Label(left_frame, text="Archives", font=("", 10, "bold"))
        left_label.pack(fill=tk.X, pady=(0, 5))

        self.zip_listbox = tk.Listbox(left_frame, activestyle='none')
        self.zip_listbox.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        left_scrollbar = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.zip_listbox.yview)
        left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.zip_listbox.config(yscrollcommand=left_scrollbar.set)

        self.zip_listbox.bind("<<ListboxSelect>>", self._on_zip_selected)

        # --- Right Panel: Preview and Details ---
        right_frame = ttk.Frame(main_frame)
        main_frame.add(right_frame, weight=1)

        right_label = ttk.Label(right_frame, text="Preview", font=("", 10, "bold"))
        right_label.pack(fill=tk.X, pady=(0, 5))

        self.preview_label = tk.Label(right_frame, background="lightgray", height=15)
        self.preview_label.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # --- Details Panel ---
        details_frame = ttk.LabelFrame(right_frame, text="Details", padding=5)
        details_frame.pack(fill=tk.X)

        self.details_text = ScrolledText(
            details_frame, width=40, height=8, state=tk.DISABLED
        )
        self.details_text.pack(fill=tk.BOTH, expand=True)

        # --- Bottom Control Panel ---
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=5)

        scan_button = ttk.Button(bottom_frame, text="Scan Directory", command=self._scan_directory)
        scan_button.pack(side=tk.LEFT, padx=(0, 5))

        clear_button = ttk.Button(bottom_frame, text="Clear", command=self._clear_list)
        clear_button.pack(side=tk.LEFT, padx=(0, 5))

        settings_button = ttk.Button(bottom_frame, text="Settings", command=self._show_settings)
        settings_button.pack(side=tk.LEFT, padx=(0, 5))

        view_button = ttk.Button(bottom_frame, text="View", command=self._open_viewer)
        view_button.pack(side=tk.LEFT)

        self.status_label = ttk.Label(bottom_frame, text="Ready")
        self.status_label.pack(side=tk.RIGHT, padx=(5, 0))

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

    def _scan_directory(self):
        """Scan a directory for ZIP files."""
        directory = filedialog.askdirectory(title="Select Directory to Scan")
        if not directory:
            return

        self.scan_stop_event.clear()
        self.scan_thread = threading.Thread(
            target=self._scan_directory_worker,
            args=(directory,),
            daemon=True
        )
        self.scan_thread.start()

    def _scan_directory_worker(self, directory: str):
        """Worker thread for scanning a directory."""
        self.status_label.config(text="Scanning...")
        self.root.update()

        try:
            zip_files = list(Path(directory).glob("**/*.zip"))
            for i, zip_path in enumerate(zip_files):
                if self.scan_stop_event.is_set():
                    break

                is_valid, members, mod_time, file_size, image_count = self.zip_scanner.analyze_zip(str(zip_path))

                if is_valid and members:
                    self._add_zip_entry(str(zip_path), members, mod_time, file_size)

                if i % CONFIG["BATCH_UPDATE_INTERVAL"] == 0:
                    self.status_label.config(text=f"Scanning... {i} files processed")
                    self.root.update()

            self.status_label.config(text=f"Found {len(self.zip_files)} valid archives")
        except Exception as e:
            messagebox.showerror("Error", f"Scan error: {e}")
            self.status_label.config(text="Scan failed")

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
        file_size: Optional[int] = None
    ):
        """Add a ZIP file to the list."""
        if zip_path in self.zip_files:
            return

        if members is None:
            is_valid, members, mod_time, file_size, _ = self.zip_scanner.analyze_zip(zip_path)
            if not is_valid or not members:
                return

        self.zip_files[zip_path] = (members, mod_time or 0, file_size or 0)

        display_text = os.path.basename(zip_path)
        if file_size:
            display_text += f" ({_format_size(file_size)})"

        self.zip_listbox.insert(tk.END, display_text)

    def _on_zip_selected(self, event):
        """Handle ZIP file selection."""
        selection = self.zip_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        zip_entries = list(self.zip_files.keys())
        if index >= len(zip_entries):
            return

        zip_path = zip_entries[index]
        self.current_selected_zip = zip_path

        members, mod_time, file_size = self.zip_files[zip_path]

        self._update_details(zip_path, members, mod_time, file_size)
        self._load_preview(zip_path, members, 0)

    def _update_details(self, zip_path: str, members: List[str], mod_time: float, file_size: int):
        """Update the details panel."""
        details = f"Archive: {os.path.basename(zip_path)}\n"
        details += f"Images: {len(members)}\n"
        details += f"Size: {_format_size(file_size)}\n"
        if mod_time:
            details += f"Modified: {format_datetime(mod_time)}\n"

        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete(1.0, tk.END)
        self.details_text.insert(tk.END, details)
        self.details_text.config(state=tk.DISABLED)

    def _load_preview(self, zip_path: str, members: List[str], index: int):
        """Load preview image."""
        if index >= len(members):
            return

        self.current_preview_index = index
        cache_key = (zip_path, members[index])

        target_size = (
            CONFIG["PERFORMANCE_THUMBNAIL_SIZE"] if self.app_settings['performance_mode']
            else CONFIG["THUMBNAIL_SIZE"]
        )

        self.current_preview_future = self.thread_pool.submit(
            load_image_data_async,
            zip_path,
            members[index],
            self.app_settings['max_thumbnail_size'],
            target_size,
            self.result_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.app_settings['performance_mode']
        )

        self.root.after(50, self._check_preview_result)

    def _check_preview_result(self):
        """Check if preview image is ready."""
        try:
            result = self.result_queue.get_nowait()
            if result.success and result.data:
                photo = ImageTk.PhotoImage(result.data)
                self.preview_label.config(image=photo)
                self.preview_label.image = photo
        except queue.Empty:
            if self.current_preview_future and not self.current_preview_future.done():
                self.root.after(50, self._check_preview_result)

    def _open_viewer(self):
        """Open the multi-image viewer."""
        if not self.current_selected_zip:
            messagebox.showwarning("No Selection", "Please select an archive first.")
            return

        if not self.app_settings.get('viewer_enabled', True):
            messagebox.showinfo("Disabled", "Multi-image viewer is disabled in settings.")
            return

        zip_path = self.current_selected_zip
        members, _, _ = self.zip_files[zip_path]

        index = self.current_preview_index or 0

        ImageViewerWindow(
            self.root,
            zip_path,
            members,
            index,
            self.app_settings,
            self.cache,
            self.result_queue,
            self.thread_pool,
            self.zip_manager
        )

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
        self.preview_label.config(image='')
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
    else:
        root = tk.Tk()

    app = MainApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
