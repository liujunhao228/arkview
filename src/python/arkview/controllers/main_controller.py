"""
Main application controller - coordinates between UI and business logic.
"""

from typing import Dict, Any, Optional
from PySide6.QtWidgets import QMainWindow
from PySide6.QtCore import QObject, Slot

from ..services import ApplicationService
from ..models import AppSettings, ZipFileInfo, ScanProgress, ScanResult
from ..config import CONFIG


class MainController(QObject):
    """Main controller that coordinates the application."""
    
    def __init__(self, main_window: QMainWindow):
        super().__init__()
        self.main_window = main_window
        
        # Initialize application service
        self.app_service = ApplicationService(CONFIG)
        
        # Connect service signals to controller methods
        self._connect_service_signals()
        
    def _connect_service_signals(self):
        """Connect application service signals to controller handlers."""
        # UI update signals
        self.app_service.update_status.connect(self.main_window._on_update_status)
        self.app_service.update_preview.connect(self.main_window._on_update_preview)
        self.app_service.show_error.connect(self.main_window._show_error)
        
        # Data update signals
        self.app_service.zip_files_updated.connect(self._on_zip_files_updated)
        self.app_service.selection_changed.connect(self._on_selection_changed)
        self.app_service.scan_progress_updated.connect(self._on_scan_progress)
        self.app_service.scan_completed_updated.connect(self._on_scan_completed)
        
    def get_app_service(self) -> ApplicationService:
        """Get the application service instance."""
        return self.app_service
        
    # Service proxy methods
    def scan_directory(self, directory: str):
        """Start directory scan."""
        self.app_service.scan_directory(directory)
        
    def stop_scan(self):
        """Stop directory scan."""
        self.app_service.stop_scan()
        
    def select_zip_file(self, zip_path: str):
        """Select a ZIP file."""
        self.app_service.select_zip_file(zip_path)
        
    def load_preview_image(self, zip_path: str, member_name: str, index: int = 0):
        """Load preview image."""
        self.app_service.load_preview_image(zip_path, member_name, index)
        
    def load_thumbnail(self, zip_path: str, member_name: str, size: tuple):
        """Load thumbnail."""
        self.app_service.load_thumbnail(zip_path, member_name, size)
        
    def update_settings(self, settings: AppSettings):
        """Update application settings."""
        self.app_service.update_settings(settings)
        
    def clear_selection(self):
        """Clear selection."""
        self.app_service.clear_selection()
        
    def cleanup(self):
        """Cleanup resources."""
        self.app_service.cleanup()
        
    # Signal handlers
    @Slot(object)
    def _on_zip_files_updated(self, zip_files: Dict[str, ZipFileInfo]):
        """Handle ZIP files update."""
        # This will be handled by the main window
        if hasattr(self.main_window, '_on_zip_files_updated'):
            self.main_window._on_zip_files_updated(zip_files)
            
    @Slot(str, object, int)
    def _on_selection_changed(self, zip_path: str, members: list, index: int):
        """Handle selection change."""
        # This will be handled by the main window
        if hasattr(self.main_window, '_on_selection_changed'):
            self.main_window._on_selection_changed(zip_path, members, index)
            
    @Slot(object)
    def _on_scan_progress(self, progress: ScanProgress):
        """Handle scan progress."""
        # This will be handled by the main window
        if hasattr(self.main_window, '_on_scan_progress'):
            self.main_window._on_scan_progress(progress)
            
    @Slot(object)
    def _on_scan_completed(self, result: ScanResult):
        """Handle scan completion."""
        # This will be handled by the main window
        if hasattr(self.main_window, '_on_scan_completed'):
            self.main_window._on_scan_completed(result)