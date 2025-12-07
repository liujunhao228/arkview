"""
Main Arkview Application - PySide6 Implementation
"""

from .ui.main_window import MainWindow
import sys
from PySide6.QtWidgets import QApplication


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for consistent look
    
    main_window = MainWindow()
    main_window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()