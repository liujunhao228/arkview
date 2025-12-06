"""
Main Arkview Application - PySide UI Implementation
"""

import os
import sys
import platform
import queue
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

# 导入新的配置模块
from .config import CONFIG, parse_human_size
from .core import (
    ZipScanner, ZipFileManager, LRUCache, load_image_data_async,
    LoadResult, _format_size, RUST_AVAILABLE
)
from .pyside_ui import (
    SettingsDialog, ImageViewerWindow, SlideView
)
from .pyside_gallery import GalleryView


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

    # View constants
    VIEWS = ["explorer", "gallery", "slide"]
    VIEW_DISPLAY_NAMES = {
        "explorer": "Resource Explorer",
        "gallery": "Gallery",
        "slide": "Slide"
    }
    
    def _handle_tab_switch(self):
        """Handle Tab key to switch between main views."""
        view_order = ["explorer", "gallery"]
        try:
            current_index = view_order.index(self.current_view)
            next_index = (current_index + 1) % len(view_order)
            self._switch_view(view_order[next_index])
        except ValueError:
            self._switch_view("explorer")  # Default to explorer if current view not in order

    def _handle_gallery_key(self, direction: str):
        """Handle gallery navigation keys."""
        if self.current_view == "gallery" and self.gallery_widget:
            self.gallery_widget.handle_keypress(direction)

    def _switch_view(self, view: str):
        """Switch between different views."""
        if view not in self.VIEWS or self.current_view == view:
            return

        # Save context when leaving slide view
        if self.current_view == "slide" and view != "slide":
            self.slide_view_context["previous_view"] = self.current_view

        self.current_view = view
        self._update_view_state()

    def _switch_to_previous_view(self):
        """Switch back to the previous view from slide view."""
        previous_view = self.slide_view_context.get("previous_view", "explorer")
        self._switch_view(previous_view)

    def _update_view_state(self):
        """Update both button states and view visibility."""
        self._update_view_buttons()
        self._update_view_visibility()
        self._handle_post_switch_action()

    def _update_view_buttons(self):
        """Update view button styles based on current view."""
        # Common style components
        normal_style = """
            QPushButton {
                background-color: #3a3f4b;
                border: 1px solid #444a58;
                color: #e8eaed;
            }
        """
        active_style = """
            QPushButton {
                background-color: #00bc8c;
                border-color: #00a47a;
                color: #ffffff;
                font-weight: bold;
            }
        """
        
        # Reset all buttons to normal style
        self.explorer_view_button.setStyleSheet(normal_style)
        self.gallery_view_button.setStyleSheet(normal_style)
        
        # Apply active style to current view button
        if self.current_view == "explorer":
            self.explorer_view_button.setStyleSheet(active_style)
        elif self.current_view == "gallery":
            self.gallery_view_button.setStyleSheet(active_style)

    def _update_view_visibility(self):
        """Update view visibility based on current view."""
        # Hide all views first
        self.explorer_view_frame.hide()
        self.gallery_view_frame.hide()
        self.slide_view_frame.hide()
        
        # Show current view
        view_frames = {
            "explorer": self.explorer_view_frame,
            "gallery": self.gallery_view_frame,
            "slide": self.slide_view_frame
        }
        
        if self.current_view in view_frames:
            view_frames[self.current_view].show()

    def _handle_post_switch_action(self):
        """Handle actions that need to occur after view switching."""
        # Special handling for gallery view
        if self.current_view == "gallery" and self.gallery_widget:
            self.gallery_widget.populate()
            
        # Special handling for slide view
        elif self.current_view == "slide" and self.slide_widget:
            # Context should be set before calling this method
            pass

    def _refresh_gallery(self):
        """Refresh gallery view if it's currently active."""
        if self.current_view == "gallery" and self.gallery_widget:
            self.gallery_widget.populate()

    # ==================== ZIP文件处理相关方法 ====================
    
    def _scan_directory(self):
        """扫描目录中的ZIP文件"""
        from PySide6.QtWidgets import QFileDialog
        
        directory = QFileDialog.getExistingDirectory(self, "Select Directory to Scan")
        if not directory:
            return

        self.update_status.emit("Scanning...")
        self.scan_stop_event.clear()
        
        # 在单独的线程中执行扫描操作
        self.scan_thread = threading.Thread(
            target=self._scan_directory_worker,
            args=(directory,),
            daemon=True
        )
        self.scan_thread.start()

    def _scan_directory_worker(self, directory: str):
        """扫描目录的工作线程"""
        try:
            # 获取所有ZIP文件
            zip_files = [str(p) for p in Path(directory).glob("**/*.zip")]
            total_files = len(zip_files)

            if total_files == 0:
                self.update_status.emit("No ZIP files found")
                return

            # 批量处理参数
            batch_size = max(1, CONFIG["BATCH_SCAN_SIZE"])
            ui_update_interval = max(1, CONFIG["BATCH_UPDATE_INTERVAL"])
            
            # 处理状态
            pending_entries: List[Tuple[str, Optional[List[str]], Optional[float], Optional[int], Optional[int]]] = []
            processed = 0
            valid_found = 0

            def flush_pending():
                """刷新待处理的条目"""
                if not pending_entries:
                    return
                batch = pending_entries.copy()
                pending_entries.clear()
                self.add_zip_entries_signal.emit(batch)

            # 分批处理ZIP文件
            for start in range(0, total_files, batch_size):
                if self.scan_stop_event.is_set():
                    break

                batch_paths = zip_files[start:start + batch_size]
                try:
                    batch_results = self.zip_scanner.batch_analyze_zips(batch_paths, collect_members=False)
                except Exception as e:
                    self._handle_scan_error(e)
                    return

                # 处理分析结果
                for zip_path, is_valid, members, mod_time, file_size, image_count in batch_results:
                    processed += 1
                    if is_valid:
                        pending_entries.append((zip_path, members, mod_time, file_size, image_count))
                        valid_found += 1

                # 定期刷新待处理条目
                if len(pending_entries) >= batch_size:
                    flush_pending()

                # 更新进度
                if processed % ui_update_interval == 0 or processed >= total_files:
                    self.scan_progress.emit(processed, total_files)

            # 刷新剩余条目
            flush_pending()

            # 发送最终状态
            final_message = (
                "Scan canceled" if self.scan_stop_event.is_set()
                else f"Found {valid_found} valid archives (of {processed} scanned)"
            )
            self.update_status.emit(final_message)
            self.scan_completed.emit(valid_found, processed)
            
        except Exception as e:
            self._handle_scan_error(e)

    def _handle_scan_error(self, error: Exception):
        """处理扫描过程中的错误"""
        error_msg = f"Scan error: {error}"
        self.show_error_signal.emit("Error", error_msg)
        self.update_status.emit("Scan failed")

    def _add_zip_file(self):
        """添加单个ZIP文件"""
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
        """分析并添加ZIP文件"""
        try:
            is_valid, members, mod_time, file_size, image_count = self.zip_scanner.analyze_zip(zip_path)

            if is_valid and members:
                self._add_zip_entry(zip_path, members, mod_time, file_size, image_count)
            else:
                self._show_invalid_zip_warning(zip_path)
        except Exception as e:
            self._show_error("Analysis Error", f"Failed to analyze ZIP file: {e}")

    def _show_invalid_zip_warning(self, zip_path: str):
        """显示无效ZIP文件警告"""
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
        """添加单个ZIP文件条目"""
        self._add_zip_entries_bulk([(zip_path, members, mod_time, file_size, image_count)])

    def _add_zip_entries_bulk(self, entries: List[Tuple[str, Optional[List[str]], Optional[float], Optional[int], Optional[int]]]):
        """批量添加多个ZIP文件条目"""
        if not entries:
            return

        # 处理并获取显示项
        display_items = self._process_entries_for_display(entries)
        
        # 添加到列表框
        if display_items:
            for item_text in display_items:
                item = QListWidgetItem(item_text)
                self.zip_listbox.addItem(item)

        # 刷新画廊视图
        self._refresh_gallery()

        # 管理选择事件连接
        self._manage_zip_selection_connection()

    def _show_error(self, title: str, message: str):
        """显示错误消息（线程安全）"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, title, message)

    def _process_entries_for_display(self, entries: List[Tuple[str, Optional[List[str]], Optional[float], Optional[int], Optional[int]]]) -> List[str]:
        """Process entries and prepare them for display."""
        display_items = []
        for zip_path, members, mod_time, file_size, image_count in entries:
            # Skip if already in zip_files
            if zip_path in self.zip_files:
                print(f"[DEBUG] Skipping {zip_path}, already in zip_files")
                continue

            # Resolve entry details using helper method
            resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count = self._resolve_entry_details(
                zip_path, members, mod_time, file_size, image_count)

            # Ensure image count is set
            if resolved_image_count is None:
                resolved_image_count = len(resolved_members) if resolved_members else 0

            # Use provided values or defaults
            entry_mod_time = resolved_mod_time or 0
            entry_file_size = resolved_file_size or 0

            # Store in zip_files dictionary
            self.zip_files[zip_path] = (resolved_members, entry_mod_time, entry_file_size, resolved_image_count)
            print(f"[DEBUG] Added {zip_path} to zip_files with {resolved_image_count} images")

            # Create display text
            display_text = os.path.basename(zip_path)
            if entry_file_size:
                display_text += f" ({_format_size(entry_file_size)})"
            display_items.append(display_text)
            
        return display_items

    def _resolve_entry_details(self, zip_path: str, members: Optional[List[str]], mod_time: Optional[float], 
                              file_size: Optional[int], image_count: Optional[int]) -> Tuple[Optional[List[str]], Optional[float], Optional[int], Optional[int]]:
        """Resolve the details for a ZIP file entry by analyzing if necessary."""
        # If we need both members and metadata, perform full analysis
        if members is None and (mod_time is None or file_size is None or image_count is None):
            print(f"[DEBUG] Analyzing zip {zip_path} (full analysis)")
            is_valid, analyzed_members, analyzed_mod_time, analyzed_file_size, analyzed_image_count = self.zip_scanner.analyze_zip(zip_path)
            print(f"[DEBUG] Analysis result - valid: {is_valid}, members count: {len(analyzed_members) if analyzed_members else 0}, image_count: {analyzed_image_count}")
            return analyzed_members, analyzed_mod_time, analyzed_file_size, analyzed_image_count
        
        # If we only need members list but don't have it
        if members is None:
            print(f"[DEBUG] Analyzing zip {zip_path} (members only)")
            is_valid, analyzed_members, _, _, _ = self.zip_scanner.analyze_zip(zip_path)
            return analyzed_members, mod_time, file_size, image_count

        # Return existing values if no analysis needed
        return members, mod_time, file_size, image_count

    def _manage_zip_selection_connection(self):
        """Manage the ZIP selection event connection to avoid duplicates."""
        # Use a flag to track connection state instead of relying on exception handling
        if hasattr(self, '_zip_selection_connected') and self._zip_selection_connected:
            self.zip_listbox.itemSelectionChanged.disconnect(self._on_zip_selected)
        
        self.zip_listbox.itemSelectionChanged.connect(self._on_zip_selected)
        self._zip_selection_connected = True

    def _on_update_status(self, message: str):
        """Update status bar (thread-safe)."""
        if hasattr(self, 'status_label') and self.status_label is not None:
            self.status_label.setText(message)

    def _on_update_preview(self, result_tuple):
        """Update the preview image with aspect ratio scaling."""
        if not hasattr(self, 'preview_label') or not self.preview_label:
            return
            
        pil_image, error_msg = result_tuple
        
        # Clear previous content
        self.preview_label.clear()
        
        if pil_image and not error_msg:
            try:
                # Convert PIL image to QPixmap
                qimage = PIL.ImageQt.toqimage(pil_image)
                pixmap = QPixmap.fromImage(qimage)
                
                # Store the pixmap for resizing during window resize
                self.current_preview_pixmap = pixmap
                
                # Scale the pixmap to fit the label while maintaining aspect ratio
                scaled_pixmap = pixmap.scaled(
                    self.preview_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.preview_label.setPixmap(scaled_pixmap)
                # No need to set text when displaying image
            except Exception as e:
                error_text = f"Error converting image: {str(e)}"
                self.preview_label.setText(error_text)
                print(f"[ERROR] {error_text}")
        else:
            # Display appropriate error message
            error_text = f"Error: {error_msg}" if error_msg else "Preview not available"
            self.preview_label.setText(error_text)

    def _on_zip_selected(self):
        """Handle ZIP file selection."""
        # Reset preview if no items are selected
        selected_items = self.zip_listbox.selectedItems()
        if not selected_items:
            self._reset_preview()
            return

        # Get the selected ZIP file
        item = selected_items[0]
        current_index = self.zip_listbox.row(item)
        zip_entries = list(self.zip_files.keys())
        
        # Validate index
        if current_index >= len(zip_entries) or current_index < 0:
            self._reset_preview()
            return

        # Update current selection
        selected_zip = zip_entries[current_index]
        self.current_selected_zip = selected_zip
        
        # Update details panel
        _, mod_time, file_size, image_count = self.zip_files[selected_zip]
        self._update_details_panel(selected_zip, mod_time, file_size, image_count)

        # Handle preview loading
        entry = self.zip_files.get(selected_zip)
        if not entry:
            self._reset_preview("Archive data unavailable")
            return
            
        members = entry[0]
        if members and len(members) > 0:
            self._load_preview(selected_zip, members, 0)
        else:
            # Load members in background if not loaded yet
            self._reset_preview("Loading archive contents...")
            self._load_members_for_preview(selected_zip)

        # Update details panel
        _, mod_time, file_size, image_count = self.zip_files[selected_zip]
        self._update_details_panel(selected_zip, mod_time, file_size, image_count)

    def _on_scan_progress(self, processed: int, total: int):
        """Handle scan progress updates."""
        if hasattr(self, 'status_label') and self.status_label is not None:
            if total > 0:
                progress_percent = (processed / total) * 100
                self.status_label.setText(f"Scanning... {processed}/{total} ({progress_percent:.1f}%)")
            else:
                self.status_label.setText(f"Scanning... {processed} files processed")

    def _on_scan_completed(self, valid_count: int, total_processed: int):
        """Handle scan completion."""
        if hasattr(self, 'status_label') and self.status_label is not None:
            self.status_label.setText(f"Scan completed: {valid_count} valid archives found out of {total_processed} total files")
            
        # Refresh gallery view if active
        if hasattr(self, 'gallery_widget') and self.gallery_widget and self.current_view == "gallery":
            self._refresh_gallery()

    def _ensure_members_loaded(self, zip_path: str) -> Optional[List[str]]:
        """Ensure members list is loaded for a ZIP file."""
        entry = self.zip_files.get(zip_path)
        if not entry:
            return None

        members, mod_time, file_size, image_count = entry
        if members is not None:
            return members

        # Members not loaded yet, perform analysis
        return self._analyze_and_update_zip_entry(zip_path)

    def _analyze_and_update_zip_entry(self, zip_path: str) -> Optional[List[str]]:
        """Analyze ZIP file and update its entry in zip_files dictionary."""
        try:
            is_valid, members, mod_time, file_size, image_count = self.zip_scanner.analyze_zip(zip_path)
            if is_valid and members:
                # Update zip_files with new information
                self.zip_files[zip_path] = (
                    members,
                    mod_time or 0,
                    file_size or 0,
                    len(members)
                )
                return members
            return None
        except Exception as e:
            print(f"[ERROR] Failed to analyze ZIP file {zip_path}: {e}")
            return None

    def _load_members_for_preview(self, zip_path: str):
        """Load ZIP members in a worker thread and emit results when ready."""
        # Avoid duplicate loading requests
        if zip_path in self._loading_members:
            return
            
        self._loading_members.add(zip_path)

        def task():
            try:
                members = self._ensure_members_loaded(zip_path)
            except Exception as e:
                # Emit error signal if loading fails
                self.show_error_signal.emit(
                    "Error",
                    f"Failed to load archive contents for '{Path(zip_path).name}': {e}"
                )
                members = None
            finally:
                self.members_loaded_signal.emit(zip_path, members)

        self.thread_pool.submit(task)

    def _on_members_loaded(self, zip_path: str, members: Optional[List[str]]):
        """Handle members loaded signal (thread-safe)."""
        # Remove from loading set
        self._loading_members.discard(zip_path)
        
        # Only process if this is still the currently selected ZIP
        if zip_path != self.current_selected_zip:
            return

        if members and len(members) > 0:
            # Update details with fresh member count
            entry = self.zip_files.get(zip_path)
            if entry:
                _, mod_time, file_size, _ = entry
                self.zip_files[zip_path] = (members, mod_time, file_size, len(members))
                self._update_details_panel(zip_path, mod_time, file_size, len(members))
            self._load_preview_image(zip_path, members, 0)
        else:
            self._reset_preview("No images found in archive")

    def _update_details_panel(self, zip_path: str, mod_time: float, file_size: int, image_count: int):
        """Update the details panel with archive information."""
        if not hasattr(self, 'details_content_label') or not self.details_content_label:
            return

        # Build details text
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

    def _load_preview_image(self, zip_path: str, members: List[str], index: int):
        """Load preview image with proper validation and state management."""
        # Validate the request
        if not members or index < 0 or index >= len(members):
            return

        # Cancel any ongoing preview task
        if self.current_preview_future and not self.current_preview_future.done():
            self.current_preview_future.cancel()

        # Clear the preview queue
        self._clear_preview_result_queue()

        # Update preview state
        self.current_preview_index = index
        self.current_preview_members = members
        self.current_preview_cache_key = (zip_path, members[index])

        # Update UI elements
        self._update_preview_ui_elements(index, len(members))

        # Set loading message
        self.preview_label.clear()
        self.preview_label.setText("Loading preview...")

        # Submit the preview loading task
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
            (zip_path, members[index]),
            self.zip_manager,
            self.app_settings['performance_mode']
        )

        # Start checking for results
        self._check_preview_result()

    def _clear_preview_result_queue(self):
        """Clear all items from the preview result queue."""
        try:
            while True:
                self.preview_queue.get_nowait()
        except queue.Empty:
            pass

    def _update_preview_ui_elements(self, index: int, total_count: int):
        """Update preview navigation UI elements."""
        # Update info label
        self.preview_info_label.setText(f"Image {index + 1} / {total_count}")

        # Update navigation buttons
        self.preview_prev_button.setEnabled(index > 0)
        self.preview_next_button.setEnabled(index < total_count - 1)

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
        """Reset the preview panel and clear any ongoing operations."""
        # Cancel any ongoing preview task
        if self.current_preview_future and not self.current_preview_future.done():
            self.current_preview_future.cancel()
        self.current_preview_future = None
        
        # Clear preview state
        self.current_preview_members = None
        self.current_preview_index = None
        self.current_preview_cache_key = None

        # Drain any pending preview results
        self._clear_preview_result_queue()

        # Reset UI elements
        self.preview_label.clear()
        self.preview_label.setText(message)
        self.preview_info_label.setText('')
        self.preview_prev_button.setEnabled(False)
        self.preview_next_button.setEnabled(False)

    def _load_preview(self, zip_path: str, members: List[str], index: int):
        """Load preview for given ZIP file, members and index."""
        if not members or index < 0 or index >= len(members):
            return
            
        self._load_preview_image(zip_path, members, index)

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

    def _switch_to_slide_view(self, zip_path: str, members: List[str], index: int, previous_view: str):
        """Private helper to switch to slide view with given context.
        
        Args:
            zip_path: Path to the ZIP file
            members: List of member names in the ZIP
            index: Current image index
            previous_view: The view that initiated the transition ("explorer" or "gallery")
        """
        # Set context for slide view
        self.slide_view_context = {
            "zip_path": zip_path,
            "members": members,
            "current_index": index,
            "previous_view": previous_view
        }

        # Populate slide widget and switch to slide view
        self.slide_widget.populate(zip_path, members, index)
        self._switch_view("slide")

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

        self._switch_to_slide_view(zip_path, members, self.current_preview_index or 0, "explorer")

    def _open_viewer_from_gallery(self, zip_path: str, members: List[str], index: int):
        """Open slide view when triggered from gallery view."""
        self._switch_to_slide_view(zip_path, members, index, "gallery")

    def _on_gallery_selection(self, zip_path: str, members: List[str], index: int):
        """Handle selection change in gallery view."""
        self.current_selected_zip = zip_path
        self.current_preview_members = members
        self.current_preview_index = index

        entry = self.zip_files.get(zip_path)
        if entry:
            _, mod_time, file_size, image_count = entry
            self._update_details_panel(zip_path, mod_time, file_size, image_count)

    def _update_cache_capacity(self):
        """Update cache capacity based on current performance mode setting."""
        new_capacity = (
            CONFIG["CACHE_MAX_ITEMS_PERFORMANCE"] 
            if self.app_settings.get('performance_mode') 
            else CONFIG["CACHE_MAX_ITEMS_NORMAL"]
        )
        self.cache.resize(new_capacity)

    def _show_settings(self):
        """Show settings dialog and update application settings."""
        dialog = SettingsDialog(self, self.app_settings)
        dialog.exec()
        
        # Update cache capacity based on new performance mode setting
        self._update_cache_capacity()

    def _clear_list(self):
        """Clear all loaded ZIP files and reset UI state."""
        # Clear UI components
        self.zip_listbox.clear()
        
        # Clear data structures
        self.zip_files.clear()
        self.current_selected_zip = None
        
        # Reset preview and details
        self._reset_preview("No archives loaded")
        self.details_content_label.setText("")
        
        # Refresh views
        if self.gallery_widget:
            self.gallery_widget.clear()

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
        """Handle application closing with proper resource cleanup."""
        # Signal scan thread to stop
        self.scan_stop_event.set()
        
        # Close all zip file handles
        self.zip_manager.close_all()
        
        # Stop thumbnail loader thread
        if hasattr(self, 'thumbnail_loader') and self.thumbnail_loader:
            self.thumbnail_loader.stop()
        
        # Shutdown thread pool gracefully
        if hasattr(self, 'thread_pool'):
            self.thread_pool.shutdown(wait=True)
        
        # Clean up slide widget
        if hasattr(self, 'slide_widget') and self.slide_widget:
            self.slide_widget.cleanup()
        
        # Accept the close event
        event.accept()

    def resizeEvent(self, event):
        """Handle window resize events to rescale preview image while maintaining aspect ratio."""
        super().resizeEvent(event)
        
        # Rescale the preview image when the window is resized
        if (hasattr(self, 'current_preview_pixmap') and 
            self.current_preview_pixmap and 
            hasattr(self, 'preview_label')):
            
            try:
                # Scale pixmap to fit label while maintaining aspect ratio
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