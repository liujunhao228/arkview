"""
Dialog implementations for Arkview UI layer.
"""

from typing import Dict, Any
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QCheckBox,
    QSpinBox, QPushButton, QGroupBox, QComboBox, QLineEdit
)
from PySide6.QtCore import Qt


class SettingsDialog(QDialog):
    """Settings dialog for Arkview."""
    
    def __init__(self, config: Dict[str, Any], parent=None):
        super().__init__(parent)
        
        self.config = config.copy()
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(400, 300)
        
        self._setup_ui()
        self._populate_settings()
        self._apply_dark_theme()
        
    def _setup_ui(self):
        """Setup the settings dialog UI."""
        layout = QVBoxLayout(self)
        
        # Performance settings group
        performance_group = QGroupBox("Performance")
        performance_layout = QFormLayout(performance_group)
        
        self.performance_mode_checkbox = QCheckBox("Enable performance mode by default")
        performance_layout.addRow(self.performance_mode_checkbox)
        
        self.cache_size_spinbox = QSpinBox()
        self.cache_size_spinbox.setRange(1, 100)
        self.cache_size_spinbox.setSuffix(" images")
        performance_layout.addRow("Cache size:", self.cache_size_spinbox)
        
        layout.addWidget(performance_group)
        
        # Display settings group
        display_group = QGroupBox("Display")
        display_layout = QFormLayout(display_group)
        
        self.thumbnail_size_combo = QComboBox()
        self.thumbnail_size_combo.addItems(["Small", "Medium", "Large"])
        display_layout.addRow("Thumbnail size:", self.thumbnail_size_combo)
        
        self.window_size_edit = QLineEdit()
        self.window_size_edit.setPlaceholderText("e.g., 1024x768")
        display_layout.addRow("Default window size:", self.window_size_edit)
        
        layout.addWidget(display_group)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        ok_button.setDefault(True)
        buttons_layout.addWidget(ok_button)
        
        layout.addLayout(buttons_layout)
        
    def _populate_settings(self):
        """Populate dialog with current settings."""
        # Performance mode
        self.performance_mode_checkbox.setChecked(
            self.config.get("DEFAULT_PERFORMANCE_MODE", False))
        
        # Cache size
        cache_capacity = self.config.get("CACHE_MAX_ITEMS_NORMAL", 50)
        self.cache_size_spinbox.setValue(cache_capacity)
        
        # Thumbnail size
        thumb_size = self.config.get("THUMBNAIL_SIZE", (280, 280))
        if thumb_size[0] <= 180:
            self.thumbnail_size_combo.setCurrentText("Small")
        elif thumb_size[0] <= 220:
            self.thumbnail_size_combo.setCurrentText("Medium")
        else:
            self.thumbnail_size_combo.setCurrentText("Large")
            
        # Window size
        window_size = self.config.get("WINDOW_SIZE", (1050, 750))
        self.window_size_edit.setText(f"{window_size[0]}x{window_size[1]}")
        
    def _apply_dark_theme(self):
        """Apply dark theme to the settings dialog."""
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #e0e0e0;
            }
            QGroupBox {
                background-color: #3c3f41;
                border: 1px solid #555555;
                border-radius: 4px;
                margin-top: 8px;
                color: #bbbbbb;
                padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
            }
            QLabel {
                color: #e0e0e0;
            }
            QCheckBox {
                color: #bbbbbb;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #555555;
                background-color: #45494a;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #555555;
                background-color: #4b6eaf;
            }
            QSpinBox, QComboBox, QLineEdit {
                background-color: #45494a;
                color: #e0e0e0;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #3c3f41;
                border: none;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #4b6eaf;
            }
            QComboBox QAbstractItemView {
                background-color: #45494a;
                border: 1px solid #555555;
                selection-background-color: #4b6eaf;
            }
            QPushButton {
                background-color: #3c3f41;
                color: #bbbbbb;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 60px;
            }
            QPushButton:hover {
                background-color: #4b6eaf;
                border: 1px solid #555555;
            }
            QPushButton:pressed {
                background-color: #3a588c;
            }
            QPushButton:disabled {
                background-color: #4a4d4f;
                color: #888888;
                border: 1px solid #666666;
            }
        """)
        
    def get_settings(self) -> Dict[str, Any]:
        """Get settings from the dialog."""
        settings = {}
        
        # Performance settings
        settings["DEFAULT_PERFORMANCE_MODE"] = self.performance_mode_checkbox.isChecked()
        settings["CACHE_MAX_ITEMS_NORMAL"] = self.cache_size_spinbox.value()
        
        # Display settings based on combo box selection
        thumb_text = self.thumbnail_size_combo.currentText()
        if thumb_text == "Small":
            settings["THUMBNAIL_SIZE"] = (180, 180)
            settings["GALLERY_THUMB_SIZE"] = (160, 160)
        elif thumb_text == "Medium":
            settings["THUMBNAIL_SIZE"] = (220, 220)
            settings["GALLERY_THUMB_SIZE"] = (200, 200)
        else:  # Large
            settings["THUMBNAIL_SIZE"] = (280, 280)
            settings["GALLERY_THUMB_SIZE"] = (240, 240)
            
        # Window size
        window_size_text = self.window_size_edit.text()
        if "x" in window_size_text:
            try:
                width, height = map(int, window_size_text.split("x"))
                settings["WINDOW_SIZE"] = (width, height)
            except ValueError:
                # Keep default if parsing fails
                pass
                
        return settings


class AboutDialog(QDialog):
    """About dialog for Arkview."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowTitle("About Arkview")
        self.setModal(True)
        self.resize(300, 200)
        
        self._setup_ui()
        self._apply_dark_theme()
        
    def _setup_ui(self):
        """Setup the about dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Title
        title_label = QLabel("Arkview")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # Version
        version_label = QLabel("Version 4.0 - Rust-Python Hybrid")
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)
        
        # Description
        desc_label = QLabel(
            "A high-performance image browser for viewing images inside ZIP archives.\n\n"
            "Built with Rust core for performance and Python/Qt for flexibility."
        )
        desc_label.setWordWrap(True)
        desc_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(desc_label)
        
        # OK button
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        ok_layout = QHBoxLayout()
        ok_layout.addStretch()
        ok_layout.addWidget(ok_button)
        ok_layout.addStretch()
        layout.addLayout(ok_layout)