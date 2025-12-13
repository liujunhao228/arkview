"""
Playlist service for Arkview.
Manages playlists for sequential image viewing across archives.
Optimized version that uses lazy loading to reduce memory footprint.
"""

from typing import List, Optional, Tuple
from ..core.models import ZipFileInfo, LightweightPlaylistEntry
import logging

# 设置日志记录器
logger = logging.getLogger(__name__)


class PlaylistEntry:
    """Represents an entry in the playlist."""
    
    def __init__(self, archive_path: str, image_member: str):
        self.archive_path = archive_path
        self.image_member = image_member


class OptimizedPlaylistService:
    """Optimized service for managing image playlists with lazy loading."""
    
    def __init__(self, zip_manager=None):
        # 存储归档文件路径而非完整对象
        self.archive_paths: List[str] = []
        # 存储每个归档的图片成员数量，避免存储所有成员名称
        self.archive_image_counts: List[int] = []
        # 存储归档对象的轻量级缓存
        self.archive_cache: dict = {}
        self.current_index = 0
        self.loop_mode = False
        self._cache_size_limit = 10
        self._zip_manager = zip_manager
        logger.debug("OptimizedPlaylistService initialized")
    
    def set_zip_manager(self, zip_manager):
        """设置ZipFileManager实例"""
        self._zip_manager = zip_manager
    
    def create_from_archives(self, archives: List[ZipFileInfo]):
        """Create a playlist from a list of archives with minimal memory footprint."""
        logger.debug(f"Creating optimized playlist from {len(archives)} archives")
        self.archive_paths = [archive.path for archive in archives]
        self.archive_image_counts = [archive.image_count for archive in archives]
        self.archive_cache.clear()
        self.current_index = 0
        logger.debug(f"Optimized playlist created with {len(self.archive_paths)} archives")
    
    def _get_total_entries(self) -> int:
        """Calculate total number of entries without creating them."""
        return sum(self.archive_image_counts)
    
    def _find_archive_and_image_indices(self, flat_index: int) -> Tuple[int, int]:
        """
        Convert a flat index to (archive_index, image_index) pair.
        """
        current_count = 0
        for archive_idx, image_count in enumerate(self.archive_image_counts):
            if flat_index < current_count + image_count:
                image_idx = flat_index - current_count
                return archive_idx, image_idx
            current_count += image_count
        return -1, -1  # Index out of range
    
    def _load_archive_info(self, archive_index: int) -> Optional[ZipFileInfo]:
        """Load archive information with caching."""
        if not (0 <= archive_index < len(self.archive_paths)):
            return None
            
        archive_path = self.archive_paths[archive_index]
        
        # Check cache first
        if archive_path in self.archive_cache:
            logger.debug(f"Archive info retrieved from cache: {archive_path}")
            return self.archive_cache[archive_path]
        
        # If we have zip_manager, try to load the info
        if self._zip_manager:
            try:
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
        """Limit cache size by removing oldest entries."""
        while len(self.archive_cache) > self._cache_size_limit:
            oldest_key = next(iter(self.archive_cache))
            del self.archive_cache[oldest_key]
            logger.debug(f"Cache cleaned up, removed: {oldest_key}")
    
    def next_entry(self) -> Optional[Tuple[str, str]]:
        """Get the next entry in the playlist as (archive_path, image_member)."""
        logger.debug(f"next_entry called. Current index: {self.current_index}, Total entries: {self._get_total_entries()}")
        
        if not self.archive_paths:
            logger.debug("No archives in playlist")
            return None
        
        total_entries = self._get_total_entries()
        if total_entries == 0:
            logger.debug("No images in playlist")
            return None
            
        if self.current_index < total_entries - 1:
            self.current_index += 1
        elif self.loop_mode:
            self.current_index = 0
        else:
            logger.debug("At end of playlist and loop_mode is disabled")
            return None
        
        # Find the archive and image indices
        archive_index, image_index = self._find_archive_and_image_indices(self.current_index)
        if archive_index == -1:
            logger.debug("Could not find archive for index")
            return None
            
        # Try to get archive info
        archive_info = self._load_archive_info(archive_index)
        if archive_info and archive_info.members and image_index < len(archive_info.members):
            image_member = archive_info.members[image_index]
            logger.debug(f"Next entry: {archive_info.path} -> {image_member}")
            return (archive_info.path, image_member)
        else:
            # Return path and None for member - caller will need to reload
            archive_path = self.archive_paths[archive_index]
            logger.debug(f"Next entry (path only): {archive_path}")
            return (archive_path, None)
    
    def prev_entry(self) -> Optional[Tuple[str, str]]:
        """Get the previous entry in the playlist as (archive_path, image_member)."""
        logger.debug(f"prev_entry called. Current index: {self.current_index}, Total entries: {self._get_total_entries()}")
        
        if not self.archive_paths:
            logger.debug("No archives in playlist")
            return None
        
        total_entries = self._get_total_entries()
        if total_entries == 0:
            logger.debug("No images in playlist")
            return None
            
        if self.current_index > 0:
            self.current_index -= 1
        elif self.loop_mode and total_entries > 0:
            self.current_index = total_entries - 1
        else:
            logger.debug("At beginning of playlist and loop_mode is disabled")
            return None
        
        # Find the archive and image indices
        archive_index, image_index = self._find_archive_and_image_indices(self.current_index)
        if archive_index == -1:
            logger.debug("Could not find archive for index")
            return None
            
        # Try to get archive info
        archive_info = self._load_archive_info(archive_index)
        if archive_info and archive_info.members and image_index < len(archive_info.members):
            image_member = archive_info.members[image_index]
            logger.debug(f"Previous entry: {archive_info.path} -> {image_member}")
            return (archive_info.path, image_member)
        else:
            # Return path and None for member - caller will need to reload
            archive_path = self.archive_paths[archive_index]
            logger.debug(f"Previous entry (path only): {archive_path}")
            return (archive_path, None)
    
    def get_current_entry(self) -> Optional[Tuple[str, str]]:
        """Get the current entry as (archive_path, image_member)."""
        logger.debug(f"get_current_entry called. Current index: {self.current_index}, Total entries: {self._get_total_entries()}")
        
        if not self.archive_paths:
            logger.debug("No archives in playlist")
            return None
        
        total_entries = self._get_total_entries()
        if total_entries == 0 or not (0 <= self.current_index < total_entries):
            logger.debug("No current entry")
            return None
        
        # Find the archive and image indices
        archive_index, image_index = self._find_archive_and_image_indices(self.current_index)
        if archive_index == -1:
            logger.debug("Could not find archive for index")
            return None
            
        # Try to get archive info
        archive_info = self._load_archive_info(archive_index)
        if archive_info and archive_info.members and image_index < len(archive_info.members):
            image_member = archive_info.members[image_index]
            logger.debug(f"Current entry: {archive_info.path} -> {image_member}")
            return (archive_info.path, image_member)
        else:
            # Return path and None for member - caller will need to reload
            archive_path = self.archive_paths[archive_index]
            logger.debug(f"Current entry (path only): {archive_path}")
            return (archive_path, None)
    
    def set_current_index(self, index: int):
        """Set the current index."""
        logger.debug(f"set_current_index called with index: {index}")
        total_entries = self._get_total_entries()
        if 0 <= index < total_entries:
            self.current_index = index
            logger.debug("Current index updated successfully")
        else:
            logger.debug("Invalid index")
    
    def get_progress(self) -> tuple:
        """Get playback progress as (current, total)."""
        total = self._get_total_entries()
        progress = (self.current_index, total)
        logger.debug(f"get_progress returning: {progress}")
        return progress


class PlaylistService:
    """Service for managing image playlists."""
    
    def __init__(self):
        self.entries: List[PlaylistEntry] = []
        self.current_index = 0
        self.loop_mode = False
        logger.debug("PlaylistService initialized")
    
    def create_from_archives(self, archives: List[ZipFileInfo]):
        """Create a playlist from a list of archives."""
        logger.debug(f"Creating playlist from {len(archives)} archives")
        self.entries = []
        for archive in archives:
            if archive.members:
                for member in archive.members:
                    self.entries.append(PlaylistEntry(archive.path, member))
                    logger.debug(f"Added entry: {archive.path} -> {member}")
        self.current_index = 0
        logger.debug(f"Playlist created with {len(self.entries)} entries")
    
    def next_entry(self) -> Optional[PlaylistEntry]:
        """Get the next entry in the playlist."""
        logger.debug(f"next_entry called. Current index: {self.current_index}, Total entries: {len(self.entries)}")
        
        if not self.entries:
            logger.debug("No entries in playlist")
            return None
            
        if self.current_index < len(self.entries) - 1:
            self.current_index += 1
            entry = self.entries[self.current_index]
            logger.debug(f"Next entry: {entry.archive_path} -> {entry.image_member}")
            return entry
        
        if self.loop_mode:
            self.current_index = 0
            entry = self.entries[0]
            logger.debug(f"Looping to first entry: {entry.archive_path} -> {entry.image_member}")
            return entry
            
        logger.debug("At end of playlist and loop_mode is disabled")
        return None
    
    def prev_entry(self) -> Optional[PlaylistEntry]:
        """Get the previous entry in the playlist."""
        logger.debug(f"prev_entry called. Current index: {self.current_index}, Total entries: {len(self.entries)}")
        
        if not self.entries:
            logger.debug("No entries in playlist")
            return None
            
        if self.current_index > 0:
            self.current_index -= 1
            entry = self.entries[self.current_index]
            logger.debug(f"Previous entry: {entry.archive_path} -> {entry.image_member}")
            return entry
        
        if self.loop_mode:
            self.current_index = len(self.entries) - 1
            entry = self.entries[self.current_index]
            logger.debug(f"Looping to last entry: {entry.archive_path} -> {entry.image_member}")
            return entry
            
        logger.debug("At beginning of playlist and loop_mode is disabled")
        return None
    
    def get_current_entry(self) -> Optional[PlaylistEntry]:
        """Get the current entry."""
        logger.debug(f"get_current_entry called. Current index: {self.current_index}, Total entries: {len(self.entries)}")
        if 0 <= self.current_index < len(self.entries):
            entry = self.entries[self.current_index]
            logger.debug(f"Current entry: {entry.archive_path} -> {entry.image_member}")
            return entry
        logger.debug("No current entry")
        return None
    
    def set_current_index(self, index: int):
        """Set the current index."""
        logger.debug(f"set_current_index called with index: {index}")
        if 0 <= index < len(self.entries):
            self.current_index = index
            logger.debug("Current index updated successfully")
        else:
            logger.debug("Invalid index")
    
    def get_progress(self) -> tuple:
        """Get playback progress as (current, total)."""
        progress = (self.current_index, len(self.entries))
        logger.debug(f"get_progress returning: {progress}")
        return progress