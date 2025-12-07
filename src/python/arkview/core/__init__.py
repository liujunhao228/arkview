"""
Core package for Arkview.
"""

# This file makes the core directory a Python package

from .models import LoadResult, ZipFileInfo
from .cache import LRUCache
from .file_manager import ZipFileManager

# Try to import Rust bindings if available
try:
    from .. import arkview_core as rust_bindings
except ImportError:
    rust_bindings = None

def _format_size(size_bytes: int) -> str:
    """Formats byte size into a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.1f} GB"

__all__ = ['_format_size', 'LoadResult', 'ZipFileInfo', 'LRUCache', 'ZipFileManager', 'rust_bindings']