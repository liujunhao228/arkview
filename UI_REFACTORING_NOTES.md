# Arkview UI Refactoring - PySide Implementation

## Overview

This refactoring improves the code organization, maintainability, and extensibility of the Arkview PySide UI by introducing a unified View Management System. The external behavior remains completely unchanged.

## Key Improvements

### 1. **View Management System** (`pyside_views.py`)

#### New Components:

- **BaseView**: Abstract base class for all view implementations
  - Defines standard interface for all views: `create_ui()`, `on_show()`, `on_hide()`, `cleanup()`
  - Ensures consistency across different view types
  - Makes it trivial to add new view types

- **ViewManager**: Centralized view lifecycle manager
  - Handles view registration, switching, and visibility
  - Maintains current view state
  - Provides callbacks for view switch events
  - Eliminates scattered view management logic

- **ExplorerView**: Resource Explorer view implementation
  - Encapsulates the ZIP file list + preview panel UI
  - Previously scattered across MainApp
  - Ready to be extended with additional features

### 2. **Code Organization Improvements**

#### Before (pyside_main.py):
- 1327 lines with mixed concerns
- View creation, switching, and visibility logic scattered throughout
- Direct references to view widgets from MainApp
- Duplicate code for view button styling and visibility management

#### After:
- `pyside_main.py`: Focuses on application logic and event handling (~1250 lines)
- `pyside_views.py`: Contains view definitions and management (~350 lines)
- Clear separation of concerns
- View-specific UI creation isolated in respective classes

### 3. **Benefits**

#### Maintainability:
- View implementation details isolated in their own classes
- Changes to one view don't impact others
- Easier to locate and modify view-specific code

#### Extensibility:
- Adding new views is straightforward:
  1. Create a new class inheriting from `BaseView`
  2. Implement the four required methods
  3. Register with `ViewManager`
  4. Done! No need to modify MainApp's view switching logic

#### Consistency:
- All views follow the same interface
- View switching behavior is consistent and predictable
- Reduced risk of bugs when managing view states

### 4. **Architecture**

```
┌─────────────────────────────────────────┐
│         MainApp (Main Window)            │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │      ViewManager                   │ │
│  │  ┌──────────────┐                  │ │
│  │  │ExplorerView  │ (BaseView)       │ │
│  │  ├──────────────┤                  │ │
│  │  │ zip_listbox  │                  │ │
│  │  │preview_label │                  │ │
│  │  └──────────────┘                  │ │
│  │                                    │ │
│  │  ┌──────────────┐                  │ │
│  │  │ GalleryView  │ (not yet wrapped) │ │
│  │  └──────────────┘                  │ │
│  │                                    │ │
│  │  ┌──────────────┐                  │ │
│  │  │  SlideView   │ (not yet wrapped) │ │
│  │  └──────────────┘                  │ │
│  └────────────────────────────────────┘ │
│                                          │
│  Coordinated View Switching & State      │
└─────────────────────────────────────────┘
```

### 5. **Migration Approach**

To maintain backward compatibility and preserve all functionality:

1. **ExplorerView** is fully wrapped with the new system
2. **GalleryView** and **SlideView** remain as-is but are managed by ViewManager
3. MainApp maintains references to all view components for existing code
4. All signals, callbacks, and event handlers work exactly as before

### 6. **Future Extensions**

The new architecture makes it easy to add features like:

- **Comparison View**: Side-by-side image comparison
- **Batch Processing View**: Process multiple archives
- **Settings View**: Dedicated settings panel
- **Search View**: Full-text archive search
- **Thumbnail Grid View**: Alternative gallery layout

Each would simply:
1. Inherit from `BaseView`
2. Implement the required methods
3. Be registered with `ViewManager`

No modifications to MainApp's core view switching logic needed.

## Implementation Details

### ViewManager Features

```python
# Register a view
view_manager.register_view(my_view)

# Switch to a view
view_manager.switch_to_view("view_id")

# Get current view
current = view_manager.get_current_view()

# Listen for view changes
view_manager.on_view_switched(lambda prev, curr: ...)

# Clean up all views
view_manager.cleanup_all()
```

### Creating Custom Views

```python
from pyside_views import BaseView

class MyCustomView(BaseView):
    def __init__(self):
        super().__init__("custom", "My Custom View", "🎨")
    
    def create_ui(self) -> QFrame:
        # Build and return your UI
        frame = QFrame()
        layout = QVBoxLayout(frame)
        # ... build UI ...
        return frame
    
    def on_show(self):
        # Called when view becomes visible
        pass
    
    def on_hide(self):
        # Called when view is hidden
        pass
    
    def cleanup(self):
        # Clean up resources
        pass
```

## Backward Compatibility

- All existing functionality preserved
- API remains unchanged
- No impact on external code
- Same UI appearance and behavior
- Performance characteristics identical

## Testing

All functionality has been tested to ensure:
- View switching works correctly
- All controls respond to events
- Data flows between views as expected
- No visual regressions
- Memory management is correct

## Files Modified

- `src/python/arkview/pyside_main.py`: Refactored UI setup, added ViewManager integration
- `src/python/arkview/pyside_views.py`: NEW - View management system and ExplorerView

## Files Unchanged

- `src/python/arkview/pyside_gallery.py`: Gallery view (same functionality)
- `src/python/arkview/pyside_ui.py`: UI components like SlideView (same functionality)
- `src/python/arkview/core.py`: Core logic (same functionality)
- All other files remain unchanged
