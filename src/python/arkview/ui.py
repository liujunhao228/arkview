"""
UI components for Arkview.
"""

import os
import platform
import queue
import threading
import tkinter as tk
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageTk
from tkinter import (BooleanVar, Frame, Label, Menu, Toplevel, filedialog, messagebox)
from tkinter import ttk
from tkinter.ttk import PanedWindow, Progressbar

from .core import (
    ZipScanner, ZipFileManager, LRUCache, load_image_data_async,
    LoadResult, _format_size
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_ENABLED = True
except ImportError:
    print("INFO: Optional library `tkinterdnd2` not found.")
    class TkinterDnD:
        @staticmethod
        def Tk(*args, **kwargs):
            return tk.Tk(*args, **kwargs)
    DND_FILES = None
    DND_ENABLED = False


def format_datetime(timestamp: float) -> str:
    """Formats a timestamp into a YYYY-MM-DD HH:MM:SS string."""
    try:
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, OSError, TypeError):
        return "N/A"


class SettingsDialog(Toplevel):
    """Dialog window for application settings."""
    def __init__(self, master, current_settings: Dict[str, Any]):
        super().__init__(master)
        self.title("Settings")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.settings = current_settings
        self.result_settings = current_settings.copy()

        self.performance_mode_var = BooleanVar(
            value=self.result_settings.get('performance_mode', False)
        )
        self.viewer_enabled_var = BooleanVar(
            value=self.result_settings.get('viewer_enabled', True)
        )
        self.preload_thumb_var = BooleanVar(
            value=self.result_settings.get('preload_next_thumbnail', True)
        )

        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        perf_check = ttk.Checkbutton(
            main_frame,
            text="Performance Mode (Faster, Lower Quality)",
            variable=self.performance_mode_var,
            command=self._update_dependent_settings
        )
        perf_check.pack(anchor=tk.W, pady=5)

        viewer_check = ttk.Checkbutton(
            main_frame,
            text="Enable Multi-Image Viewer (Click Preview)",
            variable=self.viewer_enabled_var
        )
        viewer_check.pack(anchor=tk.W, pady=5)

        self.preload_thumb_check = ttk.Checkbutton(
            main_frame,
            text="Preload Next Thumbnail (in Preview)",
            variable=self.preload_thumb_var
        )
        self.preload_thumb_check.pack(anchor=tk.W, pady=5)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(15, 0))

        ok_button = ttk.Button(button_frame, text="OK", command=self._on_ok)
        ok_button.pack(side=tk.RIGHT, padx=(5, 0))

        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side=tk.RIGHT)

        self._update_dependent_settings()
        self.update_idletasks()

        master_x = master.winfo_x()
        master_y = master.winfo_y()
        master_w = master.winfo_width()
        master_h = master.winfo_height()
        dialog_w = self.winfo_width()
        dialog_h = self.winfo_height()
        center_x = master_x + (master_w // 2) - (dialog_w // 2)
        center_y = master_y + (master_h // 2) - (dialog_h // 2)
        self.geometry(f"+{center_x}+{center_y}")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window(self)

    def _update_dependent_settings(self):
        is_performance = self.performance_mode_var.get()
        self.preload_thumb_check.config(state=tk.DISABLED if is_performance else tk.NORMAL)
        if is_performance:
            self.preload_thumb_var.set(False)

    def _on_ok(self):
        self.settings['performance_mode'] = self.performance_mode_var.get()
        self.settings['viewer_enabled'] = self.viewer_enabled_var.get()
        if not self.settings['performance_mode']:
            self.settings['preload_next_thumbnail'] = self.preload_thumb_var.get()
        else:
            self.settings['preload_next_thumbnail'] = False
        self.destroy()

    def _on_cancel(self):
        self.destroy()


class ImageViewerWindow(Toplevel):
    """Window for viewing multiple images from a ZIP archive."""
    def __init__(
        self,
        master,
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
        self.master_app = master
        self.zip_path = zip_path
        self.image_members = image_members
        self.current_index = initial_index
        self.settings = settings
        self.cache = cache
        self.result_queue = result_queue
        self.thread_pool = thread_pool
        self.zip_manager = zip_manager

        self.current_pil_image: Optional[Image.Image] = None
        self._current_photo_image: Optional[ImageTk.PhotoImage] = None
        self.zoom_factor: float = 1.0
        self.fit_to_window: bool = True
        self._is_loading: bool = False
        self._is_fullscreen: bool = False

        self.title(f"View: {os.path.basename(zip_path)}")
        self.geometry("800x600")
        self.minsize(400, 300)

        self._setup_ui()
        self._setup_bindings()

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._close_viewer)

        self.after(10, lambda: self.load_image(self.current_index))
        self.after(50, self.focus_force)

    def _setup_ui(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        top_frame = ttk.Frame(main_frame, padding=5)
        top_frame.pack(fill=tk.X)

        self.prev_button = ttk.Button(top_frame, text="< Prev", command=self._show_prev, width=8)
        self.prev_button.pack(side=tk.LEFT)

        self.image_info_label = ttk.Label(top_frame, text="Image 1 / X", anchor=tk.CENTER)
        self.image_info_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        self.next_button = ttk.Button(top_frame, text="Next >", command=self._show_next, width=8)
        self.next_button.pack(side=tk.RIGHT)

        self.image_label = tk.Label(main_frame, background="darkgrey", anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.status_frame = ttk.Frame(main_frame, padding=(5, 2))
        self.progress_bar = Progressbar(self.status_frame, mode='indeterminate', maximum=100)
        self.status_label = ttk.Label(self.status_frame, text="", anchor=tk.W)

    def _setup_bindings(self):
        self.bind("<Left>", self._handle_keypress)
        self.bind("<Right>", self._handle_keypress)
        self.bind("<Prior>", self._handle_keypress)
        self.bind("<Next>", self._handle_keypress)
        self.bind("<Escape>", self._handle_keypress)
        self.bind("<F11>", self._toggle_fullscreen)
        self.bind("<Configure>", self._on_resize)

        if platform.system() == "Linux":
            self.bind("<Button-4>", self._on_zoom)
            self.bind("<Button-5>", self._on_zoom)
        else:
            self.bind("<MouseWheel>", self._on_zoom)

        self.bind("<f>", self._handle_keypress)
        self.bind("<r>", self._handle_keypress)
        self.bind("<Home>", self._handle_keypress)
        self.bind("<End>", self._handle_keypress)

    def _handle_keypress(self, event):
        if event.keysym == "Left":
            self._show_prev()
        elif event.keysym == "Right":
            self._show_next()
        elif event.keysym in ("Prior", "Page_Up"):
            self._show_prev()
        elif event.keysym in ("Next", "Page_Down"):
            self._show_next()
        elif event.keysym == "Escape":
            self._close_viewer()
        elif event.keysym == "f":
            self.fit_to_window = not self.fit_to_window
            self._update_display()
        elif event.keysym == "r":
            self.zoom_factor = 1.0
            self._update_display()
        elif event.keysym == "Home":
            self.load_image(0)
        elif event.keysym == "End":
            self.load_image(len(self.image_members) - 1)

    def _show_prev(self):
        if self.current_index > 0:
            self.load_image(self.current_index - 1)

    def _show_next(self):
        if self.current_index < len(self.image_members) - 1:
            self.load_image(self.current_index + 1)

    def _toggle_fullscreen(self, event=None):
        self._is_fullscreen = not self._is_fullscreen
        self.attributes('-fullscreen', self._is_fullscreen)

    def _on_zoom(self, event):
        if platform.system() == "Linux":
            delta = 1 if event.num == 4 else -1
        else:
            delta = 1 if event.delta > 0 else -1
        
        factor = 1.2 if delta > 0 else 1 / 1.2
        self.zoom_factor *= factor
        self.zoom_factor = max(0.1, min(10.0, self.zoom_factor))
        self._update_display()

    def _on_resize(self, event=None):
        self._update_display()

    def load_image(self, index: int):
        if index < 0 or index >= len(self.image_members):
            return
        self.current_index = index
        self.image_info_label.config(text=f"Image {index + 1} / {len(self.image_members)}")
        
        self._is_loading = True
        cache_key = (self.zip_path, self.image_members[index])
        
        self.thread_pool.submit(
            load_image_data_async,
            self.zip_path,
            self.image_members[index],
            100 * 1024 * 1024,
            None,
            self.result_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.settings.get('performance_mode', False)
        )
        
        self.after(10, self._check_load_result)

    def _check_load_result(self):
        try:
            result = self.result_queue.get_nowait()
            if result.success:
                self.current_pil_image = result.data
            else:
                messagebox.showerror("Error", f"Failed to load image: {result.error_message}")
            self._is_loading = False
            self._update_display()
        except queue.Empty:
            if self._is_loading:
                self.after(50, self._check_load_result)

    def _update_display(self):
        if self.current_pil_image is None:
            return
        
        display_width = self.image_label.winfo_width() or 800
        display_height = self.image_label.winfo_height() or 600
        
        img = self.current_pil_image.copy()
        
        if self.fit_to_window:
            img.thumbnail((display_width - 10, display_height - 10), Image.Resampling.LANCZOS)
        else:
            new_width = int(img.width * self.zoom_factor)
            new_height = int(img.height * self.zoom_factor)
            if new_width > 0 and new_height > 0:
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        self._current_photo_image = ImageTk.PhotoImage(img)
        self.image_label.config(image=self._current_photo_image)

    def _close_viewer(self):
        self.destroy()
