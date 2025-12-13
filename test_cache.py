from src.python.arkview.services.cache_service import UnifiedCacheService
from PIL import Image
import tempfile
import os

# 创建一个简单的测试
cache = UnifiedCacheService(10)

# 创建一个简单的图像用于测试
img = Image.new('RGB', (100, 100), color='red')

# 测试放入缓存
cache.put(('test', 'key'), img)

# 测试从缓存获取
retrieved_img = cache.get(('test', 'key'))
print('Image retrieved from cache:', retrieved_img is not None)

# 测试缓存统计信息
stats = cache.get_stats()
print('Cache stats:', stats)

print('Test completed successfully')
