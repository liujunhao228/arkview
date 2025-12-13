"""
Data models for Arkview core layer.
"""

import os
from typing import Optional, List, Tuple
from dataclasses import dataclass
from PIL import Image

# Import configuration
from ..config import parse_human_size


@dataclass
class ZipFileInfo:
    """Information about a ZIP file."""
    path: str
    is_valid: bool
    members: Optional[List[str]]
    mod_time: Optional[float]
    file_size: Optional[int]
    image_count: int

    def get_formatted_size(self) -> str:
        """Format file size into human-readable string."""
        if self.file_size is None:
            return "Unknown"

        return parse_human_size(self.file_size)


class LightweightPlaylistEntry:
    """A lightweight version of playlist entry that doesn't store full objects."""
    
    def __init__(self, archive_path: str, image_member: str):
        self.archive_path = archive_path
        self.image_member = image_member
    
    @classmethod
    def from_zip_file_info(cls, zip_info: ZipFileInfo, image_member: str) -> 'LightweightPlaylistEntry':
        """Create a lightweight entry from ZipFileInfo."""
        return cls(zip_info.path, image_member)
    
    def to_tuple(self) -> Tuple[str, str]:
        """Convert to tuple representation."""
        return (self.archive_path, self.image_member)


@dataclass
class LoadResult:
    """Result of an asynchronous image load operation."""
    success: bool
    data: Optional[Image.Image] = None
    error_message: str = ""
    cache_key: Optional[tuple] = None


@dataclass
class AppConfig:
    """Application configuration settings."""
    thumbnail_size: Tuple[int, int] = (280, 280)
    performance_thumbnail_size: Tuple[int, int] = (180, 180)
    gallery_thumb_size: Tuple[int, int] = (220, 220)
    gallery_preview_size: Tuple[int, int] = (480, 480)
    batch_scan_size: int = 50
    batch_update_interval: int = 20
    max_thumbnail_load_size: int = 10 * 1024 * 1024
    performance_max_thumbnail_load_size: int = 3 * 1024 * 1024
    max_viewer_load_size: int = 100 * 1024 * 1024
    performance_max_viewer_load_size: int = 30 * 1024 * 1024
    cache_max_items_normal: int = 50
    cache_max_items_performance: int = 25
    preload_viewer_neighbors_normal: int = 2
    preload_viewer_neighbors_performance: int = 1
    preload_next_thumbnail: bool = True
    window_size: Tuple[int, int] = (1050, 750)
    viewer_zoom_factor: float = 1.2
    viewer_max_zoom: float = 10.0
    viewer_min_zoom: float = 0.1
    preview_update_delay: int = 250
    thread_pool_workers: int = 8
    app_version: str = "4.0 - Rust-Python Hybrid"
    image_extensions: set = None

    def __post_init__(self):
        from ..config import CONFIG  # Import here to avoid circular import
        if self.image_extensions is None:
            self.image_extensions = CONFIG["IMAGE_EXTENSIONS"]


class ImageExtensions:
    """Standard image extensions supported by the application."""

    @classmethod
    def is_image_file(cls, filename: str) -> bool:
        """Check if a file is an image based on its extension."""
        try:
            from ..core import arkview_core
            return arkview_core.is_image_file(filename)
        except ImportError:
            # Fallback to Python implementation if Rust extension is not available
            if not filename or filename.endswith('/'):
                return False
            _, ext = os.path.splitext(filename)
            from ..config import CONFIG  # Import here to avoid circular import
            return ext.lower() in CONFIG["IMAGE_EXTENSIONS"]