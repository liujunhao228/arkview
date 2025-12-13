"""
Unified cache service for Arkview application.
Combines LRU, LFU, and adaptive cache strategies in a single interface.
"""

import threading
import time
import gc
from typing import Optional, Any, Dict, Callable, Union
from collections import defaultdict
from PIL import Image
from enum import Enum

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class CacheStrategy(Enum):
    """Enumeration of supported cache strategies"""
    LRU = "lru"
    LFU = "lfu"
    ADAPTIVE = "adaptive"


class UnifiedCacheService:
    """Unified cache service supporting multiple cache algorithms."""

    def __init__(self, capacity: int = 50, strategy: CacheStrategy = CacheStrategy.LRU,
                 max_memory_mb: float = 200):
        self.capacity = capacity
        self.strategy = strategy
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self._lock = threading.RLock()
        
        # 初始化基础统计
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'errors': 0,
            'access_count': 0,
        }
        
        # 根据策略创建对应的缓存实例
        if strategy == CacheStrategy.LRU:
            self.cache_impl = LRUCacheImpl(capacity, self._on_evict)
        elif strategy == CacheStrategy.LFU:
            self.cache_impl = LFUCacheImpl(capacity, self.max_memory_bytes, self._on_evict)
        elif strategy == CacheStrategy.ADAPTIVE:
            self.cache_impl = AdaptiveLRUCacheImpl(capacity, self._on_evict)
        else:
            raise ValueError(f"Unsupported cache strategy: {strategy}")

    def _on_evict(self, key: tuple, value: Image.Image):
        """当缓存项被驱逐时的回调函数"""
        self.stats['evictions'] += 1

    def get(self, key: tuple) -> Optional[Image.Image]:
        """从缓存获取数据"""
        try:
            with self._lock:
                self.stats['access_count'] += 1
                result = self.cache_impl.get(key)
                if result is not None:
                    self.stats['hits'] += 1
                else:
                    self.stats['misses'] += 1
                return result
        except Exception as e:
            self.stats['errors'] += 1
            print(f"Cache get error: {e}")
            return None

    def put(self, key: tuple, value: Image.Image):
        """向缓存添加数据"""
        if not isinstance(value, Image.Image):
            print(f"Cache Warning: Attempted to cache non-Image object for key {key}")
            return

        try:
            with self._lock:
                self.cache_impl.put(key, value)
        except Exception as e:
            self.stats['errors'] += 1
            print(f"Cache put error: {e}")

    def clear(self):
        """清空缓存"""
        try:
            with self._lock:
                self.cache_impl.clear()
        except Exception as e:
            self.stats['errors'] += 1
            print(f"Cache clear error: {e}")

    def resize(self, new_capacity: int):
        """调整缓存容量"""
        if new_capacity <= 0:
            raise ValueError("Cache capacity must be positive.")
        try:
            with self._lock:
                self.capacity = new_capacity
                self.cache_impl.resize(new_capacity)
        except Exception as e:
            self.stats['errors'] += 1
            print(f"Cache resize error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            base_stats = self.stats.copy()
            base_stats['size'] = len(self.cache_impl)
            base_stats['capacity'] = self.capacity
            base_stats['hit_rate'] = self._calculate_hit_rate()
            base_stats['memory_usage'] = getattr(self.cache_impl, 'get_memory_usage', lambda: 0)()
            
            # 添加系统内存信息
            if PSUTIL_AVAILABLE:
                base_stats['system_memory_percent'] = psutil.virtual_memory().percent
                
            return base_stats

    def _calculate_hit_rate(self) -> float:
        """计算缓存命中率"""
        total = self.stats['hits'] + self.stats['misses']
        return (self.stats['hits'] / total) if total > 0 else 0.0

    def __len__(self) -> int:
        """返回缓存中的项目数"""
        return len(self.cache_impl)

    def __contains__(self, key: tuple) -> bool:
        """检查键是否存在于缓存中"""
        return key in self.cache_impl

    def update_strategy(self, new_strategy: CacheStrategy):
        """在运行时更新缓存策略"""
        with self._lock:
            # 保存当前缓存内容
            current_items = {}
            if hasattr(self.cache_impl, 'get_all_items'):
                current_items = self.cache_impl.get_all_items()
            
            # 创建新的缓存实现
            if new_strategy == CacheStrategy.LRU:
                self.cache_impl = LRUCacheImpl(self.capacity, self._on_evict)
            elif new_strategy == CacheStrategy.LFU:
                self.cache_impl = LFUCacheImpl(self.capacity, self.max_memory_bytes, self._on_evict)
            elif new_strategy == CacheStrategy.ADAPTIVE:
                self.cache_impl = AdaptiveLRUCacheImpl(self.capacity, self._on_evict)
            else:
                raise ValueError(f"Unsupported cache strategy: {new_strategy}")
            
            # 恢复缓存内容
            for key, value in current_items.items():
                self.cache_impl.put(key, value)
            
            self.strategy = new_strategy


class LRUCacheImpl:
    """LRU缓存实现"""
    
    def __init__(self, capacity: int, on_evict: Optional[Callable] = None):
        self.cache = {}
        self.capacity = capacity
        self._lock = threading.RLock()
        self.on_evict = on_evict  # 回调函数，当元素被驱逐时调用
        self.memory_usage = 0  # 当前内存使用量
        self.image_sizes = {}  # 存储每个图像的估算大小

    def _estimate_image_memory(self, image: Image.Image) -> int:
        """估算图像内存占用"""
        try:
            width, height = image.size
            # 考虑色彩通道数量和每通道位数
            channels = len(image.getbands())
            # 假设每通道8位（1字节）或16位（2字节）
            bytes_per_channel = 2 if image.mode in ("I", "F") else 1  # 32位整数或浮点数为2字节
            estimated_size = width * height * channels * bytes_per_channel
            # 加上额外的元数据开销
            return estimated_size + 1024  # 额外1KB元数据开销
        except Exception:
            # 出现异常时给出保守估计
            return 1024 * 1024  # 1MB默认值

    def get(self, key: tuple) -> Optional[Image.Image]:
        """获取缓存项"""
        with self._lock:
            if key not in self.cache:
                return None
            else:
                # 更新访问时间（LRU机制）
                value = self.cache[key]
                # 对于LRU，我们实际上需要一个有序字典结构，这里简化处理
                return value

    def put(self, key: tuple, value: Image.Image):
        """添加缓存项"""
        with self._lock:
            try:
                # 确保图像完全加载
                if hasattr(value, 'load'):
                    value.load()
            except Exception as e:
                print(f"Cache Warning: Failed to load image data before caching key {key}: {e}")
                return

            # 估算图像内存占用
            estimated_size = self._estimate_image_memory(value)

            if key in self.cache:
                # 更新现有项，调整内存用量
                old_size = self.image_sizes.get(key, 0)
                self.memory_usage = self.memory_usage - old_size + estimated_size
                self.image_sizes[key] = estimated_size
                self.cache[key] = value
            else:
                # 添加新项
                self.image_sizes[key] = estimated_size
                self.memory_usage += estimated_size

                if len(self.cache) >= self.capacity:
                    # 移除最久未使用的项（这里简化为移除第一个项）
                    evicted_key, evicted_image = next(iter(self.cache.items()))
                    self.cache.pop(evicted_key)
                    evicted_size = self.image_sizes.pop(evicted_key, 0)
                    self.memory_usage -= evicted_size
                    try:
                        # 关闭被驱逐的图像以释放内存
                        if hasattr(evicted_image, 'close'):
                            evicted_image.close()
                        # 调用回调函数
                        if self.on_evict:
                            self.on_evict(evicted_key, evicted_image)
                    except Exception as e:
                        print(f"Cache Warning: Error closing evicted image: {e}")
                self.cache[key] = value

    def clear(self):
        """清空缓存"""
        with self._lock:
            # 关闭图像以释放内存
            for key, image in self.cache.items():
                try:
                    if hasattr(image, 'close'):
                        image.close()
                    # 调用回调函数
                    if self.on_evict:
                        self.on_evict(key, image)
                except Exception as e:
                    print(f"Cache Warning: Error closing image during clear: {e}")
            self.cache.clear()
            self.image_sizes.clear()
            self.memory_usage = 0

    def resize(self, new_capacity: int):
        """调整容量"""
        with self._lock:
            old_capacity = self.capacity
            self.capacity = new_capacity
            while len(self.cache) > self.capacity:
                # 移除最久未使用的项
                evicted_key, evicted_image = next(iter(self.cache.items()))
                self.cache.pop(evicted_key)
                evicted_size = self.image_sizes.pop(evicted_key, 0)
                self.memory_usage -= evicted_size
                try:
                    if hasattr(evicted_image, 'close'):
                        evicted_image.close()
                    # 调用回调函数
                    if self.on_evict:
                        self.on_evict(evicted_key, evicted_image)
                except Exception as e:
                    print(f"Cache Warning: Error closing evicted image during resize: {e}")

    def get_memory_usage(self) -> int:
        """获取内存使用量"""
        with self._lock:
            return self.memory_usage

    def __len__(self) -> int:
        with self._lock:
            return len(self.cache)

    def __contains__(self, key: tuple) -> bool:
        with self._lock:
            return key in self.cache

    def get_all_items(self) -> Dict:
        """获取所有缓存项（用于策略切换）"""
        with self._lock:
            return self.cache.copy()


class LFUCacheImpl:
    """LFU缓存实现"""
    
    def __init__(self, capacity: int, max_memory_bytes: int = 200 * 1024 * 1024, on_evict: Optional[Callable] = None):
        self.cache = {}  # key -> (value, frequency)
        self.frequency_list = defaultdict(list)  # frequency -> keys
        self.capacity = capacity
        self.min_frequency = 0
        self.memory_usage = 0
        self.max_memory_bytes = max_memory_bytes
        self._lock = threading.RLock()
        self.on_evict = on_evict
        self.image_sizes = {}  # 存储每个图像的估算大小

    def _estimate_image_memory(self, image: Image.Image) -> int:
        """估算图像内存占用"""
        try:
            width, height = image.size
            # 考虑色彩通道数量和每通道位数
            channels = len(image.getbands())
            # 假设每通道8位（1字节）或16位（2字节）
            bytes_per_channel = 2 if image.mode in ("I", "F") else 1  # 32位整数或浮点数为2字节
            estimated_size = width * height * channels * bytes_per_channel
            # 加上额外的元数据开销
            return estimated_size + 1024  # 额外1KB元数据开销
        except Exception:
            # 出现异常时给出保守估计
            return 1024 * 1024  # 1MB默认值

    def get(self, key: tuple) -> Optional[Image.Image]:
        """获取缓存项"""
        with self._lock:
            if key not in self.cache:
                return None
            else:
                value, freq = self.cache[key]
                # 更新频率
                self.frequency_list[freq].remove(key)
                if not self.frequency_list[freq] and self.min_frequency == freq:
                    self.min_frequency += 1
                self.cache[key] = (value, freq + 1)
                self.frequency_list[freq + 1].append(key)
                return value

    def put(self, key: tuple, value: Image.Image):
        """添加缓存项"""
        if not isinstance(value, Image.Image):
            print(f"Cache Warning: Attempted to cache non-Image object for key {key}")
            return

        with self._lock:
            try:
                # 确保图像完全加载
                if hasattr(value, 'load'):
                    value.load()
            except Exception as e:
                print(f"Cache Warning: Failed to load image data before caching key {key}: {e}")
                return

            # 估算图像内存占用
            estimated_size = self._estimate_image_memory(value)

            # 检查内存使用情况，若超限则进行清理
            if self.memory_usage + estimated_size > self.max_memory_bytes:
                self._evict_for_memory(estimated_size)

            if key in self.cache:
                # 更新现有项
                old_value, freq = self.cache[key]
                self.cache[key] = (value, freq + 1)
                self.frequency_list[freq].remove(key)
                self.frequency_list[freq + 1].append(key)
                self.memory_usage = self.memory_usage - self._estimate_image_memory(old_value) + estimated_size
            else:
                # 添加新项
                if len(self.cache) >= self.capacity:
                    # 移除最低频率项
                    self._evict()

                self.cache[key] = (value, 1)
                self.frequency_list[1].append(key)
                self.min_frequency = 1
                self.memory_usage += estimated_size
                self.image_sizes[key] = estimated_size

    def _evict(self):
        """移除最少使用的项"""
        if not self.frequency_list[self.min_frequency]:
            return

        # 获取要移除的键
        key_to_remove = self.frequency_list[self.min_frequency].pop(0)
        value, freq = self.cache.pop(key_to_remove, (None, None))
        size = self.image_sizes.pop(key_to_remove, 0)

        if value and hasattr(value, 'close'):
            try:
                value.close()
            except Exception:
                pass

        # 更新内存使用量
        if value:
            self.memory_usage -= size

        # 调用驱逐回调
        if value and self.on_evict:
            self.on_evict(key_to_remove, value)

    def _evict_for_memory(self, required_size: int):
        """为新数据腾出内存空间"""
        # 清理内存直到有足够的空间容纳新数据
        while self.memory_usage + required_size > self.max_memory_bytes and len(self.cache) > 0:
            # 根据驱逐策略移除项目
            self._evict()

        # 手动触发垃圾回收
        gc.collect()

    def clear(self):
        """清空缓存"""
        with self._lock:
            # 关闭图像以释放内存
            for key, (image, freq) in self.cache.items():
                try:
                    if hasattr(image, 'close'):
                        image.close()
                    # 调用回调函数
                    if self.on_evict:
                        self.on_evict(key, image)
                except Exception:
                    pass
            self.cache.clear()
            self.frequency_list.clear()
            self.image_sizes.clear()
            self.min_frequency = 0
            self.memory_usage = 0

    def resize(self, new_capacity: int):
        """调整容量"""
        if new_capacity <= 0:
            raise ValueError("Cache capacity must be positive.")
        with self._lock:
            old_capacity = self.capacity
            self.capacity = new_capacity
            while len(self.cache) > self.capacity:
                self._evict()

    def get_memory_usage(self) -> int:
        """获取内存使用量"""
        with self._lock:
            return self.memory_usage

    def __len__(self) -> int:
        with self._lock:
            return len(self.cache)

    def __contains__(self, key: tuple) -> bool:
        with self._lock:
            return key in self.cache

    def get_all_items(self) -> Dict:
        """获取所有缓存项（用于策略切换）"""
        with self._lock:
            # 返回值部分，不包括频率
            return {k: v[0] for k, v in self.cache.items()}


class AdaptiveLRUCacheImpl(LRUCacheImpl):
    """自适应LRU缓存实现"""
    
    def __init__(self, capacity: int, on_evict: Optional[Callable] = None, 
                 min_capacity: int = 10, max_capacity: int = 200):
        super().__init__(capacity, on_evict)
        self.min_capacity = min_capacity
        self.max_capacity = max_capacity
        self.recent_hit_rates = []  # 存储最近的命中率以进行趋势分析

    def adjust_capacity_based_on_performance(self):
        """根据近期性能调整缓存容量"""
        # 计算最近的平均命中率
        if len(self.recent_hit_rates) >= 5:
            avg_hit_rate = sum(self.recent_hit_rates[-5:]) / 5
            self.recent_hit_rates = self.recent_hit_rates[-5:]  # 保留最近5个值

            # 如果命中率较低且还有增长空间，则增加容量
            if avg_hit_rate < 0.7 and self.capacity < self.max_capacity:
                new_capacity = min(self.capacity + 5, self.max_capacity)
                self.resize(new_capacity)
            # 如果命中率较高且容量过大，则减小容量以节省内存
            elif avg_hit_rate > 0.9 and self.capacity > self.min_capacity:
                new_capacity = max(self.capacity - 5, self.min_capacity)
                self.resize(new_capacity)

    def get(self, key: tuple) -> Optional[Image.Image]:
        """获取缓存项"""
        result = super().get(key)
        return result

    def put(self, key: tuple, value: Image.Image):
        """添加缓存项，带容量自适应"""
        # 记录命中率以供后续调整
        if 'access_count' in dir(self):  # 检查是否有访问计数
            if self.access_count > 0:
                current_hit_rate = self.hit_rate
                self.recent_hit_rates.append(current_hit_rate)
                # 定期调整容量
                if len(self.recent_hit_rates) % 10 == 0:
                    self.adjust_capacity_based_on_performance()

        super().put(key, value)

    def resize(self, new_capacity: int):
        """调整容量"""
        super().resize(new_capacity)

    @property
    def hit_rate(self) -> float:
        """获取缓存命中率"""
        if self.access_count == 0:
            return 0.0
        return self.hits / self.access_count if hasattr(self, 'hits') and hasattr(self, 'access_count') else 0.0