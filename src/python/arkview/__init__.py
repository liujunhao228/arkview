"""
Arkview - High-Performance Archived Image Viewer
Hybrid Rust-Python Architecture
"""

__version__ = "4.0.0"

try:
    from . import arkview_core
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False

__all__ = ["RUST_AVAILABLE"]
