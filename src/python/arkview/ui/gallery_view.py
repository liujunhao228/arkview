"""
Gallery view implementation for Arkview UI layer.
"""

import os
import platform
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QFrame, QScrollArea, QGridLayout, QLabel, QSizePolicy,
    QVBoxLayout, QHBoxLayout, QWidget, QScrollBar, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread, Slot, QPropertyAnimation, QEasingCurve, QPoint, QPointF, Property
from PySide6.QtGui import QPixmap, QPalette, QColor, QCursor, QPainter, QRadialGradient
from PIL import Image
import PIL.ImageQt

from ..core.cache import LRUCache
from ..core.file_manager import ZipFileManager
from ..core.models import LoadResult
from ..core import _format_size


class RippleEffect(QWidget):
    """Ripple effect widget for click animations."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self._ripple_radius = 0
        self.ripple_center = QPointF(0, 0)
        self.animation = QPropertyAnimation(self, b"rippleRadius")
        self.animation.setDuration(600)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.finished.connect(self._on_animation_finished)
        
    def rippleRadius(self):
        """Getter for ripple radius property."""
        return self._ripple_radius
        
    def setRippleRadius(self, radius):
        """Setter for ripple radius property."""
        self._ripple_radius = radius
        self.update()
        
    # 定义属性
    rippleRadius = Property(float, rippleRadius, setRippleRadius)
        
    def start_ripple(self, pos: QPointF):
        """Start ripple animation at given position."""
        self.ripple_center = pos
        self.animation.setStartValue(0)
        self.animation.setEndValue(max(self.width(), self.height()) * 1.5)
        self.animation.start()
        
    def _on_animation_finished(self):
        """Handle animation finished."""
        self.hide()
        
    def paintEvent(self, event):
        """Paint ripple effect."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw ripple
        gradient = QRadialGradient(self.ripple_center, self._ripple_radius)
        gradient.setColorAt(0, QColor(26, 115, 232, 50))
        gradient.setColorAt(1, QColor(26, 115, 232, 0))
        
        painter.setBrush(gradient)
        painter.setPen(Qt.NoPen)
        painter.drawRect(self.rect())
        
    def showEvent(self, event):
        """Handle show event."""
        super().showEvent(event)
        self.raise_()
        
    def resizeEvent(self, event):
        """Handle resize event."""
        super().resizeEvent(event)
        # Update animation end value when size changes
        if self.animation.state() == QPropertyAnimation.Running:
            self.animation.setEndValue(max(self.width(), self.height()) * 1.5)


class GalleryCard(QFrame):
    """Individual card for displaying a ZIP file in the gallery."""
    
    def __init__(self, zip_path: str, members: Optional[List[str]], 
                 mod_time: float, file_size: int, image_count: int,
                 on_clicked: Callable, on_double_clicked: Callable):
        super().__init__()
        
        self.zip_path = zip_path
        self.members = members
        self.mod_time = mod_time
        self.file_size = file_size
        self.image_count = image_count
        self.on_clicked = on_clicked
        self.on_double_clicked = on_double_clicked
        
        self.selected = False
        self.thumbnail_pixmap = None
        
        # 初始化透明度动画
        self.opacity_effect = None
        self.animation = None
        
        # 添加涟漪效果
        self.ripple_effect = RippleEffect(self)
        self.ripple_effect.hide()
        
        self._setup_ui()
        self._update_display()
        
        # 添加淡入动画
        self._setup_animation()
        
    def _setup_ui(self):
        """Setup the card UI."""
        self.setFixedSize(220, 300)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setLineWidth(1)
        
        # 添加圆角和阴影效果
        self.setStyleSheet("""
            GalleryCard {
                background-color: white;
                border-radius: 10px;
                border: 1px solid #ddd;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Thumbnail area
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setMinimumSize(200, 200)
        self.thumbnail_label.setMaximumSize(200, 200)
        self.thumbnail_label.setStyleSheet("""
            background-color: #f8f9fa;
            border: 1px solid #eaeaea;
            border-radius: 8px;
        """)
        layout.addWidget(self.thumbnail_label)
        
        # Info area
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        filename = os.path.basename(self.zip_path)
        self.name_label = QLabel(filename)
        self.name_label.setStyleSheet("""
            font-weight: bold; 
            font-size: 13px;
            color: #202124;
        """)
        self.name_label.setWordWrap(True)
        info_layout.addWidget(self.name_label)
        
        details = f"{self.image_count} images | {_format_size(self.file_size)}"
        self.details_label = QLabel(details)
        self.details_label.setStyleSheet("""
            color: #5f6368; 
            font-size: 11px;
        """)
        info_layout.addWidget(self.details_label)
        
        layout.addLayout(info_layout)
        
        # Click handling
        self.mousePressEvent = self._handle_click
        self.mouseDoubleClickEvent = self._handle_double_click
        
    def _setup_animation(self):
        """Setup fade-in animation."""
        # 创建透明度效果
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        
        # 创建动画
        self.animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation.setDuration(300)
        self.animation.setStartValue(0)
        self.animation.setEndValue(1)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.start()
        
    def _update_display(self):
        """Update card display based on current state."""
        if self.selected:
            self.setStyleSheet("""
                GalleryCard {
                    background-color: #e8f0fe;
                    border-radius: 10px;
                    border: 2px solid #1a73e8;
                }
            """)
        else:
            self.setStyleSheet("""
                GalleryCard {
                    background-color: white;
                    border-radius: 10px;
                    border: 1px solid #dadce0;
                }
                GalleryCard:hover {
                    border: 1px solid #1a73e8;
                    background-color: #f8f9fa;
                }
            """)
            
    def enterEvent(self, event):
        """Handle mouse enter event."""
        # 添加鼠标悬停效果
        self.setCursor(QCursor(Qt.PointingHandCursor))
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        """Handle mouse leave event."""
        # 恢复默认光标
        self.setCursor(QCursor(Qt.ArrowCursor))
        super().leaveEvent(event)
        
    def _handle_click(self, event):
        """Handle mouse click event."""
        # 显示涟漪效果
        if event.position():
            self.ripple_effect.setGeometry(self.rect())
            self.ripple_effect.show()
            self.ripple_effect.start_ripple(event.position())
            
        self.on_clicked(self)
        
    def _handle_double_click(self, event):
        """Handle mouse double-click event."""
        self.on_double_clicked(self)
        
    def set_selected(self, selected: bool):
        """Set card selection state."""
        self.selected = selected
        self._update_display()
        
    def set_thumbnail(self, pixmap: QPixmap):
        """Set thumbnail pixmap."""
        self.thumbnail_pixmap = pixmap
        self.thumbnail_label.setText("")  # 清除加载文本
        self.thumbnail_label.setStyleSheet("""
            background-color: #f8f9fa;
            border: 1px solid #eaeaea;
            border-radius: 8px;
        """)
        self.thumbnail_label.setPixmap(pixmap.scaled(
            200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            
    def resizeEvent(self, event):
        """Handle resize event."""
        super().resizeEvent(event)
        # 更新涟漪效果大小
        self.ripple_effect.setGeometry(self.rect())


class GalleryView(QFrame):
    """Gallery view component with mobile-like UX and modern design."""
    
    def __init__(
        self,
        parent: QWidget,
        zip_files: Dict[str, Tuple[Optional[List[str]], float, int, int]],
        app_settings: Dict[str, Any],
        cache: LRUCache,
        zip_manager: ZipFileManager,
        config: Dict[str, Any],
        ensure_members_loaded_func: Callable[[str], Optional[List[str]]],
        on_selection_changed: Callable[[str, List[str], int], None],
        open_viewer_func: Callable[[str, List[str], int], None]
    ):
        super().__init__(parent)
        
        self.zip_files = zip_files
        self.app_settings = app_settings
        self.cache = cache
        self.zip_manager = zip_manager
        self.config = config
        self.ensure_members_loaded = ensure_members_loaded_func
        self.on_selection_changed = on_selection_changed
        self.open_viewer_func = open_viewer_func
        
        # UI state
        self.cards: List[GalleryCard] = []
        self.selected_card: Optional[GalleryCard] = None
        self.card_mapping: Dict[str, GalleryCard] = {}
        
        # Scrolling state
        self.scroll_position = 0
        self.visible_cards = set()
        
        # Setup UI
        self._setup_ui()
        self.populate()
        
    def _setup_ui(self):
        """Setup the gallery view UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Header
        header_layout = QHBoxLayout()
        title_label = QLabel("Comic Archives")
        title_label.setStyleSheet("""
            font-size: 28px; 
            font-weight: 600;
            color: #202124;
        """)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        count_label = QLabel(f"{len(self.zip_files)} archives")
        count_label.setStyleSheet("""
            font-size: 14px; 
            color: #5f6368;
            background-color: #f1f3f4;
            padding: 5px 12px;
            border-radius: 12px;
        """)
        header_layout.addWidget(count_label)
        
        layout.addLayout(header_layout)
        
        # Scroll area for cards
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        
        # 添加滚动条样式
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: #f1f3f4;
                width: 10px;
                border-radius: 5px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #dadce0;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #bcc0c4;
            }
        """)
        
        # Content widget
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background-color: transparent;")
        self.grid_layout = QGridLayout(self.content_widget)
        self.grid_layout.setAlignment(Qt.AlignTop)
        self.grid_layout.setSpacing(25)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_area.setWidget(self.content_widget)
        layout.addWidget(self.scroll_area)
        
        # Connect scroll events
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        
    def populate(self):
        """Populate the gallery with ZIP file cards."""
        # Clear existing cards
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
                
        self.cards.clear()
        self.card_mapping.clear()
        
        # Create cards for each ZIP file
        row, col = 0, 0
        for zip_path, (members, mod_time, file_size, image_count) in self.zip_files.items():
            card = GalleryCard(
                zip_path=zip_path,
                members=members,
                mod_time=mod_time,
                file_size=file_size,
                image_count=image_count,
                on_clicked=self._on_card_clicked,
                on_double_clicked=self._on_card_double_clicked
            )
            
            self.grid_layout.addWidget(card, row, col)
            self.cards.append(card)
            self.card_mapping[zip_path] = card
            
            col += 1
            # 根据窗口宽度动态调整列数
            if col >= self._calculate_columns():
                col = 0
                row += 1
                
        # Trigger thumbnail loading
        QTimer.singleShot(100, self._load_visible_thumbnails)
        
    def _calculate_columns(self) -> int:
        """Calculate number of columns based on available width."""
        if not self.scroll_area:
            return 4  # 默认4列
            
        available_width = self.scroll_area.width() - 20  # 减去滚动条和边距
        # 每个卡片宽220px，间距25px
        column_width = 220 + 25
        columns = max(1, available_width // column_width)
        return min(columns, 6)  # 最多6列
        
    def resizeEvent(self, event):
        """Handle resize events to adjust grid layout."""
        super().resizeEvent(event)
        # 重新布局卡片
        self._rearrange_cards()
        
    def _rearrange_cards(self):
        """Rearrange cards based on current width."""
        # 清除现有布局
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                self.grid_layout.removeWidget(widget)
                
        # 重新添加卡片
        row, col = 0, 0
        columns = self._calculate_columns()
        
        for card in self.cards:
            self.grid_layout.addWidget(card, row, col)
            col += 1
            if col >= columns:
                col = 0
                row += 1
                
        # 触发缩略图加载
        QTimer.singleShot(100, self._load_visible_thumbnails)
        
    def _on_card_clicked(self, card: GalleryCard):
        """Handle card click event."""
        # Deselect previous card
        if self.selected_card and self.selected_card != card:
            self.selected_card.set_selected(False)
            
        # Select new card
        card.set_selected(True)
        self.selected_card = card
        
        # Notify about selection change
        if card.members is not None:
            self.on_selection_changed(card.zip_path, card.members, 0)
            
    def _on_card_double_clicked(self, card: GalleryCard):
        """Handle card double-click event."""
        # Ensure members are loaded
        members = self.ensure_members_loaded(card.zip_path)
        if members:
            self.open_viewer_func(card.zip_path, members, 0)
            
    def _on_scroll_changed(self, value: int):
        """Handle scroll position change."""
        self.scroll_position = value
        # 使用单次定时器避免频繁触发
        if hasattr(self, '_scroll_timer'):
            self._scroll_timer.stop()
        else:
            self._scroll_timer = QTimer()
            self._scroll_timer.setSingleShot(True)
            self._scroll_timer.timeout.connect(self._load_visible_thumbnails)
        self._scroll_timer.start(150)
        
    def _load_visible_thumbnails(self):
        """Load thumbnails for visible cards."""
        if not self.cards:
            return
            
        # Get the visible area
        scroll_area = self.scroll_area
        scroll_value = scroll_area.verticalScrollBar().value()
        viewport_height = scroll_area.viewport().height()
        
        # Calculate which cards are visible
        card_height = 325  # Card height + spacing
        start_index = max(0, scroll_value // card_height - 2)  # Add larger buffer
        visible_count = (viewport_height // card_height) + 4  # Add larger buffer
        end_index = min(len(self.cards), start_index + visible_count)
        
        # Load thumbnails for visible cards
        for i in range(start_index, end_index):
            if i < len(self.cards):
                card = self.cards[i]
                self._load_card_thumbnail(card)
        
    def _load_card_thumbnail(self, card: GalleryCard):
        """Load thumbnail for a specific card."""
        # Skip if already loaded
        if card.thumbnail_pixmap is not None:
            return
            
        # 显示加载指示器
        card.thumbnail_label.setText("Loading...")
        card.thumbnail_label.setStyleSheet("""
            background-color: #f8f9fa;
            border: 1px solid #eaeaea;
            border-radius: 8px;
            color: #5f6368;
            font-size: 12px;
        """)
            
        # Make sure we have members
        if card.members is None:
            members = self.ensure_members_loaded(card.zip_path)
            if members is not None:
                card.members = members
            else:
                card.thumbnail_label.setText("Failed to load")
                return
                
        # Make sure we have at least one image
        if not card.members:
            card.thumbnail_label.setText("No images")
            return
            
        # Get the first image as thumbnail
        first_image = card.members[0]
        cache_key = (card.zip_path, first_image)
        
        # Check cache first
        cached_image = self.cache.get(cache_key)
        if cached_image is not None:
            try:
                qimage = PIL.ImageQt.ImageQt(cached_image)
                pixmap = QPixmap.fromImage(qimage)
                card.set_thumbnail(pixmap)
                return
            except Exception as e:
                print(f"Error converting cached image: {e}")
        
        # Load the image
        try:
            zf = self.zip_manager.get_zipfile(card.zip_path)
            if zf is None:
                card.thumbnail_label.setText("ZIP error")
                return
                
            image_data = zf.read(first_image)
            from io import BytesIO
            with BytesIO(image_data) as image_stream:
                img = Image.open(image_stream)
                img.load()
                
            # Resize for thumbnail
            img.thumbnail((200, 200), Image.Resampling.LANCZOS)
            
            # Cache it
            self.cache.put(cache_key, img)
            
            # Convert to QPixmap and set
            qimage = PIL.ImageQt.ImageQt(img)
            pixmap = QPixmap.fromImage(qimage)
            card.set_thumbnail(pixmap)
        except Exception as e:
            print(f"Error loading thumbnail for {card.zip_path}: {e}")
            # Show error in thumbnail area
            card.thumbnail_label.setText("Load failed")
            card.thumbnail_label.setStyleSheet("""
                background-color: #fce8e6;
                border: 1px solid #fad2cf;
                border-radius: 8px;
                color: #c5221f;
                font-size: 12px;
            """)
        
    def update_performance_mode(self, enabled: bool):
        """Update view for performance mode change."""
        self.app_settings["performance_mode"] = enabled
        # Reload thumbnails with new settings
        QTimer.singleShot(100, self._load_visible_thumbnails)
        
    def refresh_view(self):
        """Refresh the gallery view."""
        self.populate()
