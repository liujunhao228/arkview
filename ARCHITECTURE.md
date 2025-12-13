# Arkview Architecture

## Overview

Arkview is a modern, high-performance image browser designed for quickly browsing images stored in ZIP archives. It uses a hybrid architecture combining Rust's I/O performance advantages with Python's flexibility in UI development.

## Key Components

### 1. Core Layer

Located in `src/python/arkview/core/`, this layer contains fundamental data structures and utilities:

- `models.py`: Data models like `ZipFileInfo` and utility functions
- `cache.py`: LRU cache implementation for efficient data storage
- `file_manager.py`: `ZipFileManager` class for managing ZIP file resources

### 2. Service Layer

Located in `src/python/arkview/services/`, this layer encapsulates business logic and provides clean APIs:

- `zip_service.py`: `ZipService` for ZIP scanning and analysis operations
- `image_service.py`: `ImageService` for image loading and processing
- `thumbnail_service.py`: `ThumbnailService` for thumbnail generation and caching
- `cache_service.py`: High-level cache management services
- `config_service.py`: Application configuration management

### 3. UI Layer

Located in `src/python/arkview/ui/`, this layer handles user interface presentation:

- `main_window.py`: Main application window
- `viewer_window.py`: Full-screen image viewer
- `gallery_view.py`: Thumbnail gallery view
- `dialogs.py`: Various dialog implementations

## Data Flow

```
[UI Layer]
    ↓ (uses)
[Service Layer] ←→ [Cache Service]
    ↓ (uses)
[Core Layer]
    ↓ (calls)
[Rust Backend via PyO3]
```

## Key Classes and Responsibilities

### ZipFileManager (Core Layer)
Manages opening and closing of ZipFile objects to avoid resource leaks:
- Implements LRU (Least Recently Used) strategy for keeping frequently accessed ZIP files open
- Thread-safe implementation using locks
- Limits maximum number of concurrently open ZIP files

### ZipService (Service Layer)
Provides higher-level ZIP file operations:
- ZIP content analysis to identify image-only archives
- Integration with Rust backend for performance acceleration
- Timeout control and batch processing capabilities
- Uses ZipFileManager internally for resource management

### ImageService (Service Layer)
Handles image loading and processing operations:
- Asynchronous image loading from ZIP archives
- Caching mechanisms for improved performance
- Preloading strategies for smooth browsing experience

### ThumbnailService (Service Layer)
Specialized service for thumbnail generation:
- Dedicated worker threads for thumbnail processing
- Integration with caching systems
- Performance optimization modes

## Communication Patterns

### Qt Signal/Slot Mechanism
Used extensively for asynchronous operations:
- Image loading completion notifications
- Progress updates
- Error reporting

### Dependency Injection
Services are injected into UI components to promote loose coupling:
- Cache services injected into image services
- Image services injected into thumbnail services
- Services injected into UI components

## Rust Integration

The Rust backend provides performance-critical functionality:
- Fast ZIP file scanning and analysis
- Optimized image processing routines
- Parallel processing capabilities

Communication with Python occurs through PyO3 FFI bindings.

## Caching Strategy

Arkview implements multi-layered caching:
- Primary cache for full-size images
- Thumbnail cache for preview images
- Metadata cache for ZIP file information

LRU eviction policy ensures optimal memory usage while maintaining performance.

## Threading Model

- UI runs on main thread
- Image loading operations occur in worker threads
- Thumbnail generation uses dedicated thread pool
- ZIP file I/O managed through resource manager with thread safety