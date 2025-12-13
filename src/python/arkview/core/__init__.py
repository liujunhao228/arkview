""" 
Core package for Arkview. 
"""

# Make core directory a Python package
# Export key models and utilities from the core package

from .models import (
    ZipFileInfo,
    LoadResult,
    AppConfig,
    ImageExtensions,
)

try:
    # Import from Rust module first
    from .. import arkview_core
    _format_size = arkview_core.format_size
except ImportError:
    # Fallback implementation if Rust extension is not available
    def _format_size(size_bytes):
        """Fallback implementation of format_size function."""
        KB = 1024.0
        MB = KB * 1024.0
        GB = MB * 1024.0

        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / KB:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / MB:.1f} MB"
        else:
            return f"{size_bytes / GB:.1f} GB"

from .file_manager import ZipFileManager
from .legacy import LegacyZipFileManager
from .integration import RustIntegrationLayer

__all__ = [
    'ZipFileInfo',
    'LoadResult',
    'AppConfig',
    'ImageExtensions',
    '_format_size',
    'ZipFileManager',
    'LegacyZipFileManager',
    'RustIntegrationLayer'
]