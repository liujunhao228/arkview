"""
Image service implementation for Arkview.
Handles image loading, processing and transformation operations.
"""

import io
from typing import Optional, Tuple
from PIL import Image, ImageOps, UnidentifiedImageError

from ..core.models import LoadResult
from ..core.cache import LRUCache
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


class ImageService:
    """Service for handling image loading and processing operations."""
    
    def __init__(self, cache: LRUCache, zip_manager: ZipFileManager):
        self.cache = cache
        self.zip_manager = zip_manager

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
        if not force_reload:
            cached_image = self.cache.get(cache_key)
            if cached_image is not None:
                try:
                    if target_size:
                        img_to_process = cached_image.copy()
                        resampling_method = (
                            Image.Resampling.NEAREST if performance_mode
                            else Image.Resampling.LANCZOS
                        )
                        img_to_process.thumbnail(target_size, resampling_method)
                        result = LoadResult(success=True, data=img_to_process, cache_key=cache_key)
                    else:
                        # Return the cached image directly if no resizing needed
                        result = LoadResult(success=True, data=cached_image, cache_key=cache_key)
                    
                    return result
                except Exception as e:
                    print(f"Async Load Warning: Error processing cached image for {cache_key}: {e}")

        zf = self.zip_manager.get_zipfile(zip_path)
        if zf is None:
            result = LoadResult(success=False, error_message="Cannot open ZIP", cache_key=cache_key)
            return result

        try:
            member_info = zf.getinfo(member_name)

            if member_info.file_size == 0:
                result = LoadResult(success=False, error_message="Image file empty", cache_key=cache_key)
                return result
                
            if member_info.file_size > max_load_size:
                err_msg = f"Too large ({_format_size(member_info.file_size)} > {_format_size(max_load_size)})"
                result = LoadResult(success=False, error_message=err_msg, cache_key=cache_key)
                return result

            image_data = zf.read(member_name)
            with io.BytesIO(image_data) as image_stream:
                img = ImageOps.exif_transpose(Image.open(image_stream))
                img.load()

            # Cache the original loaded image
            self.cache.put(cache_key, img)

            # Prepare display image
            if target_size:
                resampling_method = (
                    Image.Resampling.NEAREST if performance_mode
                    else Image.Resampling.LANCZOS
                )
                img_thumb = img.copy()
                img_thumb.thumbnail(target_size, resampling_method)
                result = LoadResult(success=True, data=img_thumb, cache_key=cache_key)
            else:
                result = LoadResult(success=True, data=img, cache_key=cache_key)
            
            return result

        except KeyError:
            result = LoadResult(success=False, error_message=f"Member '{member_name}' not found", cache_key=cache_key)
            return result
        except UnidentifiedImageError:
            result = LoadResult(success=False, error_message="Invalid image format", cache_key=cache_key)
            return result
        except Image.DecompressionBombError:
            result = LoadResult(success=False, error_message="Decompression Bomb", cache_key=cache_key)
            return result
        except MemoryError:
            result = LoadResult(success=False, error_message="Out of memory", cache_key=cache_key)
            return result
        except Exception as e:
            print(f"Async Load Error: Failed processing {cache_key}: {type(e).__name__} - {e}")
            result = LoadResult(success=False, error_message=f"Load error: {type(e).__name__}", cache_key=cache_key)
            return result