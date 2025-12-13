#!/usr/bin/env python3
"""
Test script to validate the refactored Arkview code.
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

def test_config_module():
    """Test that the new config module works correctly."""
    print("Testing config module...")
    from src.python.arkview.config import CONFIG, parse_human_size
    
    # Check that constants exist
    assert "MAX_FILE_SIZE" in CONFIG
    assert "IMAGE_EXTENSIONS" in CONFIG
    assert CONFIG["IMAGE_EXTENSIONS"] == {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.ico'}
    
    # Test size parsing
    assert parse_human_size(1023) == "1023 B"
    assert parse_human_size(1024) == "1.0 KB"
    assert parse_human_size(1024*1024) == "1.0 MB"
    
    print("Config module test passed!")


def test_cache_service():
    """Test that the unified cache service works correctly."""
    print("Testing unified cache service...")
    from src.python.arkview.core.unified_cache import UnifiedCacheService, CacheStrategy
    from PIL import Image
    
    # Create a simple test image
    test_image = Image.new('RGB', (100, 100), color='red')
    
    # Test LRU strategy
    cache = UnifiedCacheService(capacity=2, strategy=CacheStrategy.LRU)
    cache.put(("test_key1",), test_image)
    retrieved = cache.get(("test_key1",))
    assert retrieved is not None
    assert len(cache) == 1
    
    # Test statistics
    stats = cache.get_stats()
    assert 'hits' in stats
    assert 'misses' in stats
    assert stats['hit_rate'] == 1.0  # One hit, no misses yet
    
    print("Unified cache service test passed!")


def test_image_file_check():
    """Test that the image file check function works."""
    print("Testing image file check...")
    try:
        from src.python.arkview.core import arkview_core
        
        # Test Rust implementation
        assert arkview_core.is_image_file("test.jpg") == True
        assert arkview_core.is_image_file("test.png") == True
        assert arkview_core.is_image_file("test.txt") == False
        assert arkview_core.is_image_file("test") == False
        assert arkview_core.is_image_file("") == False
        
        print("Rust image file check test passed!")
    except ImportError:
        print("Rust extension not available, skipping Rust image file check test")
    
    # Test Python fallback
    from src.python.arkview.core.models import ImageExtensions
    
    assert ImageExtensions.is_image_file("test.jpg") == True
    assert ImageExtensions.is_image_file("test.png") == True
    assert ImageExtensions.is_image_file("test.txt") == False
    assert ImageExtensions.is_image_file("test") == False
    assert ImageExtensions.is_image_file("") == False
    
    print("Python image file check test passed!")


def test_size_formatting():
    """Test that size formatting works in both Rust and Python."""
    print("Testing size formatting...")
    try:
        from src.python.arkview.core import arkview_core
        
        # Test Rust implementation
        assert arkview_core.format_size(1023) == "1023 B"
        assert arkview_core.format_size(1024) == "1.0 KB"
        assert arkview_core.format_size(1024*1024) == "1.0 MB"
        
        print("Rust size formatting test passed!")
    except ImportError:
        print("Rust extension not available, skipping Rust size formatting test")
    
    # Test Python implementation
    from src.python.arkview.config import parse_human_size
    
    assert parse_human_size(1023) == "1023 B"
    assert parse_human_size(1024) == "1.0 KB"
    assert parse_human_size(1024*1024) == "1.0 MB"
    
    print("Python size formatting test passed!")


def test_backward_compatibility():
    """Test that old cache interfaces still work."""
    print("Testing backward compatibility...")
    from src.python.arkview.core.cache import LRUCache, AdaptiveLRUCache
    from PIL import Image
    
    # Create a simple test image
    test_image = Image.new('RGB', (50, 50), color='blue')
    
    # Test old LRU interface
    lru_cache = LRUCache(capacity=5)
    lru_cache.put(("test_lru",), test_image)
    result = lru_cache.get(("test_lru",))
    assert result is not None
    assert len(lru_cache) == 1
    
    # Test old AdaptiveLRU interface
    adaptive_cache = AdaptiveLRUCache(capacity=5)
    adaptive_cache.put(("test_adaptive",), test_image)
    result = adaptive_cache.get(("test_adaptive",))
    assert result is not None
    assert len(adaptive_cache) == 1
    
    print("Backward compatibility test passed!")


if __name__ == "__main__":
    print("Starting tests for refactored Arkview code...")
    
    test_config_module()
    test_cache_service()
    test_image_file_check()
    test_size_formatting()
    test_backward_compatibility()
    
    print("\nAll tests passed! Refactoring was successful.")