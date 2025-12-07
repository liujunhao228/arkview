"""
Arkview - A high-performance image browser for viewing images inside ZIP archives.
"""

__version__ = "4.0.0"

# Expose main UI components
from .ui.main_window import MainWindow
from .ui.gallery_view import GalleryView
from .ui.viewer_window import ImageViewerWindow
from .ui.dialogs import SettingsDialog, AboutDialog

# Expose services
from .services.zip_service import ZipService
from .services.image_service import ImageService
from .services.thumbnail_service import ThumbnailService
from .services.config_service import ConfigService
from .services.cache_service import CacheService, EnhancedCacheService

# Expose core components
from .core.cache import LRUCache
from .core.file_manager import ZipFileManager
from .core.models import LoadResult, ZipFileInfo

__all__ = [
    "MainWindow",
    "GalleryView", 
    "ImageViewerWindow",
    "SettingsDialog",
    "AboutDialog",
    "ZipService",
    "ImageService",
    "ThumbnailService",
    "ConfigService",
    "CacheService",
    "EnhancedCacheService",
    "LRUCache",
    "ZipFileManager",
    "LoadResult",
    "ZipFileInfo"
]