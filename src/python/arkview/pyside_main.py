"""
Main Arkview Application - PySide UI Implementation
"""
"""
DEPRECATED: This file is deprecated and replaced by the new layered architecture.

The new architecture separates concerns into distinct layers:
- UI Layer: ui/main_window.py, ui/gallery_view.py, ui/viewer_window.py, ui/dialogs.py
- Service Layer: services/*.py
- Core Layer: core/*.py

Please use the new modules instead.
"""

import warnings
warnings.warn("pyside_main.py is deprecated, use ui/main_window.py instead", DeprecationWarning)

# Preserve the old interface for backward compatibility
def main():
    """Deprecated main function"""
    from .ui.main_window import MainWindow
    import sys
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    main_window = MainWindow()
    main_window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
