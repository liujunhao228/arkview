"""
Image service implementation for Arkview.
Handles image loading, processing and transformation operations.
"""

import io
from typing import Optional, Tuple
from PIL import Image, ImageOps, UnidentifiedImageError

from ..core.models import LoadResult
from ..core.file_manager import ZipFileManager


def _format_size(size_bytes: int) -> str:
    """Formats byte size into a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.1f} GB"


def _generate_cache_key(zip_path: str, member_name: str, target_size: Optional[Tuple[int, int]]) -> tuple:
    """
    生成缓存键，确保不同尺寸的图像使用不同的键
    
    Args:
        zip_path: ZIP文件路径
        member_name: ZIP内成员名称
        target_size: 目标尺寸 (width, height) 或 None 表示原始尺寸
        
    Returns:
        tuple: 缓存键
    """
    if target_size is None:
        return (zip_path, member_name, "original")
    else:
        width, height = target_size
        return (zip_path, member_name, f"{width}x{height}")


class ImageService:
    """Service for handling image loading and processing operations."""
    
    def __init__(self, cache_service, zip_manager: ZipFileManager):
        # 支持两种类型的缓存服务以保持向后兼容
        self.cache_service = cache_service
        self.zip_manager = zip_manager
        # 判断是否使用增强的缓存服务
        self.use_enhanced_cache = hasattr(cache_service, 'get_stats')

    def load_image_data_async(
        self,
        zip_path: str,
        member_name: str,
        max_load_size: int,
        target_size: Optional[Tuple[int, int]],
        cache_key: tuple,
        performance_mode: bool,
        force_reload: bool = False
    ) -> Optional[LoadResult]:
        """
        Asynchronously loads image data from a ZIP archive member.
        This method can be called synchronously but is designed to work with async patterns.
        """
        # 使用改进的缓存键生成方法
        enhanced_cache_key = _generate_cache_key(zip_path, member_name, target_size)
        
        # 确定使用哪种缓存类型
        cache_type = "thumbnail" if target_size is not None else "primary"
        
        # 尝试从缓存获取
        if not force_reload:
            cached_image = None
            if self.use_enhanced_cache:
                cached_image = self.cache_service.get(enhanced_cache_key, cache_type)
            else:
                cached_image = self.cache_service.get(enhanced_cache_key)
                
            if cached_image is not None:
                try:
                    if target_size:
                        img_to_process = cached_image.copy()
                        resampling_method = (
                            Image.Resampling.NEAREST if performance_mode
                            else Image.Resampling.LANCZOS
                        )
                        img_to_process.thumbnail(target_size, resampling_method)
                        result = LoadResult(success=True, data=img_to_process, cache_key=enhanced_cache_key)
                    else:
                        # Return the cached image directly if no resizing needed
                        result = LoadResult(success=True, data=cached_image, cache_key=enhanced_cache_key)
                    
                    return result
                except Exception as e:
                    print(f"Async Load Warning: Error processing cached image for {enhanced_cache_key}: {e}")
        
        # 缓存未命中或强制重新加载，执行实际加载
        try:
            # 获取ZIP文件句柄
            zip_file = self.zip_manager.get_zipfile(zip_path)
            if zip_file is None:
                return LoadResult(success=False, error_message="Failed to open ZIP file", cache_key=enhanced_cache_key)
            
            # 读取图像数据
            with zip_file.open(member_name) as file:
                image_data = file.read()
            
            # 加载图像
            img = Image.open(io.BytesIO(image_data))
            
            # 根据目标尺寸处理图像
            if target_size:
                resampling_method = (
                    Image.Resampling.NEAREST if performance_mode
                    else Image.Resampling.LANCZOS
                )
                img.thumbnail(target_size, resampling_method)
            
            # 缓存处理后的图像
            if self.use_enhanced_cache:
                self.cache_service.put(enhanced_cache_key, img, cache_type)
            else:
                self.cache_service.put(enhanced_cache_key, img)
            
            result = LoadResult(success=True, data=img, cache_key=enhanced_cache_key)
            return result
            
        except Exception as e:
            error_msg = f"Failed to load image {member_name} from {zip_path}: {str(e)}"
            print(error_msg)
            return LoadResult(success=False, error_message=error_msg, cache_key=enhanced_cache_key)