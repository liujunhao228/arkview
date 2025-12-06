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
        self.display_mode = "gallery"  # "gallery" or "album"
        self.gallery_queue: queue.Queue = queue.Queue()
        self.gallery_thumbnail_requests: Dict[Tuple[str, str], str] = {}
        self._gallery_thumbnail_after_id: Optional[str] = None
        
        # 用于优化滚动的变量
        self._visible_items_range = (0, 0)
        self._last_canvas_y = 0
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the gallery UI with mobile-like design."""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        
        # 顶部导航栏
        self.nav_frame = ttk.Frame(main_frame)
        self.nav_frame.pack(fill=tk.X, padx=12, pady=(8, 8))
        
        self.back_button = ttk.Button(
            self.nav_frame,
            text="⬅ Back to Albums",
            command=self._show_gallery_view,
            bootstyle="secondary-outline",
            state=tk.DISABLED  # 初始状态禁用
        )
        self.back_button.pack(side=tk.LEFT)
        
        self.album_title_label = ttk.Label(
            self.nav_frame, 
            text="🎞️ Gallery", 
            font=("Segoe UI", 13, "bold")
        )
        self.album_title_label.pack(side=tk.LEFT, padx=(10, 0))
        
        self.gallery_count_label = ttk.Label(
            self.nav_frame,
            text="",
            font=("Segoe UI", 9),
            foreground="#888888"
        )
        self.gallery_count_label.pack(side=tk.LEFT, padx=(10, 0))
        
        # 主内容区域
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=8)
        
        self.gallery_canvas = tk.Canvas(
            content_frame,
            bg="#1a1d1e",
            highlightthickness=0
        )
        gallery_scrollbar = ttk.Scrollbar(
            content_frame, 
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
    
    def _process_gallery_thumbnail_queue(self):
        """Consume gallery thumbnail results from worker threads."""
        print(f"Processing gallery thumbnail queue, items: {self.gallery_queue.qsize()}")
        self._gallery_thumbnail_after_id = None
        processed_count = 0
        
        try:
            while processed_count < 30:  # 增加每次处理的数量
                try:
                    result = self.gallery_queue.get_nowait()
                    print(f"Got result from queue: success={getattr(result, 'success', 'N/A')}, cache_key={getattr(result, 'cache_key', 'N/A')}")
                except queue.Empty:
                    break
                    
                # 尝试从结果中提取卡片键
                card_key = self._extract_card_key_from_result(result)
                print(f"Extracted card_key: {card_key}")
                
                # 如果_extract_card_key_from_result没有返回有效的card_key，
                # 则尝试直接使用cache_key（如果它是字符串）或者cache_key的第一个元素
                if not card_key:
                    if hasattr(result, 'cache_key'):
                        if isinstance(result.cache_key, str):
                            card_key = result.cache_key
                        elif isinstance(result.cache_key, tuple) and len(result.cache_key) > 0:
                            # 对于画廊视图，cache_key应该是(zip_path, member_path)
                            card_key = result.cache_key[0]
                
                if not card_key:
                    print(f"No card key found for result with cache_key: {getattr(result, 'cache_key', 'unknown')}")
                    # 清理请求记录
                    self._cleanup_thumbnail_request(result)
                    processed_count += 1
                    continue
                
                label = self.gallery_thumb_labels.get(card_key)
                if not label:
                    # 尝试使用cache_key的第一个元素作为备选
                    if hasattr(result, 'cache_key') and isinstance(result.cache_key, tuple) and len(result.cache_key) > 0:
                        alt_key = result.cache_key[0]
                        label = self.gallery_thumb_labels.get(alt_key)
                        if label:
                            card_key = alt_key  # 更新card_key为实际找到标签的键
                            print(f"Using alternative key: {alt_key}")
                    
                    # 如果仍然找不到标签，则跳过
                    if not label:
                        print(f"No label found for card key: {card_key}")
                        # 清理请求记录
                        self._cleanup_thumbnail_request(result)
                        processed_count += 1
                        continue
                
                # 处理缩略图结果
                self._handle_thumbnail_result(result, card_key, label)
                
                # 清理请求记录
                self._cleanup_thumbnail_request(result)
                
                processed_count += 1
                
        except Exception as e:
            print(f"Error processing thumbnail queue: {e}")
            import traceback
            traceback.print_exc()
        
        # 继续轮询如果有更多请求
        if self.gallery_thumbnail_requests or processed_count > 0:
            self._schedule_gallery_thumbnail_poll()
        
        # 更新画布的滚动区域，确保界面正确显示
        self.after(10, self._update_canvas_scrollregion)
        print(f"Finished processing thumbnail queue, processed: {processed_count}")
    
    def _on_gallery_canvas_configure(self, event=None):
        """Handle canvas configure events."""
        if event:
            # 重新排列卡片以适应新的宽度
            self._reflow_gallery_cards()

    def _on_gallery_frame_configure(self, event=None):
        """增强的frame配置事件处理"""
        # 延迟更新滚动区域以避免频繁调用
        if hasattr(self, '_resize_timer'):
            self.after_cancel(self._resize_timer)
        
        # 增加延迟时间以获得更稳定的布局
        self._resize_timer = self.after(150, self._update_canvas_scrollregion)
        
    def _on_mousewheel(self, event):
        """增强的鼠标滚轮处理"""
        # 先停止正在进行的缩略图处理
        if self._gallery_thumbnail_after_id:
            self.after_cancel(self._gallery_thumbnail_after_id)
            self._gallery_thumbnail_after_id = None
        
        # 执行滚动
        if platform.system() == "Windows":
            delta = int(-1*(event.delta/120))
        elif platform.system() == "Darwin":  # macOS
            delta = int(-1*event.delta)
        else:  # Linux
            if event.num == 4:
                delta = -1
            elif event.num == 5:
                delta = 1
            else:
                delta = 0
        
        if delta != 0:
            self.gallery_canvas.yview_scroll(delta, "units")
        
        # 延迟恢复缩略图处理以减少滚动时的卡顿
        self.after(50, self._schedule_gallery_thumbnail_poll)

    def _on_canvas_click(self, event=None):
        """Handle canvas click events."""
        # 可以根据需要添加点击处理逻辑
        pass

    def _cleanup_unused_thumbnails(self):
        """Clean up unused thumbnails to free memory."""
        # 清理缩略图的逻辑可以根据需要扩展
        pass

    def _is_card_visible(self, index):
        """Check if a card at given index is visible."""
        # 总是返回True以确保所有卡片都被创建并加载缩略图
        # 这样可以避免因为虚拟化而导致的缩略图加载问题
        return True

    def _update_canvas_scrollregion(self):
        """Update the scroll region of the canvas."""
        self.gallery_canvas.update_idletasks()
        bbox = self.gallery_canvas.bbox("all")
        if bbox:
            # 添加额外边距防止内容截断
            margin = 20
            scrollregion = (bbox[0] - margin, bbox[1] - margin, 
                           bbox[2] + margin, bbox[3] + margin)
            self.gallery_canvas.configure(scrollregion=scrollregion)

    def populate(self):
        """Populate gallery with thumbnails of ZIP files."""
        # 确保我们在画廊视图模式
        self.display_mode = "gallery"
        self.back_button.config(state=tk.DISABLED)
        self.album_title_label.config(text="🎞️ Gallery")
        
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
            self.gallery_count_label.config(text="")
            return
        
        self.gallery_count_label.config(text=f"{len(zip_paths)} albums")
        
        for idx, zip_path in enumerate(zip_paths):
            self._create_gallery_card(zip_path, idx)
        
        self._reflow_gallery_cards()
        
        # 重置滚动位置
        self.gallery_canvas.yview_moveto(0)
        
        # 确保缩略图轮询已经启动
        self._schedule_gallery_thumbnail_poll()
    
    def _create_gallery_card(self, zip_path: str, idx: int):
        """改进的画廊卡片创建"""
        card_container = tk.Frame(
            self.gallery_inner_frame,
            bg="#1a1d1e",
            highlightthickness=0,
            width=220,
            height=280
        )
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
        
        # 创建双缓冲的缩略图显示区域
        thumb_container = tk.Frame(card, bg="#1f2224", highlightthickness=0, height=200)
        thumb_container.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        thumb_container.pack_propagate(False)
        
        # 使用带背景的Label防止闪烁
        thumb_label = tk.Label(
            thumb_container,
            text="⏳",
            bg="#1f2224",
            fg="#555555",
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
        
        # 获取文件信息
        entry = self.zip_files.get(zip_path)
        if entry:
            members, size, image_count, _ = entry
            size_text = _format_size(size) if size > 0 else "Unknown"
            count_text = f"{image_count} images" if image_count > 0 else "No images"
            
            details_label = tk.Label(
                info_frame,
                text=f"{count_text} • {size_text}",
                bg="#252829",
                fg="#888888",
                font=("Segoe UI", 8),
                anchor=tk.W
            )
            details_label.pack(fill=tk.X)
        
        # 绑定点击事件 - 点击卡片直接显示专辑内容
        for widget in [card_container, card, thumb_container, thumb_label, info_frame, title_label]:
            widget.bind("<Button-1>", lambda e, z=zip_path: self._on_gallery_card_click(z))
        
        # 请求缩略图
        entry = self.zip_files.get(zip_path)
        if entry:
            if entry[0]:  # 如果有成员列表
                # 使用第一张图片作为缩略图
                self._request_gallery_thumbnail(zip_path, entry[0][0])
            else:
                # 成员列表尚未加载，需要先加载再请求缩略图
                self._request_gallery_thumbnail_for_unloaded_members(zip_path)
                # 确保轮询已经开始
                self._schedule_gallery_thumbnail_poll()
        else:
            # 如果没有entry，显示警告图标
            thumb_label.config(
                text="⚠️",
                font=("Segoe UI", 28),
                fg="#ff7b72"
            )
            # 确保轮询已经开始
            self._schedule_gallery_thumbnail_poll()
    
    def _ensure_members_loaded_and_request_thumbnail(self, zip_path: str):
        """
        确保成员列表已加载，并请求第一张图片作为缩略图。
        如果成员列表为空或加载失败，则显示错误图标。
        """
        try:
            # 确保成员列表已加载
            members = self.ensure_members_loaded(zip_path)
            if members and len(members) > 0:
                # 在主线程中请求第一张图片作为缩略图
                self.after(0, lambda: self._request_gallery_thumbnail(zip_path, members[0]))
            else:
                # 没有找到图片，更新UI显示错误
                self.after(0, lambda: self._show_error_thumbnail(zip_path))
        except Exception as e:
            print(f"Error loading members for {zip_path}: {e}")
            self.after(0, lambda: self._show_error_thumbnail(zip_path))
    
    def _on_gallery_card_click(self, zip_path: str):
        """Handle gallery card click event - show album content in gallery view."""
        self._show_album_view(zip_path)

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
    
    def _request_gallery_thumbnail(self, zip_path: str, member_path: str):
        """Queue a thumbnail load request for a gallery card."""
        cache_key = (zip_path, member_path)
        print(f"Requesting thumbnail for {zip_path}, member: {member_path}, cache_key: {cache_key}")
        
        if cache_key in self.gallery_thumbnail_requests:
            print(f"Thumbnail request already exists for {cache_key}")
            # 即使已经存在请求，也要确保轮询已经开始
            self._schedule_gallery_thumbnail_poll()
            return
        
        # 如果已经有缓存的缩略图，则直接使用
        existing_thumb = self.gallery_thumbnails.get(zip_path)
        if existing_thumb:
            print(f"Using cached thumbnail for {zip_path}")
            label = self.gallery_thumb_labels.get(zip_path)
            if label:
                label.config(image=existing_thumb, text="", bg="#1f2224")
                label.image = existing_thumb
            # 即使使用了缓存，也要确保轮询已经开始
            self._schedule_gallery_thumbnail_poll()
            return
        
        # 正确地将 zip_path 作为值存储，以便后续查找
        self.gallery_thumbnail_requests[cache_key] = zip_path
        print(f"Added thumbnail request: {cache_key} -> {zip_path}")
        
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
        
        # 确保缩略图轮询已经启动
        self._schedule_gallery_thumbnail_poll()
        print("Scheduled thumbnail poll")
    
    def _request_gallery_thumbnail_for_unloaded_members(self, zip_path: str):
        """为成员列表尚未加载的zip文件请求缩略图"""
        def load_and_request():
            try:
                # 加载成员列表
                members = self.ensure_members_loaded(zip_path)
                if members and len(members) > 0:
                    # 获取第一张图片作为缩略图
                    first_image = members[0]
                    # 在主线程中调度缩略图请求
                    self.after(0, lambda: self._request_gallery_thumbnail(zip_path, first_image))
            except Exception as e:
                print(f"Error loading members for {zip_path}: {e}")
                # 在主线程中显示错误
                self.after(0, lambda: self._show_thumbnail_error(zip_path))
        
        # 在线程池中执行成员加载和缩略图请求
        self.thread_pool.submit(load_and_request)
        
    def _show_thumbnail_error(self, zip_path: str):
        """显示缩略图错误"""
        thumb_label = self.gallery_thumb_labels.get(zip_path)
        if thumb_label:
            thumb_label.config(
                text="⚠️",
                font=("Segoe UI", 28),
                fg="#ff7b72"
            )
    
    def _reflow_gallery_cards(self):
        """改进的响应式布局算法并确保触发缩略图加载"""
        # 根据实际窗口大小动态调整列数
        canvas_width = self.gallery_canvas.winfo_width()
        
        # 计算合适的列数 (最小宽度为220px)
        if canvas_width > 0:
            calculated_columns = max(1, canvas_width // 220)
            self.gallery_columns = calculated_columns
        else:
            # 默认列数
            self.gallery_columns = 3
            
        if self.display_mode == "album":
            # 专辑视图使用固定的2列布局
            columns = 2
        else:
            # 画廊视图使用动态计算的列数
            columns = self.gallery_columns
            
        zip_paths = list(self.gallery_cards.keys())
        for idx, zip_path in enumerate(zip_paths):
            row = idx // columns
            col = idx % columns
            self.gallery_cards[zip_path].grid(
                row=row, 
                column=col, 
                padx=8, 
                pady=8, 
                sticky="nsew"
            )
        
        # 配置列和行权重，确保均匀分布
        for col in range(columns):
            self.gallery_inner_frame.grid_columnconfigure(col, weight=1, uniform="card")
        
        # 计算需要的行数
        rows_needed = (len(zip_paths) + columns - 1) // columns
        for row in range(rows_needed):
            self.gallery_inner_frame.grid_rowconfigure(row, weight=1, uniform="card")
        
        # 确保开始处理缩略图队列 - 在布局变化后强制触发缩略图加载
        self._schedule_gallery_thumbnail_poll()
        
        # 延迟更新画布的滚动区域以确保布局稳定
        self.after(50, self._update_canvas_scrollregion)
        
        # 额外确保缩略图轮询已启动（双重保障）
        if not self._gallery_thumbnail_after_id:
            self._schedule_gallery_thumbnail_poll()
    
    def _schedule_gallery_thumbnail_poll(self):
        """带防抖动的轮询调度"""
        # 取消之前的调度
        if self._gallery_thumbnail_after_id is not None:
            self.after_cancel(self._gallery_thumbnail_after_id)
        
        # 延迟执行以合并快速连续的请求
        self._gallery_thumbnail_after_id = self.after(50, self._process_gallery_thumbnail_queue)
    
    def _extract_card_key_from_result(self, result):
        """从结果中提取card_key"""
        try:
            if not hasattr(result, 'cache_key'):
                print("Result object has no attribute 'cache_key'")
                return None
                
            cache_key = result.cache_key
            
            # 情况1: 画廊视图 - cache_key is (zip_path, member_path)
            if isinstance(cache_key, tuple) and len(cache_key) == 2 and not isinstance(cache_key[0], tuple):
                card_key = self.gallery_thumbnail_requests.get(cache_key)
                if card_key:
                    return card_key
                else:
                    print(f"Failed to find card_key for gallery view cache_key: {cache_key}")
                    return None
                    
            # 情况2: 专辑视图 - cache_key is ((zip_path, member_path), card_key)
            elif (isinstance(cache_key, tuple) and len(cache_key) == 2 and 
                  isinstance(cache_key[0], tuple) and len(cache_key[0]) == 2):
                # 返回嵌套元组中的第二个元素，即 card_key
                return cache_key[1]
                
            # 情况3: 兼容旧格式或特殊情况，cache_key 直接是字符串 (zip_path)
            elif isinstance(cache_key, str):
                return cache_key
                
            # 情况4: 长度为1的元组
            elif isinstance(cache_key, tuple) and len(cache_key) == 1:
                return cache_key[0]
                
            else:
                print(f"Unexpected cache_key format: {cache_key} (type: {type(cache_key)})")
                
        except Exception as e:
            print(f"Exception in _extract_card_key_from_result: {e}")
            import traceback
            traceback.print_exc()
            
        return None

    def _handle_thumbnail_result(self, result, card_key, label):
        """处理单个缩略图结果"""
        print(f"Handling thumbnail result for card_key: {card_key}")
        try:
            if result.success and result.data:
                try:
                    print(f"Creating PhotoImage for {card_key}")
                    photo = ImageTk.PhotoImage(result.data)
                    self.gallery_thumbnails[card_key] = photo
                    label.config(image=photo, text="", bg="#1f2224")
                    label.image = photo  # 保持引用
                    print(f"Successfully set thumbnail for {card_key}")
                except Exception as e:
                    print(f"Error creating PhotoImage for {card_key}: {e}")
                    import traceback
                    traceback.print_exc()
                    self._set_error_thumbnail(label)
            else:
                error_msg = getattr(result, 'error_message', 'Unknown error')
                print(f"Thumbnail load failed for {card_key}: {error_msg}")
                self._set_error_thumbnail(label)
        except Exception as e:
            print(f"Error in _handle_thumbnail_result for {card_key}: {e}")
            import traceback
            traceback.print_exc()
            self._set_error_thumbnail(label)

    def _set_error_thumbnail(self, label):
        """设置错误缩略图"""
        label.config(
            text="⚠️",
            font=("Segoe UI", 28),
            fg="#ff7b72",
            image="",
            bg="#1f2224"
        )
        label.image = None

    def _cleanup_thumbnail_request(self, result):
        """清理缩略图请求"""
        try:
            # 画廊视图的请求记录需要被清理，专辑视图的不需要
            if (hasattr(result, 'cache_key') and 
                isinstance(result.cache_key, tuple) and 
                len(result.cache_key) == 2 and 
                not isinstance(result.cache_key[0], tuple)):
                if result.cache_key in self.gallery_thumbnail_requests:
                    del self.gallery_thumbnail_requests[result.cache_key]
        except Exception as e:
            print(f"Error cleaning up thumbnail request: {e}")
    
    def _debug_thumbnail_process(self):
        """调试缩略图处理流程"""
        print("=== Thumbnail Process Debug Info ===")
        print(f"Gallery thumbnail requests: {len(self.gallery_thumbnail_requests)}")
        print(f"Gallery thumbnails: {len(self.gallery_thumbnails)}")
        print(f"Gallery thumb labels: {len(self.gallery_thumb_labels)}")
        print(f"Gallery cards: {len(self.gallery_cards)}")
        
        if self.gallery_thumbnail_requests:
            print("Current thumbnail requests:")
            for key, value in self.gallery_thumbnail_requests.items():
                print(f"  {key} -> {value}")
        
        if self.gallery_thumbnails:
            print("Current thumbnails:")
            for key, value in self.gallery_thumbnails.items():
                print(f"  {key}: {type(value)}")
        
        if self.gallery_thumb_labels:
            print("Current thumb labels:")
            for key, value in self.gallery_thumb_labels.items():
                print(f"  {key}: {value}")
    
    def _show_gallery_view(self):
        """显示压缩包画廊视图"""
        self.display_mode = "gallery"
        self.back_button.config(state=tk.DISABLED)
        self.album_title_label.config(text="🎞️ Gallery")
        self.populate()
        # 确保缩略图加载开始
        self._schedule_gallery_thumbnail_poll()
    
    def _show_album_view(self, zip_path: str):
        """显示特定压缩包的内容视图"""
        self.display_mode = "album"
        self.back_button.config(state=tk.NORMAL)
        album_name = os.path.basename(zip_path)
        self.album_title_label.config(text=f"📁 {album_name}")
        self._display_album_content(zip_path)
        # 确保缩略图加载开始
        self._schedule_gallery_thumbnail_poll()