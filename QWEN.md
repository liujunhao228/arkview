# Arkview Project Overview

## Project Type
Arkview is a **hybrid Rust-Python application** designed as a high-performance image viewer for archived images in ZIP files. It combines the performance benefits of Rust for I/O operations with the flexibility of Python for the user interface.

## Project Purpose
Arkview is a modern, high-performance image viewer specifically designed to quickly browse images within archive files (ZIP). It features a hybrid Rust-Python architecture that combines the performance benefits of Rust for I/O operations with the flexibility of Python for the user interface.

## Architecture
- **Rust Backend (`src/lib.rs`)**: Provides performance-critical operations with:
  - ZipScanner: Fast ZIP file analysis and image file detection
  - ImageProcessor: Image validation, thumbnail generation, and metadata extraction
  - PyO3 bindings for Python integration
- **Python Frontend**: 
  - Core integration layer with LRU cache and async image loading (`src/python/arkview/core.py`)
  - UI components (`src/python/arkview/ui.py`)
  - Main application window and orchestration (`src/python/arkview/main.py`)

## Core Components

### Rust Components (`src/lib.rs`)
- **ZipScanner**: Fast ZIP file analysis for identifying archives containing only image files
- **ImageProcessor**: Image validation, thumbnail generation, and metadata extraction
- **Utilities**: Helper functions including `format_size` for file size formatting

### Python Components
- **core.py**: Integration layer between Rust and Python, including LRU cache and async image loading
- **ui.py**: UI components (SettingsDialog, ImageViewerWindow)
- **main.py**: Main application window and orchestration

## Key Features
- Hybrid Rust-Python architecture with PyO3 integration
- Fast ZIP scanning using native Rust implementation (10x+ performance improvement)
- Preview & Viewer: Browse thumbnails with a full-screen multi-image viewer
- Performance Mode: Optimize for speed and lower memory usage on limited hardware
- Drag & Drop: Drag and drop archives into the application (requires `tkinterdnd2`)
- Batch Scanning: Scan entire directories for image archives
- Caching: LRU cache for thumbnail and viewer images
- Cross-Platform: Works on Windows, macOS, and Linux

## Building and Running

### Prerequisites
- Python 3.8 or higher
- Rust toolchain (for building from source)

### Development Build
```bash
# Install dependencies
pip install maturin

# Build and install (development mode with debug info)
maturin develop

# Or for optimized development build
maturin develop --release
```

### Production Build
```bash
# Create wheel for distribution
maturin build --release --out dist/
```

### Running the Application
```bash
# After building with maturin
python -m arkview.main

# Or directly if installed
arkview
```

## Dependencies

### Build Dependencies
- **maturin**: Rust-Python build tool
- **Rust toolchain**: For compiling Rust code

### Runtime Dependencies  
- **Pillow** (>=9.0.0): Image processing
- **ttkbootstrap** (>=1.10.0): Modern Tkinter UI theming

### Optional Dependencies
- **tkinterdnd2** (>=0.3.0): Drag and drop support

### Rust Dependencies
- **pyo3**: Rust-Python interop
- **zip**: ZIP file reading  
- **image**: Image format handling and processing
- **rayon**: Data parallelism
- **parking_lot**: Efficient synchronization primitives

## Development Conventions

### Code Structure
- Rust code in `src/lib.rs` with PyO3 bindings
- Python modules in `src/python/arkview/`:
  - `core.py`: Core integration logic
  - `ui.py`: UI components  
  - `main.py`: Main application logic

### Performance Optimizations
- Rust acceleration for ZIP scanning and image processing
- LRU caching for images to reduce repeated loading
- Async loading using thread pools
- Performance mode to trade quality for speed on limited hardware
- Optimized build settings with LTO and code stripping

### Build Optimization Settings
The `Cargo.toml` includes aggressive optimization settings:
- `opt-level = 3`: Maximum optimization
- `lto = true`: Link-time optimization  
- `strip = true`: Strip debug symbols
- `codegen-units = 1`: Better optimization

## Performance Metrics
- ZIP scanning: 10x+ faster than pure Python implementation
- Image loading: 3x faster than pure Python implementation
- Memory usage: 30-40% lower peak memory usage
- Binary size: Significantly reduced through Rust optimization

## Testing
The project supports pytest for testing:
```bash
# Run tests
pytest tests/
```

## File Structure
```
arkview/
├── src/
│   ├── lib.rs                          # Rust backend implementation
│   └── python/arkview/
│       ├── __init__.py                 # Package initialization
│       ├── core.py                     # Core Python-Rust integration
│       ├── ui.py                       # UI components
│       └── main.py                     # Main application
├── Cargo.toml                          # Rust dependencies and build config
├── pyproject.toml                      # Python project metadata (PEP 517/518)
├── setup.py                            # Legacy Python setup (fallback)
├── .gitignore                          # Git ignore rules
├── README.md                           # User documentation
└── DEVELOPMENT.md                      # Developer documentation
```

## Configuration
Settings accessible through the Settings dialog:
- Performance Mode: Trade quality for speed
- Multi-Image Viewer: Enable/disable the full-screen viewer
- Preload Thumbnails: Automatically load the next thumbnail (disabled in performance mode)

## Supported Formats
- Image formats: JPEG, PNG, GIF, BMP, TIFF, WebP, ICO
- Archive format: ZIP files containing image files
- Maximum ZIP file size: Determined by available memory

## Troubleshooting
- If Rust acceleration is not available, the application will fall back to pure Python implementation
- For high memory usage, enable Performance Mode in settings or reduce cache size
- Drag and drop requires optional tkinterdnd2 dependency