# Development Guide for Arkview

## Project Structure

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
└── DEVELOPMENT.md                      # This file
```

## Setup Development Environment

### Prerequisites

- Python 3.8+
- Rust 1.70+ (from https://rustup.rs/)
- Git

### Initial Setup

```bash
# Clone repository
git clone https://github.com/yourusername/arkview.git
cd arkview

# Install Rust (if not already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install --upgrade pip setuptools wheel
pip install maturin pytest Pillow
```

### Building the Project

#### Using Maturin (Recommended)

```bash
# Development build (with debug info)
maturin develop

# Development build (optimized)
maturin develop --release

# Production build (wheel)
maturin build --release
```

#### Using Cargo + Setup.py (Alternative)

```bash
# Build Rust extension
cargo build --release

# Install Python package
pip install -e .
```

## Development Workflow

### Running the Application

```bash
# After building with maturin
python -m arkview.main

# Or directly
arkview
```

### Testing

```bash
# Run tests
pytest tests/

# Run with coverage
pytest --cov=arkview tests/
```

### Code Structure

#### Rust Module (`src/lib.rs`)

- **ZipScanner class**: Scans ZIP archives for image files
  - `is_image_file()`: Checks if a file is a recognized image format
  - `analyze_zip()`: Returns metadata and image list from a ZIP file

- **ImageProcessor class**: Processes images
  - `generate_thumbnail()`: Creates thumbnails with specified dimensions
  - `extract_image_from_zip()`: Extracts raw image data from archives
  - `validate_image_format()`: Validates image format

#### Python Core Module (`src/python/arkview/core.py`)

- **LRUCache**: Thread-safe cache implementation
- **ZipFileManager**: Manages open ZIP file handles
- **ZipScanner**: Python wrapper around Rust scanner with fallback
- **LoadResult**: Data class for async results
- **load_image_data_async()**: Async image loading worker

#### UI Module (`src/python/arkview/ui.py`)

- **SettingsDialog**: Settings configuration window
- **ImageViewerWindow**: Full-screen image viewer

#### Main Application (`src/python/arkview/main.py`)

- **MainApp**: Main application class
  - Manages ZIP file list
  - Handles user interactions
  - Coordinates threading and loading

## Building Optimization

### Rust Build Optimization

The `Cargo.toml` includes optimization settings:

```toml
[profile.release]
opt-level = 3              # Maximum optimization
lto = true                 # Link-time optimization
strip = true               # Strip debug symbols
codegen-units = 1          # Better optimization
```

This results in a small, fast binary (~5-10 MB depending on platform).

### Python Packaging Optimization

- Uses `[build-system]` standard (PEP 517/518)
- Maturin handles Rust compilation automatically
- Minimal dependencies (only Pillow required)

## Performance Profiling

### Profile Python Code

```bash
# Using cProfile
python -m cProfile -s cumulative -m arkview.main

# Using py-spy
pip install py-spy
py-spy record -o profile.svg -- python -m arkview.main
```

### Profile Rust Code

```bash
# Using perf (Linux)
cargo build --release
perf record --call-graph=dwarf ./target/release/arkview
perf report

# Using Instruments (macOS)
cargo instruments -t "System Trace" --release
```

## Common Issues

### Build Fails: "PyO3 version mismatch"

```bash
# Solution: Reinstall maturin and clean
pip install --upgrade maturin
cargo clean
maturin develop --release
```

### Import Error: "No module named arkview_core"

This means the Rust extension wasn't built. Rebuild with maturin:

```bash
maturin develop --release
```

### PySide6 Import Error

PySide6 is installed automatically via `pip install .`, but you can install it manually:

```bash
pip install PySide6>=6.5.0
```

If you are on Linux and encounter issues with missing Qt platform plugins, ensure you have the necessary system packages (e.g., `qt6-base-dev` on Debian/Ubuntu) or run with `QT_QPA_PLATFORM=xcb` on Wayland.

## Contributing Guidelines

### Code Style

- **Python**: Follow PEP 8, use type hints
- **Rust**: Use `cargo fmt` and `cargo clippy`

```bash
# Format Rust code
cargo fmt

# Check for issues
cargo clippy -- -D warnings
```

### Before Committing

```bash
# Format all code
cargo fmt
autopep8 -r --in-place src/python/

# Run linters
cargo clippy -- -D warnings
pylint src/python/arkview/

# Run tests
pytest tests/
```

## Release Process

1. Update version in `Cargo.toml` and `setup.py`
2. Update `CHANGELOG` section in `README.md`
3. Create git tag: `git tag v4.0.0`
4. Build wheels: `maturin build --release`
5. Upload to PyPI: `twine upload dist/*`

## Debugging

### Enable Rust Logging

```bash
RUST_LOG=debug python -m arkview.main
```

### Python Debugging with PDB

```python
# In Python code
import pdb; pdb.set_trace()
```

### Environment Variables

- `RUST_LOG`: Set Rust logging level (debug, info, warn, error)
- `PYTHONUNBUFFERED=1`: Unbuffered Python output

## Architecture Notes

### Why Hybrid Approach?

1. **Rust for Performance**: Native ZIP reading, image detection are much faster than pure Python
2. **Python for Flexibility**: UI updates, complex logic are easier to maintain in Python
3. **Minimal Overhead**: PyO3 bridge is very efficient (~0% overhead for simple operations)

### Threading Model

- Main thread: Tkinter UI (single-threaded requirement)
- Worker threads: Image loading via ThreadPoolExecutor
- Queue-based communication: Results passed back to main thread
- Lock-based synchronization: Thread-safe caching with parking_lot

### Memory Management

- LRU Cache limits memory usage for loaded images
- Rust manages ZIP file handles efficiently
- PIL images are eagerly loaded to prevent stream issues
- Reference counting ensures cleanup

## Performance Targets

- ZIP scanning: < 1s for 1GB archive (10x faster than pure Python)
- Thumbnail loading: < 500ms for 280x280px thumbnail
- Viewer load: < 2s for full-resolution image (100MB file)
- Memory footprint: < 200MB for typical usage

## Useful Resources

- [PyO3 Documentation](https://pyo3.rs/)
- [Maturin Documentation](https://www.maturin.rs/)
- [Rust Image Crate](https://docs.rs/image/)
- [Rust Zip Crate](https://docs.rs/zip/)
