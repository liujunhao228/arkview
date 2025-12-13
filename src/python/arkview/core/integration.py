"""
Integration layer for Rust and Python implementations.
This module handles the fallback logic between Rust-accelerated and pure Python implementations.
"""

from typing import Optional, List, Tuple

# Try to import Rust components
try:
    from .. import arkview_core
    RUST_AVAILABLE = True
    ZipScannerRust = arkview_core.ZipScanner
    ImageProcessorRust = arkview_core.ImageProcessor
except ImportError:
    RUST_AVAILABLE = False
    ZipScannerRust = None
    ImageProcessorRust = None


class RustIntegrationLayer:
    """Centralized integration point for Rust components."""
    
    @staticmethod
    def is_rust_available() -> bool:
        """Check if Rust components are available."""
        return RUST_AVAILABLE
    
    @staticmethod
    def get_zip_scanner():
        """Get Rust-based ZIP scanner if available."""
        return ZipScannerRust() if RUST_AVAILABLE else None
    
    @staticmethod
    def get_image_processor():
        """Get Rust-based image processor if available."""
        return ImageProcessorRust() if RUST_AVAILABLE else None
