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

from .core import ZipFileManager, LRUCache, load_image_data_async, _format_size


class ThumbnailWorker(QObject):
    """Worker object for handling thumbnail loading in a separate thread."""
    thumbnailLoaded = Signal(object, tuple)  # LoadResult, cache_key
    finished = Signal()
    
    def __init__(self, gallery_queue):
        super().__init__()
        self.gallery_queue = gallery_queue
        self.running = True
        
    @Slot()
    def processThumbnails(self):
        """Process thumbnail loading tasks."""
        try:
            while self.running:
                try:
                    result = self.gallery_queue.get(timeout=0.1)
                    if result:
                        self.thumbnailLoaded.emit(result, getattr(result, 'cache_key', None))
                except queue.Empty:
                    # Timeout, continue loop
                    continue
                except Exception as e:
                    print(f"Error processing thumbnail: {e}")
        except Exception as e:
            print(f"Fatal error in thumbnail worker: {e}")
        finally:
            self.finished.emit()
        
        
class GalleryView(QFrame):
    """Gallery view component with mobile-like UX and modern design."""

    def __init__(
        self,
        parent,
        zip_files: Dict[str, Tuple[Optional[List[str]], float, int, int]],
        app_settings: Dict[str, Any],
        cache: LRUCache,
        thread_pool,
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
        self.gallery_thumbnails: Dict[str, QPixmap] = {}
        self.gallery_cards: Dict[str, QWidget] = {}  # Changed from tk.Frame to QWidget
        self.gallery_thumb_labels: Dict[str, QLabel] = {}
        self.gallery_title_labels: Dict[str, QLabel] = {}
        self.gallery_selected_zip: Optional[str] = None
        self.gallery_selected_index: int = 0
        self.gallery_image_index: int = 0
        self.gallery_current_members: Optional[List[str]] = None
        self.display_mode = "gallery"  # "gallery" or "album"
        self.current_album_zip_path: Optional[str] = None  # 添加当前专辑zip路径属性
        self.gallery_queue: queue.Queue = queue.Queue()
        self.gallery_thumbnail_requests: Dict[Tuple[str, str], str] = {}
        self._gallery_thumbnail_after_id: Optional[str] = None

        # For optimizing scrolling
        self._visible_items_range = (0, 0)
        self._last_canvas_y = 0

        # Setup threaded thumbnail loading
        self.thumbnail_thread = QThread()
        self.thumbnail_worker = ThumbnailWorker(self.gallery_queue)
        self.thumbnail_worker.moveToThread(self.thumbnail_thread)
        self.thumbnail_worker.thumbnailLoaded.connect(self._handle_thumbnail_result_slot)
        self.thumbnail_thread.started.connect(self.thumbnail_worker.processThumbnails)
        self.thumbnail_thread.start()

        # Add cleanup connection
        self.destroyed.connect(self._cleanup_worker)

        self._setup_ui()
        
        # Apply dark theme
        self._apply_dark_theme()

    @Slot(object, tuple)
    def _handle_thumbnail_result_slot(self, result, cache_key):
        """Handle thumbnail result from worker thread."""
        self._handle_thumbnail_result(result, cache_key)

    def _cleanup_worker(self):
        """Clean up worker thread resources."""
        if hasattr(self, 'thumbnail_worker'):
            self.thumbnail_worker.running = False
        if hasattr(self, 'thumbnail_thread'):
            self.thumbnail_thread.quit()
            self.thumbnail_thread.wait(1000)  # Wait up to 1 second

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
        """Populate gallery with thumbnails of ZIP files."""
        # Ensure we're in gallery view mode
        self._prepare_gallery_view()
        
        # Clear existing content
        self._clear_gallery_content()

        zip_paths = list(self.zip_files.keys())
        if not zip_paths:
            self._show_empty_gallery_message()
            return

        self.gallery_count_label.setText(f"{len(zip_paths)} albums")

        # Calculate number of columns based on available width
        self._calculate_columns_for_gallery_view()

        # Create cards for each ZIP file
        self._create_gallery_cards(zip_paths)

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
            return

        # Store the zip path to use as card key later
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

        # With our threaded approach, we don't need explicit polling scheduling
        # The worker thread will emit signals when thumbnails are ready

    def _request_gallery_thumbnail_for_unloaded_members(self, zip_path: str):
        """Request thumbnail for a ZIP file with unloaded members."""
        def load_and_request():
            try:
                # Load members
                members = self.ensure_members_loaded(zip_path)
                if members and len(members) > 0:
                    # Get first image as thumbnail
                    first_image = members[0]
                    self._request_gallery_thumbnail(zip_path, first_image)
            except Exception as e:
                print(f"Error loading members for {zip_path}: {e}")
                # Show error in UI from the main thread
                # Since this is in a thread, we'd need to emit a signal or use invokeMethod

        # Submit to thread pool
        self.thread_pool.submit(load_and_request)

    def resizeEvent(self, event):
        """Handle resize events to reflow gallery cards."""
        super().resizeEvent(event)
        # Recalculate columns based on new width
        available_width = self.gallery_inner_widget.width()
        if available_width > 0:
            if self.display_mode == "gallery" and self.gallery_cards:
                calculated_columns = max(1, available_width // 250)  # Match card width
                if calculated_columns != self.gallery_columns:
                    self.gallery_columns = calculated_columns
                    self._reflow_cards()
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

    def _clear_layout_widgets(self):
        """Clear all widgets from the gallery layout."""
        for i in reversed(range(self.gallery_inner_layout.count())):
            widget = self.gallery_inner_layout.itemAt(i).widget()
            if widget:
                self.gallery_inner_layout.removeWidget(widget)

    def _reflow_gallery_cards(self):
        """Reflow gallery cards in gallery view mode."""
        zip_paths = list(self.gallery_cards.keys())
        for idx, zip_path in enumerate(zip_paths):
            row = idx // self.gallery_columns
            col = idx % self.gallery_columns
            self.gallery_inner_layout.addWidget(self.gallery_cards[zip_path], row, col)

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

    def _schedule_gallery_thumbnail_poll(self):
        """Schedule thumbnail polling with debouncing."""
        # We don't need to do anything here anymore because we're using a dedicated 
        # worker thread that processes results as they come in through signals
        # This approach is safer than trying to use QTimer from arbitrary threads
        pass

    def _process_gallery_thumbnail_queue(self):
        """Process any pending gallery thumbnail requests."""
        # This method serves as a placeholder since the actual processing
        # happens in the worker thread connected to the thumbnailLoaded signal
        pass

    def _handle_thumbnail_result(self, result, cache_key):
        """Process a single thumbnail result."""
        if not result or not cache_key:
            return
            
        # Extract card key from cache_key
        card_key = self._extract_card_key_from_result(type('obj', (object,), {'cache_key': cache_key}))
        if not card_key:
            return

        label = self.gallery_thumb_labels.get(card_key)
        if not label:
            return

        if hasattr(result, 'success') and result.success and hasattr(result, 'data') and result.data:
            try:
                # Convert PIL image to QPixmap
                qimage = PIL.ImageQt.ImageQt(result.data)
                pixmap = QPixmap.fromImage(qimage)
                self.gallery_thumbnails[card_key] = pixmap
                
                # Scale with aspect ratio preservation instead of stretching
                scaled_pixmap = pixmap.scaled(
                    210, 180,  # 略小于容器尺寸以避免边缘被裁剪
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                label.setPixmap(scaled_pixmap)
                label.setText("")
                label.setStyleSheet("background-color: #1f2224; padding: 5px;")
            except Exception as e:
                print(f"Error creating QPixmap for {card_key}: {e}")
                self._set_error_thumbnail(label)
        else:
            self._set_error_thumbnail(label)

        # Clean up request record
        self._cleanup_thumbnail_request(type('obj', (object,), {'cache_key': cache_key}))

    def _extract_card_key_from_result(self, result):
        """Extract card key from a thumbnail result."""
        if isinstance(result.cache_key, tuple):
            if len(result.cache_key) == 2:
                # Gallery view: (zip_path, member_path)
                if not isinstance(result.cache_key[0], tuple):
                    return self.gallery_thumbnail_requests.get(result.cache_key)
                # Album view: ((zip_path, member_path), card_key) - Not implemented in this version yet
                else:
                    return result.cache_key[1]
        return None


    def _set_error_thumbnail(self, label):
        """Display an error thumbnail."""
        label.setText("⚠️")
        label.setStyleSheet("color: #ff7b72; font-size: 28pt; background-color: #1f2224;")

    def _cleanup_thumbnail_request(self, result):
        """Clean up thumbnail request records."""
        # Only clean up gallery view requests, not album view requests
        if isinstance(result.cache_key, tuple) and len(result.cache_key) == 2 and not isinstance(result.cache_key[0], tuple):
            if result.cache_key in self.gallery_thumbnail_requests:
                del self.gallery_thumbnail_requests[result.cache_key]

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

        # Request thumbnail
        self._request_image_thumbnail(zip_path, member_path, card_key)

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

    def _connect_image_card_click_events(self, zip_path: str, member_path: str, index: int,
                                       card_container: QWidget, thumb_label: QLabel, 
                                       title_label: QLabel, info_frame: QWidget):
        """Connect click events for all parts of the image card."""
        thumb_label.mousePressEvent = lambda event, z=zip_path, m=member_path, i=index: self._on_image_card_click(z, m, i)
        title_label.mousePressEvent = lambda event, z=zip_path, m=member_path, i=index: self._on_image_card_click(z, m, i)
        info_frame.mousePressEvent = lambda event, z=zip_path, m=member_path, i=index: self._on_image_card_click(z, m, i)
        card_container.mousePressEvent = lambda event, z=zip_path, m=member_path, i=index: self._on_image_card_click(z, m, i)

    def _request_image_thumbnail(self, zip_path: str, member_path: str, card_key: str):
        """Request thumbnail for an image in album view."""
        cache_key = (zip_path, member_path)

        # Use special format to distinguish album view from gallery view
        special_key = (cache_key, card_key)

        self.thread_pool.submit(
            load_image_data_async,
            zip_path,
            member_path,
            self.app_settings['max_thumbnail_size'],
            self.config["GALLERY_THUMB_SIZE"],
            self.gallery_queue,
            self.cache,
            special_key,
            self.zip_manager,
            self.app_settings['performance_mode']
        )

    def _on_image_card_click(self, zip_path: str, member_path: str, index: int):
        """Handle image card click event."""
        # Open viewer showing this image
        if self.open_viewer_callback:
            # Get all members of the ZIP file
            entry = self.zip_files.get(zip_path)
            if entry:
                members = entry[0]
                if members is None:
                    members = self.ensure_members_loaded(zip_path)

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

