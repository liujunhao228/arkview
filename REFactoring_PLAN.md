# Arkview 重构方案

## 1. 现状分析

通过对代码的深入分析，我们了解到 Arkview 采用了典型的三层架构：
1. **核心层(core)** - 提供基础数据结构和通用功能
2. **服务层(services)** - 封装业务逻辑和提供API接口
3. **UI层(ui)** - 处理用户界面展示

目前系统已经具备了基本的图片浏览功能，包括 ZIP 文件解析、图片加载、缓存管理和用户界面等核心功能。

## 2. 为未来功能扩展的重构计划

### 2.1 引入 NavigationService（导航服务）

为了支持幻灯片放映、跨压缩包浏览等功能，我们需要一个专门的导航服务来管理图片序列和浏览逻辑。

```python
# src/python/arkview/services/navigation_service.py

"""
Navigation service for Arkview.
Handles navigation logic for slideshow, cross-archive browsing, and other advanced features.
"""

from typing import List, Optional, Tuple
from ..core.models import ZipFileInfo


class NavigationService:
    """Service for managing navigation between images and archives."""
    
    def __init__(self):
        self.archives: List[ZipFileInfo] = []
        self.current_archive_index = 0
        self.current_image_index = 0
        self.loop_mode = False  # 是否开启循环浏览
    
    def set_archives(self, archives: List[ZipFileInfo]):
        """Set the list of archives to navigate through."""
        self.archives = archives
        self.current_archive_index = 0
        self.current_image_index = 0
    
    def next_image(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Navigate to the next image.
        Returns tuple of (archive_path, image_member) or (None, None) if at end.
        """
        if not self.archives:
            return None, None
            
        current_archive = self.archives[self.current_archive_index]
        
        # 如果当前压缩包还有下一张图片
        if self.current_image_index < len(current_archive.members) - 1:
            self.current_image_index += 1
            return current_archive.path, current_archive.members[self.current_image_index]
        
        # 如果当前是最后一个压缩包且不循环
        if self.current_archive_index >= len(self.archives) - 1 and not self.loop_mode:
            return None, None
            
        # 移动到下一个压缩包
        self.current_archive_index = (self.current_archive_index + 1) % len(self.archives)
        self.current_image_index = 0
        
        next_archive = self.archives[self.current_archive_index]
        if next_archive.members:
            return next_archive.path, next_archive.members[0]
        
        return None, None
    
    def prev_image(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Navigate to the previous image.
        Returns tuple of (archive_path, image_member) or (None, None) if at beginning.
        """
        if not self.archives:
            return None, None
            
        # 如果当前图片不是压缩包内的第一张
        if self.current_image_index > 0:
            self.current_image_index -= 1
            current_archive = self.archives[self.current_archive_index]
            return current_archive.path, current_archive.members[self.current_image_index]
        
        # 如果当前是第一个压缩包且不循环
        if self.current_archive_index <= 0 and not self.loop_mode:
            return None, None
            
        # 移动到上一个压缩包
        self.current_archive_index = (self.current_archive_index - 1) % len(self.archives)
        prev_archive = self.archives[self.current_archive_index]
        
        if prev_archive.members:
            self.current_image_index = len(prev_archive.members) - 1
            return prev_archive.path, prev_archive.members[self.current_image_index]
        
        return None, None
    
    def get_current_position(self) -> Tuple[int, int, int]:
        """Get current position as (archive_index, image_index, total_archives)."""
        return self.current_archive_index, self.current_image_index, len(self.archives)
    
    def goto_position(self, archive_index: int, image_index: int):
        """Go to a specific position."""
        if 0 <= archive_index < len(self.archives):
            archive = self.archives[archive_index]
            if 0 <= image_index < len(archive.members):
                self.current_archive_index = archive_index
                self.current_image_index = image_index
```

### 2.2 增强 ImageViewerWindow 以支持幻灯片放映

我们需要扩展 ImageViewerWindow 以支持幻灯片放映功能：

```python
# src/python/arkview/ui/viewer_window.py （部分增强）

"""
Enhanced viewer window implementation for Arkview UI layer.
Adds support for slideshow functionality.
"""

from typing import List, Optional
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QLabel, QScrollArea, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QToolBar, QSizePolicy, QStatusBar, QSlider, QStyle
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QPropertyAnimation
from PySide6.QtGui import QPixmap, QAction, QKeySequence, QKeyEvent, QWheelEvent

from ..core.cache_keys import ImageCacheKind, make_image_cache_key
from ..core.file_manager import ZipFileManager
from ..core.models import LoadResult
from ..services.image_service import ImageService
from ..services.navigation_service import NavigationService  # 新增导入
from PIL import Image
import PIL.ImageQt


class ImageViewerWindow(QMainWindow):
    """Enhanced window for viewing images from ZIP archives with slideshow support."""
    
    def __init__(
        self,
        image_service: ImageService,
        navigation_service: NavigationService,  # 新增参数
        parent=None
    ):
        super().__init__(parent)
        
        self.image_service = image_service
        self.navigation_service = navigation_service  # 新增属性
        self.current_pixmap: Optional[QPixmap] = None
        self.scale_factor = 1.0
        self.min_scale = 0.1
        self.max_scale = 10.0
        self.zoom_factor = 1.2
        self.auto_fit = True
        self.performance_mode = False
        
        # 幻灯片放映相关属性
        self.slideshow_timer = QTimer()
        self.slideshow_timer.timeout.connect(self._next_slide)
        self.slideshow_delay = 3000  # 默认3秒间隔
        
        # Image state
        self.current_zip_path: Optional[str] = None
        self.image_members: List[str] = []
        self.current_index = 0
        
        self._setup_ui()
        self._setup_toolbar()
        self._setup_shortcuts()
        self._apply_dark_theme()
        

    def _setup_toolbar(self):
        """Setup the enhanced toolbar with slideshow controls."""
        toolbar = self.addToolBar('Main')
        toolbar.setMovable(False)
        
        # ... existing actions ...
        
        # 幻灯片放映相关动作
        self.slideshow_action = QAction("Slideshow", self)
        self.slideshow_action.setCheckable(True)
        self.slideshow_action.triggered.connect(self._toggle_slideshow)
        toolbar.addAction(self.slideshow_action)
        
        # 幻灯片速度控制
        speed_slider = QSlider(Qt.Horizontal)
        speed_slider.setRange(1, 10)  # 1-10秒
        speed_slider.setValue(3)  # 默认3秒
        speed_slider.setToolTip("Slide duration")
        speed_slider.valueChanged.connect(self._change_slideshow_speed)
        toolbar.addWidget(speed_slider)
        
    def _toggle_slideshow(self, checked):
        """Toggle slideshow mode."""
        if checked:
            self.slideshow_timer.start(self.slideshow_delay)
            self.slideshow_action.setText("Stop Slideshow")
        else:
            self.slideshow_timer.stop()
            self.slideshow_action.setText("Slideshow")
            
    def _change_slideshow_speed(self, value):
        """Change slideshow speed."""
        self.slideshow_delay = value * 1000  # 转换为毫秒
        if self.slideshow_timer.isActive():
            self.slideshow_timer.stop()
            self.slideshow_timer.start(self.slideshow_delay)
            
    def _next_slide(self):
        """Show the next slide in slideshow mode."""
        next_archive, next_member = self.navigation_service.next_image()
        if next_archive and next_member:
            self.display_image(next_archive, next_member)
        else:
            # 到达末尾，停止幻灯片
            self._toggle_slideshow(False)
```

### 2.3 增强 MainWindow 以支持新功能

更新主窗口以整合新服务和支持新功能：

```python
# src/python/arkview/ui/main_window.py （部分增强）

"""
Enhanced main window implementation for Arkview UI layer.
Adds support for new features like cross-archive browsing.
"""

# ... existing imports ...
from ..services.navigation_service import NavigationService  # 新增导入


class MainWindow(QMainWindow):
    """Enhanced main application window with support for new features."""
    
    def __init__(self):
        super().__init__()
        
        # Initialize services
        self._initialize_services()
        
        # Initialize UI
        self._setup_ui()
        
        # Initialize state
        self._initialize_state()
        
        # Apply dark theme
        self._apply_dark_theme()
        
    def _initialize_services(self):
        """Initialize all required services."""
        # Initialize services
        self.cache_service = CacheService(capacity=CONFIG["CACHE_MAX_ITEMS_NORMAL"])
        self.zip_manager = ZipFileManager()

        # Initialize other services
        self.zip_service = ZipService()
        self.image_service = ImageService(self.cache_service, self.zip_manager)
        self.thumbnail_service = ThumbnailService(self.cache_service, CONFIG)
        self.config_service = ConfigService()
        self.navigation_service = NavigationService()  # 新增服务

        # Connect thumbnail service signals
        self.thumbnail_service.thumbnailLoaded.connect(self._on_thumbnail_loaded)
        
```

### 2.4 创建播放列表功能

为支持跨压缩包浏览，我们需要实现播放列表功能：

```python
# src/python/arkview/services/playlist_service.py

"""
Playlist service for Arkview.
Manages playlists for sequential image viewing across archives.
"""

from typing import List, Optional
from ..core.models import ZipFileInfo


class PlaylistEntry:
    """Represents an entry in the playlist."""
    
    def __init__(self, archive_path: str, image_member: str):
        self.archive_path = archive_path
        self.image_member = image_member


class PlaylistService:
    """Service for managing image playlists."""
    
    def __init__(self):
        self.entries: List[PlaylistEntry] = []
        self.current_index = 0
        self.loop_mode = False
    
    def create_from_archives(self, archives: List[ZipFileInfo]):
        """Create a playlist from a list of archives."""
        self.entries = []
        for archive in archives:
            if archive.members:
                for member in archive.members:
                    self.entries.append(PlaylistEntry(archive.path, member))
        self.current_index = 0
    
    def next_entry(self) -> Optional[PlaylistEntry]:
        """Get the next entry in the playlist."""
        if not self.entries:
            return None
            
        if self.current_index < len(self.entries) - 1:
            self.current_index += 1
            return self.entries[self.current_index]
        
        if self.loop_mode:
            self.current_index = 0
            return self.entries[0]
            
        return None
    
    def prev_entry(self) -> Optional[PlaylistEntry]:
        """Get the previous entry in the playlist."""
        if not self.entries:
            return None
            
        if self.current_index > 0:
            self.current_index -= 1
            return self.entries[self.current_index]
        
        if self.loop_mode:
            self.current_index = len(self.entries) - 1
            return self.entries[self.current_index]
            
        return None
    
    def get_current_entry(self) -> Optional[PlaylistEntry]:
        """Get the current entry."""
        if 0 <= self.current_index < len(self.entries):
            return self.entries[self.current_index]
        return None
    
    def set_current_index(self, index: int):
        """Set the current index."""
        if 0 <= index < len(self.entries):
            self.current_index = index
    
    def get_progress(self) -> tuple:
        """Get playback progress as (current, total)."""
        return self.current_index, len(self.entries)
```

## 3. 总结

这个重构方案为 Arkview 的后续功能扩展提供了良好的基础：

1. **NavigationService** - 提供了统一的导航逻辑，便于实现幻灯片放映和跨压缩包浏览
2. **增强的 ImageViewerWindow** - 添加了幻灯片放映功能和相关 UI 控件
3. **PlaylistService** - 为跨压缩包浏览提供了播放列表管理功能

这些改动都是非破坏性的，它们在现有架构的基础上增加了新功能，同时保持了原有功能的完整性。这样可以确保在添加新功能时不会影响现有的稳定功能。

下一步可以根据具体需求逐步实现这些功能模块，并通过适当的 UI 控件让用户能够方便地使用这些新功能。