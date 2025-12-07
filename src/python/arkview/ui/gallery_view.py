"""
Gallery view implementation for Arkview UI layer.
Simplified, high-performance design focused on usability over visual effects.
"""

import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QFrame, QScrollArea, QGridLayout, QLabel, QSizePolicy,
    QVBoxLayout, QHBoxLayout, QWidget
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QCursor, QKeyEvent
from PIL import Image
import PIL.ImageQt

from ..core.cache import LRUCache
from ..core.file_manager import ZipFileManager
from ..core.models import LoadResult
from ..core import _format_size


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
        self.size_badge = self._create_badge(_format_size(self.file_size), accent=False)
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
                background-color: #ffffff;
                border: 1px solid #dfe1e5;
                border-radius: 12px;
            }
            QFrame#galleryCard[selected="true"] {
                border: 2px solid #1a73e8;
                background-color: #f5f8ff;
            }
            QFrame#galleryCard:hover {
                border-color: #4c8bf5;
            }
            QFrame#thumbnailContainer {
                background-color: #f5f6f8;
                border-radius: 10px;
            }
            QLabel#cardTitle {
                font-size: 14px;
                font-weight: 600;
                color: #1b1f3b;
            }
            QLabel#metaLabel {
                color: #5f6368;
                font-size: 12px;
            }
            QLabel.metaBadge {
                border-radius: 10px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel.metaBadge[muted="false"] {
                background-color: #e8f0fe;
                color: #174ea6;
            }
            QLabel.metaBadge[muted="true"] {
                background-color: #f1f3f4;
                color: #3c4043;
            }
            QLabel#thumbnailMessage {
                color: #3c4043;
                font-size: 13px;
            }
            QLabel#thumbnailMessage[state="loading"] {
                color: #1a73e8;
            }
            QLabel#thumbnailMessage[state="error"] {
                color: #c5221f;
            }
            QLabel#thumbnailMessage[state="empty"] {
                color: #5f6368;
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
        self.current_columns = 4

        # Scrolling state
        self.scroll_position = 0
        self.visible_cards = set()

        # Enable keyboard focus
        self.setFocusPolicy(Qt.StrongFocus)

        # Setup UI
        self._setup_ui()
        self.populate()
        
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
            color: #202124;
        """)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.count_label = QLabel(f"{len(self.zip_files)} archives")
        self.count_label.setStyleSheet("""
            font-size: 13px;
            color: #3c4043;
            background-color: #eef3ff;
            padding: 4px 10px;
            border-radius: 10px;
        """)
        header_layout.addWidget(self.count_label)
        layout.addLayout(header_layout)

        hint_label = QLabel("Arrow keys navigate • Enter opens • Esc clears selection")
        hint_label.setStyleSheet("""
            color: #5f6368;
            font-size: 12px;
        """)
        layout.addWidget(hint_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; }
            QScrollBar:vertical {
                border: none;
                background: #f4f5f7;
                width: 10px;
                border-radius: 5px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #c7ccd1;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #aeb4bb;
            }
        """)

        self.content_widget = QWidget()
        self.grid_layout = QGridLayout(self.content_widget)
        self.grid_layout.setAlignment(Qt.AlignTop)
        self.grid_layout.setHorizontalSpacing(20)
        self.grid_layout.setVerticalSpacing(25)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area.setWidget(self.content_widget)
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

        columns = self._calculate_columns()
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
            if col >= columns:
                col = 0
                row += 1

        self.current_columns = columns
        self.count_label.setText(f"{len(self.zip_files)} archives")
        QTimer.singleShot(100, self._load_visible_thumbnails)
        self.setFocus(Qt.OtherFocusReason)
        
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
        
        spacing = (self.grid_layout.verticalSpacing() or 20)
        card_height = (self.cards[0].height() if self.cards else 300) + spacing
        card_height = max(card_height, 200)
        start_index = max(0, scroll_value // card_height - 1)
        visible_count = (viewport_height // card_height) + 3
        end_index = min(len(self.cards), start_index + visible_count)

        for i in range(start_index, end_index):
            if i < len(self.cards):
                card = self.cards[i]
                self._load_card_thumbnail(card)
        
    def _load_card_thumbnail(self, card: GalleryCard):
        """Load thumbnail for a specific card with improved error handling."""
        if card.thumbnail_pixmap is not None:
            return

        card.show_loading_state()

        if card.members is None:
            members = self.ensure_members_loaded(card.zip_path)
            if members is not None:
                card.members = members
            else:
                card.show_error_state("Failed to open")
                return

        if not card.members:
            card.show_empty_state()
            return

        first_image = card.members[0]
        cache_key = (card.zip_path, first_image)

        cached_image = self.cache.get(cache_key)
        if cached_image is not None:
            try:
                qimage = PIL.ImageQt.ImageQt(cached_image)
                pixmap = QPixmap.fromImage(qimage)
                card.set_thumbnail(pixmap)
                return
            except Exception as e:
                print(f"Error converting cached image: {e}")

        try:
            zf = self.zip_manager.get_zipfile(card.zip_path)
            if zf is None:
                card.show_error_state("ZIP error")
                return

            image_data = zf.read(first_image)
            from io import BytesIO
            with BytesIO(image_data) as image_stream:
                img = Image.open(image_stream)
                img.load()

            img.thumbnail((210, 210), Image.Resampling.LANCZOS)
            self.cache.put(cache_key, img)

            qimage = PIL.ImageQt.ImageQt(img)
            pixmap = QPixmap.fromImage(qimage)
            card.set_thumbnail(pixmap)
        except Exception as e:
            print(f"Error loading thumbnail for {card.zip_path}: {e}")
            card.show_error_state()

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard shortcuts for navigation."""
        key = event.key()

        if key == Qt.Key_Escape:
            self._clear_selection()
        elif key == Qt.Key_Return or key == Qt.Key_Enter:
            self._open_selected()
        elif key in (Qt.Key_Left, Qt.Key_A):
            self._navigate_card(-1)
        elif key in (Qt.Key_Right, Qt.Key_D):
            self._navigate_card(1)
        elif key in (Qt.Key_Up, Qt.Key_W):
            self._navigate_card(-self.current_columns)
        elif key in (Qt.Key_Down, Qt.Key_S):
            self._navigate_card(self.current_columns)
        elif key == Qt.Key_Home:
            self._navigate_to_first()
        elif key == Qt.Key_End:
            self._navigate_to_last()
        else:
            super().keyPressEvent(event)

    def _clear_selection(self):
        """Clear current selection."""
        if self.selected_card:
            self.selected_card.set_selected(False)
            self.selected_card = None
            self.on_selection_changed("", [], 0)

    def _open_selected(self):
        """Open viewer for selected card."""
        if self.selected_card:
            self._on_card_double_clicked(self.selected_card)

    def _navigate_card(self, delta: int):
        """Navigate to adjacent card."""
        if not self.cards:
            return

        if self.selected_card is None:
            target_card = self.cards[0]
        else:
            try:
                current_index = self.cards.index(self.selected_card)
                target_index = max(0, min(len(self.cards) - 1, current_index + delta))
                target_card = self.cards[target_index]
            except ValueError:
                target_card = self.cards[0]

        self._on_card_clicked(target_card)
        self._ensure_card_visible(target_card)

    def _navigate_to_first(self):
        """Navigate to first card."""
        if self.cards:
            self._on_card_clicked(self.cards[0])
            self._ensure_card_visible(self.cards[0])

    def _navigate_to_last(self):
        """Navigate to last card."""
        if self.cards:
            self._on_card_clicked(self.cards[-1])
            self._ensure_card_visible(self.cards[-1])

    def _ensure_card_visible(self, card: GalleryCard):
        """Ensure the given card is visible in the scroll area."""
        self.scroll_area.ensureWidgetVisible(card, 50, 50)

    def update_performance_mode(self, enabled: bool):
        """Update view for performance mode change."""
        self.app_settings["performance_mode"] = enabled
        QTimer.singleShot(100, self._load_visible_thumbnails)

    def refresh_view(self):
        """Refresh the gallery view."""
        self.populate()

