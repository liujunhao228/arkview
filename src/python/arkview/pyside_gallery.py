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
        self.nav_frame.setFixedHeight(40)
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
        self.album_title_label.setStyleSheet("font-size: 13pt; font-weight: bold; color: #e8eaed;")
        nav_layout.addWidget(self.album_title_label)

        self.gallery_count_label = QLabel("")
        self.gallery_count_label.setStyleSheet("font-size: 9pt; color: #888888;")
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

        scroll_area.setWidget(self.gallery_inner_widget)

        main_layout.addWidget(scroll_area)

        # Create a container frame for event handling
        self.gallery_container = scroll_area

    def populate(self):
        """Populate gallery with thumbnails of ZIP files."""
        # Ensure we're in gallery view mode
        self.display_mode = "gallery"
        # self.back_button.setEnabled(False)  # This needs to be fixed
        self.album_title_label.setText("🎞️ Gallery")

        # Clear existing content
        for i in reversed(range(self.gallery_inner_layout.count())):
            self.gallery_inner_layout.itemAt(i).widget().setParent(None)

        # Clear references to help garbage collection
        self.gallery_cards.clear()
        self.gallery_thumb_labels.clear()
        self.gallery_title_labels.clear()

        zip_paths = list(self.zip_files.keys())
        if not zip_paths:
            empty_label = QLabel("No albums yet\n\nUse 'Scan Directory' to add archives")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet("font-size: 12pt; color: #666666;")
            empty_label.setMinimumHeight(300)
            self.gallery_inner_layout.addWidget(empty_label, 0, 0, 1, 1)
            self.gallery_count_label.setText("")
            return

        self.gallery_count_label.setText(f"{len(zip_paths)} albums")

        # Calculate number of columns based on available width
        available_width = self.gallery_inner_widget.width()
        if available_width > 0:
            calculated_columns = max(1, available_width // 220)
            self.gallery_columns = calculated_columns
        else:
            self.gallery_columns = 3

        for idx, zip_path in enumerate(zip_paths):
            row = idx // self.gallery_columns
            col = idx % self.gallery_columns
            self._create_gallery_card(zip_path, idx, row, col)

    def _create_gallery_card(self, zip_path: str, idx: int, row: int, col: int):
        """Create a gallery card for a ZIP file."""
        # Card container
        card_container = QWidget()
        card_container.setFixedSize(220, 280)
        card_container.setStyleSheet("""
            QWidget {
                background-color: #252829;
                border: none;
                border-radius: 4px;
            }
        """)
        
        # Add hover effect with event filter
        card_container.installEventFilter(self)
        
        layout = QVBoxLayout(card_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Thumbnail container
        thumb_container = QWidget()
        thumb_container.setFixedSize(220, 200)
        thumb_container.setStyleSheet("background-color: #1f2224;")
        thumb_layout = QVBoxLayout(thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)

        # Thumbnail label
        thumb_label = QLabel()
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("background-color: #1f2224; color: #555555; font-size: 32pt;")
        thumb_label.setText("⏳")
        thumb_label.setMinimumSize(220, 200)
        thumb_layout.addWidget(thumb_label)
        self.gallery_thumb_labels[zip_path] = thumb_label

        layout.addWidget(thumb_container)

        # Info frame
        info_frame = QWidget()
        info_frame.setStyleSheet("background-color: #252829;")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(12, 8, 12, 8)

        title_label = QLabel(os.path.basename(zip_path))
        title_label.setStyleSheet("color: #ffffff; font-size: 10pt; font-weight: bold; text-align: left;")
        title_label.setWordWrap(True)
        info_layout.addWidget(title_label)
        self.gallery_title_labels[zip_path] = title_label

        # File details
        entry = self.zip_files.get(zip_path)
        if entry:
            members, mod_time, file_size, image_count = entry
            size_text = _format_size(file_size) if file_size > 0 else "Unknown"
            count_text = f"{image_count} images" if image_count > 0 else "No images"

            details_label = QLabel(f"{count_text} • {size_text}")
            details_label.setStyleSheet("color: #888888; font-size: 8pt; text-align: left;")
            info_layout.addWidget(details_label)

        layout.addWidget(info_frame)

        # Store the card
        self.gallery_cards[zip_path] = card_container

        # Connect click event
        thumb_label.mousePressEvent = lambda event, z=zip_path: self._on_gallery_card_click(z)
        title_label.mousePressEvent = lambda event, z=zip_path: self._on_gallery_card_click(z)
        info_frame.mousePressEvent = lambda event, z=zip_path: self._on_gallery_card_click(z)
        card_container.mousePressEvent = lambda event, z=zip_path: self._on_gallery_card_click(z)

        # Add to layout
        self.gallery_inner_layout.addWidget(card_container, row, col)

        # Request thumbnail
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
                label.setPixmap(pixmap.scaled(220, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                label.setText("")
                label.setStyleSheet("background-color: #1f2224;")
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
        self._back_button_enabled = True
        self._update_back_button_style()
        album_name = os.path.basename(zip_path)
        self.album_title_label.setText(f"📁 {album_name}")
        self._display_album_content(zip_path)

    def _display_album_content(self, zip_path: str):
        """Display the contents of a ZIP file."""
        # Clear existing content
        for i in reversed(range(self.gallery_inner_layout.count())):
            self.gallery_inner_layout.itemAt(i).widget().setParent(None)

        # Clear references
        self.gallery_cards.clear()
        self.gallery_thumb_labels.clear()
        self.gallery_title_labels.clear()

        entry = self.zip_files.get(zip_path)
        if not entry:
            return

        members = entry[0]
        if members is None:
            members = self.ensure_members_loaded(zip_path)

        if not members:
            empty_label = QLabel("No images found in this album")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet("font-size: 12pt; color: #666666;")
            empty_label.setMinimumHeight(300)
            self.gallery_inner_layout.addWidget(empty_label, 0, 0, 1, 1)
            self.gallery_count_label.setText("0 images")
            return

        self.gallery_count_label.setText(f"{len(members)} images")

        # Create 2-column grid for album view
        for idx, member_path in enumerate(members):
            row = idx // 2
            col = idx % 2
            self._create_image_card(zip_path, member_path, idx, row, col)

    def _create_image_card(self, zip_path: str, member_path: str, index: int, row: int, col: int):
        """Create a card for a single image in album view."""
        # Card container
        card_key = f"{zip_path}:{index}"
        card_container = QWidget()
        card_container.setFixedSize(220, 280)
        card_container.setStyleSheet("""
            QWidget {
                background-color: #252829;
                border: none;
                border-radius: 4px;
            }
        """)
        
        layout = QVBoxLayout(card_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Thumbnail container
        thumb_container = QWidget()
        thumb_container.setFixedSize(220, 200)
        thumb_container.setStyleSheet("background-color: #1f2224;")
        thumb_layout = QVBoxLayout(thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)

        thumb_label = QLabel()
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("background-color: #1f2224; color: #555555; font-size: 32pt;")
        thumb_label.setText("⏳")
        thumb_label.setMinimumSize(220, 200)
        thumb_layout.addWidget(thumb_label)
        self.gallery_thumb_labels[card_key] = thumb_label

        layout.addWidget(thumb_container)

        # Info frame
        info_frame = QWidget()
        info_frame.setStyleSheet("background-color: #252829;")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(12, 8, 12, 8)

        title_label = QLabel(os.path.basename(member_path))
        title_label.setStyleSheet("color: #ffffff; font-size: 10pt; font-weight: bold; text-align: left;")
        title_label.setWordWrap(True)
        info_layout.addWidget(title_label)
        self.gallery_title_labels[card_key] = title_label

        layout.addWidget(info_frame)

        # Store the card
        self.gallery_cards[card_key] = card_container

        # Connect click event
        thumb_label.mousePressEvent = lambda event, z=zip_path, m=member_path, i=index: self._on_image_card_click(z, m, i)
        title_label.mousePressEvent = lambda event, z=zip_path, m=member_path, i=index: self._on_image_card_click(z, m, i)
        info_frame.mousePressEvent = lambda event, z=zip_path, m=member_path, i=index: self._on_image_card_click(z, m, i)
        card_container.mousePressEvent = lambda event, z=zip_path, m=member_path, i=index: self._on_image_card_click(z, m, i)

        # Add to layout
        self.gallery_inner_layout.addWidget(card_container, row, col)

        # Request thumbnail
        self._request_image_thumbnail(zip_path, member_path, card_key)

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