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
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    QSize, QPoint, QRect, QUrl, QMetaObject, Q_ARG
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
    SettingsDialog, ImageViewerWindow
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


class MainApp(QMainWindow):
    """Main Arkview Application with PySide UI."""
    
    # Custom signals
    update_status = Signal(str)
    update_preview = Signal(object)  # (pil_image, str_error)
    
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

        self.scan_thread = None
        self.scan_stop_event = threading.Event()

        self.current_view = "explorer"  # "explorer" or "gallery"
        self.gallery_widget: Optional[GalleryView] = None

        # Set up the UI
        self._setup_ui()
        self._setup_menu()
        self._setup_keyboard_shortcuts()
        
        # Connect signals
        self.update_status.connect(self._on_update_status)
        self.update_preview.connect(self._on_update_preview)
        
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
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # View switcher at the top
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
        
        # Container for switchable views
        self.views_container = QFrame()
        views_layout = QVBoxLayout(self.views_container)
        views_layout.setContentsMargins(0, 0, 0, 0)
        
        # === RESOURCE EXPLORER VIEW ===
        self.explorer_view_frame = QFrame()
        explorer_layout = QHBoxLayout(self.explorer_view_frame)
        explorer_layout.setContentsMargins(8, 8, 8, 8)
        
        # Main splitter
        self.main_splitter = QSplitter(Qt.Horizontal)
        
        # --- Left Panel: ZIP File List ---
        left_frame = QFrame()
        left_layout = QVBoxLayout(left_frame)
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
        
        # Add left frame to splitter
        self.main_splitter.addWidget(left_frame)
        
        # --- Right Panel: Preview and Details ---
        right_frame = QFrame()
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(5, 5, 5, 5)
        
        right_label = QLabel("🖼️  Preview")
        right_label.setStyleSheet("font-weight: bold; color: #e8eaed; font-size: 11pt;")
        right_layout.addWidget(right_label)
        
        # Preview navigation controls
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
        
        # Preview container
        preview_container = QFrame()
        preview_container.setFrameStyle(QFrame.StyledPanel)
        preview_container.setStyleSheet("background-color: #2a2d2e; border: 1px solid #3a3f4b;")
        preview_container.setMinimumHeight(200)  # Set minimum height
        
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
        self.preview_label.setScaledContents(True)  # Make images scale to fit
        preview_container_layout.addWidget(self.preview_label)
        
        right_layout.addWidget(preview_container)
        
        # Details panel
        details_frame = QGroupBox("ℹ️  Details")
        details_layout = QVBoxLayout(details_frame)
        
        self.details_text = QScrollArea()
        self.details_text.setMinimumHeight(150)
        self.details_text.setWidgetResizable(True)
        self.details_widget = QWidget()
        self.details_layout = QVBoxLayout(self.details_widget)
        self.details_text.setWidget(self.details_widget)
        
        self.details_content_label = QLabel()
        self.details_content_label.setWordWrap(True)
        self.details_layout.addWidget(self.details_content_label)
        
        details_layout.addWidget(self.details_text)
        
        right_layout.addWidget(details_frame)
        
        # Add right frame to splitter
        self.main_splitter.addWidget(right_frame)
        
        # Set splitter weights
        self.main_splitter.setStretchFactor(0, 1)  # Left panel
        self.main_splitter.setStretchFactor(1, 1)  # Right panel
        
        explorer_layout.addWidget(self.main_splitter)
        
        # === GALLERY VIEW ===
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
        
        # Add both views to container
        views_layout.addWidget(self.explorer_view_frame)
        views_layout.addWidget(self.gallery_view_frame)
        
        main_layout.addWidget(self.views_container)
        
        # --- Bottom Control Panel ---
        bottom_frame = QFrame()
        bottom_frame.setFixedHeight(40)
        bottom_frame.setStyleSheet("background-color: #2c323c; border: none;")
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(8, 5, 8, 5)
        
        # Buttons container
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
        view_button.clicked.connect(self._open_viewer)
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
        
        # Status container
        status_container = QFrame()
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignRight)
        self.status_label.setStyleSheet("color: #e8eaed; font-size: 9pt;")
        status_layout.addWidget(self.status_label)
        
        bottom_layout.addWidget(status_container, stretch=1)
        
        main_layout.addWidget(bottom_frame)
        
        # Initialize visibility
        self._update_view_buttons()
        self._update_view_visibility()

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
        if view not in ["explorer", "gallery"]:
            return

        if self.current_view == view:
            return

        self.current_view = view
        self._update_view_buttons()
        self._update_view_visibility()

        if view == "gallery" and self.gallery_widget:
            self.gallery_widget.populate()

    def _update_view_buttons(self):
        """Update view button styles based on current view."""
        if self.current_view == "explorer":
            self.explorer_view_button.setStyleSheet("""
                QPushButton {
                    background-color: #00bc8c;
                    border-color: #00a47a;
                    color: #ffffff;
                    font-weight: bold;
                }
            """)
            self.gallery_view_button.setStyleSheet("""
                QPushButton {
                    background-color: #3a3f4b;
                    border: 1px solid #444a58;
                    color: #e8eaed;
                }
            """)
        else:
            self.explorer_view_button.setStyleSheet("""
                QPushButton {
                    background-color: #3a3f4b;
                    border: 1px solid #444a58;
                    color: #e8eaed;
                }
            """)
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
        if self.current_view == "explorer":
            self.gallery_view_frame.hide()
            self.explorer_view_frame.show()
        else:
            self.explorer_view_frame.hide()
            self.gallery_view_frame.show()

    def _refresh_gallery(self):
        """Refresh gallery view if visible."""
        if self.gallery_widget and self.current_view == "gallery":
            self.gallery_widget.populate()

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
                # Use QTimer to safely call UI update from main thread
                QTimer.singleShot(0, lambda: self.update_status.emit("No ZIP files found"))
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
                # Use QTimer to call from main thread
                QTimer.singleShot(0, lambda: self._add_zip_entries_bulk(batch))

            for start in range(0, total_files, batch_size):
                if self.scan_stop_event.is_set():
                    break

                batch_paths = zip_files[start:start + batch_size]
                try:
                    batch_results = self.zip_scanner.batch_analyze_zips(batch_paths, collect_members=False)
                except Exception as e:
                    # Use QTimer to call from main thread
                    QTimer.singleShot(0, lambda: self._show_error("Error", f"Scan error: {e}"))
                    QTimer.singleShot(0, lambda: self.update_status.emit("Scan failed"))
                    return

                for zip_path, is_valid, members, mod_time, file_size, image_count in batch_results:
                    processed += 1
                    if is_valid:
                        pending_entries.append((zip_path, members, mod_time, file_size, image_count))
                        valid_found += 1

                if len(pending_entries) >= batch_size:
                    flush_pending()

                if processed % ui_update_interval == 0 or processed >= total_files:
                    # Use QTimer to call from main thread
                    QTimer.singleShot(0, lambda: self.update_status.emit(f"Scanning... {processed}/{total_files} files processed"))

            flush_pending()

            final_message = (
                "Scan canceled" if self.scan_stop_event.is_set()
                else f"Found {valid_found} valid archives (of {processed} scanned)"
            )
            # Use QTimer to call from main thread
            QTimer.singleShot(0, lambda: self.update_status.emit(final_message))
        except Exception as e:
            QTimer.singleShot(0, lambda: self._show_error("Error", f"Scan error: {e}"))
            QTimer.singleShot(0, lambda: self.update_status.emit("Scan failed"))

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
        if not entries:
            return

        display_items = []
        for zip_path, members, mod_time, file_size, image_count in entries:
            if zip_path in self.zip_files:
                continue

            resolved_members = members
            resolved_mod_time = mod_time
            resolved_file_size = file_size
            resolved_image_count = image_count

            if resolved_members is None and resolved_image_count is None:
                is_valid, resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count = self.zip_scanner.analyze_zip(zip_path)
                if not is_valid or not resolved_members:
                    continue
            elif resolved_members is None and (resolved_mod_time is None or resolved_file_size is None):
                # Need complete metadata for display
                is_valid, resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count = self.zip_scanner.analyze_zip(zip_path)
                if not is_valid:
                    continue

            if resolved_image_count is None:
                resolved_image_count = len(resolved_members) if resolved_members else 0

            entry_mod_time = resolved_mod_time or 0
            entry_file_size = resolved_file_size or 0

            self.zip_files[zip_path] = (resolved_members, entry_mod_time, entry_file_size, resolved_image_count)

            display_text = os.path.basename(zip_path)
            if entry_file_size:
                display_text += f" ({_format_size(entry_file_size)})"
            display_items.append(display_text)

        if display_items:
            for item_text in display_items:
                item = QListWidgetItem(item_text)
                self.zip_listbox.addItem(item)

        self._refresh_gallery()

        # Connect selection event if not already connected
        try:
            self.zip_listbox.itemSelectionChanged.disconnect(self._on_zip_selected)
        except:
            pass  # Already disconnected
        self.zip_listbox.itemSelectionChanged.connect(self._on_zip_selected)

    def _on_update_status(self, message: str):
        """Update status bar (thread-safe)."""
        self.status_label.setText(message)

    def _on_update_preview(self, result_tuple):
        """Update preview (thread-safe)."""
        pil_image, error_msg = result_tuple
        if pil_image and not error_msg:
            # Convert PIL image to QPixmap
            qimage = PIL.ImageQt.toqpixmap(pil_image)
            self.preview_label.setPixmap(qimage)
            self.preview_label.setText("")  # Clear text when showing image
        else:
            self.preview_label.clear()
            self.preview_label.setText(f"Error: {error_msg}" if error_msg else "Select a ZIP file")

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

        zip_path = zip_entries[index]
        self.current_selected_zip = zip_path

        entry = self.zip_files[zip_path]
        members, mod_time, file_size, image_count = entry

        if members is None:
            members = self._ensure_members_loaded(zip_path)
            if not members:
                self._reset_preview("No images found")
                return
            members, mod_time, file_size, image_count = self.zip_files[zip_path]

        if not members:
            self._reset_preview("No images found")
            return

        self._update_details(zip_path, mod_time, file_size, image_count)
        self._load_preview(zip_path, members, 0)

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

    def _update_details(self, zip_path: str, mod_time: float, file_size: int, image_count: int):
        """Update the details panel."""
        details = f"Archive: {os.path.basename(zip_path)}\n"
        details += f"Images: {image_count}\n"
        details += f"Size: {_format_size(file_size)}\n"
        if mod_time:
            from datetime import datetime
            details += f"Modified: {datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M:%S')}\n"

        self.details_content_label.setText(details)

    def _load_preview(self, zip_path: str, members: List[str], index: int):
        """Load preview image."""
        if not members or index >= len(members) or index < 0:
            return

        if self.current_preview_future and not self.current_preview_future.done():
            self.current_preview_future.cancel()

        # Clear the queue
        while True:
            try:
                self.preview_queue.get_nowait()
            except queue.Empty:
                break

        self.current_preview_index = index
        self.current_preview_members = members
        cache_key = (zip_path, members[index])
        self.current_preview_cache_key = cache_key

        # Update preview info label
        self.preview_info_label.setText(f"Image {index + 1} / {len(members)}")

        # Update navigation button states
        self.preview_prev_button.setEnabled(index > 0)
        self.preview_next_button.setEnabled(index < len(members) - 1)

        target_size = (
            CONFIG["PERFORMANCE_THUMBNAIL_SIZE"] if self.app_settings['performance_mode']
            else CONFIG["THUMBNAIL_SIZE"]
        )

        self.preview_label.setText("Loading preview...")
        self.preview_label.clear()

        self.current_preview_future = self.thread_pool.submit(
            load_image_data_async,
            zip_path,
            members[index],
            self.app_settings['max_thumbnail_size'],
            target_size,
            self.preview_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.app_settings['performance_mode']
        )

        # Use QTimer to periodically check for results
        self._check_preview_result()

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
        """Handle preview click to open viewer."""
        self._open_viewer()

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

    def _open_viewer(self):
        """Open the multi-image viewer."""
        if not self.current_selected_zip:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Selection", "Please select an archive first.")
            return

        if not self.app_settings.get('viewer_enabled', True):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Disabled", "Multi-image viewer is disabled in settings.")
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

        index = self.current_preview_index or 0

        viewer_queue = queue.Queue()
        viewer_window = ImageViewerWindow(
            self,
            zip_path,
            members,
            index,
            self.app_settings,
            self.cache,
            viewer_queue,
            self.thread_pool,
            self.zip_manager
        )
        viewer_window.show()

    def _open_viewer_from_gallery(self, zip_path: str, members: List[str], index: int):
        """Open viewer when triggered from gallery view."""
        if not self.app_settings.get('viewer_enabled', True):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Disabled", "Multi-image viewer is disabled in settings.")
            return

        viewer_queue = queue.Queue()
        viewer_window = ImageViewerWindow(
            self,
            zip_path,
            members,
            index,
            self.app_settings,
            self.cache,
            viewer_queue,
            self.thread_pool,
            self.zip_manager
        )
        viewer_window.show()

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

    def closeEvent(self, event):
        """Handle application closing."""
        self.scan_stop_event.set()
        self.zip_manager.close_all()
        self.thread_pool.shutdown(wait=False)
        event.accept()


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for consistent look
    
    main_window = MainApp()
    main_window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()