"""
Image loading service - handles image loading from ZIP files.
"""

from typing import Optional, Dict, Any, Tuple
from PySide6.QtCore import QObject, Signal, Slot

from ..models import LoadResult, ImageLoadRequest, ThumbnailLoadRequest
from ..infrastructure import (
    load_image_data_async, 
    ZipFileManager, 
    LRUCache, 
    ImageLoaderSignals,
    _format_size
)


class ImageLoaderService(QObject):
    """Service for loading images from ZIP files."""
    
    # Signals
    image_loaded = Signal(object)  # LoadResult
    thumbnail_loaded = Signal(object, tuple)  # LoadResult, cache_key
    
    def __init__(self, zip_manager: ZipFileManager, cache: LRUCache, config: Dict[str, Any]):
        super().__init__()
        self.zip_manager = zip_manager
        self.cache = cache
        self.config = config
        
    def load_image(self, request: ImageLoadRequest) -> None:
        """Load an image based on the request."""
        if not request.force_reload:
            cached_image = self.cache.get(request.cache_key)
            if cached_image is not None:
                try:
                    if request.target_size:
                        from PIL import Image
                        img_to_process = cached_image.copy()
                        resampling_method = (
                            Image.Resampling.NEAREST if request.performance_mode
                            else Image.Resampling.LANCZOS
                        )
                        img_to_process.thumbnail(request.target_size, resampling_method)
                        result = LoadResult(
                            success=True, 
                            data=img_to_process, 
                            cache_key=request.cache_key
                        )
                    else:
                        result = LoadResult(
                            success=True, 
                            data=cached_image, 
                            cache_key=request.cache_key
                        )
                    
                    self.image_loaded.emit(result)
                    return
                except Exception as e:
                    print(f"Error processing cached image for {request.cache_key}: {e}")

        # Create signals for async loading
        signals = ImageLoaderSignals()
        signals.image_loaded.connect(self._on_image_loaded)
        
        # Load image asynchronously
        load_image_data_async(
            request.zip_path,
            request.member_name,
            request.max_size,
            request.target_size,
            signals,
            self.cache,
            request.cache_key,
            self.zip_manager,
            request.performance_mode,
            request.force_reload
        )
        
    def load_thumbnail(self, request: ThumbnailLoadRequest) -> None:
        """Load a thumbnail based on the request."""
        # Create signals for async loading
        signals = ImageLoaderSignals()
        signals.image_loaded.connect(
            lambda result: self.thumbnail_loaded.emit(result, request.cache_key)
        )
        
        # Load thumbnail asynchronously
        load_image_data_async(
            request.zip_path,
            request.member_path,
            request.max_size,
            request.resize_params,
            signals,
            self.cache,
            request.cache_key,
            self.zip_manager,
            request.performance_mode
        )
        
    @Slot(object)
    def _on_image_loaded(self, result: LoadResult) -> None:
        """Handle loaded image result."""
        self.image_loaded.emit(result)
        
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            'cache_size': len(self.cache),
            'cache_capacity': self.cache.capacity
        }
        
    def clear_cache(self) -> None:
        """Clear the image cache."""
        self.cache.clear()
        
    def resize_cache(self, new_capacity: int) -> None:
        """Resize the cache capacity."""
        self.cache.resize(new_capacity)