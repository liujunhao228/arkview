# Arkview - High-performance ZIP Image Browser

Arkview is a modern, high-performance image browser designed specifically for quickly viewing images inside ZIP archives. It uses a Rust-Python hybrid architecture, combining Rust's I/O performance advantages with Python's flexibility in UI development.

![Screenshot](docs/screenshot.png)

## Features

- Fast scanning of ZIP files and identification of image files
- Thumbnail preview and full-screen multi-image viewer
- Drag-and-drop support and directory batch scanning
- LRU cache mechanism to improve repeated access performance
- Cross-platform support (Windows/macOS/Linux)
- Performance mode to trade quality for speed and memory usage

## Technical Architecture

```
+---------------------+
|     Python UI       |
| (PySide6 + Qt)      |
+----------+----------+
           |
           v
+---------------------+
|     Services        |
| (Business Logic)    |
+----------+----------+
           |
           v
+---------------------+
|   Rust-Python Bridge|
|    (PyO3 FFI)       |
+----------+----------+
           |
           v
+---------------------+
|     Rust Core       |
| (ZipScanner, Image  |
|  Processor, Utils)  |
+---------------------+
```

## Code Structure

- **main.py**: Main entry point
- **ui/**: UI layer components
  - **main_window.py**: Main application window
  - **gallery_view.py**: Gallery view implementation
  - **viewer_window.py**: Image viewer window
  - **dialogs.py**: Dialog components (Settings, About)
- **services/**: Business logic services
  - **zip_service.py**: ZIP file handling service
  - **image_service.py**: Image processing service
  - **thumbnail_service.py**: Thumbnail loading service
  - **cache_service.py**: Cache management service
  - **config_service.py**: Configuration management service
- **core/**: Core components
  - **models.py**: Data models
  - **cache.py**: LRU cache implementation
  - **file_manager.py**: ZIP file manager
  - **rust_bindings.py**: Rust bindings interface
- **core.py**: Legacy integration layer (deprecated)

## Performance Optimizations

1. **Rust Acceleration**: ZIP scanning and image processing are implemented in Rust for maximum performance
2. **LRU Cache**: Reduces repeated loading of the same images
3. **Async Loading**: Non-blocking image loading using Qt threading
4. **Performance Mode**: Option to reduce quality and memory usage for older hardware

## Requirements

- Python 3.8 or higher
- Rust toolchain (for building from source)
- PySide6 >= 6.5.0
- Pillow >= 9.0.0

## Installation

### From Source

```bash
# Install maturin
pip install maturin

# Clone and enter the project directory
git clone https://github.com/yourusername/arkview.git
cd arkview

# Development installation (automatically compiles Rust extension)
maturin develop

# Run
python -m arkview
```

### Building Executables

```bash
# Build wheel package
maturin build --release

# Or use the build script
python build.py exe    # Single executable file
python build.py dir    # Directory-based executable
```

## Usage

1. Launch Arkview
2. Drag and drop a folder containing ZIP files onto the window, or use "File" -> "Open Directory"
3. Browse through the gallery of ZIP archives
4. Click on any archive to select it, double-click to open the viewer
5. Toggle "Performance Mode" for faster operation on older hardware

## License

MIT License. See [LICENSE](LICENSE) for details.
