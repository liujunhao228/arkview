"""
Gallery View for Arkview - mobile-like browsing with keyboard shortcuts.
"""

import os
import platform
import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import ImageTk
import ttkbootstrap as ttk

from .core import ZipFileManager, LRUCache, load_image_data_async, _format_size


class GalleryView(ttk.Frame):
    """Gallery view component with thumbnail grid and image preview."""
    
    def __init__(
        self,
        parent,
        zip_files: Dict[str, Tuple[Optional[List[str]], float, int, int]],
        app_settings: Dict[str, Any],
        cache: LRUCache,
        thread_pool: ThreadPoolExecutor,
        zip_manager: ZipFileManager,
        config: Dict[str, Any],
        ensure_members_loaded_callback: Callable,
        selection_callback: Optional[Callable[[str, List[str], int], None]] = None,
        open_viewer_callback: Optional[Callable[[str, List[str], int], None]] = None
    ):
        super().__init__(parent)
        
        self.zip_files = zip_files
        self.app_settings = app_settings
        self.cache = cache
        self.thread_pool = thread_pool
        self.zip_manager = zip_manager
        self.config = config
        self.ensure_members_loaded = ensure_members_loaded_callback
        self.selection_callback = selection_callback
        self.open_viewer_callback = open_viewer_callback
        
        self.gallery_columns = 3
        self.gallery_thumbnails: Dict[str, ImageTk.PhotoImage] = {}
        self.gallery_cards: Dict[str, tk.Frame] = {}
        self.gallery_thumb_labels: Dict[str, tk.Label] = {}
        self.gallery_title_labels: Dict[str, tk.Label] = {}
        self.gallery_selected_zip: Optional[str] = None
        self.gallery_selected_index: int = 0
        self.gallery_image_index: int = 0
        self.gallery_current_members: Optional[List[str]] = None
        self.gallery_queue: queue.Queue = queue.Queue()
        self.gallery_thumbnail_requests: Dict[Tuple[str, str], str] = {}
        self._gallery_thumbnail_after_id: Optional[str] = None
        self.gallery_preview_queue: queue.Queue = queue.Queue()
        self.gallery_preview_future = None
        self.gallery_preview_cache_key: Optional[Tuple[str, str]] = None
        self._gallery_swipe_start_x: Optional[int] = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the gallery UI."""
        gallery_main = ttk.Panedwindow(self, orient=tk.VERTICAL)
        gallery_main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        top_frame = ttk.Frame(gallery_main)
        gallery_main.add(top_frame, weight=3)
        
        grid_label = ttk.Label(top_frame, text="🎞️ Gallery View", font=("", 11, "bold"))
        grid_label.pack(fill=tk.X, pady=(0, 8))
        
        canvas_frame = ttk.Frame(top_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        self.gallery_canvas = tk.Canvas(
            canvas_frame,
            bg="#1f2123",
            highlightthickness=0
        )
        gallery_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.gallery_canvas.yview)
        self.gallery_canvas.config(yscrollcommand=gallery_scrollbar.set)
        
        gallery_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.gallery_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.gallery_inner_frame = ttk.Frame(self.gallery_canvas)
        self.gallery_canvas_window = self.gallery_canvas.create_window(
            (0, 0), window=self.gallery_inner_frame, anchor=tk.NW
        )
        
        self.gallery_inner_frame.bind("<Configure>", self._on_gallery_frame_configure)
        self.gallery_canvas.bind("<Configure>", self._on_gallery_canvas_configure)
        
        bottom_frame = ttk.Frame(gallery_main)
        gallery_main.add(bottom_frame, weight=2)
        
        preview_header = ttk.Frame(bottom_frame)
        preview_header.pack(fill=tk.X, pady=(8, 8))
        
        self.gallery_preview_label = ttk.Label(
            preview_header, 
            text="Select an archive to preview", 
            font=("", 10, "bold")
        )
        self.gallery_preview_label.pack(side=tk.LEFT)
        
        nav_frame = ttk.Frame(preview_header)
        nav_frame.pack(side=tk.RIGHT)
        
        self.gallery_prev_btn = ttk.Button(
            nav_frame,
            text="◀",
            command=self._gallery_prev_image,
            width=3,
            bootstyle="secondary-outline"
        )
        self.gallery_prev_btn.pack(side=tk.LEFT, padx=(0, 5))
        self.gallery_prev_btn.config(state=tk.DISABLED)
        
        self.gallery_img_info = ttk.Label(nav_frame, text="", font=("", 9))
        self.gallery_img_info.pack(side=tk.LEFT, padx=10)
        
        self.gallery_next_btn = ttk.Button(
            nav_frame,
            text="▶",
            command=self._gallery_next_image,
            width=3,
            bootstyle="secondary-outline"
        )
        self.gallery_next_btn.pack(side=tk.LEFT, padx=(5, 0))
        self.gallery_next_btn.config(state=tk.DISABLED)
        
        preview_container = ttk.Frame(bottom_frame, relief=tk.FLAT, borderwidth=1)
        preview_container.pack(fill=tk.BOTH, expand=True)
        
        self.gallery_preview_img = tk.Label(
            preview_container,
            background="#2a2d2e",
            text="",
            anchor=tk.CENTER,
            cursor="hand2",
            fg="#ffffff",
            font=("", 10)
        )
        self.gallery_preview_img.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        self.gallery_preview_img.bind("<MouseWheel>", self._gallery_on_scroll)
        if platform.system() == "Linux":
            self.gallery_preview_img.bind("<Button-4>", self._gallery_on_scroll)
            self.gallery_preview_img.bind("<Button-5>", self._gallery_on_scroll)
        
        self.gallery_preview_img.bind("<ButtonPress-1>", self._gallery_swipe_start)
        self.gallery_preview_img.bind("<ButtonRelease-1>", self._gallery_swipe_end)
    
    def _on_gallery_frame_configure(self, event=None):
        """Update scroll region when gallery frame changes."""
        self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all"))
    
    def _on_gallery_canvas_configure(self, event):
        """Adjust inner frame width when canvas is resized."""
        canvas_width = event.width
        self.gallery_canvas.itemconfig(self.gallery_canvas_window, width=canvas_width)
    
    def populate(self):
        """Populate gallery with thumbnails of ZIP files."""
        for child in self.gallery_inner_frame.winfo_children():
            child.destroy()
        
        self.gallery_cards.clear()
        self.gallery_thumb_labels.clear()
        self.gallery_title_labels.clear()
        
        zip_paths = list(self.zip_files.keys())
        if not zip_paths:
            empty_label = ttk.Label(
                self.gallery_inner_frame,
                text="No archives yet.\nUse 'Scan Directory' to add ZIP files.",
                font=("", 11),
                justify=tk.CENTER
            )
            empty_label.grid(row=0, column=0, padx=20, pady=40)
            self._reset_gallery_preview()
            return
        
        for idx, zip_path in enumerate(zip_paths):
            self._create_gallery_card(zip_path, idx)
        
        self._reflow_gallery_cards()
    
    def _reflow_gallery_cards(self):
        """Arrange gallery cards in grid layout."""
        zip_paths = list(self.gallery_cards.keys())
        for idx, zip_path in enumerate(zip_paths):
            row = idx // self.gallery_columns
            col = idx % self.gallery_columns
            self.gallery_cards[zip_path].grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
        
        for col in range(self.gallery_columns):
            self.gallery_inner_frame.grid_columnconfigure(col, weight=1)
        
        self._schedule_gallery_thumbnail_poll()
    
    def _create_gallery_card(self, zip_path: str, index: int):
        """Create a gallery card for a ZIP file."""
        card = tk.Frame(
            self.gallery_inner_frame,
            bg="#2a2d2e",
            bd=2,
            relief=tk.FLAT,
            cursor="hand2",
            highlightthickness=1,
            highlightbackground="#3a3d40"
        )
        self.gallery_cards[zip_path] = card
        
        thumb_label = tk.Label(
            card,
            text="Loading cover...",
            bg="#2a2d2e",
            fg="#f8f9fa",
            wraplength=200,
            justify=tk.CENTER,
            width=24,
            height=10
        )
        thumb_label.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.gallery_thumb_labels[zip_path] = thumb_label
        
        title_label = tk.Label(
            card,
            text=os.path.basename(zip_path),
            bg="#2a2d2e",
            fg="#f8f9fa",
            wraplength=200,
            justify=tk.CENTER,
            font=("Segoe UI", 10, "bold")
        )
        title_label.pack(fill=tk.X, padx=6, pady=(0, 4))
        self.gallery_title_labels[zip_path] = title_label
        
        meta_label = tk.Label(
            card,
            text=self._format_gallery_meta(self.zip_files.get(zip_path)),
            bg="#2a2d2e",
            fg="#b0b4b8",
            wraplength=200,
            justify=tk.CENTER,
            font=("Segoe UI", 9)
        )
        meta_label.pack(fill=tk.X, padx=6, pady=(0, 6))
        
        for widget in (card, thumb_label, title_label, meta_label):
            widget.bind("<Button-1>", lambda e, path=zip_path: self._on_gallery_card_click(path))
        
        entry = self.zip_files.get(zip_path)
        members = entry[0] if entry else None
        if members is None:
            members = self.ensure_members_loaded(zip_path)
        
        if members:
            existing_thumb = self.gallery_thumbnails.get(zip_path)
            if existing_thumb:
                thumb_label.config(image=existing_thumb, text="")
                thumb_label.image = existing_thumb
            else:
                self._request_gallery_thumbnail(zip_path, members[0])
        else:
            thumb_label.config(text="No images found", fg="#ffb347")
    
    def _format_gallery_meta(self, entry) -> str:
        """Format metadata display for gallery card."""
        if not entry:
            return ""
        _, _, file_size, image_count = entry
        size_str = _format_size(file_size) if file_size else "?"
        return f"📷 {image_count} • 📦 {size_str}"
    
    def _on_gallery_card_click(self, zip_path: str):
        """Handle gallery card click event."""
        self.gallery_selected_zip = zip_path
        self._update_gallery_selection_styles()
        
        entry = self.zip_files.get(zip_path)
        if not entry:
            return
        
        members = entry[0]
        if members is None:
            members = self.ensure_members_loaded(zip_path)
        
        if not members:
            self.gallery_current_members = None
            self.gallery_preview_label.config(text="No images found")
            self.gallery_prev_btn.config(state=tk.DISABLED)
            self.gallery_next_btn.config(state=tk.DISABLED)
            return
        
        self.gallery_current_members = members
        basename = os.path.basename(zip_path)
        self.gallery_preview_label.config(text=f"📦 {basename}")
        
        self._gallery_load_preview_image(0)
    
    def _update_gallery_selection_styles(self):
        """Update card styles based on current selection."""
        for path, card in self.gallery_cards.items():
            if path == self.gallery_selected_zip:
                card.config(highlightbackground="#00bc8c", highlightthickness=3, bd=2)
            else:
                card.config(highlightbackground="#3a3d40", highlightthickness=1, bd=2)
    
    def _reset_gallery_preview(self):
        """Reset gallery preview area."""
        self.gallery_preview_label.config(text="Select an archive to preview")
        self.gallery_preview_img.config(image='', text="")
        self.gallery_preview_img.image = None
        self.gallery_img_info.config(text="")
        self.gallery_prev_btn.config(state=tk.DISABLED)
        self.gallery_next_btn.config(state=tk.DISABLED)
        
        self.gallery_selected_zip = None
        self.gallery_current_members = None
        self.gallery_image_index = 0
    
    def _request_gallery_thumbnail(self, zip_path: str, member_path: str):
        """Queue a thumbnail load request for a gallery card."""
        cache_key = (zip_path, member_path)
        if cache_key in self.gallery_thumbnail_requests:
            return
        
        self.gallery_thumbnail_requests[cache_key] = zip_path
        
        self.thread_pool.submit(
            load_image_data_async,
            zip_path,
            member_path,
            self.app_settings['max_thumbnail_size'],
            self.config["GALLERY_THUMB_SIZE"],
            self.gallery_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.app_settings['performance_mode']
        )
    
    def _schedule_gallery_thumbnail_poll(self):
        """Start polling loop to apply loaded thumbnails."""
        if self._gallery_thumbnail_after_id is None:
            self._gallery_thumbnail_after_id = self.after(30, self._process_gallery_thumbnail_queue)
    
    def _process_gallery_thumbnail_queue(self):
        """Consume gallery thumbnail results from worker threads."""
        self._gallery_thumbnail_after_id = None
        try:
            while True:
                result = self.gallery_queue.get_nowait()
                zip_path = self.gallery_thumbnail_requests.pop(result.cache_key, None)
                if not zip_path:
                    continue
                label = self.gallery_thumb_labels.get(zip_path)
                if not label:
                    continue
                
                if result.success and result.data:
                    photo = ImageTk.PhotoImage(result.data)
                    self.gallery_thumbnails[zip_path] = photo
                    label.config(image=photo, text="")
                    label.image = photo
                else:
                    message = result.error_message or "Failed to load"
                    label.config(text=message, fg="#ff7b72", image="")
                    label.image = None
        except queue.Empty:
            pass
        
        if self.gallery_thumbnail_requests:
            self._schedule_gallery_thumbnail_poll()

    def _notify_selection(self):
        """Notify external listener about current selection."""
        if (
            self.selection_callback
            and self.gallery_selected_zip
            and self.gallery_current_members
        ):
            self.selection_callback(
                self.gallery_selected_zip,
                self.gallery_current_members,
                self.gallery_image_index
            )

    def _gallery_load_preview_image(self, index: int):
        """Load preview image for selected ZIP in gallery."""
        if not self.gallery_current_members or index < 0 or index >= len(self.gallery_current_members):
            return

        self.gallery_image_index = index

        self.gallery_prev_btn.config(state=tk.NORMAL if index > 0 else tk.DISABLED)
        self.gallery_next_btn.config(state=tk.NORMAL if index < len(self.gallery_current_members) - 1 else tk.DISABLED)
        
        self.gallery_img_info.config(
            text=f"{index + 1} / {len(self.gallery_current_members)}"
        )
        
        if self.gallery_preview_future and not self.gallery_preview_future.done():
            self.gallery_preview_future.cancel()
        
        while True:
            try:
                self.gallery_preview_queue.get_nowait()
            except queue.Empty:
                break
        
        cache_key = (self.gallery_selected_zip, self.gallery_current_members[index])
        self.gallery_preview_cache_key = cache_key
        
        self.gallery_preview_img.config(image='', text="Loading...")
        self.gallery_preview_img.image = None
        
        self.gallery_preview_future = self.thread_pool.submit(
            load_image_data_async,
            self.gallery_selected_zip,
            self.gallery_current_members[index],
            self.app_settings['max_thumbnail_size'],
            self.config["GALLERY_PREVIEW_SIZE"],
            self.gallery_preview_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.app_settings['performance_mode']
        )
        
        self._notify_selection()
        self.after(20, self._check_gallery_preview_result)
    
    def _check_gallery_preview_result(self):
        """Check if gallery preview image is ready."""
        expected_key = self.gallery_preview_cache_key
        if expected_key is None:
            return
        
        try:
            while True:
                result = self.gallery_preview_queue.get_nowait()
                if result.cache_key != expected_key:
                    continue
                
                if result.success and result.data:
                    photo = ImageTk.PhotoImage(result.data)
                    self.gallery_preview_img.config(image=photo, text="")
                    self.gallery_preview_img.image = photo
                else:
                    message = result.error_message or "Preview failed"
                    self.gallery_preview_img.config(image='', text=f"Error: {message}")
                    self.gallery_preview_img.image = None
                
                self.gallery_preview_future = None
                return
        except queue.Empty:
            if self.gallery_preview_future and not self.gallery_preview_future.done():
                self.after(20, self._check_gallery_preview_result)
    
    def _gallery_prev_image(self):
        """Show previous image in gallery preview."""
        if self.gallery_current_members and self.gallery_image_index > 0:
            self._gallery_load_preview_image(self.gallery_image_index - 1)
    
    def _gallery_next_image(self):
        """Show next image in gallery preview."""
        if self.gallery_current_members and self.gallery_image_index < len(self.gallery_current_members) - 1:
            self._gallery_load_preview_image(self.gallery_image_index + 1)
    
    def _gallery_on_scroll(self, event):
        """Handle mouse wheel scrolling in gallery preview."""
        if not self.gallery_current_members:
            return
        
        if platform.system() == "Linux":
            delta = 1 if event.num == 4 else -1
        else:
            delta = 1 if event.delta > 0 else -1
        
        if delta > 0:
            self._gallery_prev_image()
        else:
            self._gallery_next_image()
    
    def _gallery_swipe_start(self, event):
        """Record swipe start position."""
        self._gallery_swipe_start_x = event.x
    
    def _gallery_swipe_end(self, event):
        """Handle swipe gesture."""
        if self._gallery_swipe_start_x is None:
            return
        
        delta_x = event.x - self._gallery_swipe_start_x
        threshold = 50
        
        if abs(delta_x) > threshold:
            if delta_x > 0:
                self._gallery_prev_image()
            else:
                self._gallery_next_image()
        
        self._gallery_swipe_start_x = None
    
    def handle_keypress(self, event):
        """Handle keyboard navigation in gallery view."""
        if event.keysym in ("Left", "Up"):
            self._gallery_prev_image()
            return "break"
        elif event.keysym in ("Right", "Down", "space"):
            self._gallery_next_image()
            return "break"
        elif event.keysym == "Home":
            self._gallery_load_preview_image(0)
            return "break"
        elif event.keysym == "End":
            if self.gallery_current_members:
                self._gallery_load_preview_image(len(self.gallery_current_members) - 1)
            return "break"
        elif event.keysym == "Return":
            if self.gallery_selected_zip and self.gallery_current_members and self.open_viewer_callback:
                self.open_viewer_callback(
                    self.gallery_selected_zip,
                    self.gallery_current_members,
                    self.gallery_image_index
                )
            return "break"
        elif event.keysym == "Escape":
            self._reset_gallery_preview()
            self._update_gallery_selection_styles()
            return "break"
        return None
    
    def set_viewer_callback(self, callback: Callable[[str, List[str], int], None]):
        """Set the callback for opening the viewer."""
        self.open_viewer_callback = callback
