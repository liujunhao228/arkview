"""
Cache service implementation for Arkview.
Provides a high-level interface for cache management.
"""

from typing import Optional, Any, Dict
from PIL import Image
import time
import threading

from ..core.cache import LRUCache


class CacheStats:
    """缓存统计信息"""
    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.errors = 0
        self.last_access_time = 0.0
        self._lock = threading.Lock()
        
    @property
    def hit_rate(self) -> float:
        """计算缓存命中率"""
        total = self.hits + self.misses
        return (self.hits / total) if total > 0 else 0.0
        
    def record_hit(self):
        with self._lock:
            self.hits += 1
            self.last_access_time = time.time()
            
    def record_miss(self):
        with self._lock:
            self.misses += 1
            
    def record_eviction(self):
        with self._lock:
            self.evictions += 1
            
    def record_error(self):
        with self._lock:
            self.errors += 1
            
    def reset(self):
        with self._lock:
            self.hits = 0
            self.misses = 0
            self.evictions = 0
            self.errors = 0
            self.last_access_time = 0.0


class EnhancedCacheService:
    """增强的缓存服务"""
    
    def __init__(self, capacity: int = 50):
        self.primary_cache = LRUCache(capacity)
        self.thumbnail_cache = LRUCache(capacity // 2)  # 专门用于缩略图
        self.metadata_cache = LRUCache(100)  # 用于元数据缓存
        self.stats = CacheStats()
        self._lock = threading.RLock()
        
    def get(self, key: tuple, cache_type: str = "primary") -> Optional[Image.Image]:
        """从指定缓存获取数据"""
        try:
            cache = self._get_cache_by_type(cache_type)
            result = cache.get(key)
            if result is not None:
                self.stats.record_hit()
            else:
                self.stats.record_miss()
            return result
        except Exception as e:
            self.stats.record_error()
            print(f"Cache get error: {e}")
            return None
            
    def put(self, key: tuple, value: Image.Image, cache_type: str = "primary"):
        """向指定缓存添加数据"""
        try:
            if not isinstance(value, Image.Image):
                print(f"Cache Warning: Attempted to cache non-Image object for key {key}")
                self.stats.record_error()
                return
                
            cache = self._get_cache_by_type(cache_type)
            cache.put(key, value)
        except Exception as e:
            self.stats.record_error()
            print(f"Cache put error: {e}")
            
    def _get_cache_by_type(self, cache_type: str):
        """根据类型获取对应缓存实例"""
        caches = {
            "primary": self.primary_cache,
            "thumbnail": self.thumbnail_cache,
            "metadata": self.metadata_cache
        }
        return caches.get(cache_type, self.primary_cache)
        
    def clear(self, cache_type: str = "all"):
        """清空指定缓存或所有缓存"""
        with self._lock:
            if cache_type == "all":
                self.primary_cache.clear()
                self.thumbnail_cache.clear()
                self.metadata_cache.clear()
            else:
                cache = self._get_cache_by_type(cache_type)
                cache.clear()
                
    def resize(self, new_capacity: int, cache_type: str = "all"):
        """调整缓存容量"""
        with self._lock:
            if cache_type == "all":
                self.primary_cache.resize(new_capacity)
                self.thumbnail_cache.resize(new_capacity // 2)
                self.metadata_cache.resize(100)
            else:
                cache = self._get_cache_by_type(cache_type)
                if cache_type == "thumbnail":
                    cache.resize(new_capacity // 2)
                else:
                    cache.resize(new_capacity)
                    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            "primary": {
                "size": len(self.primary_cache),
                "capacity": getattr(self.primary_cache, 'capacity', 'unknown'),
                "hit_rate": self.primary_cache.hit_rate
            },
            "thumbnail": {
                "size": len(self.thumbnail_cache),
                "capacity": getattr(self.thumbnail_cache, 'capacity', 'unknown'),
                "hit_rate": self.thumbnail_cache.hit_rate
            },
            "metadata": {
                "size": len(self.metadata_cache),
                "capacity": getattr(self.metadata_cache, 'capacity', 'unknown'),
                "hit_rate": self.metadata_cache.hit_rate
            },
            "stats": {
                "hits": self.stats.hits,
                "misses": self.stats.misses,
                "hit_rate": self.stats.hit_rate,
                "evictions": self.stats.evictions,
                "errors": self.stats.errors
            }
        }


# 为了向后兼容，保留原有的CacheService类
class CacheService:
    """向后兼容的服务类"""
    
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