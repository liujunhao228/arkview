# Arkview - High-Performance ZIP Image Browser

## Project Overview

Arkview is a modern, high-performance image browser designed specifically for quickly viewing images inside ZIP archives. It uses a Rust-Python hybrid architecture, combining Rust's I/O performance advantages with Python's flexibility in UI development. The application provides both a GUI interface and command-line functionality for browsing image collections stored in ZIP files.

**Architecture:**
- **Python UI Layer**: Built with PySide6/Qt for cross-platform desktop interface
- **Services Layer**: Business logic for ZIP handling, image processing, and caching
- **Rust-Python Bridge**: Created with PyO3 FFI for high-performance operations
- **Rust Core**: ZIP scanning, image processing, and utility functions

## Key Components

### Rust Core (`src/lib.rs`)
The Rust component provides three main classes:
- `ZipScanner`: Analyzes ZIP files to determine if they contain only images, counts images, and extracts metadata
- `ImageProcessor`: Handles image extraction and thumbnail generation from ZIP files
- `format_size`: Utility function for human-readable file size formatting

### Python Bindings (`src/python/arkview/arkview_core.*.pyd`)
The compiled Rust extension is exposed to Python through PyO3-generated bindings.

### Python Application Layer
- **Main entry points**: Located in `src/python/arkview/main.py`
- **UI components**: Located in `src/python/arkview/ui/`
- **Service layer**: Located in `src/python/arkview/services/`
- **Core utilities**: Located in `src/python/arkview/core/`

## Building and Running

### Development Setup
```bash
# Install maturin
pip install maturin

# Development installation (compiles Rust extension automatically)
maturin develop

# Run the application
python -m arkview
```

### Production Builds
```bash
# Build wheel package
maturin build --release

# Alternative build methods using build.py
python build.py wheel    # Build wheel package
python build.py exe      # Build standalone executable (single file)
python build.py dir      # Build standalone executable (directory)
```

### Dependencies
- **Runtime**: Python 3.8+, PySide6 >= 6.5.0, Pillow >= 9.0.0
- **Build**: Rust toolchain, maturin
- **Development**: pytest >= 7.0 (optional)

## Performance Optimizations

1. **Rust Acceleration**: ZIP scanning and image processing are implemented in Rust for maximum performance
2. **LRU Cache**: Reduces repeated loading of the same images
3. **Async Loading**: Non-blocking image loading using Qt threading
4. **Performance Mode**: Option to reduce quality and memory usage for older hardware
5. **File Size Limits**: Implements limits (500MB) and entry limits (10,000) to prevent resource exhaustion
6. **Timeout Protection**: Analysis operations timeout after 15 seconds to prevent hanging

## Features

- Fast scanning of ZIP files and identification of image files
- Thumbnail preview and full-screen multi-image viewer
- Drag-and-drop support and directory batch scanning
- LRU cache mechanism to improve repeated access performance
- Cross-platform support (Windows/macOS/Linux)
- Performance mode to trade quality for speed and memory usage

## Development Conventions

- The project follows a hybrid Rust/Python architecture, with performance-critical code in Rust
- Uses PyO3 for safe Rust-Python interoperability
- Implements timeout mechanisms and resource limits to ensure stability
- Uses MIT license (as specified in README)
- Organizes Python code in a layered architecture: UI → Services → Core → Rust bindings

## Project Files

- `Cargo.toml` - Rust project configuration and dependencies
- `pyproject.toml` - Python packaging configuration using maturin
- `build.py` - Custom build script for wheels and executables using PyInstaller
- `setup.py` - Traditional Python packaging setup
- `ARCHITECTURE.md` - Detailed architecture documentation (if exists)
- `src/lib.rs` - Rust core implementation
- `src/python/` - Python application source