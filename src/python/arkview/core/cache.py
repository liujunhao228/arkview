"""
LRU Cache implementation for Arkview core layer.
This module now serves as a wrapper for the unified cache service.
"""

from .unified_cache import UnifiedCacheService, CacheStrategy


# 保留原始LRUCache接口以向后兼容
class LRUCache:
    """Wrapper for the UnifiedCacheService using LRU strategy."""

    def __init__(self, capacity: int, on_evict=None):
        self.service = UnifiedCacheService(
            capacity=capacity,
            strategy=CacheStrategy.LRU,
        )
        self.capacity = capacity

    def get(self, key: tuple):
        return self.service.get(key)

    def put(self, key: tuple, value):
        self.service.put(key, value)

    def clear(self):
        self.service.clear()

    def resize(self, new_capacity: int):
        self.service.resize(new_capacity)

    def __len__(self):
        return len(self.service)

    def __contains__(self, key: tuple):
        return key in self.service

    def get_memory_usage(self):
        stats = self.service.get_stats()
        return stats.get('memory_usage', 0)

    @property
    def hit_rate(self):
        stats = self.service.get_stats()
        total = stats['hits'] + stats['misses']
        return (stats['hits'] / total) if total > 0 else 0.0


# 保留原始AdaptiveLRUCache接口以向后兼容
class AdaptiveLRUCache:
    """Wrapper for the UnifiedCacheService using adaptive strategy."""

    def __init__(self, capacity: int, min_capacity: int = 10, max_capacity: int = 200):
        self.service = UnifiedCacheService(
            capacity=capacity,
            strategy=CacheStrategy.ADAPTIVE,
        )
        self.capacity = capacity

    def get(self, key: tuple):
        return self.service.get(key)

    def put(self, key: tuple, value):
        self.service.put(key, value)

    def clear(self):
        self.service.clear()

    def resize(self, new_capacity: int):
        self.service.resize(new_capacity)

    def __len__(self):
        return len(self.service)

    def __contains__(self, key: tuple):
        return key in self.service

    def get_memory_usage(self):
        stats = self.service.get_stats()
        return stats.get('memory_usage', 0)

    @property
    def hit_rate(self):
        stats = self.service.get_stats()
        total = stats['hits'] + stats['misses']
        return (stats['hits'] / total) if total > 0 else 0.0


class SmartCacheStrategy:
    """智能缓存策略，根据不同使用场景选择合适的缓存方式"""

    def __init__(self, cache_service):
        self.cache_service = cache_service
        self.usage_patterns = {}  # 记录不同图片的使用模式

    def determine_cache_type(self, zip_path: str, member_name: str,
                           target_size=None):
        """
        根据使用模式决定应该使用哪种缓存类型

        Args:
            zip_path: ZIP文件路径
            member_name: 成员名称
            target_size: 目标尺寸

        Returns:
            str: 缓存类型 ("primary", "thumbnail", "metadata")
        """
        key = (zip_path, member_name)

        # 如果是原始尺寸图像，使用主缓存
        if target_size is None:
            return "primary"

        # 如果是缩略图尺寸，使用缩略图缓存
        # 这里可以根据具体尺寸阈值进行判断
        if target_size:
            width, height = target_size
            if width <= 300 and height <= 300:
                return "thumbnail"
        return "primary"

    def record_usage(self, zip_path: str, member_name: str):
        """记录图片使用情况"""
        key = (zip_path, member_name)
        if key not in self.usage_patterns:
            self.usage_patterns[key] = {"access_count": 0, "last_access": 0}

        self.usage_patterns[key]["access_count"] += 1
        import time
        self.usage_patterns[key]["last_access"] = time.time()

    def should_preload(self, zip_path: str, member_name: str) -> bool:
        """判断是否应该预加载该图片"""
        key = (zip_path, member_name)
        pattern = self.usage_patterns.get(key, {})
        access_count = pattern.get("access_count", 0)

        # 如果访问次数超过阈值，则值得预加载
        return access_count > 3