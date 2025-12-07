"""
Gallery View for Arkview - PySide Implementation
"""

import os
import platform
import queue
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QFrame, QScrollArea, QGridLayout, QLabel, QSizePolicy,
    QVBoxLayout, QHBoxLayout, QWidget, QScrollBar, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread, Slot
from PySide6.QtGui import QPixmap, QPalette, QColor
from PIL import Image
import PIL.ImageQt

from .core import ZipFileManager, LRUCache, load_image_data_async, _format_size, ImageLoaderSignals


class GalleryThumbnailWorker(QObject):
    """Worker object for handling gallery thumbnail loading."""
    thumbnailLoaded = Signal(object, tuple)  # LoadResult, cache_key
    load_thumbnail = Signal(str, str, tuple, int, tuple, bool)  # 添加信号定义
    finished = Signal()  # 添加finished信号
    
    def __init__(self, cache, zip_manager, config):
        super().__init__()
        self.cache = cache
        self.zip_manager = zip_manager
        self.config = config
        self.running = True  # 添加 running 属性以保持接口一致
        # 连接信号到槽
        self.load_thumbnail.connect(self.process_load_thumbnail)
        
    @Slot(str, str, tuple, int, tuple, bool)
    def process_load_thumbnail(self, zip_path: str, member_path: str, cache_key: tuple,
                              max_size: int, resize_params: tuple, performance_mode: bool):
        """Load a thumbnail in a worker thread."""
        try:
            # Create signals instance for this load operation
            signals = ImageLoaderSignals()
            signals.image_loaded.connect(lambda result: self.thumbnailLoaded.emit(result, cache_key))
            
            # Call the async loading function with signals
            load_image_data_async(
                zip_path, member_path, max_size, resize_params,
                signals, self.cache, cache_key, self.zip_manager, performance_mode
            )
        except Exception as e:
            print(f"Error loading gallery thumbnail: {e}")
        finally:
            # 发出finished信号
            self.finished.emit()


class GalleryView(QFrame):
    """Gallery view component with mobile-like UX and modern design."""

    def __init__(
        self,
        parent: QWidget,
        zip_files: Dict[str, Tuple[Optional[List[str]], float, int, int]],
        app_settings: Dict[str, Any],
        cache: LRUCache,
        zip_manager: ZipFileManager,
        config: Dict[str, Any],
        ensure_members_loaded_func: Callable[[str], Optional[List[str]]],
        on_selection_changed: Callable[[str, List[str], int], None],
        open_viewer_func: Callable[[str, List[str], int], None]
    ):
        super().__init__(parent)
        self.zip_files = zip_files
        self.app_settings = app_settings
        self.cache = cache
        self.zip_manager = zip_manager
        self.config = config
        self.ensure_members_loaded = ensure_members_loaded_func
        self.on_selection_changed = on_selection_changed
        self.open_viewer_func = open_viewer_func

        # 移除对thread_pool的依赖，使用Qt信号槽机制
        
        # Gallery cards storage
        self.cards: List[GalleryCard] = []
        self.card_mapping: Dict[Tuple[str, str], GalleryCard] = {}
        
        # Threading components for background loading
        self.loading_thread = QThread()
        self.loading_worker = GalleryThumbnailWorker(
            self.cache, self.zip_manager, self.config
        )
        self.loading_worker.moveToThread(self.loading_thread)
        # 连接 load_thumbnail 信号到其处理槽
        self.loading_worker.load_thumbnail.connect(self.loading_worker.process_load_thumbnail)
        self.loading_worker.thumbnailLoaded.connect(self._on_thumbnail_loaded)
        self.loading_worker.finished.connect(self.loading_thread.quit)
        self.loading_thread.start()
        
        # UI state
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.gallery_widget = QWidget()
        self.gallery_layout = QGridLayout(self.gallery_widget)
        self.gallery_layout.setContentsMargins(10, 10, 10, 10)
        self.gallery_layout.setSpacing(10)
        
        self.scroll_area.setWidget(self.gallery_widget)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.scroll_area)
        
        self._apply_dark_theme()

    @Slot(object, tuple)
    def _handle_thumbnail_result_slot(self, result, cache_key):
        """Handle thumbnail result from worker thread."""
        self._handle_thumbnail_result(result, cache_key)
        # Force UI refresh if needed
        if hasattr(self, 'gallery_widget') and self.gallery_widget:
            self.gallery_widget.show()
            self.gallery_widget.repaint()

    def _cleanup_worker(self):
        """Clean up worker thread resources."""
        # 停止缩略图工作线程
        if hasattr(self, 'thumbnail_worker'):
            self.thumbnail_worker.running = False
        if hasattr(self, 'thumbnail_thread'):
            self.thumbnail_thread.quit()
            self.thumbnail_thread.wait(1000)  # Wait up to 1 second
            
        # 停止画廊缩略图工作线程
        if hasattr(self, 'gallery_thumbnail_worker'):
            # 如果未来需要在 GalleryThumbnailWorker 中加入中断逻辑，可以在这里设置标志
            pass
        if hasattr(self, 'gallery_thumbnail_thread'):
            self.gallery_thumbnail_thread.quit()
            self.gallery_thumbnail_thread.wait(1000)  # Wait up to 1 second

    def closeEvent(self, event):
        """Handle view closing."""
        try:
            self._cleanup_worker()
        except Exception as e:
            # Ignore errors during cleanup
            pass
        super().closeEvent(event)

    def _apply_dark_theme(self):
        """Apply dark theme to the gallery view."""
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(26, 29, 30))
        self.setPalette(palette)
        
        self.setStyleSheet("""
            GalleryView {
                background-color: #1a1d1e;
            }
            QLabel {
                color: #e8eaed;
            }
            QFrame {
                background-color: #252829;
                border: none;
            }
        """)

    def _setup_ui(self):
        """Setup the gallery UI with mobile-like design."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Top navigation bar
        self.nav_frame = QFrame()
        self.nav_frame.setFixedHeight(50)  # Increase height for better proportion
        self.nav_frame.setStyleSheet("background-color: #2c323c; border: none;")
        nav_layout = QHBoxLayout(self.nav_frame)
        nav_layout.setContentsMargins(12, 8, 12, 8)

        self.back_button = QLabel("⬅ Back to Albums")
        self.back_button.setStyleSheet("color: #e8eaed; font-weight: bold;")
        self.back_button.setFixedWidth(150)
        self._back_button_enabled = False  # Track state since QLabel doesn't have enabled property
        nav_layout.addWidget(self.back_button)

        # Install event filter to handle clicks
        self.back_button.installEventFilter(self)

        self.album_title_label = QLabel("🎞️ Gallery")
        self.album_title_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #e8eaed;")  # Slightly larger font
        nav_layout.addWidget(self.album_title_label)

        self.gallery_count_label = QLabel("")
        self.gallery_count_label.setStyleSheet("font-size: 10pt; color: #888888;")  # Slightly larger font
        nav_layout.addWidget(self.gallery_count_label)

        # Add spacer to push other items to the left
        nav_spacer = QWidget()
        nav_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        nav_layout.addWidget(nav_spacer)

        main_layout.addWidget(self.nav_frame)

        # Main content area with scroll
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #1a1d1e;
                border: none;
            }
            QScrollBar:vertical {
                background: #2c323c;
                width: 15px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #565c64;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #676e7a;
            }
        """)

        self.gallery_inner_widget = QWidget()
        self.gallery_inner_layout = QGridLayout(self.gallery_inner_widget)
        self.gallery_inner_layout.setAlignment(Qt.AlignTop)
        self.gallery_inner_layout.setSpacing(12)  # Add spacing between cards

        scroll_area.setWidget(self.gallery_inner_widget)

        main_layout.addWidget(scroll_area)

        # Create a container frame for event handling
        self.gallery_container = scroll_area

    def populate(self):
        """Populate the gallery with images from all ZIP files."""
        # Clear existing cards
        self.clear()
        
        # Create cards for all images in all ZIP files
        for zip_path, (members, _, _, _) in self.zip_files.items():
            if not members:
                # Try to load members if not available
                members = self.ensure_members_loaded(zip_path)
                if not members:
                    continue
                    
            for member_name in members:
                card = GalleryCard(zip_path, member_name, self)
                card.clicked.connect(self._on_card_clicked)
                self.gallery_layout.addWidget(card)
                self.cards.append(card)
                self.card_mapping[(zip_path, member_name)] = card
                
        # Trigger initial thumbnail loading and processing
        QTimer.singleShot(0, self._reflow_gallery_cards)
        
    def clear(self):
        """Clear all gallery cards."""
        for card in self.cards:
            card.setParent(None)
        self.cards.clear()
        self.card_mapping.clear()

    def _prepare_gallery_view(self):
        """Prepare the gallery view mode."""
        self.display_mode = "gallery"
        # self.back_button.setEnabled(False)  # This needs to be fixed
        self.album_title_label.setText("🎞️ Gallery")

    def _show_empty_gallery_message(self):
        """Show a message when no albums are present in the gallery."""
        empty_label = QLabel("No albums yet\n\nUse 'Scan Directory' to add archives")
        empty_label.setAlignment(Qt.AlignCenter)
        empty_label.setStyleSheet("font-size: 12pt; color: #666666;")
        empty_label.setMinimumHeight(300)
        self.gallery_inner_layout.addWidget(empty_label, 0, 0, 1, 1)
        self.gallery_count_label.setText("")

    def _calculate_columns_for_gallery_view(self):
        """Calculate the number of columns for gallery view based on available width."""
        available_width = self.gallery_inner_widget.width()
        if available_width > 0:
            calculated_columns = max(1, available_width // 250)  # Adjust for new card width
            self.gallery_columns = calculated_columns
        else:
            self.gallery_columns = 3

    def _create_gallery_cards(self, zip_paths: List[str]):
        """Create gallery cards for each ZIP file."""
        for idx, zip_path in enumerate(zip_paths):
            row = idx // self.gallery_columns
            col = idx % self.gallery_columns
            self._create_gallery_card(zip_path, idx, row, col)

    def _create_gallery_card(self, zip_path: str, idx: int, row: int, col: int):
        """Create a gallery card for a ZIP file."""
        # Card container
        card_container = self._create_card_container()
        
        # Add hover effect with event filter
        card_container.installEventFilter(self)
        
        layout = QVBoxLayout(card_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Thumbnail container
        thumb_container = self._create_thumbnail_container()
        thumb_layout = QVBoxLayout(thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)

        # Thumbnail label
        thumb_label = self._create_thumbnail_label(zip_path)
        thumb_layout.addWidget(thumb_label)
        self.gallery_thumb_labels[zip_path] = thumb_label

        layout.addWidget(thumb_container)

        # Info frame
        info_frame = self._create_info_frame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(12, 10, 12, 10)  # More spacious margins

        title_label = self._create_title_label(zip_path)
        info_layout.addWidget(title_label)
        self.gallery_title_labels[zip_path] = title_label

        # File details
        self._add_file_details(info_layout, zip_path)

        layout.addWidget(info_frame)

        # Store the card
        self.gallery_cards[zip_path] = card_container

        # Connect click event
        self._connect_card_click_events(zip_path, card_container, thumb_label, title_label, info_frame)

        # Add to layout
        self.gallery_inner_layout.addWidget(card_container, row, col)

        # Request thumbnail
        self._request_card_thumbnail(zip_path)
        
        # Force refresh
        card_container.show()
        card_container.repaint()

    def _create_card_container(self) -> QWidget:
        """Create the main container for a gallery card."""
        card_container = QWidget()
        card_container.setFixedSize(240, 300)  # Slightly larger for better proportions
        card_container.setStyleSheet("""
            QWidget {
                background-color: #252829;
                border: none;
                border-radius: 6px;  /* Slightly larger radius */
            }
        """)
        return card_container

    def _create_thumbnail_container(self) -> QWidget:
        """Create the container for the thumbnail image."""
        thumb_container = QWidget()
        thumb_container.setFixedSize(240, 210)  # Adjust size accordingly
        thumb_container.setStyleSheet("background-color: #1f2224;")
        return thumb_container

    def _create_thumbnail_label(self, zip_path: str) -> QLabel:
        """Create the label for displaying the thumbnail."""
        thumb_label = QLabel()
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("background-color: #1f2224; color: #555555; font-size: 32pt;")
        thumb_label.setText("⏳")
        thumb_label.setMinimumSize(240, 210)  # Adjust size accordingly
        return thumb_label

    def _create_info_frame(self) -> QWidget:
        """Create the frame containing file information."""
        info_frame = QWidget()
        info_frame.setStyleSheet("background-color: #252829;")
        return info_frame

    def _create_title_label(self, zip_path: str) -> QLabel:
        """Create the label for displaying the file title."""
        title_label = QLabel(os.path.basename(zip_path))
        title_label.setStyleSheet("color: #ffffff; font-size: 11pt; font-weight: bold; text-align: left;")  # Larger font
        title_label.setWordWrap(True)
        return title_label

    def _add_file_details(self, info_layout: QVBoxLayout, zip_path: str):
        """Add file details to the info layout."""
        entry = self.zip_files.get(zip_path)
        if entry:
            members, mod_time, file_size, image_count = entry
            size_text = _format_size(file_size) if file_size > 0 else "Unknown"
            count_text = f"{image_count} images" if image_count > 0 else "No images"

            details_label = QLabel(f"{count_text} • {size_text}")
            details_label.setStyleSheet("color: #888888; font-size: 9pt; text-align: left;")  # Larger font
            info_layout.addWidget(details_label)

    def _connect_card_click_events(self, zip_path: str, card_container: QWidget, 
                                  thumb_label: QLabel, title_label: QLabel, info_frame: QWidget):
        """Connect click events for all parts of the card."""
        thumb_label.mousePressEvent = lambda event, z=zip_path: self._on_gallery_card_click(z)
        title_label.mousePressEvent = lambda event, z=zip_path: self._on_gallery_card_click(z)
        info_frame.mousePressEvent = lambda event, z=zip_path: self._on_gallery_card_click(z)
        card_container.mousePressEvent = lambda event, z=zip_path: self._on_gallery_card_click(z)

    def _request_card_thumbnail(self, zip_path: str):
        """Request thumbnail for a gallery card."""
        entry = self.zip_files.get(zip_path)
        if entry:
            if entry[0]:  # If there's a members list
                # Use the first image as thumbnail
                self._request_gallery_thumbnail(zip_path, entry[0][0])
            else:
                # Members list not loaded yet, need to load first
                self._request_gallery_thumbnail_for_unloaded_members(zip_path)
        else:
            # If no entry, show error icon
            thumb_label = self.gallery_thumb_labels.get(zip_path)
            if thumb_label:
                thumb_label.setText("⚠️")
                thumb_label.setStyleSheet("color: #ff7b72; font-size: 28pt;")

    def _request_gallery_thumbnail_for_unloaded_members(self, zip_path: str):
        """Request thumbnail for a gallery card that hasn't loaded members yet."""
        # Load members first
        members = self.ensure_members_loaded(zip_path)
        if members:
            # Now request thumbnail with first member
            self._request_gallery_thumbnail(zip_path, members[0])
        else:
            # Show error if no members
            thumb_label = self.gallery_thumb_labels.get(zip_path)
            if thumb_label:
                thumb_label.setText("⚠️")
                thumb_label.setStyleSheet("color: #ff7b72; font-size: 28pt;")

    def _on_gallery_card_click(self, zip_path: str):
        """Handle gallery card click event - show album content in gallery view."""
        self._show_album_view(zip_path)

    def _request_gallery_thumbnail(self, zip_path: str, member_path: str):
        """Queue a thumbnail load request for a gallery card."""
        cache_key = (zip_path, member_path)
        if cache_key in self.gallery_thumbnail_requests:
            return

        # If there's already a cached thumbnail, use it
        existing_thumb = self.gallery_thumbnails.get(zip_path)
        if existing_thumb:
            label = self.gallery_thumb_labels.get(zip_path)
            if label:
                label.setPixmap(existing_thumb)
                label.setText("")
                label.setStyleSheet("background-color: #1f2224;")
                # Force refresh
                label.show()
                label.repaint()
            return

        # Store the zip path to use as card key later
        self.gallery_thumbnail_requests[cache_key] = zip_path

        # 使用工作线程加载缩略图
        # Emit signal to worker thread
        self.gallery_thumbnail_worker.load_thumbnail.emit(
            zip_path, member_path,
            cache_key,
            self.app_settings['max_thumbnail_size'],
            self.config["GALLERY_THUMB_SIZE"],
            self.app_settings['performance_mode']
        )

    def resizeEvent(self, event):
        """Handle resize events to reflow gallery cards."""
        super().resizeEvent(event)
        # Recalculate columns based on new width
        if hasattr(self, 'gallery_widget') and self.gallery_widget:
            available_width = self.gallery_widget.width()
            if available_width > 0:
                # Note: Using gallery_layout instead of non-existent gallery_inner_layout
                calculated_columns = max(1, available_width // 250)  # Adjust for card width
                if hasattr(self, 'gallery_columns') and calculated_columns != self.gallery_columns:
                    self.gallery_columns = calculated_columns
                    self._reflow_gallery_cards()
            elif self.display_mode == "album":
                calculated_columns = max(1, available_width // 240)  # 220px卡片宽度 + 20px间距
                if calculated_columns != self.gallery_columns:
                    self.gallery_columns = calculated_columns
                    self._reflow_cards()

    def _reflow_cards(self):
        """Reflow gallery cards based on current column count."""
        self._clear_layout_widgets()
        
        # Re-add widgets with new positions
        if self.display_mode == "gallery":
            self._reflow_gallery_cards()
        elif self.display_mode == "album" and self.current_album_zip_path:
            self._reflow_album_cards()
        
        # Force refresh the layout
        self.gallery_inner_widget.show()
        self.gallery_inner_widget.repaint()

    def _clear_layout_widgets(self):
        """Clear all widgets from the gallery layout."""
        if hasattr(self, 'gallery_layout'):
            for i in reversed(range(self.gallery_layout.count())):
                widget = self.gallery_layout.itemAt(i).widget()
                if widget:
                    self.gallery_layout.removeWidget(widget)

    def _reflow_gallery_cards(self):
        """Reflow gallery cards based on current viewport."""
        if not hasattr(self, 'cards') or not self.cards:
            return
            
        # Calculate visible area
        if not hasattr(self, 'scroll_area') or not self.scroll_area:
            return
            
        scroll_pos = self.scroll_area.verticalScrollBar().value()
        viewport_height = self.scroll_area.viewport().height()
        card_height = 200  # Approximate card height
        spacing = 10       # Spacing between cards
        
        # Calculate which cards should be visible
        start_index = max(0, (scroll_pos // (card_height + spacing)) - 5)  # Add buffer
        visible_count = (viewport_height // (card_height + spacing)) + 10   # Add buffer
        
        # Clear layout
        if hasattr(self, 'gallery_layout'):
            for i in reversed(range(self.gallery_layout.count())):
                widget = self.gallery_layout.itemAt(i).widget()
                if widget:
                    self.gallery_layout.removeWidget(widget)
                
        # Add visible cards back to layout
        end_index = min(len(self.cards), start_index + visible_count)
        for i in range(start_index, end_index):
            if hasattr(self, 'gallery_layout'):
                self.gallery_layout.addWidget(self.cards[i])
            
        # Request thumbnails for visible cards
        for i in range(start_index, end_index):
            card = self.cards[i]
            # 使用正确的参数调用_request_gallery_thumbnail
            if hasattr(self, 'loading_worker') and self.loading_worker:
                self._queue_gallery_thumbnail(card.zip_path, card.member_name)
            
        # 不再需要处理队列，因为使用了Qt信号槽机制

    def _reflow_album_cards(self):
        """Reflow image cards in album view mode."""
        entry = self.zip_files.get(self.current_album_zip_path)
        if entry:
            members = entry[0]
            if members is None:
                members = self.ensure_members_loaded(self.current_album_zip_path)
            
            if members:
                for idx, member_path in enumerate(members):
                    row = idx // self.gallery_columns
                    col = idx % self.gallery_columns
                    card_key = f"{self.current_album_zip_path}:{idx}"
                    if card_key in self.gallery_cards:
                        self.gallery_inner_layout.addWidget(self.gallery_cards[card_key], row, col)
                # Force refresh the layout
                self.gallery_inner_widget.show()
                self.gallery_inner_widget.repaint()

    @Slot(object, tuple)
    def _handle_gallery_thumbnail_loaded(self, result, cache_key):
        """处理画廊缩略图加载结果"""
        if result.success and cache_key:
            # 更新UI
            zip_path = cache_key[0]
            pixmap = result.data
            if pixmap:
                # Convert PIL Image to QPixmap
                qimage = PIL.ImageQt.ImageQt(pixmap)
                qpixmap = QPixmap.fromImage(qimage)
                self.gallery_thumbnails[zip_path] = qpixmap
                label = self.gallery_thumb_labels.get(zip_path)
                if label:
                    label.setPixmap(qpixmap)
                    label.setText("")
                    label.setStyleSheet("background-color: #1f2224;")
                    # Force refresh
                    label.show()
                    label.repaint()
        else:
            # 显示错误
            zip_path = cache_key[0] if cache_key else "unknown"
            label = self.gallery_thumb_labels.get(zip_path)
            if label:
                label.setText("⚠️")
                label.setStyleSheet("color: #ff7b72; font-size: 28pt;")
                # Force refresh
                label.show()
                label.repaint()
                
        # 从请求列表中移除
        if cache_key in self.gallery_thumbnail_requests:
            del self.gallery_thumbnail_requests[cache_key]

    def _show_gallery_view(self, event=None):
        """Show the ZIP file gallery view."""
        self.display_mode = "gallery"
        self._back_button_enabled = False
        self._update_back_button_style()
        self.album_title_label.setText("🎞️ Gallery")
        self.populate()

    def _update_back_button_style(self):
        """Update the back button visual style based on enabled state."""
        if self._back_button_enabled:
            self.back_button.setStyleSheet("color: #00bc8c; font-weight: bold; text-decoration: underline;")
        else:
            self.back_button.setStyleSheet("color: #555555; font-weight: bold;")

    def _show_album_view(self, zip_path: str):
        """Show the contents of a specific ZIP file."""
        self.display_mode = "album"
        self.current_album_zip_path = zip_path  # 存储当前相册的zip路径
        self._back_button_enabled = True
        self._update_back_button_style()
        album_name = os.path.basename(zip_path)
        self.album_title_label.setText(f"📁 {album_name}")
        self._display_album_content(zip_path)

    def _display_album_content(self, zip_path: str):
        """Display the contents of a ZIP file."""
        # Clear existing content
        self._clear_gallery_content()

        entry = self.zip_files.get(zip_path)
        if not entry:
            return

        members = self._get_members_for_zip(zip_path, entry)
        if not members:
            self._show_no_images_message()
            return

        self.gallery_count_label.setText(f"{len(members)} images")
        
        # Calculate number of columns based on available width
        self._calculate_columns_for_album_view()
        
        # Create grid for album view based on calculated columns
        self._create_album_grid(zip_path, members)
        
        # Force UI refresh
        self.gallery_inner_widget.show()
        self.gallery_inner_widget.repaint()
        self.gallery_container.show()
        self.gallery_container.repaint()

    def _clear_gallery_content(self):
        """Clear all content from the gallery view."""
        for i in reversed(range(self.gallery_inner_layout.count())):
            self.gallery_inner_layout.itemAt(i).widget().setParent(None)

        # Clear references
        self.gallery_cards.clear()
        self.gallery_thumb_labels.clear()
        self.gallery_title_labels.clear()

    def _get_members_for_zip(self, zip_path: str, entry: Tuple[Optional[List[str]], float, int, int]) -> Optional[List[str]]:
        """Get members list for a ZIP file, loading if necessary."""
        members = entry[0]
        if members is None:
            members = self.ensure_members_loaded(zip_path)
        return members

    def _show_no_images_message(self):
        """Show a message when no images are found in the album."""
        empty_label = QLabel("No images found in this album")
        empty_label.setAlignment(Qt.AlignCenter)
        empty_label.setStyleSheet("font-size: 12pt; color: #666666;")
        empty_label.setMinimumHeight(300)
        self.gallery_inner_layout.addWidget(empty_label, 0, 0, 1, 1)
        self.gallery_count_label.setText("0 images")

    def _calculate_columns_for_album_view(self):
        """Calculate the number of columns for album view based on available width."""
        available_width = self.gallery_inner_widget.width()
        if available_width > 0:
            # 根据可用宽度计算列数，最小卡片宽度为220像素
            calculated_columns = max(1, available_width // 240)  # 220px卡片宽度 + 20px间距
            self.gallery_columns = calculated_columns
        else:
            self.gallery_columns = 3  # 默认列数

    def _create_album_grid(self, zip_path: str, members: List[str]):
        """Create the grid of image cards for the album view."""
        for idx, member_path in enumerate(members):
            row = idx // self.gallery_columns
            col = idx % self.gallery_columns
            self._create_image_card(zip_path, member_path, idx, row, col)

    def _create_image_card(self, zip_path: str, member_path: str, index: int, row: int, col: int):
        """Create a card for a single image in album view."""
        # Card container
        card_key = f"{zip_path}:{index}"
        card_container = self._create_image_card_container()
        
        layout = QVBoxLayout(card_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Thumbnail container
        thumb_container = self._create_image_thumbnail_container()
        thumb_layout = QVBoxLayout(thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)

        thumb_label = self._create_image_thumbnail_label()
        thumb_layout.addWidget(thumb_label)
        self.gallery_thumb_labels[card_key] = thumb_label

        layout.addWidget(thumb_container)

        # Info frame
        info_frame = self._create_image_info_frame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 8, 10, 8)  # 调整边距

        title_label = self._create_image_title_label(member_path)
        info_layout.addWidget(title_label)
        self.gallery_title_labels[card_key] = title_label

        layout.addWidget(info_frame)

        # Store the card
        self.gallery_cards[card_key] = card_container

        # Connect click event
        self._connect_image_card_click_events(zip_path, member_path, index, card_container, thumb_label, title_label, info_frame)
        
        # Add to layout
        self.gallery_inner_layout.addWidget(card_container, row, col)

        # Request thumbnail for this image
        self._request_image_thumbnail(zip_path, member_path, card_key)
        
        # Force refresh
        card_container.show()
        card_container.repaint()

    def _create_image_card_container(self) -> QWidget:
        """Create the main container for an image card."""
        card_key = f"{self.sender() if self.sender() else 'unknown'}"  # Placeholder - will be overridden
        card_container = QWidget()
        card_container.setFixedSize(220, 290)  # 调整高度以更好地容纳信息
        card_container.setStyleSheet("""
            QWidget {
                background-color: #2c323c;
                border: none;
                border-radius: 6px;
            }
        """)
        return card_container

    def _create_image_thumbnail_container(self) -> QWidget:
        """Create the container for the image thumbnail."""
        thumb_container = QWidget()
        thumb_container.setFixedSize(220, 190)  # 调整缩略图容器大小
        thumb_container.setStyleSheet("background-color: #1f2224; border-top-left-radius: 6px; border-top-right-radius: 6px;")
        return thumb_container

    def _create_image_thumbnail_label(self) -> QLabel:
        """Create the label for displaying the image thumbnail."""
        thumb_label = QLabel()
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("background-color: #1f2224; color: #555555; font-size: 32pt;")
        thumb_label.setText("⏳")
        thumb_label.setMinimumSize(220, 190)  # 调整缩略图标签大小
        return thumb_label

    def _create_image_info_frame(self) -> QWidget:
        """Create the frame containing image information."""
        info_frame = QWidget()
        info_frame.setStyleSheet("background-color: #2c323c; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
        return info_frame

    def _create_image_title_label(self, member_path: str) -> QLabel:
        """Create the label for displaying the image title."""
        title_label = QLabel(os.path.basename(member_path))
        title_label.setStyleSheet("color: #ffffff; font-size: 9pt; font-weight: bold; text-align: left;")
        title_label.setWordWrap(True)
        title_label.setMaximumHeight(20)  # 限制标题高度
        return title_label

    def _request_image_thumbnail(self, zip_path: str, member_path: str, card_key: str):
        """Request thumbnail for a specific image in album view."""
        cache_key = (zip_path, member_path)
        
        # Check if already cached
        cached_result = self.cache.get(cache_key)
        # LRUCache中存储的是Image对象而不是LoadResult对象
        if cached_result:
            label = self.gallery_thumb_labels.get(card_key)
            if label:
                # Convert PIL Image to QPixmap
                qimage = PIL.ImageQt.ImageQt(cached_result)
                qpixmap = QPixmap.fromImage(qimage)
                label.setPixmap(qpixmap)
                label.setText("")
                label.setStyleSheet("background-color: #1f2224;")
                # Force refresh
                label.show()
                label.repaint()
            return

        # Use gallery thumbnail worker to load thumbnail
        self.gallery_thumbnail_worker.load_thumbnail.emit(
            zip_path, 
            member_path,
            cache_key,
            self.app_settings['max_thumbnail_size'],
            self.config["GALLERY_THUMB_SIZE"],
            self.app_settings['performance_mode']
        )

    def _connect_image_card_click_events(self, zip_path: str, member_path: str, index: int,
                                       card_container: QWidget, thumb_label: QLabel, 
                                       title_label: QLabel, info_frame: QWidget):
        """Connect click events for all parts of the image card."""
        handler = lambda event, z=zip_path, m=member_path, i=index: self._on_image_card_click(z, m, i)
        thumb_label.mousePressEvent = handler
        title_label.mousePressEvent = handler
        info_frame.mousePressEvent = handler
        card_container.mousePressEvent = handler

    def _on_image_card_click(self, zip_path: str, member_path: str, index: int):
        """Handle image card click event - open viewer."""
        if self.open_viewer_callback:
            # Get all members for this ZIP
            entry = self.zip_files.get(zip_path)
            if entry:
                members = self._get_members_for_zip(zip_path, entry)
                if members:
                    self.open_viewer_callback(zip_path, members, index)

    def handle_keypress(self, direction: str):
        """Handle gallery navigation keys."""
        # This function is called from the main app when in gallery mode
        # Currently just a placeholder for future implementation
        pass

    def eventFilter(self, source, event):
        """Event filter for handling events including card hover effects and back button clicks."""
        from PySide6.QtCore import QEvent

        # Handle back button click
        if source == self.back_button:
            if event.type() == QEvent.MouseButtonPress and self._back_button_enabled:
                self._show_gallery_view()
                return True  # Event handled

        # Handle card hover effects
        if event.type() == QEvent.Enter and source in self.gallery_cards.values():
            source.setStyleSheet("""
                QWidget {
                    background-color: #3a3f4b;
                    border: none;
                    border-radius: 4px;
                }
            """)
        elif event.type() == QEvent.Leave and source in self.gallery_cards.values():
            source.setStyleSheet("""
                QWidget {
                    background-color: #252829;
                    border: none;
                    border-radius: 4px;
                }
            """)
        return super().eventFilter(source, event)

    def _queue_gallery_thumbnail(self, zip_path: str, member_name: str):
        """Queue a gallery thumbnail for loading."""
        cache_key = (zip_path, member_name)
        
        # Check if already cached
        if cache_key in self.cache:
            cached_result = self.cache.get(cache_key)
            card = self.card_mapping.get(cache_key)
            if card and cached_result:
                card.set_thumbnail(cached_result)
            return

        # Add to loading queue using Qt signals instead of standard Queue
        self.loading_worker.load_thumbnail.emit(
            zip_path,
            member_name,
            cache_key,
            self.app_settings['max_thumbnail_size'],
            self.config["GALLERY_THUMB_SIZE"], 
            self.app_settings['performance_mode']
        )

    @Slot(object, tuple)
    def _on_thumbnail_loaded(self, result, cache_key):
        """Handle loaded thumbnail result."""
        # Find the corresponding card
        card = self.card_mapping.get(cache_key)
        if card:
            if result.success and result.data:
                try:
                    # Convert PIL Image to QPixmap
                    qimage = PIL.ImageQt.ImageQt(result.data)
                    qpixmap = QPixmap.fromImage(qimage)
                    card.set_thumbnail(qpixmap)
                except Exception as e:
                    print(f"Error converting image for gallery card: {e}")
                    card.set_error(str(e))
            else:
                error_msg = result.error_message if hasattr(result, 'error_message') else "Unknown error"
                card.set_error(error_msg)
                
    def closeEvent(self, event):
        """Handle view closing."""
        self._cleanup_worker()
        super().closeEvent(event)
