# Arkview PySide Migration Guide

## Overview
Arkview has been successfully migrated from tkinter to PySide6 for better performance while maintaining the same UI appearance and interaction style.

## Changes Made

### 1. New PySide Implementation
- Created PySide6 versions of all UI components:
  - `pyside_main.py` - Main application window
  - `pyside_ui.py` - Settings dialog and image viewer
  - `pyside_gallery.py` - Gallery view component

### 2. Dependency Updates
- Updated `pyproject.toml` to replace `ttkbootstrap` with `PySide6>=6.5.0`
- Added new entry point for PySide version: `arkview-pyside`

### 3. Feature Preservation
All original functionality has been preserved:
- Resource Explorer view with ZIP file list and image preview
- Gallery view with thumbnail grid
- Settings dialog
- Multi-image viewer
- Keyboard shortcuts (Ctrl+G, Ctrl+E, Tab, arrow keys, etc.)
- Dark theme styling
- Multi-threaded image loading
- Drag and drop support (where available in PySide)

## Running the Application

### PySide Version (Recommended for performance)
```bash
# Direct execution
python -m arkview.pyside_main

# Or if installed as package
arkview-pyside
```

### Original tkinter Version (Still available)
```bash
# Direct execution
python -m arkview.main

# Or if installed as package
arkview
```

## Key Improvements with PySide

1. **Better Performance**: PySide6 offers improved rendering and UI responsiveness
2. **Modern UI Framework**: More maintainable and extensible codebase
3. **Cross-platform Consistency**: Better appearance across different platforms
4. **Active Development**: PySide6 continues to receive updates and improvements

## Migration Notes

- All original keyboard shortcuts and interactions are preserved
- UI appearance remains virtually identical to the original
- The same configuration and settings are maintained
- Image loading and caching behavior is unchanged

## Technical Details

- Uses PySide6.QtWidgets for all UI components
- Maintains the same multi-threaded image loading approach
- Preserves all original functionality and workflows
- Implements the same dark theme styling as the tkinter version