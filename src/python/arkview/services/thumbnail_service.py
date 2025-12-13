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
    finished = Signal()  # Signal emitted when worker finishes
    
    def __init__(self, cache_service, config):
        super().__init__()
        self.cache_service = cache_service
        self.config = config
        self.running = True
        from ..services.image_service import ImageService
        self.image_service = ImageService(cache_service, ZipFileManager())

    @Slot(str, str, tuple, int, tuple, bool)
    def load_thumbnail(self, zip_path: str, member_path: str, cache_key: tuple,
                      max_size: int, resize_params: tuple, performance_mode: bool):
        """Load a thumbnail in a worker thread."""
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
            print(f"Error loading thumbnail: {e}")
            # Emit error result
            error_result = LoadResult(
                success=False, 
                error_message=f"Thumbnail load error: {str(e)}", 
                cache_key=cache_key
            )
            self.thumbnailLoaded.emit(error_result, cache_key)
        finally:
            # Emit finished signal
            self.finished.emit()


class ThumbnailService(QObject):
    """Service for handling thumbnail loading and caching operations."""

    # Signals for async operations
    thumbnailRequested = Signal(str, str, object, int, object, bool)
    thumbnailLoaded = Signal(object, tuple)  # LoadResult, cache_key
    batchProcessed = Signal(list)
    errorOccurred = Signal(str, str, str)  # zip_path, member_name, error_msg
    
    def __init__(self, cache_service, config):
        super().__init__()
        self.cache_service = cache_service
        self.config = config
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._mutex = QMutex()
        self.zip_manager = ZipFileManager()
        if RUST_AVAILABLE:
            self.image_processor = ImageProcessorRust()
        else:
            self.image_processor = None
        
        # Create worker thread and worker
        self.worker_thread = QThread()
        self.worker = ThumbnailWorker(cache_service, config)
        
        # Move worker to thread
        self.worker.moveToThread(self.worker_thread)
        
        # Connect signals
        self.thumbnailRequested.connect(self.worker.load_thumbnail, Qt.QueuedConnection)
        self.worker.thumbnailLoaded.connect(self.thumbnailLoaded)

        # Start the worker thread
        self.worker_thread.start()

    def request_thumbnail(self, zip_path: str, member_path: str, cache_key: tuple,
                         max_size: int, resize_params: tuple, performance_mode: bool):
        """Request loading of a thumbnail."""
        self.thumbnailRequested.emit(
            zip_path, member_path, cache_key, max_size, resize_params, performance_mode
        )

    # No need for _on_thumbnail_loaded method as we connect worker directly to thumbnailLoaded signal

    def stop_service(self):
        """Stop the thumbnail service and cleanup resources."""
        self.worker.running = False
        if self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()