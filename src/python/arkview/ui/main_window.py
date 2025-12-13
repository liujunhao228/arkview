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

# Import services only
from ..services.zip_service import ZipService
from ..services.image_service import ImageService
from ..services.thumbnail_service import ThumbnailService
from ..services.config_service import ConfigService
from ..services import SimpleCacheService as CacheService
from ..services.navigation_service import NavigationService
from ..services.playlist_service import PlaylistService
from ..services.slideshow_service import SlideshowService
from ..core.models import ZipFileInfo

# Import UI components
from ..ui.dialogs import SettingsDialog
from ..ui.viewer_window import ImageViewerWindow
from ..ui.gallery_view import GalleryView

# Import core models (these don't contain business logic)
from ..core.models import LoadResult
from ..core.file_manager import ZipFileManager
from ..arkview_core import format_size


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
        
        # Apply dark theme
        self._apply_dark_theme()
        
    def _initialize_services(self):
        """Initialize all required services."""
        # Initialize services
        self.cache_service = CacheService(capacity=CONFIG["CACHE_MAX_ITEMS_NORMAL"])
        self.zip_manager = ZipFileManager()

        # Initialize other services
        self.zip_service = ZipService()
        self.image_service = ImageService(self.cache_service, self.zip_manager)
        self.thumbnail_service = ThumbnailService(self.cache_service, CONFIG)
        self.config_service = ConfigService()
        self.navigation_service = NavigationService()
        self.playlist_service = PlaylistService()
        # 初始化新的服务并传入zip_manager
        self.slideshow_service = SlideshowService(self.zip_manager)

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
        
    def _show_cache_stats(self):
        """显示缓存统计信息"""
        try:
            stats = self.cache_service.get_detailed_stats()
            hit_rate = stats['stats']['hit_rate']
            efficiency = stats.get('cache_efficiency', 0)
            
            self.status_bar.showMessage(
                f"缓存命中率: {hit_rate:.1%}, 效率得分: {efficiency:.2f}, "
                f"内存使用: {stats.get('memory_estimate', {}).get('total_mb', '未知')}"
            )
        except Exception as e:
            print(f"获取缓存统计信息时出错: {e}")
            
    def _preload_images(self, zip_path: str, members: List[str], current_index: int):
        """预加载相邻图片"""
        try:
            neighbor_count = 2 if not self.app_settings.get('performance_mode', False) else 1
            target_size = None  # 预加载全尺寸图像
            
            self.image_service.preload_neighbor_images(
                zip_path, members, current_index, neighbor_count, 
                target_size, self.app_settings.get('performance_mode', False)
            )
        except Exception as e:
            print(f"预加载图片时出错: {e}")
            
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

        self.welcome_label = QLabel("Welcome to Arkview!\n\nDrop a folder here to begin.")
        self.welcome_label.setObjectName("welcomeLabel")
        self.welcome_label.setAlignment(Qt.AlignCenter)

        self.layout.addWidget(self.welcome_label)
        self.setCentralWidget(self.central_widget)

        self.drag_overlay = QLabel("Drop folders or archives to load", self.central_widget)
        self.drag_overlay.setObjectName("dragOverlay")
        self.drag_overlay.setAlignment(Qt.AlignCenter)
        self.drag_overlay.hide()
        self.central_widget.installEventFilter(self)
        self._update_drag_overlay_geometry()
        
    def _clear_central_widget(self):
        """Clear all widgets from the central widget layout."""
        while self.layout.count():
            child = self.layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
    def _setup_status_bar(self):
        """Setup the status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
    def _apply_dark_theme(self):
        """Apply dark theme stylesheet to the application."""
        try:
            # 获取当前文件所在目录
            current_dir = os.path.dirname(os.path.abspath(__file__))
            qss_path = os.path.join(current_dir, "dark_theme.qss")
            
            with open(qss_path, "r", encoding="utf-8") as f:
                style_sheet = f.read()
                self.setStyleSheet(style_sheet)
        except FileNotFoundError:
            # 如果找不到样式文件，使用默认的暗色样式
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #2b2b2b;
                }
                QLabel {
                    color: #e0e0e0;
                }
                QMenuBar {
                    background-color: #3c3f41;
                    color: #bbbbbb;
                }
                QMenuBar::item:selected {
                    background-color: #4b6eaf;
                }
                QMenu {
                    background-color: #3c3f41;
                    color: #bbbbbb;
                }
                QMenu::item:selected {
                    background-color: #4b6eaf;
                }
                QToolBar {
                    background-color: #3c3f41;
                    border: none;
                }
                QStatusBar {
                    background-color: #3c3f41;
                    color: #bbbbbb;
                }
                QLabel#welcomeLabel {
                    font-size: 18px;
                    color: #aaaaaa;
                    background-color: #2b2b2b;
                    border: 2px dashed #555555;
                    border-radius: 10px;
                    padding: 40px;
                }
                QLabel#dragOverlay {
                    background-color: rgba(75, 110, 175, 0.3);
                    border: 2px dashed #4b6eaf;
                    color: #4b6eaf;
                    font-size: 18px;
                    font-weight: 600;
                    border-radius: 12px;
                }
            """)
        
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
        """Show the gallery view."""
        # Clear current view
        self._clear_central_widget()
        
        # Create gallery view
        self.gallery_view = GalleryView(
            parent=self.central_widget,
            zip_files=self.zip_files,
            app_settings={"performance_mode": self.performance_mode},
            thumbnail_service=self.thumbnail_service,
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
        if not zip_path:
            self.status_bar.showMessage("Selection cleared")
            return

        if not members:
            self.status_bar.showMessage(f"Selected {Path(zip_path).name}")
            return

        total = len(members)
        current = min(total, index + 1)
        self.status_bar.showMessage(f"Selected {Path(zip_path).name} | {current}/{total}")
        
    def _open_viewer(self, zip_path: str, members: List[str], index: int):
        """Open the image viewer."""
        # Update playlist service with all loaded archives
        all_archives = []
        for path, (archive_members, mod_time, file_size, image_count) in self.zip_files.items():
            if archive_members is not None:  # Only include archives with loaded members
                all_archives.append(ZipFileInfo(
                    path=path,
                    is_valid=True,
                    members=archive_members,
                    mod_time=mod_time,
                    file_size=file_size,
                    image_count=image_count
                ))
        
        # Sort archives by path for consistent ordering
        all_archives.sort(key=lambda x: x.path)
        print(f"DEBUG: Setting {len(all_archives)} archives in playlist service")  # 添加调试输出
        self.playlist_service.create_from_archives(all_archives)
        
        # Update navigation service with ALL archives, not just the current one
        self.navigation_service.set_archives(all_archives)
        
        viewer = ImageViewerWindow(
            image_service=self.image_service,
            navigation_service=self.navigation_service,
            parent=self
        )
        viewer.populate(zip_path, members, index)
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
            # Note: We don't have an update_performance_mode method anymore
            pass
            
        # Update cache size
        cache_capacity = CONFIG[
            "CACHE_MAX_ITEMS_PERFORMANCE" if enabled else "CACHE_MAX_ITEMS_NORMAL"]
        self.cache_service.resize(cache_capacity)
        
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
        
    def eventFilter(self, obj, event):
        """Event filter for drag/drop visual feedback."""
        if obj == self.central_widget:
            if event.type() == QEvent.Resize:
                self._update_drag_overlay_geometry()
        return super().eventFilter(obj, event)

    def _update_drag_overlay_geometry(self):
        """Update drag overlay to cover central widget."""
        if hasattr(self, 'drag_overlay'):
            margin = 16
            self.drag_overlay.setGeometry(
                margin, margin,
                self.central_widget.width() - 2 * margin,
                self.central_widget.height() - 2 * margin
            )

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter events with visual feedback."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                if os.path.isdir(path) or (os.path.isfile(path) and path.lower().endswith('.zip')):
                    event.acceptProposedAction()
                    self.drag_overlay.show()
                    self.drag_overlay.raise_()

    def dragLeaveEvent(self, event):
        """Handle drag leave event."""
        self.drag_overlay.hide()

    def dropEvent(self, event: QDropEvent):
        """Handle drop events."""
        self.drag_overlay.hide()

        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                if os.path.isdir(path):
                    self._load_directory(path)
                elif os.path.isfile(path) and path.lower().endswith('.zip'):
                    self.status_bar.showMessage("Single ZIP file handling not yet implemented.")

    def closeEvent(self, event):
        """Handle window close event."""
        self.thumbnail_service.stop_service()
        self.zip_service.zip_manager.clear()
        event.accept()