"""
Simple cache service implementation for Arkview.
Provides a simplified interface for cache management.
"""

from typing import Optional, Dict, Any
from PIL import Image

from ..core.simple_cache import SimpleLRUCache


class SimpleCacheService:
    """Simplified cache service using the simple LRU cache backend.

    Note: cache keys are plain tuples. See :mod:`arkview.core.cache_keys` for the
    recommended key helpers that explicitly separate thumbnails/originals and
    different resolutions.
    """

    def __init__(self, capacity: int = 50):
        """Initialize the cache service.

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
        """Get cache statistics."""
        return self._cache.stats

    def get_detailed_stats(self) -> Dict[str, Any]:
        """Compatibility helper for older UI code.

        The legacy UI expected a richer stats payload. We keep it lightweight and
        avoid expensive per-key analysis here.
        """

        return {"stats": self.get_stats()}

    def resize_cache(self, new_capacity: int):
        """Compatibility alias for :meth:`resize`."""
        self.resize(new_capacity)