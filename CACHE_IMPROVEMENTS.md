# Arkview 缓存系统改进说明

## 概述

本改进旨在提升 Arkview 的缓存管理能力，主要包括以下几个方面：

1. **统一缓存接口** - 提供一致的缓存访问接口
2. **多级缓存策略** - 针对不同类型的数据使用专门的缓存
3. **改进的缓存键设计** - 确保不同尺寸的图像使用不同的缓存键
4. **缓存统计和监控** - 提供详细的缓存使用情况报告
5. **增强的内存管理** - 更好地释放不再需要的图像资源

## 新增组件

### EnhancedCacheService

这是新的缓存服务类，提供了多级缓存和统计功能。

#### 初始化

```python
from ..services.cache_service import EnhancedCacheService

cache_service = EnhancedCacheService(capacity=50)
```

#### 多级缓存

EnhancedCacheService 提供三种缓存类型：

1. **primary_cache** - 主缓存，用于存储完整尺寸的图像
2. **thumbnail_cache** - 缩略图缓存，容量为主缓存的一半
3. **metadata_cache** - 元数据缓存，固定容量100

#### 使用方法

```python
# 存储数据到特定缓存
cache_service.put(key, image, cache_type="thumbnail")

# 从特定缓存获取数据
cached_image = cache_service.get(key, cache_type="thumbnail")

# 清空缓存
cache_service.clear("thumbnail")  # 清空特定缓存
cache_service.clear("all")        # 清空所有缓存

# 调整缓存容量
cache_service.resize(100, "all")  # 调整所有缓存容量

# 获取统计信息
stats = cache_service.get_stats()
```

### 改进的缓存键设计

为了防止不同尺寸的图像使用相同的缓存键，我们引入了 `_generate_cache_key` 函数：

```python
def _generate_cache_key(zip_path: str, member_name: str, target_size: Optional[Tuple[int, int]]) -> tuple:
    if target_size is None:
        return (zip_path, member_name, "original")
    else:
        width, height = target_size
        return (zip_path, member_name, f"{width}x{height}")
```

这确保了相同图像的不同尺寸版本使用不同的缓存键。

## 使用示例

### 在服务层使用

```python
# 在 ImageService 中
enhanced_cache_key = _generate_cache_key(zip_path, member_name, target_size)
cache_type = "thumbnail" if target_size is not None else "primary"

# 获取缓存数据
cached_image = self.cache_service.get(enhanced_cache_key, cache_type)

# 存储缓存数据
self.cache_service.put(enhanced_cache_key, img, cache_type)
```

### 在 UI 层使用

```python
# 在 MainWindow 中初始化
self.cache_service = EnhancedCacheService(CONFIG["CACHE_MAX_ITEMS_NORMAL"])

# 查看缓存统计信息
stats = self.cache_service.get_stats()
print(f"缓存命中率: {stats['stats']['hit_rate']:.2%}")
```

## 向后兼容性

为了保持向后兼容性，原有的 `CacheService` 类仍然可用，但它已经被标记为遗留实现。建议新代码使用 `EnhancedCacheService`。

## 性能优化建议

1. **合理设置缓存容量** - 根据可用内存和使用模式调整各缓存的容量
2. **监控缓存命中率** - 使用 `get_stats()` 方法监控缓存效果
3. **及时清理缓存** - 在适当的时候清理不再需要的缓存数据
4. **使用合适的缓存类型** - 根据数据特征选择合适的缓存类型

## 内存管理

新的缓存实现在以下方面改进了内存管理：

1. **自动关闭图像** - 当图像从缓存中被驱逐时，自动调用 `close()` 方法释放资源
2. **容量控制** - 严格控制缓存容量，防止内存无限增长
3. **及时清理** - 提供清理接口，在必要时手动释放缓存

通过这些改进，Arkview 的缓存系统现在更加高效和可靠。