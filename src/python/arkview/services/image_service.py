"""
Image service implementation for Arkview.
Handles loading and processing of images from ZIP archives.
"""

import io
import zipfile
from typing import Optional, Tuple, List

from PIL import Image, ImageOps

from ..core.cache_keys import (
    ImageCacheKind,
    is_image_cache_key,
    make_image_cache_key,
    parse_image_cache_key,
)
from ..core.models import LoadResult
from ..core.file_manager import ZipFileManager


class _SimplePreloadStrategy:
    def __init__(self, forward: int = 2, backward: int = 1):
        self._forward = forward
        self._backward = backward

    def update_browsing_pattern(self, current_index: int, member_list: List[str]):
        return

    def calculate_preload_params(self) -> Tuple[int, int]:
        return self._forward, self._backward


class ImageService:
    """Service for loading and processing images."""

    def __init__(self, cache_service, zip_manager: ZipFileManager):
        """
        Initialize the image service.
        
        Args:
            cache_service: Cache service for storing/retrieving images
            zip_manager: ZIP file manager for accessing ZIP files
        """
        self.cache_service = cache_service
        self.zip_manager = zip_manager
        self.preload_strategy = _SimplePreloadStrategy()

    def load_image_data_async(
        self,
        zip_path: str,
        member_name: str,
        max_load_size: int,
        target_size: Optional[Tuple[int, int]],
        cache_key: tuple,
        performance_mode: bool = False
    ) -> LoadResult:
        """
        Asynchronously loads image data from a ZIP archive member.
        This method can be called synchronously but is designed to work with async patterns.
        """
        try:
            canonical_original_key = make_image_cache_key(zip_path, member_name, ImageCacheKind.ORIGINAL)
            legacy_request = not is_image_cache_key(cache_key)

            # Determine which cache key represents the requested variant.
            if target_size is None:
                request_key = cache_key if legacy_request else canonical_original_key
            else:
                if legacy_request:
                    request_key = cache_key
                else:
                    request_kind = ImageCacheKind.RESIZED
                    kind, _, _, _ = parse_image_cache_key(cache_key)
                    if kind != ImageCacheKind.ORIGINAL:
                        request_kind = kind
                    request_key = make_image_cache_key(zip_path, member_name, request_kind, target_size)

                cached_variant = self.cache_service.get(request_key)
                if cached_variant is not None:
                    return LoadResult(success=True, data=cached_variant.copy(), cache_key=request_key)

            cached_original = self.cache_service.get(canonical_original_key)
            if cached_original is None and legacy_request and target_size is None:
                cached_original = self.cache_service.get(request_key)
                if cached_original is not None:
                    # Populate canonical key for future requests.
                    self.cache_service.put(canonical_original_key, cached_original.copy())

            if cached_original is not None:
                if target_size is None:
                    return LoadResult(success=True, data=cached_original.copy(), cache_key=request_key)

                resample_method = (
                    Image.Resampling.NEAREST if performance_mode
                    else Image.Resampling.LANCZOS
                )
                resized = cached_original.copy()
                resized.thumbnail(target_size, resample_method)
                self.cache_service.put(request_key, resized.copy())
                return LoadResult(success=True, data=resized, cache_key=request_key)

            # Access ZIP file
            zf = self.zip_manager.get_zip(zip_path)
            if zf is None:
                return LoadResult(success=False, error_message="Cannot open ZIP", cache_key=request_key)

            # Load image data
            member_info = zf.getinfo(member_name)

            # Check size constraints
            if member_info.file_size == 0:
                return LoadResult(success=False, error_message="Image file empty", cache_key=request_key)
            if member_info.file_size > max_load_size:
                return LoadResult(
                    success=False,
                    error_message=f"Image too large ({member_info.file_size} bytes)",
                    cache_key=request_key,
                )

            image_data = zf.read(member_name)
            with io.BytesIO(image_data) as image_stream:
                img = ImageOps.exif_transpose(Image.open(image_stream))
                img.load()

            if target_size is None:
                self.cache_service.put(canonical_original_key, img.copy())
                if legacy_request:
                    self.cache_service.put(request_key, img.copy())
                return LoadResult(success=True, data=img, cache_key=request_key)

            resample_method = (
                Image.Resampling.NEAREST if performance_mode
                else Image.Resampling.LANCZOS
            )
            resized = img.copy()
            resized.thumbnail(target_size, resample_method)
            self.cache_service.put(request_key, resized.copy())
            return LoadResult(success=True, data=resized, cache_key=request_key)
            
        except zipfile.BadZipFile:
            return LoadResult(
                success=False,
                error_message=f"Not a valid ZIP file: {zip_path}",
                cache_key=request_key,
            )
        except KeyError:
            return LoadResult(
                success=False,
                error_message=f"Image {member_name} not found in ZIP",
                cache_key=request_key,
            )
        except Exception as e:
            error_msg = f"Failed to load image {member_name} from {zip_path}: {str(e)}"
            print(error_msg)
            return LoadResult(success=False, error_message=error_msg, cache_key=request_key)
            
    def preload_neighbor_images(
        self,
        zip_path: str,
        member_list: List[str],
        current_index: int,
        neighbor_count: int,
        target_size: Optional[Tuple[int, int]],
        performance_mode: bool
    ):
        """
        预加载相邻图片以提高浏览体验
        
        Args:
            zip_path: ZIP文件路径
            member_list: 图片列表
            current_index: 当前图片索引
            neighbor_count: 预加载的邻居数量
            target_size: 目标尺寸
            performance_mode: 是否启用性能模式
        """
        start_index = max(0, current_index - neighbor_count)
        end_index = min(len(member_list), current_index + neighbor_count + 1)
        
        for i in range(start_index, end_index):
            if i != current_index:  # 跳过当前图片
                member_name = member_list[i]
                kind = ImageCacheKind.ORIGINAL if target_size is None else ImageCacheKind.RESIZED
                cache_key = make_image_cache_key(zip_path, member_name, kind, target_size)

                # 检查是否已在缓存中
                cached_image = self.cache_service.get(cache_key)
                
                # 如果不在缓存中，则加载
                if cached_image is None:
                    try:
                        self.load_image_data_async(
                            zip_path, member_name, 
                            100 * 1024 * 1024,  # max_load_size
                            target_size, 
                            cache_key, 
                            performance_mode
                        )
                    except Exception as e:
                        print(f"预加载图片失败 {member_name}: {e}")

    def smart_preload_images(
        self,
        zip_path: str,
        member_list: List[str],
        current_index: int,
        target_size: Optional[Tuple[int, int]],
        performance_mode: bool
    ):
        """
        根据用户浏览模式智能预加载图片
        """
        # 更新浏览模式
        self.preload_strategy.update_browsing_pattern(current_index, member_list)

        # 获取预加载参数
        forward_count, backward_count = self.preload_strategy.calculate_preload_params()

        # 根据方向预加载图片
        # 向后预加载
        start_idx = max(0, current_index + 1)
        end_idx = min(len(member_list), current_index + forward_count + 1)

        for i in range(start_idx, end_idx):
            self._preload_single_image(
                zip_path, member_list[i], target_size, performance_mode
            )

        # 向前预加载
        start_idx = max(0, current_index - backward_count)
        end_idx = current_index  # 不包含当前图片

        for i in range(start_idx, end_idx):
            self._preload_single_image(
                zip_path, member_list[i], target_size, performance_mode
            )

    def _preload_single_image(self, zip_path: str, member_name: str,
                             target_size: Optional[Tuple[int, int]], performance_mode: bool):
        """
        预加载单张图片
        """
        kind = ImageCacheKind.ORIGINAL if target_size is None else ImageCacheKind.RESIZED
        cache_key = make_image_cache_key(zip_path, member_name, kind, target_size)
        cached_image = self.cache_service.get(cache_key)

        if cached_image is None:
            try:
                self.load_image_data_async(
                    zip_path, member_name,
                    100 * 1024 * 1024,  # max_load_size
                    target_size,
                    cache_key,
                    performance_mode
                )
            except Exception as e:
                print(f"预加载图片失败 {member_name}: {e}")