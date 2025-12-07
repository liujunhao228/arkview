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
        toolbar.addAction(reset_zoom_action)
        
    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        # Enable key events
        self.setFocusPolicy(Qt.StrongFocus)
        
    def _load_current_image(self):
        """Load the current image."""
        if not self.image_members or self.current_index < 0 or self.current_index >= len(self.image_members):
            return
            
        member_name = self.image_members[self.current_index]
        self.status_bar.showMessage(f"Loading {member_name}...")
        
        # Determine max load size based on performance mode
        max_load_size = self.config[
            "PERFORMANCE_MAX_VIEWER_LOAD_SIZE" if self.performance_mode 
            else "MAX_VIEWER_LOAD_SIZE"
        ]
        
        # Create cache key
        cache_key = (self.zip_path, member_name, "viewer")
        
        # Load image using image service
        result = self.image_service.load_image_data_async(
            zip_path=self.zip_path,
            member_name=member_name,
            max_load_size=max_load_size,
            target_size=None,  # Load full size for viewer
            cache_key=cache_key,
            performance_mode=self.performance_mode
        )
        
        if result and result.success and result.data:
            self._display_image(result.data)
            self.status_bar.showMessage(
                f"{member_name} | {self.current_index + 1}/{len(self.image_members)}")
        else:
            error_msg = result.error_message if result else "Unknown error"
            self.status_bar.showMessage(f"Failed to load {member_name}: {error_msg}")
            
    def _display_image(self, image):
        """Display an image in the viewer."""
        from PIL import ImageQt
        
        # Convert PIL Image to QPixmap
        qt_image = ImageQt.ImageQt(image)
        self.pixmap = QPixmap.fromImage(qt_image)
        
        # Reset scale
        self.scale_factor = 1.0
        self._update_display()
        
    def _update_display(self):
        """Update image display with current scale factor."""
        if self.pixmap:
            scaled_pixmap = self.pixmap.scaled(
                self.pixmap.width() * self.scale_factor,
                self.pixmap.height() * self.scale_factor,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)
            self.image_label.resize(scaled_pixmap.size())
            
    def next_image(self):
        """Go to the next image."""
        if self.current_index < len(self.image_members) - 1:
            self.current_index += 1
            self._load_current_image()
            
    def previous_image(self):
        """Go to the previous image."""
        if self.current_index > 0:
            self.current_index -= 1
            self._load_current_image()
            
    def zoom_in(self):
        """Zoom in."""
        if self.scale_factor < self.max_scale:
            self.scale_factor *= self.zoom_factor
            self.scale_factor = min(self.scale_factor, self.max_scale)
            self._update_display()
            
    def zoom_out(self):
        """Zoom out."""
        if self.scale_factor > self.min_scale:
            self.scale_factor /= self.zoom_factor
            self.scale_factor = max(self.scale_factor, self.min_scale)
            self._update_display()
            
    def reset_zoom(self):
        """Reset zoom to fit."""
        self.scale_factor = 1.0
        self._update_display()
        
    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press events."""
        if event.key() == Qt.Key_Right:
            self.next_image()
        elif event.key() == Qt.Key_Left:
            self.previous_image()
        elif event.key() == Qt.Key_Plus or event.key() == Qt.Key_Equal:
            self.zoom_in()
        elif event.key() == Qt.Key_Minus:
            self.zoom_out()
        elif event.key() == Qt.Key_0:
            self.reset_zoom()
        else:
            super().keyPressEvent(event)