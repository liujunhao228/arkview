"""
DEPRECATED: This file is deprecated and replaced by the new layered architecture.

The new architecture separates concerns into distinct layers:
- UI Layer: ui/dialogs.py, ui/viewer_window.py
- Service Layer: services/*.py
- Core Layer: core/*.py

Please use the new modules instead.
"""

import warnings
warnings.warn("pyside_ui.py is deprecated, use ui/dialogs.py and ui/viewer_window.py instead", DeprecationWarning)

# Preserve the old interface for backward compatibility if needed
# Note: This file is now just a placeholder and should not be used in new code

import os
import platform
from typing import Any, Dict, List, Optional, Tuple, Callable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QCheckBox, QPushButton, QGroupBox, QGridLayout, QScrollArea,
    QApplication, QMainWindow, QWidget, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer, QThread, Slot, QObject
from PySide6.QtGui import QPixmap, QPalette, QColor
from PIL import Image
import PIL.ImageQt

from .core import (
    ZipScanner, ZipFileManager, LRUCache, load_image_data_async,
    LoadResult, _format_size, ImageLoaderSignals
)


class ImageViewerWorker(QObject):
    """Worker object for handling image loading in a separate thread."""
    imageLoaded = Signal(object)  # LoadResult
    loadError = Signal(str)       # error message

    def __init__(self):
        super().__init__()
        self.signals = ImageLoaderSignals()
        self.signals.image_loaded.connect(self._on_image_loaded)
        
    @Slot(str, str, tuple, int, tuple, object, object, bool)
    def load_image(self, zip_path: str, member_path: str, cache_key: tuple, 
                   max_size: int, resize_params: tuple, cache, zip_manager, performance_mode: bool):
        """Load an image from a ZIP file."""
        try:
            # Call the async loading function with signals for callback
            load_image_data_async(
                zip_path, member_path, max_size, resize_params,
                self.signals, cache, cache_key, zip_manager, performance_mode
            )
        except Exception as e:
            self.loadError.emit(str(e))
            
    @Slot(object)
    def _on_image_loaded(self, result):
        """Handle loaded image result."""
        self.imageLoaded.emit(result)


class SlideView(QFrame):
    """Slide view for displaying individual images from a ZIP archive."""
    
    def __init__(
        self,
        parent,
        zip_files: Dict[str, Tuple[Optional[List[str]], float, int, int]],
        app_settings: Dict[str, Any],
        cache: LRUCache,
        zip_manager: ZipFileManager,
        config: Dict[str, Any],
        back_callback: Optional[Callable] = None
    ):
        super().__init__(parent)
        
        self.zip_files = zip_files
        self.app_settings = app_settings
        self.cache = cache
        self.zip_manager = zip_manager
        self.config = config
        self.back_callback = back_callback
        
        self.current_zip_path: Optional[str] = None
        self.current_members: Optional[List[str]] = None
        self.current_index: int = 0
        
        # Setup threaded image loading
        self.image_loader_thread = QThread()
        self.image_loader_worker = ImageViewerWorker()
        self.image_loader_worker.moveToThread(self.image_loader_thread)
        self.image_loader_worker.imageLoaded.connect(self._on_image_loaded)
        self.image_loader_worker.loadError.connect(self._on_load_error)
        self.image_loader_thread.start()
        
        self.current_pil_image: Optional[Image.Image] = None
        self.zoom_factor: float = 1.0
        self.fit_to_window: bool = True
        self._is_loading: bool = False
        
        self._setup_ui()
        self._apply_dark_theme()
        
    def _apply_dark_theme(self):
        """Apply dark theme to the slide view."""
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(40, 44, 52))
        palette.setColor(QPalette.WindowText, QColor(233, 237, 237))
        self.setPalette(palette)
        
        self.setStyleSheet("""
            QFrame {
                background-color: #282c34;
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
            QPushButton#nav-button {
                min-width: 100px;
                padding: 8px 16px;
                font-size: 12pt;
            }
            QPushButton#back-button {
                background-color: #00bc8c;
                border-color: #00a47a;
                color: #ffffff;
                font-weight: bold;
                padding: 8px 16px;
            }
            QPushButton#back-button:hover {
                background-color: #00a47a;
            }
            QLabel {
                color: #e8eaed;
            }
        """)
        
    def _setup_ui(self):
        """Setup the slide view UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Top navigation bar
        nav_frame = QFrame()
        nav_frame.setFixedHeight(60)
        nav_layout = QHBoxLayout(nav_frame)
        nav_layout.setContentsMargins(12, 12, 12, 12)
        nav_layout.setSpacing(15)
        
        self.back_button = QPushButton("⬅ Back")
        self.back_button.setObjectName("back-button")
        self.back_button.clicked.connect(self._on_back_clicked)
        nav_layout.addWidget(self.back_button)
        
        self.title_label = QLabel("Slide View")
        self.title_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        nav_layout.addWidget(self.title_label)
        
        nav_layout.addStretch()
        
        self.image_info_label = QLabel("")
        self.image_info_label.setStyleSheet("font-size: 10pt; color: #bbbbbb;")
        nav_layout.addWidget(self.image_info_label)
        
        main_layout.addWidget(nav_frame)
        
        # Main content area
        content_frame = QFrame()
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(20, 20, 20, 20)
        
        # Image display area
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #1c1e1f; border-radius: 4px;")
        self.image_label.setMinimumSize(400, 300)
        content_layout.addWidget(self.image_label, stretch=1)
        
        # Navigation controls
        nav_controls_frame = QFrame()
        nav_controls_frame.setFixedHeight(80)
        nav_controls_layout = QHBoxLayout(nav_controls_frame)
        nav_controls_layout.setContentsMargins(0, 0, 0, 0)
        nav_controls_layout.setSpacing(20)
        
        nav_controls_layout.addStretch()
        
        self.prev_button = QPushButton("◀ Previous")
        self.prev_button.setObjectName("nav-button")
        self.prev_button.clicked.connect(self._show_prev)
        nav_controls_layout.addWidget(self.prev_button)
        
        self.next_button = QPushButton("Next ▶")
        self.next_button.setObjectName("nav-button")
        self.next_button.clicked.connect(self._show_next)
        nav_controls_layout.addWidget(self.next_button)
        
        nav_controls_layout.addStretch()
        
        content_layout.addWidget(nav_controls_frame)
        
        main_layout.addWidget(content_frame)
        
    def populate(self, zip_path: str, members: List[str], index: int = 0):
        """Populate the slide view with images from a ZIP file."""
        self.current_zip_path = zip_path
        self.current_members = members
        self.current_index = index
        
        # Update title
        zip_name = os.path.basename(zip_path)
        self.title_label.setText(f"🖼️ {zip_name}")
        
        # Load the initial image
        self.load_image(index)
        
    def load_image(self, index: int):
        """Load and display an image at the given index."""
        if (not self.current_members or 
            index < 0 or 
            index >= len(self.current_members)):
            return
            
        self.current_index = index
        self._update_navigation_state()
        
        # Update image info
        self.image_info_label.setText(
            f"Image {index + 1} of {len(self.current_members)}"
        )
        
        self._is_loading = True
        cache_key = (self.current_zip_path, self.current_members[index])
        
        # Clear previous image
        self.image_label.clear()
        self.image_label.setText("Loading...")
        
        # 使用工作线程加载图像
        self.image_loader_worker.load_image.emit(
            self.current_zip_path,
            self.current_members[index],
            cache_key,
            100 * 1024 * 1024,  # Max viewer load size
            None,  # No resizing for viewer
            self.cache,
            self.zip_manager,
            self.app_settings.get('performance_mode', False)
        )

    @Slot(object)
    def _on_image_loaded(self, result):
        """Handle loaded image result."""
        if result.success:
            self.current_pil_image = result.data
            self._update_display()
        else:
            self.image_label.setText(f"Error: {result.error_message}")
        self._is_loading = False
        
    @Slot(str)
    def _on_load_error(self, error_msg):
        """Handle image loading error."""
        self.image_label.setText(f"Error: {error_msg}")
        self._is_loading = False
                
    def _update_display(self):
        """Update the image display."""
        if self.current_pil_image is None:
            return
            
        # Get the size of the label to determine display area
        display_width = self.image_label.width()
        display_height = self.image_label.height()
        
        img = self.current_pil_image.copy()
        
        if self.fit_to_window:
            # Fit image to the display area while preserving aspect ratio
            img.thumbnail(
                (display_width - 20, display_height - 20), 
                Image.Resampling.LANCZOS
            )
        else:
            # Apply zoom factor
            new_width = int(img.width * self.zoom_factor)
            new_height = int(img.height * self.zoom_factor)
            if new_width > 0 and new_height > 0:
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
        # Convert PIL image to QPixmap and set it to the label
        try:
            qimage = PIL.ImageQt.ImageQt(img)
            pixmap = QPixmap.fromImage(qimage)
            self.image_label.setPixmap(pixmap)
            self.image_label.setText("")
        except Exception as e:
            self.image_label.setText(f"Error displaying image: {str(e)}")
            
    def _update_navigation_state(self):
        """Update the state of navigation buttons."""
        if not self.current_members:
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            return
            
        self.prev_button.setEnabled(self.current_index > 0)
        self.next_button.setEnabled(self.current_index < len(self.current_members) - 1)
        
    def _show_prev(self):
        """Show the previous image."""
        if self.current_index > 0:
            self.load_image(self.current_index - 1)
            
    def _show_next(self):
        """Show the next image."""
        if self.current_members and self.current_index < len(self.current_members) - 1:
            self.load_image(self.current_index + 1)
            
    def _on_back_clicked(self):
        """Handle back button click."""
        if self.back_callback:
            self.back_callback()
            
    def resizeEvent(self, event):
        """Handle resize events to rescale the image."""
        super().resizeEvent(event)
        if self.current_pil_image and not self._is_loading:
            self._update_display()

    def closeEvent(self, event):
        """Handle window close event."""
        # Clean up worker thread
        if hasattr(self, 'image_loader_thread'):
            self.image_loader_thread.quit()
            self.image_loader_thread.wait()
        event.accept()


def format_datetime(timestamp: float) -> str:
    """Formats a timestamp into a YYYY-MM-DD HH:MM:SS string."""
    try:
        from datetime import datetime
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, OSError, TypeError):
        return "N/A"


class SettingsDialog(QDialog):
    """Dialog window for application settings."""
    
    def __init__(self, parent, current_settings: Dict[str, Any]):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Settings")
        self.setModal(True)
        self.setFixedSize(400, 250)
        
        self.settings = current_settings
        self.result_settings = current_settings.copy()

        # Create widgets
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)

        title_label = QLabel("Application Settings")
        title_label.setStyleSheet("font-size: 12pt; font-weight: bold;")
        main_layout.addWidget(title_label)

        # Settings checkboxes
        self.performance_mode_check = QCheckBox("⚡ Performance Mode (Faster, Lower Quality)")
        self.performance_mode_check.setChecked(self.result_settings.get('performance_mode', False))
        self.performance_mode_check.toggled.connect(self._update_dependent_settings)
        main_layout.addWidget(self.performance_mode_check)

        self.viewer_enabled_check = QCheckBox("👁️ Enable Multi-Image Viewer (Click Preview)")
        self.viewer_enabled_check.setChecked(self.result_settings.get('viewer_enabled', True))
        main_layout.addWidget(self.viewer_enabled_check)

        self.preload_thumb_check = QCheckBox("🔄 Preload Next Thumbnail (in Preview)")
        self.preload_thumb_check.setChecked(self.result_settings.get('preload_next_thumbnail', True))
        main_layout.addWidget(self.preload_thumb_check)

        # Buttons
        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        button_layout.addWidget(spacer)

        cancel_button = QPushButton("Cancel")
        cancel_button.setFixedWidth(100)
        cancel_button.clicked.connect(self._on_cancel)
        button_layout.addWidget(cancel_button)

        ok_button = QPushButton("OK")
        ok_button.setFixedWidth(100)
        ok_button.setObjectName("success")
        ok_button.clicked.connect(self._on_ok)
        button_layout.addWidget(ok_button)

        main_layout.addWidget(button_frame)

        # Apply initial dependent settings
        self._update_dependent_settings()
        
        # Apply dark theme
        self._apply_dark_theme()

    def _apply_dark_theme(self):
        """Apply dark theme to the dialog."""
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(40, 44, 52))
        palette.setColor(QPalette.WindowText, QColor(233, 237, 237))
        self.setPalette(palette)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #282c34;
                color: #e8eaed;
            }
            QCheckBox {
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
            QPushButton#success {
                background-color: #5cb85c;
                border-color: #4cae4c;
                color: #ffffff;
            }
            QPushButton#success:hover {
                background-color: #4cae4c;
            }
        """)

    def _update_dependent_settings(self):
        is_performance = self.performance_mode_check.isChecked()
        self.preload_thumb_check.setEnabled(not is_performance)
        if is_performance:
            self.preload_thumb_check.setChecked(False)

    def _on_ok(self):
        self.settings['performance_mode'] = self.performance_mode_check.isChecked()
        self.settings['viewer_enabled'] = self.viewer_enabled_check.isChecked()
        if not self.settings['performance_mode']:
            self.settings['preload_next_thumbnail'] = self.preload_thumb_check.isChecked()
        else:
            self.settings['preload_next_thumbnail'] = False
        self.accept()

    def _on_cancel(self):
        self.reject()


class ImageViewerWindow(QDialog):
    """Window for viewing multiple images from a ZIP archive."""
    
    def __init__(
        self,
        parent,
        zip_path: str,
        image_members: List[str],
        initial_index: int,
        settings: Dict[str, Any],
        cache: LRUCache,
        zip_manager: ZipFileManager
    ):
        super().__init__(parent)
        self.parent_app = parent
        self.zip_path = zip_path
        self.image_members = image_members
        self.current_index = initial_index
        self.settings = settings
        self.cache = cache
        self.zip_manager = zip_manager

        self.current_pil_image: Optional[Image.Image] = None
        self.zoom_factor: float = 1.0
        self.fit_to_window: bool = True
        self._is_loading: bool = False
        self._is_fullscreen: bool = False
        
        # Setup threaded image loading with Qt signals/slots
        self.image_loader_thread = QThread()
        self.image_loader_worker = ImageViewerWorker()
        self.image_loader_worker.moveToThread(self.image_loader_thread)
        self.image_loader_worker.imageLoaded.connect(self._on_image_loaded)
        self.image_loader_worker.loadError.connect(self._on_load_error)
        self.image_loader_thread.start()

        self.setWindowTitle(f"👁️ Viewer: {os.path.basename(zip_path)}")
        self.resize(900, 650)
        self.setMinimumSize(500, 400)

        self._setup_ui()
        self._setup_keyboard_shortcuts()
        
        self._apply_dark_theme()

        # Load the initial image
        QTimer.singleShot(10, lambda: self.load_image(self.current_index))

    def _apply_dark_theme(self):
        """Apply dark theme to the viewer."""
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(40, 44, 52))
        palette.setColor(QPalette.WindowText, QColor(233, 237, 237))
        self.setPalette(palette)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #282c34;
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
        """)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Top controls
        top_frame = QFrame()
        top_frame.setFixedHeight(50)
        top_layout = QHBoxLayout(top_frame)
        top_layout.setContentsMargins(8, 8, 8, 8)
        top_layout.setSpacing(10)

        self.prev_button = QPushButton("◀ Prev")
        self.prev_button.setFixedWidth(100)
        self.prev_button.clicked.connect(self._show_prev)
        top_layout.addWidget(self.prev_button)

        self.image_info_label = QLabel(f"Image {self.current_index + 1} / {len(self.image_members)}")
        self.image_info_label.setAlignment(Qt.AlignCenter)
        self.image_info_label.setStyleSheet("font-size: 10pt;")
        top_layout.addWidget(self.image_info_label)

        self.next_button = QPushButton("Next ▶")
        self.next_button.setFixedWidth(100)
        self.next_button.clicked.connect(self._show_next)
        top_layout.addWidget(self.next_button)

        main_layout.addWidget(top_frame)

        # Image display
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #1c1e1f; border-radius: 4px;")
        self.image_label.setMinimumSize(400, 300)
        main_layout.addWidget(self.image_label, stretch=1)

        # Status bar at the bottom
        self.status_frame = QFrame()
        self.status_frame.setFixedHeight(30)
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(8, 4, 8, 4)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignLeft)
        self.status_label.setStyleSheet("font-size: 9pt; color: #bbbbbb;")
        self.status_label.setMinimumHeight(20)
        status_layout.addWidget(self.status_label)

        main_layout.addWidget(self.status_frame)

    def _setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts for the viewer."""
        # Left arrow - previous image
        from PySide6.QtGui import QShortcut, QKeySequence
        shortcut_left = QShortcut(QKeySequence(Qt.Key_Left), self)
        shortcut_left.activated.connect(self._show_prev)
        
        # Right arrow - next image
        shortcut_right = QShortcut(QKeySequence(Qt.Key_Right), self)
        shortcut_right.activated.connect(self._show_next)
        
        # Page Up - previous image
        shortcut_pgup = QShortcut(QKeySequence(Qt.Key_PageUp), self)
        shortcut_pgup.activated.connect(self._show_prev)
        
        # Page Down - next image
        shortcut_pgdn = QShortcut(QKeySequence(Qt.Key_PageDown), self)
        shortcut_pgdn.activated.connect(self._show_next)
        
        # Escape - close viewer
        shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        shortcut_esc.activated.connect(self.close)
        
        # F11 - toggle fullscreen
        shortcut_f11 = QShortcut(QKeySequence(Qt.Key_F11), self)
        shortcut_f11.activated.connect(self._toggle_fullscreen)
        
        # F - fit to window
        shortcut_f = QShortcut(QKeySequence("f"), self)
        shortcut_f.activated.connect(self._toggle_fit_to_window)
        
        # R - reset zoom
        shortcut_r = QShortcut(QKeySequence("r"), self)
        shortcut_r.activated.connect(self._reset_zoom)
        
        # Home - first image
        shortcut_home = QShortcut(QKeySequence(Qt.Key_Home), self)
        shortcut_home.activated.connect(self._go_to_first)
        
        # End - last image
        shortcut_end = QShortcut(QKeySequence(Qt.Key_End), self)
        shortcut_end.activated.connect(self._go_to_last)

    def _toggle_fullscreen(self):
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            self.showFullScreen()
        else:
            self.showNormal()

    def _toggle_fit_to_window(self):
        self.fit_to_window = not self.fit_to_window
        self._update_display()

    def _reset_zoom(self):
        self.zoom_factor = 1.0
        self._update_display()

    def _go_to_first(self):
        self.load_image(0)

    def _go_to_last(self):
        self.load_image(len(self.image_members) - 1)

    def _show_prev(self):
        if self.current_index > 0:
            self.load_image(self.current_index - 1)

    def _show_next(self):
        if self.current_index < len(self.image_members) - 1:
            self.load_image(self.current_index + 1)

    def load_image(self, index: int):
        if index < 0 or index >= len(self.image_members):
            return
        self.current_index = index
        self.image_info_label.setText(f"Image {index + 1} / {len(self.image_members)}")

        self._is_loading = True
        cache_key = (self.zip_path, self.image_members[index])

        # Clear previous image
        self.image_label.clear()
        self.image_label.setText("Loading...")
        self.status_label.setText("Loading...")

        # 使用工作线程加载图像
        self.image_loader_worker.load_image.emit(
            self.zip_path,
            self.image_members[index],
            cache_key,
            100 * 1024 * 1024,  # Max viewer load size
            None,  # No resizing for viewer
            self.cache,
            self.zip_manager,
            self.settings.get('performance_mode', False)
        )

    def _update_display(self):
        if self.current_pil_image is None:
            return

        # Get the size of the label to determine display area
        display_width = self.image_label.width()
        display_height = self.image_label.height()

        img = self.current_pil_image.copy()

        if self.fit_to_window:
            # Fit image to the display area while preserving aspect ratio
            img.thumbnail((display_width - 10, display_height - 10), Image.Resampling.LANCZOS)
        else:
            # Apply zoom factor
            new_width = int(img.width * self.zoom_factor)
            new_height = int(img.height * self.zoom_factor)
            if new_width > 0 and new_height > 0:
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Convert PIL image to QPixmap and set it to the label
        qimage = PIL.ImageQt.ImageQt(img)
        pixmap = QPixmap.fromImage(qimage)
        self.image_label.setPixmap(pixmap)
        self.image_label.setAlignment(Qt.AlignCenter)