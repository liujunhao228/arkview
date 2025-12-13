"""
Main entry point for the Arkview application.
"""

import sys
from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .services.cache_service import CacheService
from .services.simple_cache_service import SimpleCacheService
from .core.file_manager import ZipFileManager
from .config import USE_SIMPLE_CACHE, DEFAULT_CACHE_CAPACITY


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    
    # Initialize core services
    zip_manager = ZipFileManager()
    
    # Choose cache service based on configuration
    if USE_SIMPLE_CACHE:
        cache_service = SimpleCacheService(DEFAULT_CACHE_CAPACITY)
    else:
        cache_service = CacheService(DEFAULT_CACHE_CAPACITY)
    
    # Create and show main window
    window = MainWindow(cache_service, zip_manager)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()