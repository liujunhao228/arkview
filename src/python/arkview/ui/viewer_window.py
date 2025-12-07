"""
Viewer window implementation for Arkview UI layer.
"""

from typing import List, Optional
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QLabel, QScrollArea, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QToolBar, QSizePolicy, QStatusBar
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QPixmap, QAction, QKeySequence, QKeyEvent

from ..core.file_manager import ZipFileManager
from ..core.models import LoadResult
from ..services.image_service import ImageService
from PIL import Image
import PIL.ImageQt


class ImageViewerWindow(QMainWindow):
    """Window for viewing images from a ZIP archive."""
    
    def __init__(
        self,
        zip_path: str,
        image_members: List[str],
        initial_index: int,
        image_service: ImageService,
        zip_manager: ZipFileManager,
        config: dict,
        performance_mode: bool,
        parent=None
    ):
        super().__init__(parent)
        
        self.zip_path = zip_path
        self.image_members = image_members
        self.current_index = initial_index
        self.image_service = image_service
        self.zip_manager = zip_manager
        self.config = config
        self.performance_mode = performance_mode
        
        self.pixmap = None
        self.scale_factor = 1.0
        self.min_scale = config["VIEWER_MIN_ZOOM"]
        self.max_scale = config["VIEWER_MAX_ZOOM"]
        self.zoom_factor = config["VIEWER_ZOOM_FACTOR"]
        
        self._setup_ui()
        self._load_current_image()
        self._apply_dark_theme()
        
    def _setup_ui(self):
        """Setup the viewer UI."""
        self.setWindowTitle(f"Arkview Viewer - {Path(self.zip_path).name}")
        self.resize(800, 600)
        
        # Central scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setWidgetResizable(True)
        
        # Image label
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image_label.setScaledContents(False)
        
        self.scroll_area.setWidget(self.image_label)
        self.setCentralWidget(self.scroll_area)
        
        # Toolbar
        self._setup_toolbar()
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Keyboard shortcuts
        self._setup_shortcuts()
        
    def _apply_dark_theme(self):
        """Apply dark theme to the viewer window."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
            }
            QToolBar {
                background-color: #3c3f41;
                border: none;
            }
            QToolBar QToolButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 4px;
                color: #bbbbbb;
            }
            QToolBar QToolButton:hover {
                background-color: #4b6eaf;
                border: 1px solid #555555;
            }
            QToolBar QToolButton:pressed {
                background-color: #3a588c;
            }
            QStatusBar {
                background-color: #3c3f41;
                color: #bbbbbb;
                border-top: 1px solid #555555;
            }
            QLabel {
                background-color: #2b2b2b;
                color: #e0e0e0;
            }
        """)
        
    def _setup_toolbar(self):
        """Setup the viewer toolbar."""
        toolbar = QToolBar("Viewer")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # Previous image
        prev_action = QAction("Previous", self)
        prev_action.triggered.connect(self.previous_image)
        prev_action.setShortcut(QKeySequence.MoveToPreviousChar)
        toolbar.addAction(prev_action)
        
        # Next image
        next_action = QAction("Next", self)
        next_action.triggered.connect(self.next_image)
        next_action.setShortcut(QKeySequence.MoveToNextChar)
        toolbar.addAction(next_action)
        
        toolbar.addSeparator()
        
        # Zoom in
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.triggered.connect(self.zoom_in)
        zoom_in_action.setShortcut(QKeySequence.ZoomIn)
        toolbar.addAction(zoom_in_action)
        
        # Zoom out
        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.triggered.connect(self.zoom_out)
        zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        toolbar.addAction(zoom_out_action)
        
        # Reset zoom
        reset_zoom_action = QAction("Reset Zoom", self)
        reset_zoom_action.triggered.connect(self.reset_zoom)
        reset_zoom_action.setShortcut(QKeySequence("Ctrl+0"))
        toolbar.addAction(reset_zoom_action)
        
        toolbar.addSeparator()
        
        # Performance mode toggle
        self.performance_action = QAction("Performance Mode", self)
        self.performance_action.setCheckable(True)
        self.performance_action.setChecked(self.performance_mode)
        self.performance_action.toggled.connect(self.toggle_performance_mode)
        toolbar.addAction(self.performance_action)
        
    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        self.esc_shortcut = QAction(self)
        self.esc_shortcut.setShortcut(QKeySequence("Esc"))
        self.esc_shortcut.triggered.connect(self.close)
        self.addAction(self.esc_shortcut)
        
    def _load_current_image(self):
        """Load the current image."""
        if not self.image_members or self.current_index < 0 or self.current_index >= len(self.image_members):
            self.status_bar.showMessage("No image to display")
            return
            
        member_name = self.image_members[self.current_index]
        self.status_bar.showMessage(f"Loading {member_name}...")
        
        try:
            # 修复：将target_size设为None，这样就不会加载缩略图而是完整图像
            result = self.image_service.load_image_data_async(
                self.zip_path, member_name, 32 * 1024 * 1024, None, 
                (self.zip_path, member_name), self.performance_mode
            )
            
            if result.success and result.data:
                self.display_image(result.data)
                self.status_bar.showMessage(
                    f"{member_name} ({result.data.width}×{result.data.height}) "
                    f"[{ 'Performance' if self.performance_mode else 'Quality' } mode]"
                )
            else:
                self.status_bar.showMessage(f"Failed to load {member_name}")
        except Exception as e:
            self.status_bar.showMessage(f"Error loading {member_name}: {str(e)}")
            
    def display_image(self, image):
        """Display a PIL Image."""
        try:
            # Convert PIL Image to QPixmap
            qt_image = PIL.ImageQt.ImageQt(image)
            self.pixmap = QPixmap.fromImage(qt_image)
            
            # Reset scale factor
            self.scale_factor = 1.0
            
            # Display the image
            self._update_image_display()
        except Exception as e:
            self.status_bar.showMessage(f"Error displaying image: {str(e)}")
            
    def _update_image_display(self):
        """Update the image display with current scale."""
        if self.pixmap:
            scaled_pixmap = self.pixmap.scaled(
                self.pixmap.width() * self.scale_factor,
                self.pixmap.height() * self.scale_factor,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation if not self.performance_mode else Qt.FastTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)
            self.image_label.resize(scaled_pixmap.size())
            
    def next_image(self):
        """Go to the next image."""
        if self.image_members and self.current_index < len(self.image_members) - 1:
            self.current_index += 1
            self._load_current_image()
            
    def previous_image(self):
        """Go to the previous image."""
        if self.image_members and self.current_index > 0:
            self.current_index -= 1
            self._load_current_image()
            
    def zoom_in(self):
        """Zoom in on the image."""
        if self.pixmap:
            self.scale_factor = min(self.scale_factor * self.zoom_factor, self.max_scale)
            self._update_image_display()
            self.status_bar.showMessage(f"Zoom: {self.scale_factor:.1f}x")
            
    def zoom_out(self):
        """Zoom out on the image."""
        if self.pixmap:
            self.scale_factor = max(self.scale_factor / self.zoom_factor, self.min_scale)
            self._update_image_display()
            self.status_bar.showMessage(f"Zoom: {self.scale_factor:.1f}x")
            
    def reset_zoom(self):
        """Reset image zoom."""
        if self.pixmap:
            self.scale_factor = 1.0
            self._update_image_display()
            self.status_bar.showMessage("Zoom reset")
            
    def toggle_performance_mode(self, enabled):
        """Toggle performance mode."""
        self.performance_mode = enabled
        self._load_current_image()
        
    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press events."""
        if event.key() == Qt.Key_Right:
            self.next_image()
        elif event.key() == Qt.Key_Left:
            self.previous_image()
        elif event.key() == Qt.Key_Space:
            self.next_image()
        elif event.key() == Qt.Key_PageDown:
            self.next_image()
        elif event.key() == Qt.Key_PageUp:
            self.previous_image()
        else:
            super().keyPressEvent(event)