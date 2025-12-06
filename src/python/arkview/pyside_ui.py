"""
PySide UI components for Arkview.
"""

import os
import platform
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QCheckBox, QPushButton, QGroupBox, QGridLayout, QScrollArea,
    QApplication, QMainWindow, QWidget, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer, QThread
from PySide6.QtGui import QPixmap, QPalette, QColor
from PIL import Image
import PIL.ImageQt

from .core import (
    ZipScanner, ZipFileManager, LRUCache, load_image_data_async,
    LoadResult, _format_size
)


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
        result_queue,
        thread_pool,
        zip_manager: ZipFileManager
    ):
        super().__init__(parent)
        self.parent_app = parent
        self.zip_path = zip_path
        self.image_members = image_members
        self.current_index = initial_index
        self.settings = settings
        self.cache = cache
        self.result_queue = result_queue
        self.thread_pool = thread_pool
        self.zip_manager = zip_manager

        self.current_pil_image: Optional[Image.Image] = None
        self.zoom_factor: float = 1.0
        self.fit_to_window: bool = True
        self._is_loading: bool = False
        self._is_fullscreen: bool = False

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
        self.image_label.setStyleSheet("background-color: #1c1e1f;")
        self.image_label.setMinimumSize(400, 300)
        main_layout.addWidget(self.image_label, stretch=1)

        # Status bar at the bottom
        self.status_frame = QFrame()
        self.status_frame.setFixedHeight(25)
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(8, 4, 8, 4)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignLeft)
        self.status_label.setStyleSheet("font-size: 9pt;")
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

        self.thread_pool.submit(
            load_image_data_async,
            self.zip_path,
            self.image_members[index],
            100 * 1024 * 1024,
            None,  # No resizing for viewer
            self.result_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.settings.get('performance_mode', False)
        )

        self._check_load_result()

    def _check_load_result(self):
        try:
            result = self.result_queue.get_nowait()
            if result.success:
                self.current_pil_image = result.data
            else:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Error", f"Failed to load image: {result.error_message}")
            self._is_loading = False
            self._update_display()
        except Exception:
            # Queue is empty, check again later
            if self._is_loading:
                QTimer.singleShot(50, self._check_load_result)

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