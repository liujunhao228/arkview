"""
Service layer package for Arkview.
This package contains all business logic services that act as intermediaries
between the UI layer and the core layer.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Dict, Any, Callable
from PIL import Image

class ZipServiceInterface(ABC):
    """Interface for ZIP file handling service."""
    
    @abstractmethod
    def analyze_zip(self, zip_path: str, collect_members: bool = True) -> Tuple[bool, Optional[List[str]], Optional[float], Optional[int], int]:
        """Analyze a ZIP file to determine if it contains only image files."""
        pass
    
    @abstractmethod
    def batch_analyze_zips(self, zip_paths: List[str], collect_members: bool = True) -> List[Tuple[str, bool, Optional[List[str]], Optional[float], Optional[int], int]]:
        """Batch analyze multiple ZIP files."""
        pass


class ImageServiceInterface(ABC):
    """Interface for image handling service."""
    
    @abstractmethod
    def load_image_data_async(self, zip_path: str, member_name: str, max_load_size: int,
                              target_size: Optional[Tuple[int, int]], cache_key: tuple,
                              performance_mode: bool, force_reload: bool = False) -> Optional[object]:
        """Asynchronously load image data from a ZIP archive member."""
        pass


class ThumbnailServiceInterface(ABC):
    """Interface for thumbnail loading service."""
    
    @abstractmethod
    def request_thumbnail(self, zip_path: str, member_path: str, cache_key: tuple,
                         max_size: int, resize_params: tuple, performance_mode: bool):
        """Request loading of a thumbnail."""
        pass
    
    @abstractmethod
    def stop_service(self):
        """Stop the thumbnail service and cleanup resources."""
        pass


class CacheServiceInterface(ABC):
    """Interface for cache management service."""
    
    @abstractmethod
    def get(self, key: tuple) -> Optional[Image.Image]:
        """Retrieve an item from cache."""
        pass
    
    @abstractmethod
    def put(self, key: tuple, value: Image.Image):
        """Put an item into cache."""
        pass
    
    @abstractmethod
    def clear(self):
        """Clear all items from cache."""
        pass
    
    @abstractmethod
    def resize(self, new_capacity: int):
        """Resize the cache capacity."""
        pass


class ConfigServiceInterface(ABC):
    """Interface for configuration service."""
    
    @abstractmethod
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a configuration setting."""
        pass
    
    @abstractmethod
    def set_setting(self, key: str, value: Any):
        """Set a configuration setting."""
        pass
    
    @abstractmethod
    def save_settings(self):
        """Save configuration settings to persistent storage."""
        pass