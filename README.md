# Arkview - Archived Image Viewer

高性能压缩包图片浏览器 / High-Performance Archived Image Viewer

## Overview

Arkview is a modern, high-performance image viewer designed to quickly browse images within archive files (ZIP). It features a hybrid Rust-Python architecture that combines the performance benefits of Rust for I/O operations with the flexibility of Python for the user interface.

## Key Features

- **Hybrid Architecture**: Rust backend for performance-critical operations, Python frontend for UI
- **Fast ZIP Scanning**: Quickly identifies archives containing only image files using native Rust implementation
- **Preview & Viewer**: Browse thumbnails with a full-screen multi-image viewer
- **Performance Mode**: Optimize for speed and lower memory usage on limited hardware
- **Drag & Drop**: Drag and drop archives into the application (requires `tkinterdnd2`)
- **Batch Scanning**: Scan entire directories for image archives
- **Caching**: LRU cache for thumbnail and viewer images
- **Cross-Platform**: Works on Windows, macOS, and Linux

## Installation

### Prerequisites

- Python 3.8 or higher
- Rust toolchain (for building from source)

### From Source

```bash
# Clone the repository
git clone https://github.com/yourusername/arkview.git
cd arkview

# Build and install (requires Rust toolchain)
pip install .

# Or for development with maturin
pip install maturin
maturin develop
```

### From Binary

Pre-built wheels are available for common platforms.

## Usage

### Command Line

```bash
arkview
```

### Direct Python

```python
from arkview.main import main
main()
```

## Architecture

### Rust Components (`src/lib.rs`)

- **ZipScanner**: Fast ZIP file analysis and image file detection
- **ImageProcessor**: Image validation, thumbnail generation, and metadata extraction
- **Utilities**: Helper functions for file size formatting

### Python Components

- **core.py**: Integration layer between Rust and Python, including LRU cache and async image loading
- **ui.py**: UI components (SettingsDialog, ImageViewerWindow)
- **main.py**: Main application window and orchestration

## Performance Optimizations

1. **Rust Acceleration**: ZIP scanning and image processing are implemented in Rust for maximum performance
2. **LRU Cache**: Reduces repeated loading of the same images
3. **Async Loading**: Non-blocking image loading using thread pools
4. **Performance Mode**: Option to reduce quality and memory usage for older hardware
5. **Minimal Dependencies**: Optimized to reduce binary size and startup time

## Configuration

Settings are accessible through the Settings dialog:

- **Performance Mode**: Trade quality for speed
- **Multi-Image Viewer**: Enable/disable the full-screen viewer
- **Preload Thumbnails**: Automatically load the next thumbnail (disabled in performance mode)

## Building

### Native Build

```bash
# Using maturin (recommended)
pip install maturin
maturin develop  # Development build
maturin build --release  # Production build

# Or using standard Rust/setuptools
cargo build --release
```

### Building for Distribution

```bash
# Create wheel
pip install build
python -m build

# Or with maturin
maturin build --release --out dist
```

## Dependencies

### Core Dependencies

- **Pillow** (>=9.0.0): Image processing
- **PyO3**: Rust-Python interop

### Optional Dependencies

- **tkinterdnd2** (>=0.3.0): Drag and drop support

### Rust Dependencies

- **image**: Image format handling and processing
- **zip**: ZIP file reading
- **rayon**: Data parallelism
- **parking_lot**: Efficient synchronization primitives

## System Requirements

- **Minimum**: 2 GB RAM, 100 MB disk space
- **Recommended**: 4 GB RAM, modern multi-core CPU
- **Screen**: 800x600 minimum resolution

## Known Limitations

- Maximum ZIP file size: Determined by available memory
- Supported formats: JPEG, PNG, GIF, BMP, TIFF, WebP, ICO
- Single-threaded UI (tkinter limitation)

## Troubleshooting

### "Rust acceleration not available"

The application will fall back to pure Python implementation. This is slower but still functional. To enable Rust support, rebuild with the Rust toolchain installed.

### Memory usage too high

- Enable Performance Mode in settings
- Reduce cache size in configuration
- Process archives one at a time

### Slow on large archives

- Increase thread pool workers (THREAD_POOL_WORKERS in config)
- Enable Performance Mode
- Consider splitting large archives

## Contributing

Contributions are welcome! Please ensure:

1. Code follows existing style conventions
2. Rust code is optimized and well-commented for complex logic
3. Python code maintains type hints
4. All changes are tested

## License

BSD-2-Clause License - See LICENSE file for details

## Version

Current Version: 4.0.0 (Rust-Python Hybrid Optimized)

## Changelog

### 4.0.0
- Complete refactor with Rust-Python hybrid architecture
- Native ZIP scanning for 10x+ performance improvement
- Reduced binary size through Rust optimization
- LRU caching improvements
- Modern build system with maturin

### 3.9
- Previous Python-only implementation
- Performance optimizations
- UI refinements

## Authors

Arkview Contributors

## Support

For issues, feature requests, or questions, please use the GitHub issue tracker.

## UI Framework Options

Arkview now supports two UI frameworks:
- **tkinter** (original implementation) - run with `arkview`
- **PySide6** (recommended for better performance) - run with `arkview-pyside`

Both implementations provide identical functionality and appearance. The PySide6 version offers better performance and more modern UI rendering.
