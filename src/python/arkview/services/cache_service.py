"""
Cache service implementation for Arkview.
Provides a high-level interface for cache management.
"""

from typing import Optional
from PIL import Image

from ..core.cache import LRUCache


class CacheService:
    """Service for managing application cache."""
    
    def __init__(self, capacity: int = 50):
        self.cache = LRUCache(capacity)
        
    def get(self, key: tuple) -> Optional[Image.Image]:
        """Retrieve an item from cache."""
        return self.cache.get(key)
        
    def put(self, key: tuple, value: Image.Image):
        """Put an item into cache."""
        self.cache.put(key, value)
        
    def clear(self):
        """Clear all items from cache."""
        self.cache.clear()
        
    def resize(self, new_capacity: int):
        """Resize the cache capacity."""
        self.cache.resize(new_capacity)
        
    def __len__(self) -> int:
        """Return the number of items in the cache."""
        return len(self.cache)
        
    def __contains__(self, key: tuple) -> bool:
        """Check if a key exists in the cache."""
        return key in self.cache