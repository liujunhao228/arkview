"""
Main window implementation for Arkview UI layer.
"""

import os
import sys
import platform
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

# Import configuration
from ..config import CONFIG, parse_human_size

# Import services instead of core modules
from ..services.zip_service import ZipService
from ..services.image_service import ImageService
from ..services.thumbnail_service import ThumbnailService
from ..services.config_service import ConfigService

# Import UI components
from ..ui.dialogs import SettingsDialog
from ..ui.viewer_window import ImageViewerWindow
from ..ui.gallery_view import GalleryView

# Import core components that don't contain business logic
from ..core.cache import LRUCache
from ..core.file_manager import ZipFileManager
from ..core.models import LoadResult, _format_size


class MainWindow(QMainWindow):
    """Main application window using the new service layer architecture."""
    
    def __init__(self):
        super().__init__()
        
        # Initialize services
        self._initialize_services()
        
        # Initialize UI
        self._setup_ui()
        
        # Initialize state
        self._initialize_state()
        
    def _initialize_services(self):
        """Initialize all required services."""
        # Initialize core components
        self.cache = LRUCache(CONFIG["CACHE_MAX_ITEMS_NORMAL"])
        self.zip_manager = ZipFileManager()
        
        # Initialize services
        self.zip_service = ZipService()
        self.image_service = ImageService(self.cache, self.zip_manager)
        self.thumbnail_service = ThumbnailService(self.cache, self.zip_manager, CONFIG)
        self.config_service = ConfigService()
        
        # Connect thumbnail service signals
        self.thumbnail_service.thumbnailLoaded.connect(self._on_thumbnail_loaded)
        
    def _setup_ui(self):
        """Setup the user interface."""
        self.setWindowTitle(f"Arkview {CONFIG['APP_VERSION']}")
        self.resize(*CONFIG["WINDOW_SIZE"])
        
        # Setup menu bar
        self._setup_menu_bar()
        
        # Setup toolbar
        self._setup_toolbar()
        
        # Setup central widget
        self._setup_central_widget()
        
        # Setup status bar
        self._setup_status_bar()
        
    def _setup_menu_bar(self):
        """Setup the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('&File')
        
        open_action = QAction('&Open Directory...', self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._browse_directory)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('E&xit', self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View menu
        view_menu = menubar.addMenu('&View')
        
        self.performance_mode_action = QAction('&Performance Mode', self)
        self.performance_mode_action.setCheckable(True)
        self.performance_mode_action.toggled.connect(self._toggle_performance_mode)
        view_menu.addAction(self.performance_mode_action)
        
        view_menu.addSeparator()
        
        reload_action = QAction('&Reload', self)
        reload_action.setShortcut(QKeySequence.Refresh)
        reload_action.triggered.connect(self._reload_current_view)
        view_menu.addAction(reload_action)
        
        # Tools menu
        tools_menu = menubar.addMenu('&Tools')
        
        settings_action = QAction('&Settings...', self)
        settings_action.triggered.connect(self._open_settings)
        tools_menu.addAction(settings_action)
        
    def _setup_toolbar(self):
        """Setup the toolbar."""
        toolbar = self.addToolBar('Main')
        toolbar.setMovable(False)
        
        open_action = QAction(QIcon(), 'Open Directory', self)
        open_action.triggered.connect(self._browse_directory)
        toolbar.addAction(open_action)
        
        toolbar.addSeparator()
        
        self.performance_toggle = QAction(QIcon(), 'Performance Mode', self)
        self.performance_toggle.setCheckable(True)
        self.performance_toggle.toggled.connect(self._toggle_performance_mode)
        toolbar.addAction(self.performance_toggle)
        
    def _setup_central_widget(self):
        """Setup the central widget."""
        self.central_widget = QFrame()
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Create welcome label
        self.welcome_label = QLabel("Welcome to Arkview!\n\nDrop a folder here to begin.")
        self.welcome_label.setAlignment(Qt.AlignCenter)
        self.welcome_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                color: #666666;
                background-color: #f0f0f0;
                border: 2px dashed #cccccc;
                border-radius: 10px;
                padding: 40px;
            }
        """)
        
        self.layout.addWidget(self.welcome_label)
        self.setCentralWidget(self.central_widget)
        
    def _setup_status_bar(self):
        """Setup the status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
    def _initialize_state(self):
        """Initialize application state."""
        self.current_directory = None
        self.zip_files = {}  # path -> (members, mod_time, file_size, image_count)
        self.performance_mode = False
        self.gallery_view = None
        
    def _browse_directory(self):
        """Open directory browser."""
        from PySide6.QtWidgets import QFileDialog
        directory = QFileDialog.getExistingDirectory(
            self, "Select Directory", 
            self.current_directory or str(Path.home()))
        
        if directory:
            self._load_directory(directory)
            
    def _load_directory(self, directory: str):
        """Load a directory of ZIP files."""
        self.current_directory = directory
        self.status_bar.showMessage(f"Loading directory: {directory}")
        
        # Scan for ZIP files
        zip_paths = self._scan_for_zips(directory)
        
        # Analyze ZIP files
        results = self.zip_service.batch_analyze_zips(zip_paths)
        
        # Update internal state
        self.zip_files = {}
        for zip_path, is_valid, members, mod_time, file_size, image_count in results:
            if is_valid and image_count > 0:
                self.zip_files[zip_path] = (members, mod_time, file_size, image_count)
                
        # Show gallery view
        self._show_gallery_view()
        
        self.status_bar.showMessage(f"Loaded {len(self.zip_files)} valid ZIP files from {directory}")
        
    def _scan_for_zips(self, directory: str) -> List[str]:
        """Scan a directory for ZIP files."""
        zip_paths = []
        for root, _, files in os.walk(directory):
            for file in files:
                if file.lower().endswith('.zip'):
                    zip_paths.append(os.path.join(root, file))
        return zip_paths
        
    def _show_gallery_view(self):
        """Show the gallery view with ZIP files."""
        # Remove existing widgets
        for i in reversed(range(self.layout.count())): 
            self.layout.itemAt(i).widget().setParent(None)
            
        # Create gallery view
        self.gallery_view = GalleryView(
            parent=self.central_widget,
            zip_files=self.zip_files,
            app_settings={"performance_mode": self.performance_mode},
            cache=self.cache,
            zip_manager=self.zip_manager,
            config=CONFIG,
            ensure_members_loaded_func=self._ensure_members_loaded,
            on_selection_changed=self._on_selection_changed,
            open_viewer_func=self._open_viewer
        )
        
        self.layout.addWidget(self.gallery_view)
        
    def _ensure_members_loaded(self, zip_path: str) -> Optional[List[str]]:
        """Ensure ZIP file members are loaded."""
        if zip_path in self.zip_files:
            members, _, _, _ = self.zip_files[zip_path]
            if members is None:
                # Need to reload with members
                is_valid, members, mod_time, file_size, image_count = \
                    self.zip_service.analyze_zip(zip_path, collect_members=True)
                if is_valid:
                    self.zip_files[zip_path] = (members, mod_time, file_size, image_count)
                    return members
                else:
                    del self.zip_files[zip_path]
                    return None
            return members
        return None
        
    def _on_selection_changed(self, zip_path: str, members: List[str], index: int):
        """Handle selection change in gallery view."""
        # This could show a preview or update status
        self.status_bar.showMessage(f"Selected {Path(zip_path).name} | {index + 1}/{len(members)}")
        
    def _open_viewer(self, zip_path: str, members: List[str], index: int):
        """Open the image viewer."""
        viewer = ImageViewerWindow(
            zip_path=zip_path,
            image_members=members,
            initial_index=index,
            image_service=self.image_service,
            zip_manager=self.zip_manager,
            config=CONFIG,
            performance_mode=self.performance_mode,
            parent=self
        )
        viewer.show()
        
    def _on_thumbnail_loaded(self, result: LoadResult, cache_key: tuple):
        """Handle thumbnail loaded event."""
        # This will be connected to the thumbnail service signal
        # Actual implementation would depend on how the UI is structured
        pass
        
    def _toggle_performance_mode(self, enabled: bool):
        """Toggle performance mode."""
        self.performance_mode = enabled
        if self.gallery_view:
            self.gallery_view.update_performance_mode(enabled)
            
        # Update cache size
        cache_capacity = CONFIG[
            "CACHE_MAX_ITEMS_PERFORMANCE" if enabled else "CACHE_MAX_ITEMS_NORMAL"]
        self.cache.resize(cache_capacity)
        
        self.status_bar.showMessage(
            f"Performance mode {'enabled' if enabled else 'disabled'}")
            
    def _reload_current_view(self):
        """Reload the current view."""
        if self.current_directory:
            self._load_directory(self.current_directory)
            
    def _open_settings(self):
        """Open settings dialog."""
        dialog = SettingsDialog(CONFIG, self)
        if dialog.exec():
            # Apply settings if OK was pressed
            self._apply_settings(dialog.get_settings())
            
    def _apply_settings(self, settings: Dict[str, Any]):
        """Apply settings from the settings dialog."""
        # Store settings using config service
        for key, value in settings.items():
            self.config_service.set_setting(key, value)
            
        # Save settings
        self.config_service.save_settings()
        
        # Update current config
        CONFIG.update(settings)
        
        self.status_bar.showMessage("Settings applied")
        
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter events."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                if os.path.isdir(path) or (os.path.isfile(path) and path.lower().endswith('.zip')):
                    event.acceptProposedAction()
                    
    def dropEvent(self, event: QDropEvent):
        """Handle drop events."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                if os.path.isdir(path):
                    self._load_directory(path)
                elif os.path.isfile(path) and path.lower().endswith('.zip'):
                    # Handle single ZIP file
                    self.status_bar.showMessage("Loading single ZIP file...")
                    # TODO: Implement single ZIP file handling
                    
    def closeEvent(self, event):
        """Handle window close event."""
        # Clean up services
        self.thumbnail_service.stop_service()
        self.zip_manager.close_all()
        event.accept()