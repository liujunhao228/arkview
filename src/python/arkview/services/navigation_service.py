"""
Navigation service for Arkview.
Handles navigation logic for slideshow, cross-archive browsing, and other advanced features.
"""

from typing import List, Optional, Tuple
from ..core.models import ZipFileInfo
import logging

# 设置日志记录器
logger = logging.getLogger(__name__)


class NavigationService:
    """Service for managing navigation between images and archives."""
    
    def __init__(self):
        self.archives: List[ZipFileInfo] = []
        self.current_archive_index = 0
        self.current_image_index = 0
        self.loop_mode = False  # 是否开启循环浏览
        logger.debug("NavigationService initialized")
    
    def set_archives(self, archives: List[ZipFileInfo]):
        """Set the list of archives to navigate through."""
        self.archives = archives
        self.current_archive_index = 0
        self.current_image_index = 0
        logger.debug(f"Archives set. Count: {len(archives)}")
    
    def next_image(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Navigate to the next image.
        Returns tuple of (archive_path, image_member) or (None, None) if at end.
        """
        logger.debug(f"next_image called. Current position: archive={self.current_archive_index}, image={self.current_image_index}")
        
        if not self.archives:
            logger.debug("No archives available")
            return None, None
            
        current_archive = self.archives[self.current_archive_index]
        logger.debug(f"Current archive: {current_archive.path}, members count: {len(current_archive.members)}")
        
        # 如果当前压缩包还有下一张图片
        if self.current_image_index < len(current_archive.members) - 1:
            self.current_image_index += 1
            next_image = current_archive.members[self.current_image_index]
            logger.debug(f"Moving to next image in same archive: {next_image}")
            return current_archive.path, next_image
        
        # 如果当前是最后一个压缩包且不循环
        if self.current_archive_index >= len(self.archives) - 1 and not self.loop_mode:
            logger.debug("At end of archives and loop_mode is disabled")
            return None, None
            
        # 移动到下一个压缩包
        self.current_archive_index = (self.current_archive_index + 1) % len(self.archives)
        self.current_image_index = 0
        
        next_archive = self.archives[self.current_archive_index]
        logger.debug(f"Moving to next archive: {next_archive.path}, members count: {len(next_archive.members)}")
        
        if next_archive.members:
            next_image = next_archive.members[0]
            logger.debug(f"First image in next archive: {next_image}")
            return next_archive.path, next_image
        
        logger.debug("Next archive has no members")
        return None, None
    
    def prev_image(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Navigate to the previous image.
        Returns tuple of (archive_path, image_member) or (None, None) if at beginning.
        """
        logger.debug(f"prev_image called. Current position: archive={self.current_archive_index}, image={self.current_image_index}")
        
        if not self.archives:
            logger.debug("No archives available")
            return None, None
            
        # 如果当前图片不是压缩包内的第一张
        if self.current_image_index > 0:
            self.current_image_index -= 1
            current_archive = self.archives[self.current_archive_index]
            prev_image = current_archive.members[self.current_image_index]
            logger.debug(f"Moving to previous image in same archive: {prev_image}")
            return current_archive.path, prev_image
        
        # 如果当前是第一个压缩包且不循环
        if self.current_archive_index <= 0 and not self.loop_mode:
            logger.debug("At beginning of archives and loop_mode is disabled")
            return None, None
            
        # 移动到上一个压缩包
        self.current_archive_index = (self.current_archive_index - 1) % len(self.archives)
        prev_archive = self.archives[self.current_archive_index]
        logger.debug(f"Moving to previous archive: {prev_archive.path}, members count: {len(prev_archive.members)}")
        
        if prev_archive.members:
            self.current_image_index = len(prev_archive.members) - 1
            prev_image = prev_archive.members[self.current_image_index]
            logger.debug(f"Last image in previous archive: {prev_image}")
            return prev_archive.path, prev_image
        
        logger.debug("Previous archive has no members")
        return None, None
    
    def get_current_position(self) -> Tuple[int, int, int]:
        """Get current position as (archive_index, image_index, total_archives)."""
        return self.current_archive_index, self.current_image_index, len(self.archives)
    
    def goto_position(self, archive_index: int, image_index: int):
        """Go to a specific position."""
        logger.debug(f"goto_position called with archive_index={archive_index}, image_index={image_index}")
        if 0 <= archive_index < len(self.archives):
            archive = self.archives[archive_index]
            if archive.members and 0 <= image_index < len(archive.members):
                self.current_archive_index = archive_index
                self.current_image_index = image_index
                logger.debug(f"Position updated successfully")
            else:
                logger.debug(f"Invalid image_index. Archive members count: {len(archive.members) if archive.members else 0}")
        else:
            logger.debug(f"Invalid archive_index. Total archives: {len(self.archives)}")