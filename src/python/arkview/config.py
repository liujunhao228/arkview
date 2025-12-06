"""Configuration module for Arkview."""

import os
from typing import Any, Dict, Set


CONFIG: Dict[str, Any] = {
    "IMAGE_EXTENSIONS": {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.ico'},
    "THUMBNAIL_SIZE": (280, 280),
    "PERFORMANCE_THUMBNAIL_SIZE": (180, 180),
    "GALLERY_THUMB_SIZE": (220, 220),
    "GALLERY_PREVIEW_SIZE": (480, 480),
    "BATCH_SCAN_SIZE": 50,  # Number of files to scan in one batch
    "BATCH_UPDATE_INTERVAL": 20,  # UI update interval (number of files)
    "MAX_THUMBNAIL_LOAD_SIZE": 10 * 1024 * 1024,
    "PERFORMANCE_MAX_THUMBNAIL_LOAD_SIZE": 3 * 1024 * 1024,
    "MAX_VIEWER_LOAD_SIZE": 100 * 1024 * 1024,
    "PERFORMANCE_MAX_VIEWER_LOAD_SIZE": 30 * 1024 * 1024,
    "CACHE_MAX_ITEMS_NORMAL": 50,
    "CACHE_MAX_ITEMS_PERFORMANCE": 25,
    "PRELOAD_VIEWER_NEIGHBORS_NORMAL": 2,
    "PRELOAD_VIEWER_NEIGHBORS_PERFORMANCE": 1,
    "PRELOAD_NEXT_THUMBNAIL": True,
    "WINDOW_SIZE": (1050, 750),
    "VIEWER_ZOOM_FACTOR": 1.2,
    "VIEWER_MAX_ZOOM": 10.0,
    "VIEWER_MIN_ZOOM": 0.1,
    "PREVIEW_UPDATE_DELAY": 250,
    "THREAD_POOL_WORKERS": min(8, (os.cpu_count() or 1) + 4),
    "APP_VERSION": "4.0 - Rust-Python Hybrid",
}


def parse_human_size(size_str: str) -> int:
    """Parses human-readable size string into bytes."""
    import re
    
    size_str = size_str.strip().upper()
    if not size_str:
        return None
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT])?B?$', size_str)
    if not match:
        if size_str.isdigit():
            return int(size_str)
        return -1

    value = float(match.group(1))
    unit = match.group(2)

    multipliers = {'G': 1024**3, 'M': 1024**2, 'K': 1024, None: 1}
    multiplier = multipliers.get(unit, 1)

    return int(value * multiplier)