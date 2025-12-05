"""Gallery view implemented with PySide6."""

from __future__ import annotations

import os
import queue
from typing import Any, Callable, Dict, List, Optional, Tuple

from concurrent.futures import ThreadPoolExecutor

from PySide6 import QtCore, QtGui, QtWidgets

from .core import LRUCache, ZipFileManager, load_image_data_async, _format_size
from .qtcommon import PreviewLabel, pil_image_to_qpixmap


class GalleryView(QtWidgets.QWidget):
    """Grid-based gallery with preview navigation."""

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        zip_files: Dict[str, Tuple[Optional[List[str]], float, int, int]],
        app_settings: Dict[str, Any],
        cache: LRUCache,
        thread_pool: ThreadPoolExecutor,
        zip_manager: ZipFileManager,
        config: Dict[str, Any],
        ensure_members_loaded_callback: Callable[[str], Optional[List[str]]],
        selection_callback: Optional[Callable[[str, List[str], int], None]] = None,
        open_viewer_callback: Optional[Callable[[str, List[str], int], None]] = None,
    ):
        super().__init__(parent)
        self.zip_files = zip_files
        self.app_settings = app_settings
        self.cache = cache
        self.thread_pool = thread_pool
        self.zip_manager = zip_manager
        self.config = config
        self.ensure_members_loaded = ensure_members_loaded_callback
        self.selection_callback = selection_callback
        self.open_viewer_callback = open_viewer_callback

        self.thumbnail_queue: queue.Queue = queue.Queue()
        self.preview_queue: queue.Queue = queue.Queue()
        self.thumbnail_requests: Dict[tuple, QtWidgets.QListWidgetItem] = {}

        self.current_zip: Optional[str] = None
        self.current_members: Optional[List[str]] = None
        self.current_index: int = 0
        self.preview_future = None
        self.preview_cache_key: Optional[tuple] = None
        self.preview_pixmap: Optional[QtGui.QPixmap] = None
        self._thumbnail_timer_active = False
        self._preview_timer_active = False

        self._placeholder_icon = self._create_icon("⏳", "#1f2123", "#555555")
        self._error_icon = self._create_icon("⚠️", "#2b1e1e", "#ff7b72")

        self._setup_ui()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        header_layout = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("🎞️ Gallery")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        self.album_count_label = QtWidgets.QLabel("")
        self.album_count_label.setStyleSheet("color: #aaaaaa;")
        header_layout.addWidget(self.album_count_label)
        layout.addLayout(header_layout)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        layout.addWidget(splitter, 1)

        # Album grid -----------------------------------------------------
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 4, 4, 4)

        self.album_list = QtWidgets.QListWidget()
        self.album_list.setViewMode(QtWidgets.QListView.IconMode)
        self.album_list.setResizeMode(QtWidgets.QListView.Adjust)
        self.album_list.setMovement(QtWidgets.QListView.Static)
        self.album_list.setIconSize(QtCore.QSize(220, 220))
        self.album_list.setSpacing(16)
        self.album_list.setWordWrap(True)
        self.album_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.album_list.setStyleSheet(
            "QListWidget { background-color: #1a1d1e; border: 1px solid #2a2d2e; }"
            "QListWidget::item { color: #f8f9fa; }"
            "QListWidget::item:selected { border: 2px solid #00bc8c; }"
        )
        self.album_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.album_list.itemDoubleClicked.connect(self._handle_double_click)
        left_layout.addWidget(self.album_list, 1)

        splitter.addWidget(left_widget)

        # Preview panel --------------------------------------------------
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setSpacing(8)
        right_layout.setContentsMargins(8, 4, 8, 4)

        nav_layout = QtWidgets.QHBoxLayout()
        self.preview_prev_button = QtWidgets.QPushButton("◀ Prev")
        self.preview_prev_button.clicked.connect(self._preview_prev)
        self.preview_prev_button.setEnabled(False)
        nav_layout.addWidget(self.preview_prev_button)

        self.preview_info_label = QtWidgets.QLabel("Tap an album to preview")
        self.preview_info_label.setAlignment(QtCore.Qt.AlignCenter)
        nav_layout.addWidget(self.preview_info_label, 1)

        self.preview_next_button = QtWidgets.QPushButton("Next ▶")
        self.preview_next_button.clicked.connect(self._preview_next)
        self.preview_next_button.setEnabled(False)
        nav_layout.addWidget(self.preview_next_button)
        right_layout.addLayout(nav_layout)

        self.preview_label = PreviewLabel()
        self.preview_label.setText("Tap an album to preview")
        self.preview_label.clicked.connect(self._handle_preview_click)
        self.preview_label.scrolled.connect(self._handle_preview_scroll)
        right_layout.addWidget(self.preview_label, 1)

        self.preview_hint_label = QtWidgets.QLabel(
            "Double-click an album or preview to open the viewer."
        )
        self.preview_hint_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_hint_label.setStyleSheet("color: #9da0a4;")
        right_layout.addWidget(self.preview_hint_label)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

    # -------------------------------------------------------------- Helpers
    def _create_icon(self, text: str, bg: str, fg: str) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(220, 220)
        pixmap.fill(QtGui.QColor(bg))
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor(fg))
        font = painter.font()
        font.setPointSize(32)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, text)
        painter.end()
        return QtGui.QIcon(pixmap)

    # ----------------------------------------------------------- Public API
    def populate(self) -> None:
        self.album_list.clear()
        self.thumbnail_requests.clear()
        self._reset_preview("Tap an album to preview")

        zip_paths = list(self.zip_files.keys())
        if not zip_paths:
            self.album_count_label.setText("No albums")
            return

        self.album_count_label.setText(f"{len(zip_paths)} albums")
        for zip_path in zip_paths:
            item = self._create_album_item(zip_path)
            self.album_list.addItem(item)
            self._queue_thumbnail(zip_path, item)

    def handle_keypress(self, event: QtGui.QKeyEvent) -> bool:
        if not self.current_members:
            return False
        key = event.key()
        if key == QtCore.Qt.Key_Left:
            self._preview_prev()
            return True
        if key == QtCore.Qt.Key_Right:
            self._preview_next()
            return True
        if key in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._open_current_in_viewer()
            return True
        if key == QtCore.Qt.Key_Escape:
            self.album_list.clearSelection()
            self._reset_preview("Tap an album to preview")
            return True
        if key == QtCore.Qt.Key_Home:
            self._load_preview_at_index(0)
            return True
        if key == QtCore.Qt.Key_End and self.current_members:
            self._load_preview_at_index(len(self.current_members) - 1)
            return True
        return False

    # ----------------------------------------------------------- Item setup
    def _create_album_item(self, zip_path: str) -> QtWidgets.QListWidgetItem:
        item = QtWidgets.QListWidgetItem()
        item.setText(os.path.basename(zip_path))
        item.setIcon(self._placeholder_icon)
        item.setData(QtCore.Qt.UserRole, zip_path)
        item.setSizeHint(QtCore.QSize(230, 260))
        entry = self.zip_files.get(zip_path)
        if entry:
            _, mod_time, file_size, image_count = entry
            tooltip = f"{image_count} images\n{_format_size(file_size)}"
            if mod_time:
                tooltip += f"\nUpdated: {mod_time:.0f}"
            item.setToolTip(tooltip)
        return item

    # ----------------------------------------------------- Thumbnail loading
    def _queue_thumbnail(self, zip_path: str, item: QtWidgets.QListWidgetItem) -> None:
        entry = self.zip_files.get(zip_path)
        if entry and entry[0]:
            member = entry[0][0]
            self._request_thumbnail(zip_path, member, item)
        else:
            self.thread_pool.submit(self._load_members_for_thumbnail, zip_path, item)

    def _load_members_for_thumbnail(self, zip_path: str, item: QtWidgets.QListWidgetItem) -> None:
        try:
            members = self.ensure_members_loaded(zip_path)
        except Exception:
            members = None
        if members:
            QtCore.QTimer.singleShot(
                0, lambda: self._request_thumbnail(zip_path, members[0], item)
            )
        else:
            QtCore.QTimer.singleShot(0, lambda: item.setIcon(self._error_icon))

    def _request_thumbnail(self, zip_path: str, member: str, item: QtWidgets.QListWidgetItem) -> None:
        cache_key = (zip_path, member)
        if cache_key in self.thumbnail_requests:
            return
        self.thumbnail_requests[cache_key] = item
        self.thread_pool.submit(
            load_image_data_async,
            zip_path,
            member,
            self.app_settings.get("max_thumbnail_size", self.config["MAX_THUMBNAIL_LOAD_SIZE"]),
            self.config["GALLERY_THUMB_SIZE"],
            self.thumbnail_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.app_settings.get("performance_mode", False),
        )
        self._schedule_thumbnail_poll()

    def _schedule_thumbnail_poll(self) -> None:
        if self._thumbnail_timer_active:
            return
        self._thumbnail_timer_active = True
        QtCore.QTimer.singleShot(50, self._process_thumbnail_queue)

    def _process_thumbnail_queue(self) -> None:
        self._thumbnail_timer_active = False
        processed = 0
        while processed < 30:
            try:
                result = self.thumbnail_queue.get_nowait()
            except queue.Empty:
                break
            item = self.thumbnail_requests.pop(result.cache_key, None)
            if not item:
                processed += 1
                continue
            if result.success and result.data:
                pixmap = pil_image_to_qpixmap(result.data)
                item.setIcon(QtGui.QIcon(pixmap))
            else:
                item.setIcon(self._error_icon)
            processed += 1
        if not self.thumbnail_queue.empty():
            self._schedule_thumbnail_poll()

    # ------------------------------------------------------- Selection logic
    def _on_selection_changed(self) -> None:
        selected = self.album_list.selectedItems()
        if not selected:
            self.current_zip = None
            self.current_members = None
            self._reset_preview("Tap an album to preview")
            return

        item = selected[0]
        zip_path = item.data(QtCore.Qt.UserRole)
        entry = self.zip_files.get(zip_path)
        members = entry[0] if entry else None
        if members is None:
            members = self.ensure_members_loaded(zip_path)
            if not members:
                self._reset_preview("No images found")
                return
            if entry:
                self.zip_files[zip_path] = (members, entry[1], entry[2], len(members))
        self.current_zip = zip_path
        self.current_members = members
        self.current_index = 0
        self._load_preview(zip_path, members, 0)
        self._emit_selection(zip_path, members, 0)

    def _emit_selection(self, zip_path: str, members: List[str], index: int) -> None:
        if self.selection_callback:
            self.selection_callback(zip_path, members, index)

    # --------------------------------------------------- Preview management
    def _load_preview(self, zip_path: str, members: List[str], index: int) -> None:
        if not members or not (0 <= index < len(members)):
            return
        if self.preview_future and not self.preview_future.done():
            self.preview_future.cancel()
        self._drain_preview_queue()

        self.current_index = index
        cache_key = (zip_path, members[index])
        self.preview_cache_key = cache_key
        self.preview_prev_button.setEnabled(index > 0)
        self.preview_next_button.setEnabled(index + 1 < len(members))
        self.preview_info_label.setText(f"Image {index + 1} / {len(members)}")
        self.preview_label.setText("Loading preview...")
        self.preview_label.setPixmap(QtGui.QPixmap())

        self.preview_future = self.thread_pool.submit(
            load_image_data_async,
            zip_path,
            members[index],
            self.app_settings.get("max_thumbnail_size", self.config["MAX_THUMBNAIL_LOAD_SIZE"]),
            self.config["GALLERY_PREVIEW_SIZE"],
            self.preview_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.app_settings.get("performance_mode", False),
        )
        self._schedule_preview_poll()

    def _drain_preview_queue(self) -> None:
        while True:
            try:
                self.preview_queue.get_nowait()
            except queue.Empty:
                break

    def _schedule_preview_poll(self) -> None:
        if self._preview_timer_active:
            return
        self._preview_timer_active = True
        QtCore.QTimer.singleShot(40, self._process_preview_queue)

    def _process_preview_queue(self) -> None:
        self._preview_timer_active = False
        try:
            while True:
                result = self.preview_queue.get_nowait()
                if result.cache_key != self.preview_cache_key:
                    continue
                if result.success and result.data:
                    pixmap = pil_image_to_qpixmap(result.data)
                    self.preview_pixmap = pixmap
                    self.preview_label.setPixmap(pixmap)
                    self.preview_label.setText("")
                else:
                    self.preview_label.setText(result.error_message or "Preview failed")
                    self.preview_label.setPixmap(QtGui.QPixmap())
                return
        except queue.Empty:
            if self.preview_future and not self.preview_future.done():
                self._schedule_preview_poll()

    def _load_preview_at_index(self, index: int) -> None:
        if self.current_zip and self.current_members:
            self._load_preview(self.current_zip, self.current_members, index)
            self._emit_selection(self.current_zip, self.current_members, index)

    def _reset_preview(self, message: str) -> None:
        if self.preview_future and not self.preview_future.done():
            self.preview_future.cancel()
        self.preview_future = None
        self.preview_cache_key = None
        self.current_index = 0
        self.preview_label.setPixmap(QtGui.QPixmap())
        self.preview_label.setText(message)
        self.preview_info_label.setText(message)
        self.preview_prev_button.setEnabled(False)
        self.preview_next_button.setEnabled(False)

    # ------------------------------------------------------ Preview actions
    def _preview_prev(self) -> None:
        if self.current_members and self.current_index > 0:
            self._load_preview_at_index(self.current_index - 1)

    def _preview_next(self) -> None:
        if self.current_members and self.current_index + 1 < len(self.current_members):
            self._load_preview_at_index(self.current_index + 1)

    def _handle_preview_scroll(self, direction: int) -> None:
        if direction > 0:
            self._preview_prev()
        else:
            self._preview_next()

    def _handle_preview_click(self) -> None:
        self._open_current_in_viewer()

    def _handle_double_click(self, item: QtWidgets.QListWidgetItem) -> None:
        self._open_current_in_viewer()

    def _open_current_in_viewer(self) -> None:
        if self.open_viewer_callback and self.current_zip and self.current_members:
            self.open_viewer_callback(self.current_zip, self.current_members, self.current_index)
