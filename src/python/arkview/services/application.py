"""
Application service - coordinates between different services and manages application state.
"""

from typing import Dict, List, Optional, Any
from PySide6.QtCore import QObject, Signal, Slot

from ..models import (
    AppSettings, ZipFileInfo, ScanResult, ScanProgress, 
    SlideViewContext, ImageLoadRequest, ThumbnailLoadRequest
)
from .file_scanner import FileScannerService
from .image_loader import ImageLoaderService
from .file_management import FileManagementService
from ..infrastructure import LRUCache


class ApplicationService(QObject):
    """Main application service that coordinates all business operations."""
    
    # UI Signals
    update_status = Signal(str)
    update_preview = Signal(object)
    show_error = Signal(str, str)
    
    # Data Signals
    zip_files_updated = Signal(object)  # Dict[str, ZipFileInfo]
    selection_changed = Signal(str, object, int)  # zip_path, members, index
    scan_progress_updated = Signal(object)  # ScanProgress
    scan_completed_updated = Signal(object)  # ScanResult
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.config = config
        
        # Initialize services
        self.file_scanner = FileScannerService(config)
        self.image_loader = ImageLoaderService(None, LRUCache(config["CACHE_MAX_ITEMS_NORMAL"]), config)
        self.file_management = FileManagementService(config)
        
        # Update image loader with proper zip_manager
        self.image_loader.zip_manager = self.file_management.get_zip_file_manager()
        
        # Application state
        self.app_settings = AppSettings()
        self.zip_files: Dict[str, ZipFileInfo] = {}
        self.current_selected_zip: Optional[str] = None
        self.current_preview_index: Optional[int] = None
        self.current_preview_members: Optional[List[str]] = None
        self.slide_view_context = SlideViewContext()
        
        # Connect service signals
        self._connect_service_signals()
        
    def _connect_service_signals(self):
        """Connect signals from services to application service."""
        # File scanner signals
        self.file_scanner.scan_progress.connect(self._on_scan_progress)
        self.file_scanner.scan_completed.connect(self._on_scan_completed)
        self.file_scanner.scan_error.connect(self._on_scan_error)
        
        # File management signals
        self.file_management.members_loaded.connect(self._on_members_loaded)
        self.file_management.error_occurred.connect(self._on_error_occurred)
        
        # Image loader signals
        self.image_loader.image_loaded.connect(self._on_image_loaded)
        self.image_loader.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        
    @Slot(object)
    def _on_scan_progress(self, progress: ScanProgress):
        """Handle scan progress updates."""
        self.scan_progress_updated.emit(progress)
        self.update_status.emit(f"Scanning: {progress.processed}/{progress.total} files ({progress.valid_found} valid)")
        
    @Slot(object)
    def _on_scan_completed(self, result: ScanResult):
        """Handle scan completion."""
        # Update zip files dictionary
        for zip_info in result.zip_file_infos:
            self.zip_files[zip_info.path] = zip_info
            
        self.zip_files_updated.emit(self.zip_files)
        self.scan_completed_updated.emit(result)
        self.update_status.emit(f"Scan completed: {result.valid_count} valid archives found from {result.total_processed} files")
        
    @Slot(str)
    def _on_scan_error(self, error_message: str):
        """Handle scan errors."""
        self.show_error.emit("Scan Error", error_message)
        
    @Slot(str, object)
    def _on_members_loaded(self, zip_path: str, members: List[str]):
        """Handle members loaded for a ZIP file."""
        if zip_path in self.zip_files:
            self.zip_files[zip_path].members = members
            self.zip_files_updated.emit(self.zip_files)
            
        if zip_path == self.current_selected_zip:
            self.current_preview_members = members
            self.selection_changed.emit(zip_path, members, 0)
            
    @Slot(str)
    def _on_error_occurred(self, error_message: str):
        """Handle general errors."""
        self.show_error.emit("Error", error_message)
        
    @Slot(object)
    def _on_image_loaded(self, result):
        """Handle image loaded."""
        if result.success:
            self.update_preview.emit((result.data, ""))
        else:
            self.update_preview.emit((None, result.error_message))
            
    @Slot(object, tuple)
    def _on_thumbnail_loaded(self, result, cache_key):
        """Handle thumbnail loaded - to be connected by UI components."""
        pass  # UI components will connect to this signal
        
    def scan_directory(self, directory: str):
        """Start scanning a directory for ZIP files."""
        self.update_status.emit(f"Starting scan of {directory}...")
        self.file_scanner.scan_directory(directory)
        
    def stop_scan(self):
        """Stop the current scan."""
        self.file_scanner.stop_scan()
        self.update_status.emit("Scan stopped")
        
    def select_zip_file(self, zip_path: str):
        """Select a ZIP file for preview."""
        if zip_path not in self.zip_files:
            return
            
        self.current_selected_zip = zip_path
        zip_info = self.zip_files[zip_path]
        
        if zip_info.members is None:
            # Load members if not already loaded
            self.file_management.load_zip_members(zip_path)
        else:
            self.current_preview_members = zip_info.members
            self.selection_changed.emit(zip_path, zip_info.members, 0)
            
    def load_preview_image(self, zip_path: str, member_name: str, index: int = 0):
        """Load a preview image."""
        cache_key = (zip_path, member_name)
        max_size = self.config["MAX_VIEWER_LOAD_SIZE"]
        if self.app_settings.performance_mode:
            max_size = self.config["PERFORMANCE_MAX_VIEWER_LOAD_SIZE"]
            
        request = ImageLoadRequest(
            zip_path=zip_path,
            member_name=member_name,
            cache_key=cache_key,
            max_size=max_size,
            target_size=None,
            performance_mode=self.app_settings.performance_mode
        )
        
        self.current_preview_index = index
        self.image_loader.load_image(request)
        
    def load_thumbnail(self, zip_path: str, member_name: str, size: tuple) -> None:
        """Load a thumbnail."""
        cache_key = (zip_path, member_name)
        max_size = self.config["MAX_THUMBNAIL_LOAD_SIZE"]
        if self.app_settings.performance_mode:
            max_size = self.config["PERFORMANCE_MAX_THUMBNAIL_LOAD_SIZE"]
            
        request = ThumbnailLoadRequest(
            zip_path=zip_path,
            member_path=member_name,
            cache_key=cache_key,
            max_size=max_size,
            resize_params=size,
            performance_mode=self.app_settings.performance_mode
        )
        
        self.image_loader.load_thumbnail(request)
        
    def update_settings(self, settings: AppSettings):
        """Update application settings."""
        self.app_settings = settings
        
        # Update cache size if needed
        if settings.cache_max_items != self.image_loader.cache.capacity:
            self.image_loader.resize_cache(settings.cache_max_items)
            
    def clear_selection(self):
        """Clear current selection."""
        self.current_selected_zip = None
        self.current_preview_index = None
        self.current_preview_members = None
        self.update_preview.emit((None, ""))
        
    def cleanup(self):
        """Cleanup resources."""
        self.file_management.close_all_zip_files()
        self.image_loader.clear_cache()