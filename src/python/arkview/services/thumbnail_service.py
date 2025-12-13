"""
Thumbnail service implementation for Arkview.
Handles loading and caching of thumbnails.
"""

import os
import traceback
import zipfile
from typing import Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QObject, Signal, Slot, QThread, Qt, QMutex, QMutexLocker

from ..core.models import LoadResult
from ..core.file_manager import ZipFileManager
from ..core.cache_keys import make_zip_cover_thumbnail_key
try:
    from ..core import arkview_core
    RUST_AVAILABLE = True
    ImageProcessorRust = arkview_core.ImageProcessor
except ImportError:
    RUST_AVAILABLE = False
    ImageProcessorRust = None


class ThumbnailWorker(QObject):
    """Worker object for handling thumbnail loading in a separate thread."""
    thumbnailLoaded = Signal(object, tuple)  # LoadResult, cache_key
    load_thumbnail = Signal(str, str, tuple, int, tuple, bool)  # 信号定义
    finished = Signal()  # Signal emitted when worker finishes
    
    def __init__(self, cache_service, config):
        super().__init__()
        self.cache_service = cache_service
        self.config = config
        self.running = True
        from ..services.image_service import ImageService
        self.image_service = ImageService(cache_service, ZipFileManager())
        
    @Slot(str, str, tuple, int, tuple, bool)
    def process_thumbnail(self, zip_path: str, member_path: str, cache_key: tuple,
                         max_size: int, resize_params: tuple, performance_mode: bool):
        """Process a thumbnail in a worker thread."""
        if not self.running:
            return
            
        try:
            # Call the image service to load the thumbnail
            result = self.image_service.load_image_data_async(
                zip_path, member_path, max_size, resize_params,
                cache_key, performance_mode
            )
            
            # Emit the result
            self.thumbnailLoaded.emit(result, cache_key)
        except Exception as e:
            error_msg = f"Thumbnail load error: {str(e)}"
            print(f"Error loading thumbnail for {zip_path}[{member_path}]: {error_msg}")  # 添加日志输出
            traceback.print_exc()  # 打印完整的堆栈跟踪
            # Emit error result
            error_result = LoadResult(
                success=False, 
                error_message=error_msg, 
                cache_key=cache_key
            )
            self.thumbnailLoaded.emit(error_result, cache_key)
        finally:
            # Emit finished signal
            self.finished.emit()


class ThumbnailService(QObject):
    """Service for managing thumbnail loading and caching."""
    
    # Signal emitted when a thumbnail is loaded
    thumbnailLoaded = Signal(object, tuple)  # LoadResult, cache_key
    
    def __init__(self, cache_service, config):
        super().__init__()
        self.cache_service = cache_service
        self.config = config
        self.max_load_size = int(config.get("MAX_THUMBNAIL_LOAD_SIZE", 10 * 1024 * 1024))
        
        # Worker thread and object
        self.thread = QThread()
        self.worker = ThumbnailWorker(cache_service, config)
        self.worker.moveToThread(self.thread)
        
        # Connect signals
        self.worker.thumbnailLoaded.connect(self._on_thumbnail_loaded)
        self.worker.load_thumbnail.connect(self.worker.process_thumbnail)  # 连接信号到处理方法
        
        # Start the thread
        self.thread.start()
        
    def request_thumbnail(self, zip_path: str, member_path: str, cache_key: tuple,
                         max_size: int, resize_params: tuple, performance_mode: bool):
        """Request loading of a thumbnail."""
        if self.thread.isRunning():
            # Call the worker's load_thumbnail method via signal
            self.worker.load_thumbnail.emit(
                zip_path, member_path, cache_key, max_size, resize_params, performance_mode
            )
            
    def request_cover_thumbnail(self, zip_path: str, thumb_size: tuple, 
                              priority: bool, performance_mode: bool):
        """Request loading of a ZIP file cover thumbnail."""
        cover_key = make_zip_cover_thumbnail_key(zip_path, thumb_size)
        
        # Check if already in cache
        cached_image = self.cache_service.get(cover_key)
        if cached_image is not None:
            # Emit signal immediately with cached image
            result = LoadResult(success=True, data=cached_image, error_message=None)
            self.thumbnailLoaded.emit(result, cover_key)
            return
            
        # Find the first image in the ZIP file
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                first_image = None
                from ..core.models import ImageExtensions
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    if not ImageExtensions.is_image_file(info.filename):
                        continue
                    if info.file_size <= 0:
                        continue
                    if info.file_size > self.max_load_size:
                        raise ValueError(f"Cover image too large: {info.file_size} bytes")
                    first_image = info.filename
                    break
                    
                if not first_image:
                    raise ValueError("No images found")
                    
                # Request thumbnail loading
                self.request_thumbnail(
                    zip_path, first_image, cover_key,
                    self.max_load_size, thumb_size, performance_mode
                )
        except Exception as e:
            print(f"Error processing cover thumbnail for {zip_path}: {str(e)}")
            error_result = LoadResult(success=False, data=None, error_message=str(e))
            self.thumbnailLoaded.emit(error_result, cover_key)
            
    def _on_thumbnail_loaded(self, result, cache_key):
        """Handle thumbnail loaded event."""
        self.thumbnailLoaded.emit(result, cache_key)
        
    def stop_service(self):
        """Stop the thumbnail service and cleanup resources."""
        self.worker.running = False
        self.thread.quit()
        self.thread.wait()