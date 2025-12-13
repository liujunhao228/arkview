"""arkview.core.cache_keys

Small helpers for building stable, explicit cache keys.

We keep keys as plain tuples so they remain cheap to hash and work with the
existing LRU cache implementation.

Key goals:
- Explicitly separate original images vs thumbnails vs other resized variants
- Allow multiple resolutions for the same source image without collisions
- Provide a dedicated key for ZIP cover thumbnails ("first image" previews)
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Optional, Tuple, Union


class ImageCacheKind(str, Enum):
    ORIGINAL = "original"
    THUMBNAIL = "thumbnail"
    RESIZED = "resized"


Size = Tuple[int, int]


def _normalize_zip_path(zip_path: str) -> str:
    return os.path.abspath(zip_path)


def _normalize_size(size: Optional[Union[Size, Tuple[float, float]]]) -> Optional[Size]:
    if size is None:
        return None
    return int(size[0]), int(size[1])


def make_image_cache_key(
    zip_path: str,
    member_name: str,
    kind: ImageCacheKind,
    size: Optional[Size] = None,
) -> tuple:
    """Key for an image inside a ZIP.

    Structure:
        ("image", <kind>, <abs_zip_path>, <member_name>, <size_or_None>)
    """

    return (
        "image",
        kind.value,
        _normalize_zip_path(zip_path),
        member_name,
        _normalize_size(size),
    )


def is_image_cache_key(key: tuple) -> bool:
    return bool(key) and len(key) == 5 and key[0] == "image"


def parse_image_cache_key(key: tuple) -> Tuple[ImageCacheKind, str, str, Optional[Size]]:
    if not is_image_cache_key(key):
        raise ValueError(f"Not an image cache key: {key!r}")

    _, kind_value, zip_path, member_name, size = key
    return ImageCacheKind(kind_value), zip_path, member_name, size


def make_zip_cover_thumbnail_key(zip_path: str, size: Size) -> tuple:
    """Key for the ZIP cover thumbnail (first image preview).

    Structure:
        ("zip_cover_thumbnail", <abs_zip_path>, <size>)
    """

    return ("zip_cover_thumbnail", _normalize_zip_path(zip_path), _normalize_size(size))


def is_zip_cover_thumbnail_key(key: tuple) -> bool:
    return bool(key) and len(key) == 3 and key[0] == "zip_cover_thumbnail"
