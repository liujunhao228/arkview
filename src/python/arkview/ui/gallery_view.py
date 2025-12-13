"""
Gallery view implementation for Arkview UI layer.
Simplified, high-performance design focused on usability over visual effects.
"""

import os
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QSize, QTimer, Signal, Slot
from PySide6.QtGui import QPixmap, QKeyEvent

# 从Rust部分导入format_size函数
from ..arkview_core import format_size
from PIL import ImageQt


class GalleryCard(QFrame):
    """Lightweight card optimized for clarity and performance."""

    CARD_MIN_WIDTH = 190
    CARD_MAX_WIDTH = 280
    THUMBNAIL_HEIGHT = 190

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

        self.setObjectName("galleryCard")
        self.setProperty("selected", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumWidth(self.CARD_MIN_WIDTH)
        self.setMaximumWidth(self.CARD_MAX_WIDTH)
        self.setFixedHeight(300)

        self._setup_ui()
        self._apply_styles()
        self.show_loading_state()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        self.thumbnail_container = QFrame()
        self.thumbnail_container.setObjectName("thumbnailContainer")
        self.thumbnail_container.setMinimumHeight(self.THUMBNAIL_HEIGHT)
        self.thumbnail_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        thumbnail_layout = QVBoxLayout(self.thumbnail_container)
        thumbnail_layout.setContentsMargins(6, 6, 6, 6)
        thumbnail_layout.setSpacing(4)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setObjectName("thumbnailMessage")
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setWordWrap(True)
        thumbnail_layout.addWidget(self.thumbnail_label, alignment=Qt.AlignCenter)

        self.thumbnail_pixmap_label = QLabel()
        self.thumbnail_pixmap_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_pixmap_label.hide()
        thumbnail_layout.addWidget(self.thumbnail_pixmap_label)

        layout.addWidget(self.thumbnail_container)

        filename = os.path.basename(self.zip_path)
        self.name_label = QLabel(filename)
        self.name_label.setObjectName("cardTitle")
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)
        self.images_badge = self._create_badge(f"{self.image_count} images", accent=True)
        self.size_badge = self._create_badge(format_size(self.file_size), accent=False)
        badge_row.addWidget(self.images_badge)
        badge_row.addWidget(self.size_badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)

        self.meta_label = QLabel(self._format_metadata())
        self.meta_label.setObjectName("metaLabel")
        layout.addWidget(self.meta_label)
        layout.addStretch()

    def _apply_styles(self):
        self.setStyleSheet("""
            QFrame#galleryCard {
                background-color: #3c3f41;
                border: 1px solid #555555;
                border-radius: 12px;
            }
            QFrame#galleryCard[selected="true"] {
                border: 2px solid #4b6eaf;
                background-color: #45494a;
            }
            QFrame#galleryCard:hover {
                border-color: #4b6eaf;
            }
            QFrame#thumbnailContainer {
                background-color: #2b2b2b;
                border-radius: 10px;
            }
            QLabel#cardTitle {
                font-size: 14px;
                font-weight: 600;
                color: #e0e0e0;
            }
            QLabel#metaLabel {
                color: #bbbbbb;
                font-size: 12px;
            }
            QLabel.metaBadge {
                border-radius: 10px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel.metaBadge[muted="false"] {
                background-color: #4b6eaf;
                color: #ffffff;
            }
            QLabel.metaBadge[muted="true"] {
                background-color: #5a5d5e;
                color: #e0e0e0;
            }
            QLabel#thumbnailMessage {
                color: #e0e0e0;
                font-size: 13px;
            }
            QLabel#thumbnailMessage[state="loading"] {
                color: #4b6eaf;
            }
            QLabel#thumbnailMessage[state="error"] {
                color: #f2545b;
            }
            QLabel#thumbnailMessage[state="empty"] {
                color: #bbbbbb;
            }
        """)

    def _refresh_style(self, target: Optional[QWidget] = None):
        widget = target or self
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _create_badge(self, text: str, accent: bool) -> QLabel:
        badge = QLabel(text)
        badge.setObjectName("metaBadge")
        badge.setProperty("muted", "false" if accent else "true")
        badge.setAlignment(Qt.AlignCenter)
        return badge

    def _format_metadata(self) -> str:
        try:
            dt = datetime.fromtimestamp(self.mod_time)
            return f"Updated {dt.strftime('%Y-%m-%d %H:%M')}"
        except Exception:
            return "Updated recently"

    def _set_message(self, icon: str, text: str, state: str):
        self.thumbnail_label.setText(f"{icon}\n{text}")
        self.thumbnail_label.setProperty("state", state)
        self.thumbnail_label.show()
        self.thumbnail_pixmap_label.hide()
        self.thumbnail_pixmap_label.clear()
        self.thumbnail_pixmap = None
        self._refresh_style(self.thumbnail_label)

    def show_loading_state(self):
        self._set_message("⏳", "Loading preview…", "loading")

    def show_error_state(self, text: str = "Preview failed"):
        # 限制错误文本长度以避免界面混乱
        if len(text) > 100:
            text = text[:97] + "..."
        self._set_message("⚠️", text, "error")

    def show_empty_state(self):
        self._set_message("📭", "No images", "empty")

    def set_selected(self, selected: bool):
        self.selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self._refresh_style()

    def set_thumbnail(self, pixmap: QPixmap):
        self.thumbnail_pixmap = pixmap
        scaled = pixmap.scaled(204, self.THUMBNAIL_HEIGHT - 6,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumbnail_pixmap_label.setPixmap(scaled)
        self.thumbnail_pixmap_label.show()
        self.thumbnail_label.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_clicked(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_double_clicked(self)
        super().mouseDoubleClickEvent(event)


class GalleryView(QFrame):
    """Simplified, high-performance gallery view with comprehensive keyboard support."""

    coverThumbnailJobFinished = Signal(object, object, str)  # cache_key, qimage, error

    def __init__(
        self,
        parent: QWidget,
        zip_files: Dict[str, Tuple[Optional[List[str]], float, int, int]],
        app_settings: Dict[str, Any],
        thumbnail_service,  # ThumbnailService
        config: Dict[str, Any],
        ensure_members_loaded_func: Callable[[str], Optional[List[str]]],
        on_selection_changed: Callable[[str, List[str], int], None],
        open_viewer_func: Callable[[str, List[str], int], None]
    ):
        super().__init__(parent)

        self.zip_files = zip_files
        self.app_settings = app_settings
        self.thumbnail_service = thumbnail_service
        self.config = config
        self.ensure_members_loaded = ensure_members_loaded_func
        self.on_selection_changed = on_selection_changed
        self.open_viewer_func = open_viewer_func

        # UI state
        self.cards: List[GalleryCard] = []
        self.selected_card: Optional[GalleryCard] = None
        self.card_mapping: Dict[str, GalleryCard] = {}
        self.current_columns = 4
        
        # Thumbnail loading state
        self._cover_thumb_queue = deque()
        self._cover_thumb_pending = set()
        self._cover_thumb_inflight = set()

        # Scrolling state
        self.scroll_position = 0
        self.visible_cards = set()

        # Enable keyboard focus
        self.setFocusPolicy(Qt.StrongFocus)

        # Setup UI
        self._setup_ui()
        self.populate()
        
        # Connect thumbnail service signal
        self.thumbnail_service.thumbnailLoaded.connect(self._on_thumbnail_loaded)
        
    def _setup_ui(self):
        """Setup the gallery view UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header_layout = QHBoxLayout()
        self.title_label = QLabel("Archive library")
        self.title_label.setStyleSheet("""
            font-size: 24px;
            font-weight: 600;
            color: #e0e0e0;
        """)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.count_label = QLabel(f"{len(self.zip_files)} archives")
        self.count_label.setStyleSheet("""
            font-size: 13px;
            color: #e0e0e0;
            background-color: #4b6eaf;
            padding: 4px 10px;
            border-radius: 10px;
        """)
        header_layout.addWidget(self.count_label)
        layout.addLayout(header_layout)

        hint_label = QLabel("Arrow keys navigate • Enter opens • Esc clears selection")
        hint_label.setStyleSheet("""
            color: #bbbbbb;
            font-size: 12px;
        """)
        layout.addWidget(hint_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollArea > QWidget {
                background-color: transparent;
            }
        """)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.grid_widget = QWidget()
        self.grid_widget.setObjectName("gridWidget")
        self.grid_widget.setStyleSheet("""
            QWidget#gridWidget {
                background-color: #2b2b2b;
            }
        """)
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(16)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_area.setWidget(self.grid_widget)
        layout.addWidget(self.scroll_area)
        
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        
    def populate(self):
        """Populate the gallery with ZIP file cards."""
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        self.cards.clear()
        self.card_mapping.clear()
        self._cover_thumb_queue.clear()
        self._cover_thumb_pending.clear()
        self._cover_thumb_inflight.clear()

        columns = self._calculate_columns()
        row, col = 0, 0
        for zip_path, (members, mod_time, file_size, image_count) in self.zip_files.items():
            zip_path_abs = os.path.abspath(zip_path)
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
            # Use absolute path for internal lookups (cache keys normalize paths).
            self.card_mapping[zip_path_abs] = card

            col += 1
            if col >= columns:
                col = 0
                row += 1

        self.current_columns = columns
        self.count_label.setText(f"{len(self.zip_files)} archives")
        
        # Load thumbnails for visible cards to improve initial experience
        self._preload_first_thumbnails()
        
        # Schedule visible thumbnails loading after UI is fully rendered
        QTimer.singleShot(100, self._load_visible_thumbnails)
        self.setFocus(Qt.OtherFocusReason)
        
    def _adjust_cache_size(self):
        """This method is no longer needed as cache management is handled by the thumbnail service."""
        pass
        
    def _preload_first_thumbnails(self):
        """Preload thumbnails for visible cards to improve initial experience."""
        # Calculate visible cards based on current columns and rows
        visible_rows = max(2, self.height() // 300 + 1)  # Assume ~300px card height
        visible_count = min(self.current_columns * visible_rows, len(self.cards))
        
        # Preload visible cards with high priority
        for i in range(min(visible_count, len(self.cards))):
            card = self.cards[i]
            self._request_cover_thumbnail(card, priority=True)
        
        # Preload a few extra cards with lower priority
        buffer_count = min(5, len(self.cards) - visible_count)
        for i in range(visible_count, visible_count + buffer_count):
            card = self.cards[i]
            self._request_cover_thumbnail(card, priority=False)
        
    def _calculate_columns(self) -> int:
        """Calculate number of columns with improved responsive behavior."""
        if not self.scroll_area:
            return 4

        viewport_width = self.scroll_area.viewport().width()
        min_card_width = GalleryCard.CARD_MIN_WIDTH
        max_card_width = GalleryCard.CARD_MAX_WIDTH
        spacing = 20

        # Consider available space with margins
        available_width = max(320, viewport_width - 40)

        # Calculate reasonable column count
        min_columns = max(1, available_width // (max_card_width + spacing))
        max_columns = min(6, available_width // (min_card_width + spacing))
        optimal = max(1, available_width // (230 + spacing))

        columns = max(min_columns, min(max_columns, optimal))
        return columns

    def resizeEvent(self, event):
        """Handle resize events to adjust grid layout."""
        super().resizeEvent(event)
        new_columns = self._calculate_columns()
        if new_columns != self.current_columns:
            self._rearrange_cards()

    def _rearrange_cards(self):
        """Rearrange cards based on current width."""
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                self.grid_layout.removeWidget(widget)

        columns = self._calculate_columns()
        row, col = 0, 0

        for card in self.cards:
            self.grid_layout.addWidget(card, row, col)
            col += 1
            if col >= columns:
                col = 0
                row += 1

        self.current_columns = columns
        self._adjust_cache_size()
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
        """Load thumbnails for visible cards with buffer zone."""
        if not self.cards:
            return
            
        # Get the visible area
        scroll_area = self.scroll_area
        scroll_value = scroll_area.verticalScrollBar().value()
        viewport_height = scroll_area.viewport().height()
        
        spacing = (self.grid_layout.verticalSpacing() or 20)
        card_height = (self.cards[0].height() if self.cards else 300) + spacing
        card_height = max(card_height, 200)
        
        # Calculate visible range with buffer zone
        buffer_zone = 2  # Number of extra rows to preload
        start_index = max(0, (scroll_value // card_height) - buffer_zone * self.current_columns)
        visible_rows = (viewport_height // card_height) + 1
        visible_count = (visible_rows + buffer_zone * 2) * self.current_columns
        end_index = min(len(self.cards), start_index + visible_count)

        # Load thumbnails with priority for truly visible cards
        visible_start = max(0, scroll_value // card_height)
        visible_end = min(len(self.cards), visible_start + visible_rows * self.current_columns)
        
        for i in range(start_index, end_index):
            if i < len(self.cards):
                card = self.cards[i]
                # Higher priority for actually visible cards
                is_visible = visible_start <= i <= visible_end
                self._request_cover_thumbnail(card, priority=is_visible)
        
    def _request_cover_thumbnail(self, card: GalleryCard, priority: bool = False):
        """Request ZIP cover thumbnail loading."""
        if card.thumbnail_pixmap is not None:
            return

        # Request thumbnail from service
        self.thumbnail_service.request_cover_thumbnail(
            card.zip_path,
            self.config.get("GALLERY_THUMB_SIZE", (220, 220)),
            priority,
            self.app_settings.get('performance_mode', False)
        )

    def _on_thumbnail_loaded(self, result, cache_key):
        """Handle thumbnail loaded event from service."""
        zip_path = cache_key[1] if len(cache_key) > 1 else None
        card = self.card_mapping.get(zip_path)
        if card is None or card.thumbnail_pixmap is not None:
            return

        if not result.success or result.data is None:
            # 显示更详细的错误信息
            error_msg = "Preview failed"
            if hasattr(result, 'error_message') and result.error_message:
                error_msg = result.error_message
            print(f"Thumbnail load failed for {zip_path}: {error_msg}")  # 添加日志输出
            card.show_error_state(error_msg)
            return

        try:
            qimage = ImageQt.ImageQt(result.data)
            card.set_thumbnail(QPixmap.fromImage(qimage))
        except Exception as e:
            error_msg = f"Preview failed: {str(e)}"
            print(f"Error converting image for {zip_path}: {error_msg}")  # 添加日志输出
            card.show_error_state(error_msg)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard shortcuts for navigation."""
        key = event.key()

        if key == Qt.Key_Escape:
            self._clear_selection()
        elif key == Qt.Key_Return or key == Qt.Key_Enter:
            self._open_selected()
        elif key in (Qt.Key_Left, Qt.Key_A):
            if event.modifiers() == Qt.ControlModifier:
                self._navigate_card(-1)
            else:
                self._navigate_card_2d(0, -1)
        elif key in (Qt.Key_Right, Qt.Key_D):
            if event.modifiers() == Qt.ControlModifier:
                self._navigate_card(1)
            else:
                self._navigate_card_2d(0, 1)
        elif key in (Qt.Key_Up, Qt.Key_W):
            self._navigate_card_2d(-1, 0)
        elif key in (Qt.Key_Down, Qt.Key_S):
            self._navigate_card_2d(1, 0)
        elif key == Qt.Key_Home:
            if event.modifiers() == Qt.ControlModifier:
                self._navigate_to_first()
            else:
                super().keyPressEvent(event)
        elif key == Qt.Key_End:
            if event.modifiers() == Qt.ControlModifier:
                self._navigate_to_last()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def _clear_selection(self):
        """Clear current selection."""
        if self.selected_card:
            self.selected_card.set_selected(False)
            self.selected_card = None

    def _navigate_card(self, delta: int):
        """Navigate to another card relative to the currently selected one."""
        if not self.cards:
            return
            
        if self.selected_card is None:
            # 如果没有选中的卡片，则选择第一张
            target_index = 0 if delta >= 0 else len(self.cards) - 1
        else:
            # 计算目标卡片索引
            current_index = self.cards.index(self.selected_card)
            target_index = current_index + delta
            
        # 确保索引在有效范围内
        target_index = max(0, min(len(self.cards) - 1, target_index))
        
        # 选择目标卡片
        target_card = self.cards[target_index]
        self._on_card_clicked(target_card)
        
        # 确保选中的卡片可见
        self._ensure_card_visible(target_card)

    def _navigate_card_2d(self, row_delta: int, col_delta: int):
        """
        Navigate in 2D grid space (for arrow key navigation).
        This provides a more intuitive navigation experience.
        """
        if not self.cards or not self.current_columns:
            return
            
        if self.selected_card is None:
            # 如果没有选中的卡片，则选择第一张
            target_index = 0
        else:
            # 计算当前卡片的行列位置
            current_index = self.cards.index(self.selected_card)
            current_row = current_index // self.current_columns
            current_col = current_index % self.current_columns
            
            # 计算目标行列位置
            target_row = current_row + row_delta
            target_col = current_col + col_delta
            
            # 计算目标索引
            target_index = target_row * self.current_columns + target_col
            
        # 确保索引在有效范围内
        target_index = max(0, min(len(self.cards) - 1, target_index))
        
        # 选择目标卡片
        target_card = self.cards[target_index]
        self._on_card_clicked(target_card)
        
        # 确保选中的卡片可见
        self._ensure_card_visible(target_card)

    def _navigate_to_first(self):
        """Navigate to the first card."""
        if self.cards:
            target_card = self.cards[0]
            self._on_card_clicked(target_card)
            self._ensure_card_visible(target_card)

    def _navigate_to_last(self):
        """Navigate to the last card."""
        if self.cards:
            target_card = self.cards[-1]
            self._on_card_clicked(target_card)
            self._ensure_card_visible(target_card)

    def _ensure_card_visible(self, card: GalleryCard):
        """Ensure that a card is visible in the scroll area."""
        # 获取卡片在网格布局中的位置
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if widget == card:
                # 计算卡片的位置
                card_global_pos = card.mapToGlobal(card.rect().topLeft())
                scroll_area_global_pos = self.scroll_area.mapToGlobal(self.scroll_area.rect().topLeft())
                
                # 计算卡片相对于滚动区域的位置
                card_relative_pos = card_global_pos - scroll_area_global_pos
                card_top = card_relative_pos.y()
                card_bottom = card_top + card.height()
                
                # 获取滚动区域的信息
                scroll_bar = self.scroll_area.verticalScrollBar()
                viewport_height = self.scroll_area.viewport().height()
                
                # 检查卡片是否在可视区域内
                if card_top < 0:
                    # 卡片在可视区域上方，向上滚动
                    scroll_bar.setValue(scroll_bar.value() + card_top - 10)
                elif card_bottom > viewport_height:
                    # 卡片在可视区域下方，向下滚动
                    scroll_bar.setValue(scroll_bar.value() + card_bottom - viewport_height + 10)
                    
                break

    def _open_selected(self):
        """Open the currently selected card."""
        if self.selected_card:
            self._on_card_double_clicked(self.selected_card)