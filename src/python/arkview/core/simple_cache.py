"""
Simple LRU Cache implementation for Arkview.
A simplified alternative to the complex caching system.
"""

import threading
from collections import OrderedDict
from typing import Optional, Tuple
from PIL import Image


class SimpleLRUCache:
    """A simple LRU cache implementation for Image objects."""
    
    def __init__(self, capacity: int = 50):
        """
        Initialize the cache with a fixed capacity.
        
        Args:
            capacity: Maximum number of items to store in the cache
        """
        if capacity <= 0:
            raise ValueError("Cache capacity must be positive")
            
        self._cache: OrderedDict = OrderedDict()
        self._capacity = capacity
        self._lock = threading.RLock()
        
        # Statistics
        self._access_count = 0
        self._hit_count = 0

    def get(self, key: Tuple) -> Optional[Image.Image]:
        """
        Retrieve an item from the cache.
        
        Args:
            key: Cache key (typically a tuple identifying the image)
            
        Returns:
            Cached Image object or None if not found
        """
        with self._lock:
            self._access_count += 1
            
            if key not in self._cache:
                return None
                
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hit_count += 1
            return self._cache[key]

    def put(self, key: Tuple, value: Image.Image):
        """
        Add an item to the cache.
        
        Args:
            key: Cache key
            value: Image object to cache
        """
        if not isinstance(value, Image.Image):
            print(f"Cache Warning: Attempted to cache non-Image object for key {key}")
            return
            
        with self._lock:
            # Ensure image is fully loaded before caching
            try:
                if hasattr(value, 'load'):
                    value.load()
            except Exception as e:
                print(f"Cache Warning: Failed to load image data before caching key {key}: {e}")
                return

            if key in self._cache:
                # Update existing entry
                self._cache[key] = value
                self._cache.move_to_end(key)
            else:
                # Add new entry
                if len(self._cache) >= self._capacity:
                    # Remove least recently used entry (first item)
                    removed_key, removed_image = self._cache.popitem(last=False)
                    try:
                        if hasattr(removed_image, 'close'):
                            removed_image.close()
                    except Exception:
                        pass
                        
                self._cache[key] = value

    def clear(self):
        """Clear all items from the cache."""
        with self._lock:
            # Close images to free memory
            for _, image in self._cache.items():
                try:
                    if hasattr(image, 'close'):
                        image.close()
                except Exception:
                    pass
            self._cache.clear()
            
            # Reset statistics
            self._access_count = 0
            self._hit_count = 0

    def resize(self, new_capacity: int):
        """
        Resize the cache capacity.
        
        Args:
            new_capacity: New cache capacity
        """
        if new_capacity <= 0:
            raise ValueError("Cache capacity must be positive")
            
        with self._lock:
            self._capacity = new_capacity
            # Remove excess items if new capacity is smaller
            while len(self._cache) > self._capacity:
                key, image = self._cache.popitem(last=False)
                try:
                    if hasattr(image, 'close'):
                        image.close()
                except Exception:
                    pass

    def __len__(self) -> int:
        """Return the number of items in the cache."""
        with self._lock:
            return len(self._cache)

    def __contains__(self, key: Tuple) -> bool:
        """Check if a key exists in the cache."""
        with self._lock:
            return key in self._cache

    @property
    def hit_rate(self) -> float:
        """Calculate and return the cache hit rate."""
        with self._lock:
            if self._access_count == 0:
                return 0.0
            return self._hit_count / self._access_count

    @property
    def capacity(self) -> int:
        """Return the cache capacity."""
        return self._capacity

    @property
    def stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            return {
                'size': len(self._cache),
                'capacity': self._capacity,
                'access_count': self._access_count,
                'hit_count': self._hit_count,
                'hit_rate': self.hit_rate
            }