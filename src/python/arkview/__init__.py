"""
Arkview - A high-performance image browser for ZIP archives.
"""

# Version info
from .config import APP_VERSION

# Core components
from .core import (
    SimpleLRUCache,
    ZipFileManager,
    ZipFileInfo
)

# Services
from .services import (
    SimpleCacheService,
    ConfigService,
    ImageService,
    ThumbnailService,
    ZipService
)

# UI Components
from .ui import (
    MainWindow,
    ImageViewerWindow,
    GalleryView
)

__version__ = APP_VERSION

__all__ = [
    # Version
    "__version__",
    
    # Core components
    "SimpleLRUCache",
    "ZipFileManager",
    "ZipFileInfo",
    
    # Services
    "SimpleCacheService",
    "ConfigService",
    "ImageService",
    "ThumbnailService",
    "ZipService",
    
    # UI Components
    "MainWindow",
    "ImageViewerWindow",
    "GalleryView"
]