"""
Gallery View for Arkview - mobile-like browsing with enhanced UX.
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
    """Gallery view component with mobile-like UX and modern design."""
    
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
        self.min_card_width = 200
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
        self._gallery_swipe_start_y: Optional[int] = None
        
        # 用于优化滚动的变量
        self._visible_items_range = (0, 0)
        self._last_canvas_y = 0
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the gallery UI with mobile-like design."""
        gallery_main = ttk.Panedwindow(self, orient=tk.VERTICAL)
        gallery_main.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        
        top_frame = ttk.Frame(gallery_main)
        gallery_main.add(top_frame, weight=2)
        
        header_frame = ttk.Frame(top_frame)
        header_frame.pack(fill=tk.X, padx=12, pady=(8, 8))
        
        grid_label = ttk.Label(
            header_frame, 
            text="🎞️ Gallery", 
            font=("Segoe UI", 13, "bold")
        )
        grid_label.pack(side=tk.LEFT)
        
        self.gallery_count_label = ttk.Label(
            header_frame,
            text="",
            font=("Segoe UI", 9),
            foreground="#888888"
        )
        self.gallery_count_label.pack(side=tk.LEFT, padx=(10, 0))
        
        canvas_frame = ttk.Frame(top_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=8)
        
        self.gallery_canvas = tk.Canvas(
            canvas_frame,
            bg="#1a1d1e",
            highlightthickness=0
        )
        gallery_scrollbar = ttk.Scrollbar(
            canvas_frame, 
            orient=tk.VERTICAL, 
            command=self.gallery_canvas.yview
        )
        self.gallery_canvas.config(yscrollcommand=gallery_scrollbar.set)
        
        gallery_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.gallery_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.gallery_inner_frame = ttk.Frame(self.gallery_canvas)
        self.gallery_canvas_window = self.gallery_canvas.create_window(
            (0, 0), window=self.gallery_inner_frame, anchor=tk.NW
        )
        
        self.gallery_inner_frame.bind("<Configure>", self._on_gallery_frame_configure)
        self.gallery_canvas.bind("<Configure>", self._on_gallery_canvas_configure)
        
        # 添加鼠标滚轮支持
        self.gallery_canvas.bind("<MouseWheel>", self._on_mousewheel)
        if platform.system() == "Linux":
            self.gallery_canvas.bind("<Button-4>", self._on_mousewheel)
            self.gallery_canvas.bind("<Button-5>", self._on_mousewheel)
        
        # 绑定滚动事件以优化渲染
        self.gallery_canvas.bind("<Button-1>", self._on_canvas_click, "+")
        
        bottom_frame = ttk.Frame(gallery_main)
        gallery_main.add(bottom_frame, weight=3)
        
        preview_header = ttk.Frame(bottom_frame)
        preview_header.pack(fill=tk.X, padx=12, pady=(12, 8))
        
        self.gallery_preview_label = ttk.Label(
            preview_header, 
            text="Tap an album to preview", 
            font=("Segoe UI", 11, "bold")
        )
        self.gallery_preview_label.pack(side=tk.LEFT)
        
        nav_frame = ttk.Frame(preview_header)
        nav_frame.pack(side=tk.RIGHT)
        
        self.gallery_prev_btn = ttk.Button(
            nav_frame,
            text="❮",
            command=self._gallery_prev_image,
            width=4,
            bootstyle="secondary"
        )
        self.gallery_prev_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.gallery_prev_btn.config(state=tk.DISABLED)
        
        self.gallery_img_info = ttk.Label(
            nav_frame, 
            text="", 
            font=("Segoe UI", 10),
            foreground="#ffffff"
        )
        self.gallery_img_info.pack(side=tk.LEFT, padx=8)
        
        self.gallery_next_btn = ttk.Button(
            nav_frame,
            text="❯",
            command=self._gallery_next_image,
            width=4,
            bootstyle="secondary"
        )
        self.gallery_next_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.gallery_next_btn.config(state=tk.DISABLED)
        
        preview_container = ttk.Frame(bottom_frame)
        preview_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        
        self.gallery_preview_img = tk.Label(
            preview_container,
            background="#1a1d1e",
            text="",
            anchor=tk.CENTER,
            cursor="hand2",
            fg="#888888",
            font=("Segoe UI", 11)
        )
        self.gallery_preview_img.pack(fill=tk.BOTH, expand=True)
        
        self.gallery_preview_img.bind("<Double-Button-1>", lambda e: self._open_viewer_from_preview())
        self.gallery_preview_img.bind("<Button-1>", self._gallery_swipe_start)
        self.gallery_preview_img.bind("<B1-Motion>", self._gallery_swipe_motion)
        self.gallery_preview_img.bind("<ButtonRelease-1>", self._gallery_swipe_end)
        self.gallery_preview_img.bind("<MouseWheel>", self._gallery_on_scroll)
        if platform.system() == "Linux":
            self.gallery_preview_img.bind("<Button-4>", self._gallery_on_scroll)
            self.gallery_preview_img.bind("<Button-5>", self._gallery_on_scroll)
    
    def _on_canvas_click(self, event):
        """处理画布点击事件"""
        # 当用户点击画布时，确保更新可见区域
        self.after(100, self._update_visible_region)
    
    def _update_visible_region(self):
        """更新可见区域信息"""
        # 获取当前视口的边界
        canvas_height = self.gallery_canvas.winfo_height()
        if canvas_height <= 1:  # 窗口可能还未完全初始化
            return
            
        # 获取当前滚动位置
        scroll_top = self.gallery_canvas.canvasy(0)
        scroll_bottom = scroll_top + canvas_height
        
        self._last_canvas_y = scroll_top
        
        # 这里可以添加虚拟化逻辑，但现在我们只记录可见区域范围
        self._visible_items_range = (int(scroll_top), int(scroll_bottom))
    
    def _on_mousewheel(self, event):
        """处理鼠标滚轮事件以滚动画廊"""
        if platform.system() == "Linux":
            if event.num == 4:
                self.gallery_canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.gallery_canvas.yview_scroll(1, "units")
        else:
            self.gallery_canvas.yview_scroll(int(-1*(event.delta/100)), "units")
            
        # 滚动后更新可见区域
        self.after(50, self._update_visible_region)
    
    def _on_gallery_frame_configure(self, event=None):
        """Update scroll region when gallery frame changes."""
        # 使用update_idletasks确保布局完成后再计算边界框
        self.gallery_canvas.update_idletasks()
        bbox = self.gallery_canvas.bbox("all")
        if bbox:
            self.gallery_canvas.configure(scrollregion=bbox)
        
        # 确保内部框架的宽度与画布可视区域一致
        canvas_width = self.gallery_canvas.winfo_width()
        self.gallery_canvas.itemconfig(self.gallery_canvas_window, width=canvas_width)
    
    def _on_gallery_canvas_configure(self, event):
        """Adjust inner frame width and responsive columns when canvas is resized."""
        canvas_width = event.width
        self.gallery_canvas.itemconfig(self.gallery_canvas_window, width=canvas_width)
        
        new_columns = max(1, min(5, canvas_width // self.min_card_width))
        if new_columns != self.gallery_columns:
            self.gallery_columns = new_columns
            self._reflow_gallery_cards()
        else:
            # 即使列数未变，也要确保更新滚动区域
            self._update_canvas_scrollregion()
    
    def _update_canvas_scrollregion(self):
        """更新画布滚动区域以匹配内容"""
        self.gallery_canvas.update_idletasks()
        bbox = self.gallery_canvas.bbox("all")
        if bbox:
            # 添加一些额外的边距以避免底部被截断
            extended_bbox = (bbox[0], bbox[1], bbox[2], bbox[3] + 20)
            self.gallery_canvas.configure(scrollregion=extended_bbox)
    
    def populate(self):
        """Populate gallery with thumbnails of ZIP files."""
        # 清除现有内容
        for child in self.gallery_inner_frame.winfo_children():
            child.destroy()
        
        # 清除引用以帮助垃圾回收
        self.gallery_cards.clear()
        self.gallery_thumb_labels.clear()
        self.gallery_title_labels.clear()
        
        # 清理不再需要的缩略图以释放内存
        self._cleanup_unused_thumbnails()
        
        zip_paths = list(self.zip_files.keys())
        if not zip_paths:
            empty_label = ttk.Label(
                self.gallery_inner_frame,
                text="No albums yet\n\nUse 'Scan Directory' to add archives",
                font=("Segoe UI", 12),
                justify=tk.CENTER,
                foreground="#666666"
            )
            empty_label.grid(row=0, column=0, padx=20, pady=80)
            self._reset_gallery_preview()
            self.gallery_count_label.config(text="")
            return
        
        self.gallery_count_label.config(text=f"{len(zip_paths)} albums")
        
        for idx, zip_path in enumerate(zip_paths):
            self._create_gallery_card(zip_path, idx)
        
        self._reflow_gallery_cards()
        
        # 重置滚动位置
        self.gallery_canvas.yview_moveto(0)
    
    def _cleanup_unused_thumbnails(self):
        """清理未使用的缩略图以释放内存"""
        # 获取当前所有ZIP路径的集合
        current_zip_paths = set(self.zip_files.keys())
        
        # 找出不再需要的缩略图
        unused_thumbs = set(self.gallery_thumbnails.keys()) - current_zip_paths
        
        # 删除不再需要的缩略图
        for zip_path in unused_thumbs:
            photo = self.gallery_thumbnails.pop(zip_path, None)
            if photo:
                # 删除对PhotoImage的引用以帮助垃圾回收
                del photo
        
        # 清理缩略图请求队列中相关的请求
        keys_to_remove = [
            key for key in self.gallery_thumbnail_requests.keys() 
            if key[0] not in current_zip_paths
        ]
        for key in keys_to_remove:
            self.gallery_thumbnail_requests.pop(key, None)
    
    def _reflow_gallery_cards(self):
        """Arrange gallery cards in responsive grid layout."""
        zip_paths = list(self.gallery_cards.keys())
        for idx, zip_path in enumerate(zip_paths):
            row = idx // self.gallery_columns
            col = idx % self.gallery_columns
            self.gallery_cards[zip_path].grid(
                row=row, 
                column=col, 
                padx=8, 
                pady=8, 
                sticky="nsew"
            )
        
        # 配置列和行权重，确保均匀分布
        for col in range(self.gallery_columns):
            self.gallery_inner_frame.grid_columnconfigure(col, weight=1, uniform="card")
        
        # 计算需要的行数
        rows_needed = (len(zip_paths) + self.gallery_columns - 1) // self.gallery_columns
        for row in range(rows_needed):
            self.gallery_inner_frame.grid_rowconfigure(row, weight=1, uniform="card")
        
        # 更新画布的滚动区域
        self._update_canvas_scrollregion()
        self._schedule_gallery_thumbnail_poll()
    
    def _create_gallery_card(self, zip_path: str, index: int):
        """Create a modern gallery card with mobile-like styling."""
        card_container = tk.Frame(
            self.gallery_inner_frame,
            bg="#1a1d1e",
            highlightthickness=0,
            width=220,  # 固定宽度
            height=280  # 固定高度
        )
        # 确保卡片容器不会收缩
        card_container.grid_propagate(False)
        
        card = tk.Frame(
            card_container,
            bg="#252829",
            bd=0,
            relief=tk.FLAT,
            cursor="hand2",
            highlightthickness=0
        )
        card.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        self.gallery_cards[zip_path] = card_container
        
        # 设置缩略图容器的固定高度
        thumb_container = tk.Frame(card, bg="#1f2224", highlightthickness=0, height=200)
        thumb_container.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        thumb_container.pack_propagate(False)  # 防止子组件改变容器大小
        
        thumb_label = tk.Label(
            thumb_container,
            text="⏳",
            bg="#1f2224",
            fg="#555555",
            wraplength=220,
            justify=tk.CENTER,
            font=("Segoe UI", 32),
            width=20,
            height=8
        )
        thumb_label.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        self.gallery_thumb_labels[zip_path] = thumb_label
        
        info_frame = tk.Frame(card, bg="#252829", highlightthickness=0)
        info_frame.pack(fill=tk.X, padx=12, pady=8)
        
        title_label = tk.Label(
            info_frame,
            text=os.path.basename(zip_path),
            bg="#252829",
            fg="#ffffff",
            wraplength=220,
            justify=tk.LEFT,
            font=("Segoe UI", 10, "bold"),
            anchor=tk.W
        )
        title_label.pack(fill=tk.X, pady=(0, 4))
        self.gallery_title_labels[zip_path] = title_label
        
        meta_label = tk.Label(
            info_frame,
            text=self._format_gallery_meta(self.zip_files.get(zip_path)),
            bg="#252829",
            fg="#888888",
            wraplength=220,
            justify=tk.LEFT,
            font=("Segoe UI", 9),
            anchor=tk.W
        )
        meta_label.pack(fill=tk.X)
        
        # 使用更高效的方式绑定事件
        self._bind_card_events(card_container, card, thumb_container, thumb_label, 
                              info_frame, title_label, meta_label, zip_path)
        
        entry = self.zip_files.get(zip_path)
        members = entry[0] if entry else None
        if members is None:
            members = self.ensure_members_loaded(zip_path)
        
        if members:
            existing_thumb = self.gallery_thumbnails.get(zip_path)
            if existing_thumb:
                thumb_label.config(image=existing_thumb, text="", bg="#1f2224")
                thumb_label.image = existing_thumb
            else:
                self._request_gallery_thumbnail(zip_path, members[0])
        else:
            thumb_label.config(
                text="📭",
                font=("Segoe UI", 28),
                fg="#ff8866"
            )
        
        # 确保每次添加新卡片后更新滚动区域
        self.after(10, self._update_canvas_scrollregion)
    
    def _bind_card_events(self, *widgets_and_path):
        """为卡片的所有组件绑定事件"""
        zip_path = widgets_and_path[-1]
        widgets = widgets_and_path[:-1]
        
        for widget in widgets:
            widget.bind("<Button-1>", lambda e, path=zip_path: self._on_gallery_card_click(path))
            widget.bind("<Enter>", lambda e, c=widgets[1]: self._on_card_hover(c, True))
            widget.bind("<Leave>", lambda e, c=widgets[1]: self._on_card_hover(c, False))
    
    def _on_card_hover(self, card: tk.Frame, is_entering: bool):
        """Handle card hover effect."""
        if is_entering:
            # 只在不是选中状态时才改变颜色
            card_container = card.master
            if card_container and card_container != self.gallery_selected_zip:
                card.config(bg="#2d3031")
        else:
            # 恢复默认颜色
            card.config(bg="#252829")
    
    def _format_gallery_meta(self, entry) -> str:
        """Format metadata display for gallery card."""
        if not entry:
            return ""
        _, _, file_size, image_count = entry
        size_str = _format_size(file_size) if file_size else "?"
        return f"🖼 {image_count} images  •  {size_str}"
    
    def _on_gallery_card_click(self, zip_path: str):
        """Handle gallery card click event with visual feedback."""
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
            self.gallery_preview_img.config(image='', text="This album is empty")
            return
        
        self.gallery_current_members = members
        basename = os.path.basename(zip_path)
        self.gallery_preview_label.config(text=basename)
        
        self._gallery_load_preview_image(0)
    
    def _update_gallery_selection_styles(self):
        """Update card styles with modern selection indicator."""
        for path, card_container in self.gallery_cards.items():
            card = card_container.winfo_children()[0] if card_container.winfo_children() else None
            if not card:
                continue
                
            if path == self.gallery_selected_zip:
                card_container.config(bg="#00bc8c")
                card.config(highlightthickness=0)
            else:
                card_container.config(bg="#1a1d1e")
                card.config(highlightthickness=0)
    
    def _reset_gallery_preview(self):
        """Reset gallery preview area."""
        self.gallery_preview_label.config(text="Tap an album to preview")
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
        
        # 如果已经有缓存的缩略图，则直接使用
        existing_thumb = self.gallery_thumbnails.get(zip_path)
        if existing_thumb:
            label = self.gallery_thumb_labels.get(zip_path)
            if label:
                label.config(image=existing_thumb, text="", bg="#1f2224")
                label.image = existing_thumb
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
        processed_count = 0
        try:
            while processed_count < 10:  # 限制每次处理的数量以避免界面冻结
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
                    label.config(image=photo, text="", bg="#1f2224")
                    label.image = photo
                else:
                    message = result.error_message or "Failed"
                    label.config(
                        text="⚠️",
                        font=("Segoe UI", 28),
                        fg="#ff7b72",
                        image=""
                    )
                    label.image = None
                    
                processed_count += 1
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
        
        self.gallery_preview_img.config(image='', text="⏳ Loading...")
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
                    self.gallery_preview_img.config(
                        image='', 
                        text=f"⚠️ {message}",
                        font=("Segoe UI", 10)
                    )
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
        """Record swipe start position for both horizontal and vertical."""
        self._gallery_swipe_start_x = event.x
        self._gallery_swipe_start_y = event.y
    
    def _gallery_swipe_motion(self, event):
        """Handle swipe motion (for visual feedback if needed)."""
        pass
    
    def _gallery_swipe_end(self, event):
        """Handle swipe gesture with improved detection."""
        if self._gallery_swipe_start_x is None or self._gallery_swipe_start_y is None:
            return
        
        delta_x = event.x - self._gallery_swipe_start_x
        delta_y = event.y - self._gallery_swipe_start_y
        threshold = 50
        
        if abs(delta_x) > abs(delta_y) and abs(delta_x) > threshold:
            if delta_x > 0:
                self._gallery_prev_image()
            else:
                self._gallery_next_image()
        elif abs(delta_x) < 10 and abs(delta_y) < 10:
            self._open_viewer_from_preview()
        
        self._gallery_swipe_start_x = None
        self._gallery_swipe_start_y = None
    
    def _open_viewer_from_preview(self):
        """Open viewer when preview is clicked."""
        if self.gallery_selected_zip and self.gallery_current_members and self.open_viewer_callback:
            self.open_viewer_callback(
                self.gallery_selected_zip,
                self.gallery_current_members,
                self.gallery_image_index
            )
    
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
            self._open_viewer_from_preview()
            return "break"
        elif event.keysym == "Escape":
            self._reset_gallery_preview()
            self._update_gallery_selection_styles()
            return "break"
        return None
    
    def set_viewer_callback(self, callback: Callable[[str, List[str], int], None]):
        """Set the callback for opening the viewer."""
        self.open_viewer_callback = callback
