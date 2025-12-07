"""
LRU Cache implementation for Arkview core layer.
"""

import threading
from typing import Optional, OrderedDict
from collections import OrderedDict as CollectionsOrderedDict
from PIL import Image


class LRUCache:
    """Simple Least Recently Used (LRU) cache for Image objects."""
    
    def __init__(self, capacity: int):
        self.cache: OrderedDict = CollectionsOrderedDict()
        self.capacity = capacity
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Optional[Image.Image]:
        """Retrieve an item from the cache."""
        with self._lock:
            if key not in self.cache:
                return None
            else:
                self.cache.move_to_end(key)
                return self.cache[key]

    def put(self, key: tuple, value: Image.Image):
        """Add an item to the cache."""
        if not isinstance(value, Image.Image):
            print(f"Cache Warning: Attempted to cache non-Image object for key {key}")
            return
            
        with self._lock:
            try:
                # Ensure image is fully loaded before caching
                if hasattr(value, 'load'):
                    value.load()
            except Exception as e:
                print(f"Cache Warning: Failed to load image data before caching key {key}: {e}")
                return

            if key in self.cache:
                self.cache[key] = value
                self.cache.move_to_end(key)
            else:
                if len(self.cache) >= self.capacity:
                    # Remove oldest entry
                    evicted_key, evicted_image = self.cache.popitem(last=False)
                    try:
                        # Close evicted image to free memory
                        if hasattr(evicted_image, 'close'):
                            evicted_image.close()
                    except Exception:
                        pass
                self.cache[key] = value

    def clear(self):
        """Clear all items from the cache."""
        with self._lock:
            # Close images to free memory
            for _, image in self.cache.items():
                try:
                    if hasattr(image, 'close'):
                        image.close()
                except Exception:
                    pass
            self.cache.clear()

    def resize(self, new_capacity: int):
        """Resize the cache capacity."""
        if new_capacity <= 0:
            raise ValueError("Cache capacity must be positive.")
        with self._lock:
            self.capacity = new_capacity
            while len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    def __len__(self) -> int:
        """Return the number of items in the cache."""
        with self._lock:
            return len(self.cache)

    def __contains__(self, key: tuple) -> bool:
        """Check if a key exists in the cache."""
        with self._lock:
            return key in self.cache