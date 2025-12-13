"""
Service layer package for Arkview.
This package contains all business logic services that act as intermediaries
between the UI layer and the core layer.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple, List
from PIL import Image


class CacheServiceInterface(ABC):
    """缓存服务接口定义"""
    
    @abstractmethod
    def get(self, key: tuple) -> Optional[Image.Image]:
        """从缓存获取数据"""
        pass
    
    @abstractmethod
    def put(self, key: tuple, value: Image.Image):
        """将数据放入缓存"""
        pass
    
    @abstractmethod
    def clear(self):
        """清空缓存"""
        pass
    
    @abstractmethod
    def resize(self, new_capacity: int):
        """调整缓存容量"""
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        pass
    
    @abstractmethod
    def __len__(self) -> int:
        """返回缓存中的项目数"""
        pass
    
    @abstractmethod
    def __contains__(self, key: tuple) -> bool:
        """检查键是否存在于缓存中"""
        pass


class ConfigServiceInterface(ABC):
    """配置服务接口定义"""
    
    @abstractmethod
    def get_setting(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        pass
    
    @abstractmethod
    def set_setting(self, key: str, value: Any):
        """设置配置项"""
        pass
    
    @abstractmethod
    def save_settings(self):
        """保存配置项"""
        pass


class ImageServiceInterface(ABC):
    """图像服务接口定义"""
    
    @abstractmethod
    def load_image_data_async(self, zip_path: str, member_name: str, max_load_size: int,
                              target_size: Optional[Tuple[int, int]], cache_key: tuple,
                              performance_mode: bool, force_reload: bool = False) -> Optional[object]:
        """异步加载图像数据"""
        pass


class ThumbnailServiceInterface(ABC):
    """缩略图服务接口定义"""
    
    @abstractmethod
    def request_thumbnail(self, zip_path: str, member_path: str, cache_key: tuple,
                         max_size: int, resize_params: tuple, performance_mode: bool):
        """请求加载缩略图"""
        pass
    
    @abstractmethod
    def stop_service(self):
        """停止服务"""
        pass


class ZipServiceInterface(ABC):
    """ZIP文件服务接口定义"""
    
    @abstractmethod
    def analyze_zip(self, zip_path: str, collect_members: bool = True) -> Tuple[bool, Optional[List[str]], Optional[float], Optional[int], int]:
        """分析ZIP文件"""
        pass
    
    @abstractmethod
    def batch_analyze_zips(self, zip_paths: List[str], collect_members: bool = True) -> List[Tuple[str, bool, Optional[List[str]], Optional[float], Optional[int], int]]:
        """批量分析ZIP文件"""
        pass


# 初始化services模块

from .simple_cache_service import SimpleCacheService
from .config_service import ConfigService
from .image_service import ImageService
from .thumbnail_service import ThumbnailService
from .zip_service import ZipService
from .simple_cache_service import SimpleCacheService
from .navigation_service import NavigationService
from .playlist_service import PlaylistService, OptimizedPlaylistService
from .simple_cache_service import SimpleCacheService
# 添加新的服务
from .slideshow_service import SlideshowService

__all__ = [
    'ConfigService',
    'ImageService', 
    'ThumbnailService',
    'ZipService',
    'SimpleCacheService',
    'NavigationService',
    'PlaylistService',
    'OptimizedPlaylistService',
    'SlideshowService'
]