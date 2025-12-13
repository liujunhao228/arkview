"""
Main entry point for the Arkview application.
"""

import sys
from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()