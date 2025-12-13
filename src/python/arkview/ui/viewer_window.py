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
from PySide6.QtGui import QPixmap, QAction, QKeySequence, QKeyEvent, QWheelEvent

from ..core.cache_keys import ImageCacheKind, make_image_cache_key
from ..core.file_manager import ZipFileManager
from ..core.models import LoadResult
from ..services.image_service import ImageService
from PIL import Image
import PIL.ImageQt


class ImageViewerWindow(QMainWindow):
    """Window for viewing images from a ZIP archive."""
    
    def __init__(
        self,
        image_service: ImageService,
        parent=None
    ):
        super().__init__(parent)
        
        self.image_service = image_service
        self.current_pixmap: Optional[QPixmap] = None
        self.scale_factor = 1.0
        self.min_scale = 0.1
        self.max_scale = 10.0
        self.zoom_factor = 1.2
        self.auto_fit = True  # 默认启用自动适应窗口大小
        self.performance_mode = False
        
        # Image state
        self.current_zip_path: Optional[str] = None
        self.image_members: List[str] = []
        self.current_index = 0
        
        self._setup_ui()
        self._setup_toolbar()
        self._setup_shortcuts()
        self._apply_dark_theme()
        
    def _setup_ui(self):
        """Setup the main UI components."""
        self.setWindowTitle("Image Viewer")
        self.setGeometry(100, 100, 800, 600)
        
        # Central scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setWidgetResizable(True)
        self.setCentralWidget(self.scroll_area)
        
        # Image label
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image_label.setMouseTracking(True)
        self.scroll_area.setWidget(self.image_label)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
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
        
        # Auto fit
        self.auto_fit_action = QAction("Auto Fit", self)
        self.auto_fit_action.setCheckable(True)
        self.auto_fit_action.setChecked(True)
        self.auto_fit_action.toggled.connect(self.toggle_auto_fit)
        toolbar.addAction(self.auto_fit_action)
        
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
            target_size = None
            cache_key = make_image_cache_key(self.current_zip_path, member_name, ImageCacheKind.ORIGINAL)

            result = self.image_service.load_image_data_async(
                self.current_zip_path,
                member_name,
                100 * 1024 * 1024,  # max_load_size
                target_size,
                cache_key,
                self.performance_mode
            )
            
            if result and result.success:
                self._on_image_loaded(result)
                # 预加载相邻图片
                self._preload_neighbor_images()
            elif result:
                self.status_bar.showMessage(f"Error: {result.error_message}")
        except Exception as e:
            self.status_bar.showMessage(f"Error loading image: {str(e)}")
            
    def _preload_neighbor_images(self):
        """预加载相邻图片"""
        if not self.image_members or not self.current_zip_path:
            return
            
        try:
            # 使用图像服务预加载相邻图片
            neighbor_count = 2 if not self.performance_mode else 1
            target_size = None  # 预加载全尺寸图像
            
            # 这里我们只预加载下一张图片以提高性能
            if self.current_index + 1 < len(self.image_members):
                next_member = self.image_members[self.current_index + 1]
                cache_key = make_image_cache_key(self.current_zip_path, next_member, ImageCacheKind.ORIGINAL)

                # 检查是否已在缓存中
                cached_image = self.image_service.cache_service.get(cache_key)
                if cached_image is None:
                    # 异步预加载下一张图片
                    self.image_service.load_image_data_async(
                        self.current_zip_path,
                        next_member,
                        100 * 1024 * 1024,  # max_load_size
                        target_size,
                        cache_key,
                        self.performance_mode
                    )
        except Exception as e:
            print(f"预加载图片时出错: {e}")
            
    def populate(self, zip_path: str, members: List[str], index: int = 0):
        """Populate the viewer with images from a ZIP file."""
        self.current_zip_path = zip_path
        self.image_members = members
        self.current_index = index
        self.setWindowTitle(f"Image Viewer - {os.path.basename(zip_path)}")
        self._load_current_image()
        
    def _on_image_loaded(self, result: LoadResult):
        """Handle loaded image result."""
        if result.success and result.data:
            try:
                from PIL import ImageQt
                qimage = ImageQt.ImageQt(result.data)
                self.current_pixmap = QPixmap.fromImage(qimage)
                self._update_display()
                self.status_bar.showMessage(
                    f"Loaded {self.current_index + 1}/{len(self.image_members)} - "
                    f"{result.data.width}x{result.data.height}"
                )
            except Exception as e:
                self.status_bar.showMessage(f"Error displaying image: {str(e)}")
        else:
            self.status_bar.showMessage(f"Error: {result.error_message if result else 'Unknown error'}")
            
    def _update_display(self):
        """Update the image display based on current scale and auto-fit settings."""
        if not self.current_pixmap:
            return
            
        if self.auto_fit:
            # 自动适应窗口大小
            self.image_label.setPixmap(self.current_pixmap.scaled(
                self.scroll_area.viewport().size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            ))
        else:
            # 按照当前缩放比例显示
            scaled_pixmap = self.current_pixmap.scaled(
                self.current_pixmap.size() * self.scale_factor,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)
            
        # 更新标签大小以匹配图像
        self.image_label.resize(self.image_label.pixmap().size())
            
    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel events for zooming."""
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()
            
    def _fit_image_to_window(self):
        """Scale the image to fit the window size."""
        if not self.current_pixmap:
            return
            
        # 获取可用空间（减去一些边距）
        available_width = self.scroll_area.viewport().width() - 20
        available_height = self.scroll_area.viewport().height() - 20
        
        # 计算缩放比例
        pixmap_width = self.current_pixmap.width()
        pixmap_height = self.current_pixmap.height()
        
        scale_x = available_width / pixmap_width
        scale_y = available_height / pixmap_height
        fit_scale = min(scale_x, scale_y)
        
        # 应用缩放
        scaled_pixmap = self.current_pixmap.scaled(
            pixmap_width * fit_scale,
            pixmap_height * fit_scale,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation if not self.performance_mode else Qt.FastTransformation
        )
        
        self.image_label.setPixmap(scaled_pixmap)
        self.image_label.resize(scaled_pixmap.size())
        self.scale_factor = fit_scale
        
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
        if self.current_pixmap:
            self.auto_fit = False
            self.auto_fit_action.setChecked(False)
            self.scale_factor = min(self.scale_factor * self.zoom_factor, self.max_scale)
            self._update_display()
            self.status_bar.showMessage(f"Zoom: {self.scale_factor:.1f}x")
            
    def zoom_out(self):
        """Zoom out on the image."""
        if self.current_pixmap:
            self.auto_fit = False
            self.auto_fit_action.setChecked(False)
            self.scale_factor = max(self.scale_factor / self.zoom_factor, self.min_scale)
            self._update_display()
            self.status_bar.showMessage(f"Zoom: {self.scale_factor:.1f}x")
            
    def reset_zoom(self):
        """Reset image zoom."""
        if self.current_pixmap:
            self.auto_fit = True
            self.auto_fit_action.setChecked(True)
            self._update_display()
            self.status_bar.showMessage("Zoom reset")
            
    def toggle_auto_fit(self, enabled):
        """Toggle auto fit mode."""
        self.auto_fit = enabled
        self._update_display()
        if enabled:
            self.status_bar.showMessage("Auto fit enabled")
        else:
            self.status_bar.showMessage("Auto fit disabled")
            
    def toggle_performance_mode(self, enabled):
        """Toggle performance mode."""
        self.performance_mode = enabled
        self._load_current_image()
        
    def resizeEvent(self, event):
        """Handle window resize events."""
        super().resizeEvent(event)
        if self.auto_fit and self.current_pixmap:
            self._update_display()