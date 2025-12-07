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
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread, Slot
from PySide6.QtGui import QPixmap, QPalette, QColor
from PIL import Image
import PIL.ImageQt

from ..core.cache import LRUCache
from ..core.file_manager import ZipFileManager
from ..core.models import LoadResult
from ..core import _format_size


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
        
        self._setup_ui()
        self._update_display()
        
    def _setup_ui(self):
        """Setup the card UI."""
        self.setFixedWidth(220)
        self.setFixedHeight(300)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setLineWidth(1)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Thumbnail area
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setMinimumSize(200, 200)
        self.thumbnail_label.setMaximumSize(200, 200)
        self.thumbnail_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ddd;")
        layout.addWidget(self.thumbnail_label)
        
        # Info area
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        filename = os.path.basename(self.zip_path)
        self.name_label = QLabel(filename)
        self.name_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.name_label.setWordWrap(True)
        info_layout.addWidget(self.name_label)
        
        details = f"{self.image_count} images | {_format_size(self.file_size)}"
        self.details_label = QLabel(details)
        self.details_label.setStyleSheet("color: #666666; font-size: 10px;")
        info_layout.addWidget(self.details_label)
        
        layout.addLayout(info_layout)
        
        # Click handling
        self.mousePressEvent = self._handle_click
        self.mouseDoubleClickEvent = self._handle_double_click
        
    def _update_display(self):
        """Update card display based on current state."""
        if self.selected:
            self.setStyleSheet("background-color: #e0e0e0; border: 2px solid #0078d4;")
        else:
            self.setStyleSheet("background-color: white; border: 1px solid #ccc;")
            
    def _handle_click(self, event):
        """Handle mouse click event."""
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
        self.thumbnail_label.setPixmap(pixmap.scaled(
            200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))


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
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        title_label = QLabel("Comic Archives")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        count_label = QLabel(f"{len(self.zip_files)} archives")
        count_label.setStyleSheet("font-size: 14px; color: #666;")
        header_layout.addWidget(count_label)
        
        layout.addLayout(header_layout)
        
        # Scroll area for cards
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        
        # Content widget
        self.content_widget = QWidget()
        self.grid_layout = QGridLayout(self.content_widget)
        self.grid_layout.setAlignment(Qt.AlignTop)
        self.grid_layout.setSpacing(15)
        
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
            if col >= 4:  # 4 columns
                col = 0
                row += 1
                
        # Trigger thumbnail loading
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
        QTimer.singleShot(100, self._load_visible_thumbnails)
        
    def _load_visible_thumbnails(self):
        """Load thumbnails for visible cards."""
        # In a full implementation, this would use the thumbnail service
        # to load thumbnails for visible cards
        pass
        
    def update_performance_mode(self, enabled: bool):
        """Update view for performance mode change."""
        self.app_settings["performance_mode"] = enabled
        # Reload thumbnails with new settings
        QTimer.singleShot(100, self._load_visible_thumbnails)
        
    def refresh_view(self):
        """Refresh the gallery view."""
        self.populate()