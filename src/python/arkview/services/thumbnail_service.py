"""
Thumbnail service implementation for Arkview.
Handles loading and caching of thumbnails with Qt signal/slot mechanism.
"""

from typing import Tuple, Optional, TYPE_CHECKING
from PySide6.QtCore import QObject, Signal, Slot, QThread

if TYPE_CHECKING:
    from ..core.cache import LRUCache
    from ..core.file_manager import ZipFileManager
    from ..core.models import LoadResult

from ..core.models import LoadResult
from .image_service import ImageService


class ThumbnailWorker(QObject):
    """Worker object for handling thumbnail loading in a separate thread."""
    thumbnailLoaded = Signal(object, tuple)  # LoadResult, cache_key
    finished = Signal()  # Signal emitted when worker finishes
    
    def __init__(self, image_service: ImageService):
        super().__init__()
        self.image_service = image_service
        self.running = True

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
    """Service for managing thumbnail loading with Qt threading."""
    
    # Signal to request thumbnail loading
    load_thumbnail_request = Signal(str, str, tuple, int, tuple, bool)
    
    def __init__(self, cache: 'LRUCache', zip_manager: 'ZipFileManager', config: dict):
        super().__init__()
        self.cache = cache
        self.zip_manager = zip_manager
        self.config = config
        
        # Create image service
        self.image_service = ImageService(cache, zip_manager)
        
        # Create worker thread and worker
        self.worker_thread = QThread()
        self.worker = ThumbnailWorker(self.image_service)
        self.worker.moveToThread(self.worker_thread)
        
        # Connect signals
        self.load_thumbnail_request.connect(self.worker.load_thumbnail)
        self.worker.thumbnailLoaded.connect(self._on_thumbnail_loaded)
        self.worker.finished.connect(self.worker_thread.quit)
        
        # Start the worker thread
        self.worker_thread.start()

    def request_thumbnail(self, zip_path: str, member_path: str, cache_key: tuple,
                         max_size: int, resize_params: tuple, performance_mode: bool):
        """Request loading of a thumbnail."""
        self.load_thumbnail_request.emit(
            zip_path, member_path, cache_key, max_size, resize_params, performance_mode
        )

    def _on_thumbnail_loaded(self, result: LoadResult, cache_key: tuple):
        """Handle thumbnail loaded event - to be connected in UI layer."""
        # This signal needs to be connected in the UI layer
        pass

    def stop_service(self):
        """Stop the thumbnail service and cleanup resources."""
        self.worker.running = False
        if self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()