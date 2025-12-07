"""
Data models for Arkview application.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum


class ViewType(Enum):
    """Enumeration of available view types."""
    EXPLORER = "explorer"
    GALLERY = "gallery"
    SLIDE = "slide"


@dataclass
class ZipFileInfo:
    """Model representing a ZIP file information."""
    path: str
    members: Optional[List[str]]
    modification_time: float
    file_size: int
    image_count: int
    is_valid: bool = True
    
    def __post_init__(self):
        """Validate and set is_valid based on data."""
        self.is_valid = (
            self.members is not None and 
            len(self.members) > 0 and 
            self.image_count > 0
        )


@dataclass
class LoadResult:
    """Result of an image loading operation."""
    success: bool
    data: Optional[Any] = None
    error_message: str = ""
    cache_key: Optional[Tuple[str, str]] = None


@dataclass
class ScanProgress:
    """Progress information for directory scanning."""
    processed: int
    total: int
    valid_found: int


@dataclass
class ScanResult:
    """Result of directory scanning operation."""
    valid_count: int
    total_processed: int
    zip_files: List[ZipFileInfo]


@dataclass
class ImageLoadRequest:
    """Request for loading an image from ZIP."""
    zip_path: str
    member_name: str
    cache_key: Tuple[str, str]
    max_size: int
    target_size: Optional[Tuple[int, int]] = None
    performance_mode: bool = False
    force_reload: bool = False


@dataclass
class AppSettings:
    """Application settings model."""
    performance_mode: bool = False
    viewer_enabled: bool = True
    preload_next_thumbnail: bool = True
    max_thumbnail_size: int = 10 * 1024 * 1024  # 10MB
    cache_max_items: int = 50
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AppSettings':
        """Create AppSettings from dictionary."""
        return cls(
            performance_mode=data.get('performance_mode', False),
            viewer_enabled=data.get('viewer_enabled', True),
            preload_next_thumbnail=data.get('preload_next_thumbnail', True),
            max_thumbnail_size=data.get('max_thumbnail_size', 10 * 1024 * 1024),
            cache_max_items=data.get('cache_max_items', 50)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert AppSettings to dictionary."""
        return {
            'performance_mode': self.performance_mode,
            'viewer_enabled': self.viewer_enabled,
            'preload_next_thumbnail': self.preload_next_thumbnail,
            'max_thumbnail_size': self.max_thumbnail_size,
            'cache_max_items': self.cache_max_items
        }


@dataclass
class SlideViewContext:
    """Context for slide view navigation."""
    zip_path: Optional[str] = None
    members: Optional[List[str]] = None
    current_index: int = 0
    previous_view: str = "explorer"


@dataclass
class ThumbnailLoadRequest:
    """Request for thumbnail loading."""
    zip_path: str
    member_path: str
    cache_key: Tuple[str, str]
    max_size: int
    resize_params: Tuple[int, int]
    performance_mode: bool = False