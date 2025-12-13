"""
Cache service implementation for Arkview.
Provides a high-level interface for cache management.
"""

from typing import Optional, Any, Dict
from PIL import Image

from ..core.unified_cache import UnifiedCacheService, CacheStrategy


class CacheService:
    """Simplified cache service using the unified cache backend."""

    def __init__(self, capacity: int = 50, strategy: CacheStrategy = CacheStrategy.LRU,
                 max_memory_mb: float = 200):
        self.service = UnifiedCacheService(
            capacity=capacity,
            strategy=strategy,
            max_memory_mb=max_memory_mb
        )

    def get(self, key: tuple) -> Optional[Image.Image]:
        """从缓存获取数据"""
        return self.service.get(key)

    def put(self, key: tuple, value: Image.Image):
        """将数据放入缓存"""
        self.service.put(key, value)

    def clear(self):
        """清空缓存"""
        self.service.clear()

    def resize(self, new_capacity: int):
        """调整缓存容量"""
        self.service.resize(new_capacity)

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return self.service.get_stats()

    def update_strategy(self, new_strategy: CacheStrategy):
        """更新缓存策略"""
        self.service.update_strategy(new_strategy)

    def __len__(self) -> int:
        """返回缓存中的项目数"""
        return len(self.service)

    def __contains__(self, key: tuple) -> bool:
        """检查键是否存在于缓存中"""
        return key in self.service