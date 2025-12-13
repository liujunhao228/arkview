"""
Simple cache service implementation for Arkview.
Provides a simplified interface for cache management.
"""

from typing import Optional, Dict, Any
from PIL import Image

from ..core.simple_cache import SimpleLRUCache


class SimpleCacheService:
    """Simplified cache service using the simple LRU cache backend."""

    def __init__(self, capacity: int = 50):
        """
        Initialize the cache service.
        
        Args:
            capacity: Maximum number of items to store in the cache
        """
        self._cache = SimpleLRUCache(capacity)

    def get(self, key: tuple) -> Optional[Image.Image]:
        """
        Retrieve an item from the cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached Image object or None if not found
        """
        return self._cache.get(key)

    def put(self, key: tuple, value: Image.Image):
        """
        Add an item to the cache.
        
        Args:
            key: Cache key
            value: Image object to cache
        """
        self._cache.put(key, value)

    def clear(self):
        """Clear all items from the cache."""
        self._cache.clear()

    def resize(self, new_capacity: int):
        """
        Resize the cache capacity.
        
        Args:
            new_capacity: New cache capacity
        """
        self._cache.resize(new_capacity)

    def __len__(self) -> int:
        """Return the number of items in the cache."""
        return len(self._cache)

    def __contains__(self, key: tuple) -> bool:
        """Check if a key exists in the cache."""
        return key in self._cache

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        return self._cache.stats