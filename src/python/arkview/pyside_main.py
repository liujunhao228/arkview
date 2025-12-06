"""
Main Arkview Application - PySide UI Implementation
"""

import os
import sys
import platform
import queue
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QSplitter, QScrollArea,
    QListWidget, QListWidgetItem, QLabel, QPushButton, QMenuBar, QMenu,
    QStatusBar, QToolBar, QToolButton, QGridLayout, QVBoxLayout, QHBoxLayout,
    QGroupBox, QScrollArea, QScrollBar, QProgressBar, QDialog, QCheckBox,
    QLineEdit, QSpinBox, QDoubleSpinBox, QRadioButton, QButtonGroup, QTabWidget,
    QStyle, QSizePolicy, QAbstractItemView
)
from PySide6.QtCore import (
    Qt, QTimer, Signal, QObject, QThread, QMutex, QMutexLocker, QEvent,
    QSize, QPoint, QRect, QUrl, QMetaObject, Q_ARG, Slot
)
from PySide6.QtGui import (
    QAction, QKeySequence, QPixmap, QIcon, QPalette, QColor, QFont,
    QDropEvent, QDragEnterEvent, QPainter, QBrush, QLinearGradient,
    QDesktopServices, QKeyEvent, QWheelEvent
)
from PIL import Image
import PIL.ImageQt

from .core import (
    ZipScanner, ZipFileManager, LRUCache, load_image_data_async,
    LoadResult, _format_size, RUST_AVAILABLE
)
from .pyside_ui import (
    SettingsDialog, ImageViewerWindow, SlideView
)
from .pyside_gallery import GalleryView


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
    "WINDOW_SIZE": (1050, 750),
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


class ThumbnailLoader(QObject):
    """Dedicated QObject for handling thumbnail loading operations."""
    thumbnailLoaded = Signal(object, str, str)  # result, zip_path, member_name
    batchProcessed = Signal(int, int)  # processed, total
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.loader_thread = QThread()
        self.moveToThread(self.loader_thread)
        self.loader_thread.start()
        
    def stop(self):
        self.loader_thread.quit()
        self.loader_thread.wait()


class MainApp(QMainWindow):
    """Main Arkview Application with PySide UI."""
    
    # Custom signals
    update_status = Signal(str)
    update_preview = Signal(object)  # (pil_image, str_error)
    add_zip_entries_signal = Signal(list)  # List of tuples for bulk adding
    members_loaded_signal = Signal(str, object)  # zip_path, members list
    show_error_signal = Signal(str, str)  # (title, message)
    scan_progress = Signal(int, int)  # processed, total
    scan_completed = Signal(int, int)  # valid_count, total_processed
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle(f"Aarkview {CONFIG['APP_VERSION']}")
        self.resize(CONFIG["WINDOW_SIZE"][0], CONFIG["WINDOW_SIZE"][1])
        self.setMinimumSize(600, 400)

        self.zip_scanner = ZipScanner()
        self.zip_manager = ZipFileManager()
        self.cache = LRUCache(CONFIG["CACHE_MAX_ITEMS_NORMAL"])
        self.preview_queue: queue.Queue = queue.Queue()
        self.thread_pool = ThreadPoolExecutor(max_workers=CONFIG["THREAD_POOL_WORKERS"])

        # Create thumbnail loader for dedicated thread operations
        self.thumbnail_loader = ThumbnailLoader()
        self.thumbnail_loader.thumbnailLoaded.connect(self.onThumbnailLoaded)
        self.thumbnail_loader.batchProcessed.connect(self.onBatchProcessed)

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
        self._loading_members: Set[str] = set()

        self.scan_thread = None
        self.scan_stop_event = threading.Event()

        self.current_view = "explorer"  # "explorer", "gallery", or "slide"
        self.slide_view_context: Dict[str, Any] = {
            "zip_path": None,
            "members": None,
            "current_index": 0,
            "previous_view": "explorer"  # Can be "explorer" or "gallery"
        }
        self.gallery_widget: Optional[GalleryView] = None
        self.slide_widget: Optional[SlideView] = None
        self._zip_selection_connected = False  # Track connection state of zip selection signal

        # Set up the UI
        self._setup_ui()
        self._setup_menu()
        self._setup_keyboard_shortcuts()
        
        # Connect signals
        self.update_status.connect(self._on_update_status)
        self.update_preview.connect(self._on_update_preview)
        self.add_zip_entries_signal.connect(self._add_zip_entries_bulk)
        self.members_loaded_signal.connect(self._on_members_loaded)
        self.show_error_signal.connect(self._show_error)
        self.scan_progress.connect(self._on_scan_progress)
        self.scan_completed.connect(self._on_scan_completed)
        
        # Initialize flags
        self._zip_selection_connected = False
        
        # Set dark theme
        self._apply_dark_theme()

    def _apply_dark_theme(self):
        """Apply a dark theme to the application."""
        # Set dark palette
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(40, 44, 52))
        palette.setColor(QPalette.WindowText, QColor(233, 237, 237))
        palette.setColor(QPalette.Base, QColor(30, 34, 42))
        palette.setColor(QPalette.AlternateBase, QColor(40, 44, 52))
        palette.setColor(QPalette.ToolTipBase, QColor(40, 44, 52))
        palette.setColor(QPalette.ToolTipText, QColor(233, 237, 237))
        palette.setColor(QPalette.Text, QColor(233, 237, 237))
        palette.setColor(QPalette.Button, QColor(40, 44, 52))
        palette.setColor(QPalette.ButtonText, QColor(233, 237, 237))
        palette.setColor(QPalette.BrightText, QColor(255, 66, 66))
        palette.setColor(QPalette.Highlight, QColor(0, 188, 140))
        palette.setColor(QPalette.HighlightedText, QColor(30, 34, 42))
        self.setPalette(palette)
        
        # Apply stylesheet for consistent dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #282c34;
            }
            QFrame {
                background-color: #282c34;
                border: 1px solid #2c323c;
                border-radius: 4px;
            }
            QSplitter::handle {
                background-color: #2c323c;
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
            QListWidget {
                background-color: #1f222a;
                border: 1px solid #2c323c;
                color: #e8eaed;
                selection-background-color: #00bc8c;
                selection-color: #101214;
            }
            QLabel {
                color: #e8eaed;
            }
            QPushButton {
                background-color: #3a3f4b;
                border: 1px solid #444a58;
                border-radius: 4px;
                color: #e8eaed;
                padding: 6px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #444a58;
            }
            QPushButton:pressed {
                background-color: #323741;
            }
            QPushButton#primary {
                background-color: #00bc8c;
                border-color: #00a47a;
                color: #ffffff;
            }
            QPushButton#primary:hover {
                background-color: #00a47a;
            }
            QPushButton#success {
                background-color: #5cb85c;
                border-color: #4cae4c;
                color: #ffffff;
            }
            QPushButton#success:hover {
                background-color: #4cae4c;
            }
            QPushButton#warning {
                background-color: #f0ad4e;
                border-color: #eea236;
                color: #ffffff;
            }
            QPushButton#warning:hover {
                background-color: #eea236;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #2c323c;
                border-radius: 4px;
                margin-top: 1ex;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)

    def _setup_ui(self):
        """Setup the main UI."""
        # Create central widget
        self._create_central_widget()
        
        # Main layout
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # View switcher at the top
        self._setup_view_switcher(main_layout)
        
        # Container for switchable views
        self._setup_views_container(main_layout)
        
        # Bottom control panel
        self._setup_bottom_panel(main_layout)
        
        # Initialize visibility
        self._update_view_buttons()
        self._update_view_visibility()

    def _create_central_widget(self):
        """Create and set the central widget."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

    def _setup_view_switcher(self, main_layout: QVBoxLayout):
        """Setup the view switcher at the top of the UI."""
        view_switch_frame = QFrame()
        view_switch_frame.setFixedHeight(40)
        view_switch_frame.setStyleSheet("background-color: #2c323c; border: none;")
        view_switch_layout = QHBoxLayout(view_switch_frame)
        view_switch_layout.setContentsMargins(8, 5, 8, 5)
        view_switch_layout.setSpacing(10)
        
        view_label = QLabel("View:")
        view_label.setStyleSheet("font-weight: bold; color: #e8eaed; font-size: 10pt;")
        view_switch_layout.addWidget(view_label)
        
        self.explorer_view_button = QPushButton("📋 Resource Explorer")
        self.explorer_view_button.setObjectName("primary")
        self.explorer_view_button.setFixedWidth(180)
        self.explorer_view_button.clicked.connect(lambda: self._switch_view("explorer"))
        view_switch_layout.addWidget(self.explorer_view_button)
        
        self.gallery_view_button = QPushButton("🎞️ Gallery")
        self.gallery_view_button.setObjectName("secondary")
        self.gallery_view_button.setFixedWidth(150)
        self.gallery_view_button.clicked.connect(lambda: self._switch_view("gallery"))
        view_switch_layout.addWidget(self.gallery_view_button)
        
        view_switch_layout.addStretch()
        main_layout.addWidget(view_switch_frame)

    def _setup_views_container(self, main_layout: QVBoxLayout):
        """Setup the container for switchable views."""
        self.views_container = QFrame()
        views_layout = QVBoxLayout(self.views_container)
        views_layout.setContentsMargins(0, 0, 0, 0)
        
        # === RESOURCE EXPLORER VIEW ===
        self._setup_explorer_view(views_layout)
        
        # === GALLERY VIEW ===
        self._setup_gallery_view(views_layout)
        
        # === SLIDE VIEW ===
        self._setup_slide_view(views_layout)
        
        # Add all views to container
        views_layout.addWidget(self.explorer_view_frame)
        views_layout.addWidget(self.gallery_view_frame)
        views_layout.addWidget(self.slide_view_frame)
        
        main_layout.addWidget(self.views_container)

    def _setup_explorer_view(self, views_layout: QVBoxLayout):
        """Setup the resource explorer view."""
        self.explorer_view_frame = QFrame()
        explorer_layout = QHBoxLayout(self.explorer_view_frame)
        explorer_layout.setContentsMargins(8, 8, 8, 8)
        
        # Main splitter
        self.main_splitter = QSplitter(Qt.Horizontal)
        
        # --- Left Panel: ZIP File List ---
        self._setup_left_panel()
        
        # --- Right Panel: Preview and Details ---
        self._setup_right_panel()
        
        # Add frames to splitter
        self.main_splitter.addWidget(self.left_frame)
        self.main_splitter.addWidget(self.right_frame)
        
        # Set splitter weights - give more space to the preview panel
        self.main_splitter.setStretchFactor(0, 2)  # Left panel
        self.main_splitter.setStretchFactor(1, 3)  # Right panel
        
        explorer_layout.addWidget(self.main_splitter)

    def _setup_left_panel(self):
        """Setup the left panel containing the ZIP file list."""
        self.left_frame = QFrame()
        left_layout = QVBoxLayout(self.left_frame)
        left_layout.setContentsMargins(5, 5, 5, 5)
        
        left_label = QLabel("📦 Archives")
        left_label.setStyleSheet("font-weight: bold; color: #e8eaed; font-size: 11pt;")
        left_layout.addWidget(left_label)
        
        # List container
        list_container = QFrame()
        list_layout = QHBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        
        self.zip_listbox = QListWidget()
        self.zip_listbox.setStyleSheet("""
            QListWidget {
                background-color: #1f222a;
                border: 1px solid #2c323c;
                color: #e8eaed;
                selection-background-color: #00bc8c;
                selection-color: #101214;
                font: 10pt "Segoe UI";
            }
        """)
        list_layout.addWidget(self.zip_listbox)
        
        # Add scrollbar manually to maintain control
        list_scrollbar = QScrollBar()
        self.zip_listbox.setVerticalScrollBar(list_scrollbar)
        list_layout.addWidget(list_scrollbar)
        
        left_layout.addWidget(list_container)

    def _setup_right_panel(self):
        """Setup the right panel containing preview and details."""
        self.right_frame = QFrame()
        right_layout = QVBoxLayout(self.right_frame)
        right_layout.setContentsMargins(5, 5, 5, 5)
        
        right_label = QLabel("🖼️  Preview")
        right_label.setStyleSheet("font-weight: bold; color: #e8eaed; font-size: 11pt;")
        right_layout.addWidget(right_label)
        
        # Preview navigation controls
        self._setup_preview_navigation(right_layout)
        
        # Preview container
        self._setup_preview_container(right_layout)
        
        # Details panel
        self._setup_details_panel(right_layout)

    def _setup_preview_navigation(self, right_layout: QVBoxLayout):
        """Setup the preview navigation controls."""
        preview_nav_frame = QFrame()
        preview_nav_layout = QHBoxLayout(preview_nav_frame)
        preview_nav_layout.setContentsMargins(0, 0, 0, 8)
        
        self.preview_prev_button = QPushButton("◀ Prev")
        self.preview_prev_button.setFixedWidth(100)
        self.preview_prev_button.clicked.connect(self._preview_prev)
        self.preview_prev_button.setEnabled(False)
        preview_nav_layout.addWidget(self.preview_prev_button)
        
        self.preview_info_label = QLabel("")
        self.preview_info_label.setAlignment(Qt.AlignCenter)
        self.preview_info_label.setStyleSheet("font-size: 9pt;")
        preview_nav_layout.addWidget(self.preview_info_label)
        
        self.preview_next_button = QPushButton("Next ▶")
        self.preview_next_button.setFixedWidth(100)
        self.preview_next_button.clicked.connect(self._preview_next)
        self.preview_next_button.setEnabled(False)
        preview_nav_layout.addWidget(self.preview_next_button)
        
        right_layout.addWidget(preview_nav_frame)

    def _setup_preview_container(self, right_layout: QVBoxLayout):
        """Setup the preview container."""
        preview_container = QFrame()
        preview_container.setFrameStyle(QFrame.StyledPanel)
        preview_container.setStyleSheet("background-color: #2a2d2e; border: 1px solid #3a3f4b;")
        preview_container.setMinimumHeight(300)  # Increase minimum height for better proportion
        
        preview_container_layout = QVBoxLayout(preview_container)
        preview_container_layout.setContentsMargins(2, 2, 2, 2)
        
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #2a2d2e;
                color: #ffffff;
                font: 10pt;
            }
        """)
        self.preview_label.setText("Select a ZIP file")
        self.preview_label.mousePressEvent = self._on_preview_click
        self.preview_label.setScaledContents(False)  # Change to False for aspect ratio scaling
        self.preview_label.setMinimumSize(1, 1)
        preview_container_layout.addWidget(self.preview_label)
        
        right_layout.addWidget(preview_container)

    def _setup_details_panel(self, right_layout: QVBoxLayout):
        """Setup the details panel."""
        details_frame = QGroupBox("ℹ️  Details")
        details_layout = QVBoxLayout(details_frame)
        
        self.details_text = QScrollArea()
        self.details_text.setMinimumHeight(200)  # Increase minimum height
        self.details_text.setWidgetResizable(True)
        self.details_widget = QWidget()
        self.details_layout = QVBoxLayout(self.details_widget)
        self.details_text.setWidget(self.details_widget)
        
        self.details_content_label = QLabel()
        self.details_content_label.setWordWrap(True)
        self.details_layout.addWidget(self.details_content_label)
        
        details_layout.addWidget(self.details_text)
        
        right_layout.addWidget(details_frame)

    def _setup_gallery_view(self, views_layout: QVBoxLayout):
        """Setup the gallery view."""
        self.gallery_view_frame = QFrame()
        gallery_layout = QVBoxLayout(self.gallery_view_frame)
        
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
        gallery_layout.addWidget(self.gallery_widget)

    def _setup_slide_view(self, views_layout: QVBoxLayout):
        """Setup the slide view."""
        self.slide_view_frame = QFrame()
        slide_layout = QVBoxLayout(self.slide_view_frame)
        
        self.slide_widget = SlideView(
            self.slide_view_frame,
            self.zip_files,
            self.app_settings,
            self.cache,
            self.thread_pool,
            self.zip_manager,
            CONFIG,
            self._switch_to_previous_view
        )
        slide_layout.addWidget(self.slide_widget)

    def _setup_bottom_panel(self, main_layout: QVBoxLayout):
        """Setup the bottom control panel."""
        bottom_frame = QFrame()
        bottom_frame.setFixedHeight(40)
        bottom_frame.setStyleSheet("background-color: #2c323c; border: none;")
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(8, 5, 8, 5)
        
        # Buttons container
        self._setup_control_buttons(bottom_layout)
        
        # Status container
        self._setup_status_display(bottom_layout)
        
        main_layout.addWidget(bottom_frame)

    def _setup_control_buttons(self, bottom_layout: QHBoxLayout):
        """Setup the control buttons."""
        button_container = QFrame()
        button_layout = QHBoxLayout(button_container)
        button_layout.setSpacing(5)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        scan_button = QPushButton("📁 Scan Directory")
        scan_button.setObjectName("primary")
        scan_button.setFixedWidth(120)
        scan_button.clicked.connect(self._scan_directory)
        button_layout.addWidget(scan_button)
        
        view_button = QPushButton("👁️ View")
        view_button.setObjectName("success")
        view_button.setFixedWidth(80)
        view_button.clicked.connect(self._open_slide_view)  # Changed from _open_viewer to _open_slide_view
        button_layout.addWidget(view_button)
        
        clear_button = QPushButton("🗑️ Clear")
        clear_button.setObjectName("warning")
        clear_button.setFixedWidth(80)
        clear_button.clicked.connect(self._clear_list)
        button_layout.addWidget(clear_button)
        
        settings_button = QPushButton("⚙️ Settings")
        settings_button.clicked.connect(self._show_settings)
        button_layout.addWidget(settings_button)
        
        bottom_layout.addWidget(button_container)

    def _setup_status_display(self, bottom_layout: QHBoxLayout):
        """Setup the status display."""
        status_container = QFrame()
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignRight)
        self.status_label.setStyleSheet("color: #e8eaed; font-size: 9pt;")
        status_layout.addWidget(self.status_label)
        
        bottom_layout.addWidget(status_container, stretch=1)

    def _setup_menu(self):
        """Setup the menu bar."""
        # Create menu bar
        menubar = self.menuBar()
        
        file_menu = menubar.addMenu("File")
        file_menu.addAction("Scan Directory", self._scan_directory)
        file_menu.addAction("Add ZIP File", self._add_zip_file)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)
        
        view_menu = menubar.addMenu("View")
        view_menu.addAction("Settings", self._show_settings)
        view_menu.addAction("Clear List", self._clear_list)
        
        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About", self._show_about)

    def _setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts."""
        # Ctrl+G for gallery view
        shortcut_gallery = QAction(self)
        shortcut_gallery.setShortcut(QKeySequence("Ctrl+G"))
        shortcut_gallery.triggered.connect(lambda: self._switch_view("gallery"))
        self.addAction(shortcut_gallery)
        
        # Ctrl+E for explorer view
        shortcut_explorer = QAction(self)
        shortcut_explorer.setShortcut(QKeySequence("Ctrl+E"))
        shortcut_explorer.triggered.connect(lambda: self._switch_view("explorer"))
        self.addAction(shortcut_explorer)
        
        # Tab for switching views
        shortcut_tab = QAction(self)
        shortcut_tab.setShortcut(QKeySequence("Tab"))
        shortcut_tab.triggered.connect(self._handle_tab_switch)
        self.addAction(shortcut_tab)

        # Gallery navigation keys
        shortcut_left = QAction(self)
        shortcut_left.setShortcut(QKeySequence(Qt.Key_Left))
        shortcut_left.triggered.connect(lambda: self._handle_gallery_key("left"))
        self.addAction(shortcut_left)
        
        shortcut_right = QAction(self)
        shortcut_right.setShortcut(QKeySequence(Qt.Key_Right))
        shortcut_right.triggered.connect(lambda: self._handle_gallery_key("right"))
        self.addAction(shortcut_right)

    def _handle_tab_switch(self):
        """Handle Tab key to switch views."""
        if self.current_view == "explorer":
            self._switch_view("gallery")
        else:
            self._switch_view("explorer")

    def _handle_gallery_key(self, direction: str):
        """Handle gallery navigation keys."""
        if self.current_view != "gallery" or not self.gallery_widget:
            return
        # Forward to gallery widget
        self.gallery_widget.handle_keypress(direction)

    def _switch_view(self, view: str):
        """Switch between explorer and gallery views."""
        if view not in ["explorer", "gallery", "slide"]:
            return

        if self.current_view == view:
            return

        # Save context when leaving slide view
        if self.current_view == "slide" and view != "slide":
            self.slide_view_context["previous_view"] = self.current_view

        self.current_view = view
        self._update_view_buttons()
        self._update_view_visibility()

        if view == "gallery" and self.gallery_widget:
            self.gallery_widget.populate()
        elif view == "slide" and self.slide_widget:
            # Context should be set before calling this method
            pass

    def _switch_to_previous_view(self):
        """Switch back to the previous view from slide view."""
        previous_view = self.slide_view_context.get("previous_view", "explorer")
        self._switch_view(previous_view)

    def _update_view_buttons(self):
        """Update view button styles based on current view."""
        # Reset all buttons
        self.explorer_view_button.setStyleSheet("""
            QPushButton {
                background-color: #3a3f4b;
                border: 1px solid #444a58;
                color: #e8eaed;
            }
        """)
        self.gallery_view_button.setStyleSheet("""
            QPushButton {
                background-color: #3a3f4b;
                border: 1px solid #444a58;
                color: #e8eaed;
            }
        """)
        
        # Highlight current view
        if self.current_view == "explorer":
            self.explorer_view_button.setStyleSheet("""
                QPushButton {
                    background-color: #00bc8c;
                    border-color: #00a47a;
                    color: #ffffff;
                    font-weight: bold;
                }
            """)
        elif self.current_view == "gallery":
            self.gallery_view_button.setStyleSheet("""
                QPushButton {
                    background-color: #00bc8c;
                    border-color: #00a47a;
                    color: #ffffff;
                    font-weight: bold;
                }
            """)

    def _update_view_visibility(self):
        """Update view visibility based on current view."""
        self.explorer_view_frame.hide()
        self.gallery_view_frame.hide()
        self.slide_view_frame.hide()
        
        if self.current_view == "explorer":
            self.explorer_view_frame.show()
        elif self.current_view == "gallery":
            self.gallery_view_frame.show()
        elif self.current_view == "slide":
            self.slide_view_frame.show()

    def _refresh_gallery(self):
        """Refresh gallery view if visible."""
        print(f"[DEBUG] Refreshing gallery, current view: {self.current_view}")
        print(f"[DEBUG] Gallery widget exists: {self.gallery_widget is not None}")
        if self.gallery_widget and self.current_view == "gallery":
            print("[DEBUG] Calling gallery populate")
            try:
                self.gallery_widget.populate()
            except Exception as e:
                print(f"[ERROR] Error populating gallery: {e}")
        else:
            print("[DEBUG] Gallery not visible or widget not initialized")
            if not self.gallery_widget:
                print("[DEBUG] Gallery widget is None")
            if self.current_view != "gallery":
                print(f"[DEBUG] Current view is {self.current_view}, not 'gallery'")

    def _scan_directory(self):
        """Scan a directory for ZIP files."""
        from PySide6.QtWidgets import QFileDialog
        directory = QFileDialog.getExistingDirectory(self, "Select Directory to Scan")
        if not directory:
            return

        self.update_status.emit("Scanning...")
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
                # Use signal to safely call UI update from main thread
                self.update_status.emit("No ZIP files found")
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
                # Use signal to call from main thread
                self.add_zip_entries_signal.emit(batch)

            for start in range(0, total_files, batch_size):
                if self.scan_stop_event.is_set():
                    break

                batch_paths = zip_files[start:start + batch_size]
                try:
                    batch_results = self.zip_scanner.batch_analyze_zips(batch_paths, collect_members=False)
                except Exception as e:
                    # Use signals to call from main thread
                    self.show_error_signal.emit("Error", f"Scan error: {e}")
                    self.update_status.emit("Scan failed")
                    return

                for zip_path, is_valid, members, mod_time, file_size, image_count in batch_results:
                    processed += 1
                    if is_valid:
                        pending_entries.append((zip_path, members, mod_time, file_size, image_count))
                        valid_found += 1

                if len(pending_entries) >= batch_size:
                    flush_pending()

                if processed % ui_update_interval == 0 or processed >= total_files:
                    # Emit signal for progress updates
                    self.scan_progress.emit(processed, total_files)

            flush_pending()

            final_message = (
                "Scan canceled" if self.scan_stop_event.is_set()
                else f"Found {valid_found} valid archives (of {processed} scanned)"
            )
            # Use signal to call from main thread
            self.update_status.emit(final_message)
            # Emit completion signal
            self.scan_completed.emit(valid_found, processed)
        except Exception as e:
            self.show_error_signal.emit("Error", f"Scan error: {e}")
            self.update_status.emit("Scan failed")

    def _show_error(self, title: str, message: str):
        """Show error message (thread-safe)."""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, title, message)

    def _add_zip_file(self):
        """Add a single ZIP file."""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ZIP File",
            "",
            "ZIP Files (*.zip);;All Files (*.*)"
        )
        if file_path:
            self._analyze_and_add(file_path)

    def _analyze_and_add(self, zip_path: str):
        """Analyze and add a ZIP file."""
        is_valid, members, mod_time, file_size, image_count = self.zip_scanner.analyze_zip(zip_path)

        if is_valid and members:
            self._add_zip_entry(zip_path, members, mod_time, file_size)
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
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
        print(f"[DEBUG] Adding {len(entries)} entries in bulk")
        if not entries:
            print("[DEBUG] No entries to add")
            return

        display_items = self._process_entries_for_display(entries)
        
        if display_items:
            print(f"[DEBUG] Adding {len(display_items)} items to listbox")
            for item_text in display_items:
                item = QListWidgetItem(item_text)
                self.zip_listbox.addItem(item)

        print("[DEBUG] Refreshing gallery")
        self._refresh_gallery()

        # Manage selection event connection to avoid duplicates
        self._manage_zip_selection_connection()
        print("[DEBUG] Finished adding entries in bulk")

    def _process_entries_for_display(self, entries: List[Tuple[str, Optional[List[str]], Optional[float], Optional[int], Optional[int]]]) -> List[str]:
        """Process entries and prepare them for display."""
        display_items = []
        for zip_path, members, mod_time, file_size, image_count in entries:
            if zip_path in self.zip_files:
                print(f"[DEBUG] Skipping {zip_path}, already in zip_files")
                continue

            # Resolve entry details
            resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count = self._resolve_entry_details(
                zip_path, members, mod_time, file_size, image_count)

            # Check if this is a valid entry (contains images)
            if not self._is_valid_entry(resolved_members):
                print(f"[DEBUG] Invalid or empty zip: {zip_path}")
                # 即使没有图片，我们也应该添加到列表中，只是标记为不含图片
                # 除非你想完全过滤掉不含图片的压缩包
                # 这里我们假设目标是显示所有压缩包，但标注哪些包含图片
                pass
            else:
                print(f"[DEBUG] Valid zip with images: {zip_path}")

            # Update image count if needed
            if resolved_image_count is None:
                resolved_image_count = len(resolved_members) if resolved_members else 0

            entry_mod_time = resolved_mod_time or 0
            entry_file_size = resolved_file_size or 0

            self.zip_files[zip_path] = (resolved_members, entry_mod_time, entry_file_size, resolved_image_count)
            print(f"[DEBUG] Added {zip_path} to zip_files with {resolved_image_count} images")

            display_text = self._create_display_text(zip_path, entry_file_size)
            display_items.append(display_text)
            
        return display_items

    def _resolve_entry_details(self, zip_path: str, members: Optional[List[str]], mod_time: Optional[float], 
                              file_size: Optional[int], image_count: Optional[int]) -> Tuple[Optional[List[str]], Optional[float], Optional[int], Optional[int]]:
        """Resolve the details for a ZIP file entry."""
        resolved_members = members
        resolved_mod_time = mod_time
        resolved_file_size = file_size
        resolved_image_count = image_count

        if resolved_members is None and resolved_image_count is None:
            print(f"[DEBUG] Analyzing zip {zip_path} (full analysis)")
            is_valid, resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count = self.zip_scanner.analyze_zip(zip_path)
            print(f"[DEBUG] Analysis result - valid: {is_valid}, members count: {len(resolved_members) if resolved_members else 0}, image_count: {resolved_image_count}")
            # 即使不是有效的图片压缩包，我们也应该返回分析结果，而不是直接返回
            # 这样可以让调用函数决定如何处理
        elif resolved_members is None and (resolved_mod_time is None or resolved_file_size is None):
            # Need complete metadata for display
            print(f"[DEBUG] Analyzing zip {zip_path} (metadata only)")
            is_valid, resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count = self.zip_scanner.analyze_zip(zip_path)
            print(f"[DEBUG] Analysis result - valid: {is_valid}")

        return resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count

    def _is_valid_entry(self, members: Optional[List[str]]) -> bool:
        """Check if the entry is valid (has members)."""
        # 我们总是想显示这个ZIP文件，不管它是否包含图片
        # 只是会在UI中标记它包含多少图片
        return True  # 总是返回True，这样所有ZIP文件都会被添加到列表中

    def _create_display_text(self, zip_path: str, file_size: int) -> str:
        """Create the display text for a ZIP file entry."""
        display_text = os.path.basename(zip_path)
        if file_size:
            display_text += f" ({_format_size(file_size)})"
        return display_text

    def _manage_zip_selection_connection(self):
        """Manage the ZIP selection event connection to avoid duplicates."""
        # Disconnect and reconnect selection event to avoid duplicates
        # Use a flag to track connection state instead of relying on exception handling
        if hasattr(self, '_zip_selection_connected') and self._zip_selection_connected:
            self.zip_listbox.itemSelectionChanged.disconnect(self._on_zip_selected)
        
        self.zip_listbox.itemSelectionChanged.connect(self._on_zip_selected)
        self._zip_selection_connected = True

    def _on_update_status(self, message: str):
        """Update status bar (thread-safe)."""
        self.status_label.setText(message)

    def _on_update_preview(self, result_tuple):
        """Update the preview image with aspect ratio scaling."""
        pil_image, error_msg = result_tuple
        if pil_image and not error_msg:
            # Convert PIL image to QPixmap
            try:
                qimage = PIL.ImageQt.toqimage(pil_image)
                pixmap = QPixmap.fromImage(qimage)
                
                # Store the pixmap for resizing
                self.current_preview_pixmap = pixmap
                
                # Scale the pixmap to fit the label while maintaining aspect ratio
                scaled_pixmap = pixmap.scaled(
                    self.preview_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.preview_label.setPixmap(scaled_pixmap)
                self.preview_label.setText("")  # Clear text when showing image
            except Exception as e:
                self.preview_label.clear()
                self.preview_label.setText(f"Error converting image: {str(e)}")
        else:
            self.preview_label.clear()
            self.preview_label.setText(f"Error: {error_msg}" if error_msg else "Preview not available")

    def _on_zip_selected(self):
        """Handle ZIP file selection."""
        selected_items = self.zip_listbox.selectedItems()
        if not selected_items:
            self._reset_preview()
            return

        item = selected_items[0]
        index = self.zip_listbox.row(item)
        zip_entries = list(self.zip_files.keys())
        if index >= len(zip_entries):
            self._reset_preview()
            return

        selected_zip = zip_entries[index]
        self.current_selected_zip = selected_zip
        _, mod_time, file_size, image_count = self.zip_files[selected_zip]
        self._update_details(selected_zip, mod_time, file_size, image_count)

        # Load preview for first image if available
        entry = self.zip_files[selected_zip]
        members = entry[0]
        if members and len(members) > 0:
            self._load_preview(selected_zip, members, 0)
        else:
            # Load members in background if not loaded yet
            self._reset_preview("Loading archive contents...")
            self._load_members_for_preview(selected_zip)

    def _on_scan_progress(self, processed: int, total: int):
        """Handle scan progress updates."""
        if total > 0:
            progress_percent = (processed / total) * 100
            self.status_label.setText(f"Scanning... {processed}/{total} ({progress_percent:.1f}%)")
        else:
            self.status_label.setText(f"Scanning... {processed} files processed")

    def _on_scan_completed(self, valid_count: int, total_processed: int):
        """Handle scan completion."""
        self.status_label.setText(f"Scan completed: {valid_count} valid archives found out of {total_processed} total files")
        if self.gallery_widget and self.current_view == "gallery":
            self._refresh_gallery()

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

    def _load_members_for_preview(self, zip_path: str):
        """Load ZIP members in a worker thread and emit results when ready."""
        # Avoid duplicate loading requests
        if zip_path in self._loading_members:
            return
        self._loading_members.add(zip_path)

        def task():
            members = None
            try:
                members = self._ensure_members_loaded(zip_path)
            except Exception as e:
                # Emit error signal if loading fails
                self.show_error_signal.emit(
                    "Error",
                    f"Failed to load archive contents for '{Path(zip_path).name}': {e}"
                )
            finally:
                self.members_loaded_signal.emit(zip_path, members)

        self.thread_pool.submit(task)

    def _on_members_loaded(self, zip_path: str, members: Optional[List[str]]):
        """Handle members loaded signal (thread-safe)."""
        # Remove from loading set
        self._loading_members.discard(zip_path)
        
        if zip_path != self.current_selected_zip:
            return

        if members and len(members) > 0:
            # Update details with fresh member count
            entry = self.zip_files.get(zip_path)
            if entry:
                _, mod_time, file_size, _ = entry
                self.zip_files[zip_path] = (members, mod_time, file_size, len(members))
                self._update_details(zip_path, mod_time, file_size, len(members))
            self._load_preview(zip_path, members, 0)
        else:
            self._reset_preview("No images found in archive")

    def _update_details(self, zip_path: str, mod_time: float, file_size: int, image_count: int):
        """Update the details panel."""
        if zip_path is None:
            details = "Archive: Unknown\n"
        else:
            details = f"Archive: {os.path.basename(zip_path)}\n"
        details += f"Images: {image_count}\n"
        details += f"Size: {_format_size(file_size)}\n"
        if mod_time:
            from datetime import datetime
            details += f"Modified: {datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M:%S')}\n"

        self.details_content_label.setText(details)

    def _load_preview(self, zip_path: str, members: List[str], index: int):
        """Load preview image."""
        if not self._is_valid_preview_request(members, index):
            return

        self._cancel_previous_preview_task()
        self._clear_preview_queue()

        self._update_preview_state(zip_path, members, index)
        self._update_preview_ui(index, len(members))
        self._set_preview_loading_message()

        self._submit_preview_task(zip_path, members, index)

        # Use QTimer to periodically check for results
        self._check_preview_result()

    def _is_valid_preview_request(self, members: List[str], index: int) -> bool:
        """Check if the preview request is valid."""
        return members and 0 <= index < len(members)

    def _cancel_previous_preview_task(self):
        """Cancel the previous preview loading task if it exists."""
        if self.current_preview_future and not self.current_preview_future.done():
            self.current_preview_future.cancel()

    def _clear_preview_queue(self):
        """Clear the preview queue."""
        while True:
            try:
                self.preview_queue.get_nowait()
            except queue.Empty:
                break

    def _update_preview_state(self, zip_path: str, members: List[str], index: int):
        """Update the preview state variables."""
        self.current_preview_index = index
        self.current_preview_members = members
        cache_key = (zip_path, members[index])
        self.current_preview_cache_key = cache_key

    def _update_preview_ui(self, index: int, members_count: int):
        """Update the preview UI elements."""
        # Update preview info label
        self.preview_info_label.setText(f"Image {index + 1} / {members_count}")

        # Update navigation button states
        self.preview_prev_button.setEnabled(index > 0)
        self.preview_next_button.setEnabled(index < members_count - 1)

    def _set_preview_loading_message(self):
        """Set the loading message for the preview."""
        # Clear the pixmap and show loading message
        self.preview_label.clear()
        self.preview_label.setText("Loading preview...")

    def _submit_preview_task(self, zip_path: str, members: List[str], index: int):
        """Submit the preview loading task to the thread pool."""
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
            self.preview_queue,
            self.cache,
            (zip_path, members[index]),  # cache_key
            self.zip_manager,
            self.app_settings['performance_mode']
        )

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
                    # Emit signal to update preview (thread-safe)
                    self.update_preview.emit((result.data, None))
                else:
                    message = result.error_message or "Preview failed"
                    self.update_preview.emit((None, message))
                self.current_preview_future = None
                return
        except queue.Empty:
            if self.current_preview_future and not self.current_preview_future.done():
                # Check again after 20ms
                QTimer.singleShot(20, self._check_preview_result)

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

        self.preview_label.clear()
        self.preview_label.setText(message)
        self.preview_info_label.setText('')
        self.preview_prev_button.setEnabled(False)
        self.preview_next_button.setEnabled(False)

    def _on_preview_click(self, event):
        """Handle preview click to open slide view."""
        self._open_slide_view()

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

    def _open_slide_view(self):
        """Open the slide view for the currently selected ZIP file."""
        if not self.current_selected_zip:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Selection", "Please select an archive first.")
            return

        zip_path = self.current_selected_zip
        entry = self.zip_files.get(zip_path)
        if not entry:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Missing Entry", "Selected archive is no longer available.")
            return

        members = entry[0]
        if members is None:
            members = self._ensure_members_loaded(zip_path)
            if not members:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Error", "Unable to load archive contents.")
                return

        # Set context for slide view
        self.slide_view_context = {
            "zip_path": zip_path,
            "members": members,
            "current_index": self.current_preview_index or 0,
            "previous_view": "explorer"
        }

        # Populate slide widget and switch to slide view
        self.slide_widget.populate(zip_path, members, self.current_preview_index or 0)
        self._switch_view("slide")

    def _open_viewer_from_gallery(self, zip_path: str, members: List[str], index: int):
        """Open slide view when triggered from gallery view."""
        # Set context for slide view
        self.slide_view_context = {
            "zip_path": zip_path,
            "members": members,
            "current_index": index,
            "previous_view": "gallery"
        }

        # Populate slide widget and switch to slide view
        self.slide_widget.populate(zip_path, members, index)
        self._switch_view("slide")

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
        dialog = SettingsDialog(self, self.app_settings)
        dialog.exec()

        if self.app_settings.get('performance_mode'):
            new_capacity = CONFIG["CACHE_MAX_ITEMS_PERFORMANCE"]
        else:
            new_capacity = CONFIG["CACHE_MAX_ITEMS_NORMAL"]

        self.cache.resize(new_capacity)

    def _clear_list(self):
        """Clear the ZIP file list."""
        self.zip_listbox.clear()
        self.zip_files.clear()
        self.current_selected_zip = None
        self._reset_preview()
        self.details_content_label.setText("")

    def _show_about(self):
        """Show about dialog."""
        from PySide6.QtWidgets import QMessageBox
        about_text = f"""Arkview {CONFIG['APP_VERSION']}
High-Performance Archived Image Viewer

Hybrid Rust-Python Architecture
{f'Rust Acceleration: Enabled' if RUST_AVAILABLE else 'Rust Acceleration: Not Available'}

Archive browsing and image preview utility.
BSD-2-Clause License"""
        QMessageBox.about(self, "About Arkview", about_text)

    def onThumbnailLoaded(self, result, zip_path: str, member_name: str):
        """Handle thumbnail loaded signal from thumbnail loader."""
        # Add result to gallery queue if gallery view exists and is active
        if self.gallery_widget and self.current_view == "gallery":
            # The gallery widget expects results to be put in its queue for processing
            # Create a result object with the expected structure
            try:
                # Create a cache key that matches what the gallery expects
                cache_key = (zip_path, member_name)
                if hasattr(result, 'cache_key'):
                    result.cache_key = cache_key
                self.gallery_widget.gallery_queue.put(result)
            except Exception:
                # Fallback: just update the gallery
                pass

    def onBatchProcessed(self, processed: int, total: int):
        """Handle batch processed signal from thumbnail loader."""
        # Update scan progress
        self.scan_progress.emit(processed, total)

    def closeEvent(self, event):
        """Handle application closing."""
        self.scan_stop_event.set()
        self.zip_manager.close_all()
        # Stop the thumbnail loader thread
        if hasattr(self, 'thumbnail_loader'):
            self.thumbnail_loader.stop()
        self.thread_pool.shutdown(wait=False)
        
        # Clean up slide widget if it exists
        if hasattr(self, 'slide_widget') and self.slide_widget:
            # Make sure any running threads in slide widget are stopped
            pass
            
        event.accept()

    def resizeEvent(self, event):
        """Handle window resize events to rescale preview image."""
        super().resizeEvent(event)
        # Rescale the preview image when the window is resized
        if hasattr(self, 'current_preview_pixmap') and self.current_preview_pixmap:
            try:
                scaled_pixmap = self.current_preview_pixmap.scaled(
                    self.preview_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.preview_label.setPixmap(scaled_pixmap)
            except Exception as e:
                print(f"Error rescaling preview image: {e}")


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for consistent look
    
    main_window = MainApp()
    main_window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()