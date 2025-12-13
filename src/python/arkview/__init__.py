"""
Arkview package initialization.
"""

# Import core components
from .core.models import LoadResult
from .core.file_manager import ZipFileManager
from .core import LegacyZipFileManager

# Import services
from .services.cache_service import (
    UnifiedCacheService,
    MemoryAwareCacheService
)
from .services.config_service import ConfigService
from .services.image_service import ImageService
from .services.thumbnail_service import ThumbnailService
from .services.zip_service import ZipService

# Import UI components
from .ui import (
    MainWindow,
    ImageViewerWindow,
    GalleryView
)

# Import configuration
from .config import CONFIG

# Backward compatibility imports
try:
    from .core import ZipScanner
except ImportError:
    # In case rust extension is not available
    from .services.zip_service import ZipService
    ZipScanner = ZipService

__all__ = [
    # Core components
    "LoadResult",
    "ZipFileManager",
    "LegacyZipFileManager",
    "ZipScanner",
    
    # Services
    "UnifiedCacheService",
    "MemoryAwareCacheService",
    "ConfigService",
    "ImageService",
    "ThumbnailService",
    "ZipService",
    
    # UI components
    "MainWindow",
    "ImageViewerWindow",
    "GalleryView",
    
    # Configuration
    "CONFIG"
]