# Arkview Quick Start Guide

## Installation

### Option 1: From Source (Recommended for Development)

```bash
# Prerequisites: Python 3.8+, Rust, Git

# Clone repository
git clone https://github.com/yourusername/arkview.git
cd arkview

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install maturin and build
pip install maturin
maturin develop --release

# Run
arkview
```

### Option 2: Using pip (When Available on PyPI)

```bash
pip install arkview
arkview
```

### Option 3: Docker

```bash
docker run -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix arkview
```

## Usage

### Launch Application

```bash
arkview
```

### Basic Workflow

1. **Scan Directory**: Click "Scan Directory" to find all ZIP files containing only images
2. **Select Archive**: Click an archive in the left panel
3. **Preview Image**: First image appears in the preview pane
4. **View Full Size**: Click preview to open the multi-image viewer
5. **Browse**: Use arrow keys or buttons to navigate images

### Keyboard Shortcuts

In the viewer window:

| Key | Action |
|-----|--------|
| `←` / `→` | Previous / Next image |
| `↑` / `↓` | Page Up / Down |
| `Home` / `End` | First / Last image |
| `F11` | Toggle fullscreen |
| `f` | Toggle fit-to-window |
| `r` | Reset zoom |
| `Scroll` / `Mouse Wheel` | Zoom in/out |
| `Esc` | Close viewer |

### Settings

Open Settings (menu or button) to:

- **Performance Mode**: Faster loading with lower quality (for older hardware)
- **Multi-Image Viewer**: Enable/disable the full-screen viewer
- **Preload Thumbnails**: Auto-load next thumbnail (disabled in performance mode)

## Supported Archive Formats

- ZIP files only
- Must contain **only image files**

## Supported Image Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)
- GIF (.gif)
- BMP (.bmp)
- TIFF (.tiff)
- WebP (.webp)
- ICO (.ico)

## Features

✅ **Fast ZIP Scanning**: Quickly identifies valid image archives
✅ **Preview Thumbnails**: Low-resolution previews for quick browsing
✅ **Full Viewer**: High-resolution multi-image viewer
✅ **Drag & Drop**: Drag archives into the window (optional feature)
✅ **Performance Mode**: Reduced quality for older hardware
✅ **Batch Operations**: Scan entire directories

## Tips & Tricks

### Optimize Performance

1. Enable "Performance Mode" in settings
2. On older hardware, reduce cache size
3. Close other applications to free memory

### Handle Large Archives

1. Split very large archives into smaller ones
2. Increase "Thread Pool Workers" in config (if available)
3. Enable Performance Mode

### Troubleshooting

**Application won't start?**
- Ensure Python 3.8+ is installed
- Check that Pillow is installed: `pip install Pillow`
- For Rust features: `pip install maturin` and rebuild

**Drag & Drop not working?**
- Drag-and-drop is built in via PySide6; ensure you launch Arkview from a graphical desktop session
- Restart the application or try running with `QT_QPA_PLATFORM=xcb` on Wayland-based Linux desktops

**Images loading slowly?**
- Enable Performance Mode in settings
- Check system resources (RAM, CPU)
- Archive may be corrupted - try another

## Configuration

Edit archive browser settings in the Settings dialog:

```
Performance Mode        → Toggle for speed vs quality trade-off
Multi-Image Viewer      → Enable/disable full-screen viewer
Preload Thumbnails      → Pre-cache next thumbnail
```

## Environment Variables

```bash
# Enable debug logging (Rust)
RUST_LOG=debug arkview

# Unbuffered Python output
PYTHONUNBUFFERED=1 arkview
```

## System Requirements

| Aspect | Minimum | Recommended |
|--------|---------|-------------|
| OS | Windows/macOS/Linux | Any modern OS |
| RAM | 2 GB | 4 GB or more |
| Disk | 100 MB | 500 MB |
| Screen | 800x600 | 1920x1080 |
| Python | 3.8 | 3.11+ |

## Next Steps

- Read [README.md](README.md) for detailed documentation
- Check [DEVELOPMENT.md](DEVELOPMENT.md) for developer info
- Review [REFACTOR_SUMMARY.md](REFACTOR_SUMMARY.md) for architecture details

## Getting Help

1. Check Troubleshooting section above
2. Review error messages in console output
3. Report issues on GitHub with details:
   - Python version
   - Operating system
   - Archive file (if shareable)
   - Full error traceback

## Common Issues & Solutions

### Issue: "No module named 'PIL'"

**Solution:** Install Pillow
```bash
pip install Pillow
```

### Issue: "Rust acceleration not available"

**Solution:** Rebuild without Rust (pure Python mode)
```bash
pip install . --no-binary arkview
# Or install pre-built wheel
```

### Issue: Application runs slowly

**Solution:** Enable Performance Mode
```
Menu → Settings → Check "Performance Mode"
```

### Issue: Archives don't show up when scanning

**Solution:** Ensure archives contain ONLY images
```bash
# Check archive contents
unzip -l archive.zip
```

Archive is valid if ALL files are image files (no directories or other files).

## Feedback

Your feedback helps improve Arkview:

- Feature requests
- Bug reports
- Performance tips
- Use cases

Submit through GitHub issues or pull requests!

---

**Happy browsing! 📸**
