"""
Slideshow service for Arkview.
Optimized service for managing slideshow navigation across archives with reduced memory footprint.
"""

from typing import List, Optional, Tuple
from ..core.models import ZipFileInfo
import logging

# 设置日志记录器
logger = logging.getLogger(__name__)


class SlideshowService:
    """Optimized service for managing slideshow navigation with minimal memory footprint."""
    
    def __init__(self, zip_manager=None):
        # 只存储ZIP文件路径而不是完整对象，减少内存占用
        self.archive_paths: List[str] = []
        self.archive_cache: dict = {}  # 缓存最近访问的ZIP文件信息
        self.current_archive_index = 0
        self.current_image_index = 0
        self.loop_mode = False
        self._cache_size_limit = 10  # 限制缓存大小
        self._zip_manager = zip_manager  # ZipFileManager实例
        logger.debug("SlideshowService initialized")
    
    def set_zip_manager(self, zip_manager):
        """设置ZipFileManager实例"""
        self._zip_manager = zip_manager
    
    def set_archives(self, archives: List[ZipFileInfo]):
        """
        Set the list of archives to navigate through.
        Only stores paths to reduce memory footprint.
        """
        # 只存储路径而不是完整对象
        self.archive_paths = [archive.path for archive in archives]
        self.current_archive_index = 0
        self.current_image_index = 0
        self.archive_cache.clear()  # 清除旧缓存
        logger.debug(f"Archives set. Count: {len(self.archive_paths)}")
    
    def _get_archive_info(self, index: int) -> Optional[ZipFileInfo]:
        """
        Get archive info with caching to balance performance and memory usage.
        """
        if not (0 <= index < len(self.archive_paths)):
            return None
            
        archive_path = self.archive_paths[index]
        
        # 检查缓存
        if archive_path in self.archive_cache:
            logger.debug(f"Archive info retrieved from cache: {archive_path}")
            return self.archive_cache[archive_path]
        
        # 如果有zip_manager，则尝试加载信息
        if self._zip_manager:
            try:
                # 重新加载ZIP文件信息
                result = self._zip_manager.load_first_image(archive_path)
                if result and result.info:
                    self.archive_cache[archive_path] = result.info
                    self._cleanup_cache()
                    logger.debug(f"Archive info loaded and cached: {archive_path}")
                    return result.info
            except Exception as e:
                logger.error(f"Failed to load archive info for {archive_path}: {e}")
        
        logger.debug(f"Archive info not available: {archive_path}")
        return None
    
    def _cleanup_cache(self):
        """限制缓存大小，移除最旧的条目"""
        while len(self.archive_cache) > self._cache_size_limit:
            # 移除第一个（最旧的）条目
            oldest_key = next(iter(self.archive_cache))
            del self.archive_cache[oldest_key]
            logger.debug(f"Cache cleaned up, removed: {oldest_key}")
    
    def next_image(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Navigate to the next image.
        Returns tuple of (archive_path, image_member) or (None, None) if at end.
        """
        logger.debug(f"next_image called. Current position: archive={self.current_archive_index}, image={self.current_image_index}")
        
        if not self.archive_paths:
            logger.debug("No archives available")
            return None, None
        
        # 尝试获取当前档案信息
        current_archive = self._get_archive_info(self.current_archive_index)
        if current_archive and current_archive.members:
            logger.debug(f"Current archive: {current_archive.path}, members count: {len(current_archive.members)}")
            
            # 如果当前压缩包还有下一张图片
            if self.current_image_index < len(current_archive.members) - 1:
                self.current_image_index += 1
                next_image = current_archive.members[self.current_image_index]
                logger.debug(f"Moving to next image in same archive: {next_image}")
                return current_archive.path, next_image
        
        # 如果当前是最后一个压缩包且不循环
        if self.current_archive_index >= len(self.archive_paths) - 1 and not self.loop_mode:
            logger.debug("At end of archives and loop_mode is disabled")
            return None, None
            
        # 移动到下一个压缩包
        self.current_archive_index = (self.current_archive_index + 1) % len(self.archive_paths)
        self.current_image_index = 0
        
        # 尝试获取下一个档案信息
        next_archive = self._get_archive_info(self.current_archive_index)
        if next_archive and next_archive.members:
            logger.debug(f"Moving to next archive: {next_archive.path}, members count: {len(next_archive.members)}")
            next_image = next_archive.members[0]
            logger.debug(f"First image in next archive: {next_image}")
            return next_archive.path, next_image
        
        # 即使没有缓存也返回路径信息
        if self.archive_paths:
            archive_path = self.archive_paths[self.current_archive_index]
            logger.debug(f"Moving to next archive (path only): {archive_path}")
            return archive_path, None
            
        logger.debug("No archives available")
        return None, None
    
    def prev_image(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Navigate to the previous image.
        Returns tuple of (archive_path, image_member) or (None, None) if at beginning.
        """
        logger.debug(f"prev_image called. Current position: archive={self.current_archive_index}, image={self.current_image_index}")
        
        if not self.archive_paths:
            logger.debug("No archives available")
            return None, None
            
        # 尝试获取当前档案信息
        current_archive = self._get_archive_info(self.current_archive_index)
        
        # 如果当前图片不是压缩包内的第一张
        if self.current_image_index > 0 and current_archive and current_archive.members:
            self.current_image_index -= 1
            prev_image = current_archive.members[self.current_image_index]
            logger.debug(f"Moving to previous image in same archive: {prev_image}")
            return current_archive.path, prev_image
        
        # 如果当前是第一个压缩包且不循环
        if self.current_archive_index <= 0 and not self.loop_mode:
            logger.debug("At beginning of archives and loop_mode is disabled")
            return None, None
            
        # 移动到上一个压缩包
        prev_archive_index = self.current_archive_index - 1 if self.current_archive_index > 0 else len(self.archive_paths) - 1
        self.current_archive_index = prev_archive_index
        self.current_image_index = 0
        
        # 尝试获取前一个档案信息
        prev_archive = self._get_archive_info(prev_archive_index)
        if prev_archive and prev_archive.members:
            self.current_image_index = len(prev_archive.members) - 1
            prev_image = prev_archive.members[self.current_image_index]
            logger.debug(f"Last image in previous archive: {prev_image}")
            return prev_archive.path, prev_image
        
        # 即使没有缓存也返回路径信息
        if self.archive_paths:
            archive_path = self.archive_paths[prev_archive_index]
            logger.debug(f"Moving to previous archive (path only): {archive_path}")
            return archive_path, None
            
        logger.debug("No archives available")
        return None, None
    
    def get_current_position(self) -> Tuple[int, int, int]:
        """Get current position as (archive_index, image_index, total_archives)."""
        return self.current_archive_index, self.current_image_index, len(self.archive_paths)
    
    def goto_position(self, archive_index: int, image_index: int):
        """Go to a specific position."""
        logger.debug(f"goto_position called with archive_index={archive_index}, image_index={image_index}")
        if 0 <= archive_index < len(self.archive_paths):
            self.current_archive_index = archive_index
            self.current_image_index = image_index
            logger.debug(f"Position updated successfully")
        else:
            logger.debug(f"Invalid archive_index. Total archives: {len(self.archive_paths)}")
    
    def get_progress(self) -> tuple:
        """Get playback progress as (current, total)."""
        # 这是一个简化的实现，实际总图片数需要计算所有ZIP文件中的图片总数
        total_images = len(self.archive_paths)  # 近似值，实际应统计所有图片
        progress = (self.current_archive_index, total_images)
        logger.debug(f"get_progress returning: {progress}")
        return progress