"""
View management system for Arkview PySide UI.

This module provides a unified interface and management system for different views
(Resource Explorer, Gallery, Slide View, etc.) to improve maintainability and
extensibility of the UI.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QSplitter, QLabel, QPushButton, 
    QListWidget, QScrollBar, QGroupBox, QScrollArea, QWidget
)
from PySide6.QtCore import Qt


class BaseView(ABC):
    """Abstract base class for all views in Arkview."""
    
    def __init__(self, view_id: str, display_name: str, icon: str = ""):
        """
        Initialize the base view.
        
        Args:
            view_id: Unique identifier for the view (e.g., "explorer", "gallery", "slide")
            display_name: Human-readable name for the view (e.g., "Resource Explorer")
            icon: Optional icon/emoji for the view (e.g., "📋")
        """
        self.view_id = view_id
        self.display_name = display_name
        self.icon = icon
        self.is_visible = False
        self.frame: Optional[QFrame] = None
    
    @abstractmethod
    def create_ui(self) -> QFrame:
        """
        Create and return the UI frame for this view.
        
        Returns:
            QFrame: The main frame for this view
        """
        pass
    
    @abstractmethod
    def on_show(self):
        """Called when the view becomes visible."""
        pass
    
    @abstractmethod
    def on_hide(self):
        """Called when the view becomes hidden."""
        pass
    
    @abstractmethod
    def cleanup(self):
        """Clean up resources used by this view."""
        pass
    
    def show(self):
        """Show the view."""
        if self.frame:
            self.frame.show()
        self.is_visible = True
        self.on_show()
    
    def hide(self):
        """Hide the view."""
        if self.frame:
            self.frame.hide()
        self.is_visible = False
        self.on_hide()


class ViewManager:
    """Manages multiple views and handles view switching."""
    
    def __init__(self, parent_container: QFrame):
        """
        Initialize the view manager.
        
        Args:
            parent_container: The container frame that will hold all views
        """
        self.parent_container = parent_container
        self.views: Dict[str, BaseView] = {}
        self.current_view_id: Optional[str] = None
        self.view_switched_callbacks: List[Callable[[str, str], None]] = []
        
        # Setup container layout
        layout = QVBoxLayout(parent_container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout = layout
    
    def register_view(self, view: BaseView) -> None:
        """
        Register a new view with the manager.
        
        Args:
            view: The view to register
        """
        if view.view_id in self.views:
            raise ValueError(f"View with id '{view.view_id}' is already registered")
        
        self.views[view.view_id] = view
        
        # Create UI and add to container
        ui_frame = view.create_ui()
        view.frame = ui_frame
        self.container_layout.addWidget(ui_frame)
        
        # Initially hide all views
        ui_frame.hide()
    
    def switch_to_view(self, view_id: str) -> bool:
        """
        Switch to a different view.
        
        Args:
            view_id: The ID of the view to switch to
            
        Returns:
            bool: True if switch was successful, False otherwise
        """
        if view_id not in self.views:
            return False
        
        if view_id == self.current_view_id:
            return True
        
        # Hide previous view
        if self.current_view_id and self.current_view_id in self.views:
            self.views[self.current_view_id].hide()
        
        # Show new view
        previous_view_id = self.current_view_id
        self.current_view_id = view_id
        self.views[view_id].show()
        
        # Trigger callbacks
        for callback in self.view_switched_callbacks:
            callback(previous_view_id or "", view_id)
        
        return True
    
    def get_current_view(self) -> Optional[BaseView]:
        """Get the currently active view."""
        if self.current_view_id and self.current_view_id in self.views:
            return self.views[self.current_view_id]
        return None
    
    def get_view(self, view_id: str) -> Optional[BaseView]:
        """Get a view by its ID."""
        return self.views.get(view_id)
    
    def on_view_switched(self, callback: Callable[[str, str], None]) -> None:
        """
        Register a callback to be called when views are switched.
        
        Args:
            callback: Function that takes (previous_view_id, current_view_id) as arguments
        """
        self.view_switched_callbacks.append(callback)
    
    def get_all_views(self) -> Dict[str, BaseView]:
        """Get all registered views."""
        return self.views.copy()
    
    def cleanup_all(self) -> None:
        """Clean up all views."""
        for view in self.views.values():
            view.cleanup()


class ExplorerView(BaseView):
    """Resource Explorer view for browsing ZIP files."""
    
    def __init__(self, zip_data_provider: Callable):
        """
        Initialize the Explorer view.
        
        Args:
            zip_data_provider: Callable that provides zip_files dict and other data
        """
        super().__init__("explorer", "Resource Explorer", "📋")
        self.zip_data_provider = zip_data_provider
        self.zip_listbox: Optional[QListWidget] = None
        self.preview_label: Optional[QLabel] = None
        self.main_splitter: Optional[QSplitter] = None
        self.preview_prev_button: Optional[QPushButton] = None
        self.preview_next_button: Optional[QPushButton] = None
        self.preview_info_label: Optional[QLabel] = None
        self.details_content_label: Optional[QLabel] = None
        self.details_text: Optional[QScrollArea] = None
        self.details_layout: Optional[QVBoxLayout] = None
        self.details_widget: Optional[QWidget] = None
    
    def create_ui(self) -> QFrame:
        """Create the explorer view UI."""
        explorer_view_frame = QFrame()
        explorer_layout = QHBoxLayout(explorer_view_frame)
        explorer_layout.setContentsMargins(8, 8, 8, 8)
        
        self.main_splitter = QSplitter(Qt.Horizontal)
        
        # --- Left Panel: ZIP File List ---
        left_frame = QFrame()
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(5, 5, 5, 5)
        
        left_label = QLabel("📦 Archives")
        left_label.setStyleSheet("font-weight: bold; color: #e8eaed; font-size: 11pt;")
        left_layout.addWidget(left_label)
        
        list_container = QFrame()
        list_layout = QHBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        
        self.zip_listbox = QListWidget()
        self.zip_listbox.setStyleSheet("""
            QListWidget {
                background-color: #1f222a;
                border: 1px solid #2c323c;
                color: #e8eaed;
                selection-background-color: #00bc8c;
                selection-color: #101214;
                font: 10pt "Segoe UI";
            }
        """)
        list_layout.addWidget(self.zip_listbox)
        
        list_scrollbar = QScrollBar()
        self.zip_listbox.setVerticalScrollBar(list_scrollbar)
        list_layout.addWidget(list_scrollbar)
        
        left_layout.addWidget(list_container)
        self.main_splitter.addWidget(left_frame)
        
        # --- Right Panel: Preview and Details ---
        right_frame = QFrame()
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(5, 5, 5, 5)
        
        right_label = QLabel("🖼️  Preview")
        right_label.setStyleSheet("font-weight: bold; color: #e8eaed; font-size: 11pt;")
        right_layout.addWidget(right_label)
        
        preview_nav_frame = QFrame()
        preview_nav_layout = QHBoxLayout(preview_nav_frame)
        preview_nav_layout.setContentsMargins(0, 0, 0, 8)
        
        self.preview_prev_button = QPushButton("◀ Prev")
        self.preview_prev_button.setFixedWidth(100)
        self.preview_prev_button.setEnabled(False)
        preview_nav_layout.addWidget(self.preview_prev_button)
        
        self.preview_info_label = QLabel("")
        self.preview_info_label.setAlignment(Qt.AlignCenter)
        self.preview_info_label.setStyleSheet("font-size: 9pt;")
        preview_nav_layout.addWidget(self.preview_info_label)
        
        self.preview_next_button = QPushButton("Next ▶")
        self.preview_next_button.setFixedWidth(100)
        self.preview_next_button.setEnabled(False)
        preview_nav_layout.addWidget(self.preview_next_button)
        
        right_layout.addWidget(preview_nav_frame)
        
        preview_container = QFrame()
        preview_container.setFrameStyle(QFrame.StyledPanel)
        preview_container.setStyleSheet("background-color: #2a2d2e; border: 1px solid #3a3f4b;")
        preview_container.setMinimumHeight(300)
        
        preview_container_layout = QVBoxLayout(preview_container)
        preview_container_layout.setContentsMargins(2, 2, 2, 2)
        
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #2a2d2e;
                color: #ffffff;
                font: 10pt;
            }
        """)
        self.preview_label.setText("Select a ZIP file")
        self.preview_label.setScaledContents(False)
        self.preview_label.setMinimumSize(1, 1)
        preview_container_layout.addWidget(self.preview_label)
        
        right_layout.addWidget(preview_container)
        
        details_frame = QGroupBox("ℹ️  Details")
        details_layout = QVBoxLayout(details_frame)
        
        self.details_text = QScrollArea()
        self.details_text.setMinimumHeight(200)
        self.details_text.setWidgetResizable(True)
        self.details_widget = QWidget()
        self.details_layout = QVBoxLayout(self.details_widget)
        self.details_text.setWidget(self.details_widget)
        
        self.details_content_label = QLabel()
        self.details_content_label.setWordWrap(True)
        self.details_layout.addWidget(self.details_content_label)
        
        details_layout.addWidget(self.details_text)
        
        right_layout.addWidget(details_frame)
        
        self.main_splitter.addWidget(right_frame)
        
        self.main_splitter.setStretchFactor(0, 2)
        self.main_splitter.setStretchFactor(1, 3)
        
        explorer_layout.addWidget(self.main_splitter)
        
        self.frame = explorer_view_frame
        return explorer_view_frame
    
    def on_show(self):
        """Called when explorer view becomes visible."""
        pass
    
    def on_hide(self):
        """Called when explorer view becomes hidden."""
        pass
    
    def cleanup(self):
        """Clean up explorer view resources."""
        pass
