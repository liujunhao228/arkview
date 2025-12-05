"""PySide6 UI components for Arkview."""

from __future__ import annotations

import os
import queue
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets

from .core import LRUCache, ZipFileManager, load_image_data_async
from .qtcommon import pil_image_to_qpixmap


class SettingsDialog(QtWidgets.QDialog):
    """Application settings dialog."""

    def __init__(self, parent: QtWidgets.QWidget, current_settings: Dict[str, Any]):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Settings")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.settings = current_settings
        self.result_settings = current_settings.copy()

        main_layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("Application Settings")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(title)

        self.performance_checkbox = QtWidgets.QCheckBox(
            "⚡ Performance Mode (Faster, Lower Quality)"
        )
        self.performance_checkbox.setChecked(self.result_settings.get("performance_mode", False))
        self.performance_checkbox.toggled.connect(self._update_dependent_settings)
        main_layout.addWidget(self.performance_checkbox)

        self.viewer_checkbox = QtWidgets.QCheckBox(
            "👁️ Enable Multi-Image Viewer (Click Preview)"
        )
        self.viewer_checkbox.setChecked(self.result_settings.get("viewer_enabled", True))
        main_layout.addWidget(self.viewer_checkbox)

        self.preload_checkbox = QtWidgets.QCheckBox(
            "🔄 Preload Next Thumbnail (in Preview)"
        )
        self.preload_checkbox.setChecked(self.result_settings.get("preload_next_thumbnail", True))
        main_layout.addWidget(self.preload_checkbox)

        main_layout.addStretch(1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self._update_dependent_settings()

    def _update_dependent_settings(self) -> None:
        is_performance = self.performance_checkbox.isChecked()
        self.preload_checkbox.setEnabled(not is_performance)
        if is_performance and self.preload_checkbox.isChecked():
            self.preload_checkbox.setChecked(False)

    def accept(self) -> None:
        self.result_settings["performance_mode"] = self.performance_checkbox.isChecked()
        self.result_settings["viewer_enabled"] = self.viewer_checkbox.isChecked()
        if not self.performance_checkbox.isChecked():
            self.result_settings["preload_next_thumbnail"] = self.preload_checkbox.isChecked()
        else:
            self.result_settings["preload_next_thumbnail"] = False
        super().accept()


class ImageViewerWindow(QtWidgets.QDialog):
    """Modal dialog for browsing images within a ZIP archive."""

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        zip_path: str,
        image_members: List[str],
        initial_index: int,
        settings: Dict[str, Any],
        cache: LRUCache,
        result_queue: queue.Queue,
        thread_pool: ThreadPoolExecutor,
        zip_manager: ZipFileManager,
        max_load_size: int,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"👁️ Viewer: {os.path.basename(zip_path)}")
        self.setModal(True)
        self.resize(900, 650)
        self.setMinimumSize(600, 420)

        self.zip_path = zip_path
        self.image_members = image_members
        self.settings = settings
        self.cache = cache
        self.result_queue = result_queue
        self.thread_pool = thread_pool
        self.zip_manager = zip_manager
        self.max_load_size = max_load_size

        self.current_index = max(0, min(initial_index, len(image_members) - 1))
        self.current_pil_image: Optional[Image.Image] = None
        self._current_pixmap: Optional[QtGui.QPixmap] = None
        self._current_cache_key: Optional[tuple] = None
        self._load_future = None
        self._result_timer_active = False
        self._is_loading = False
        self._is_fullscreen = False
        self.zoom_factor = 1.0
        self.fit_to_window = True

        self._setup_ui()
        QtCore.QTimer.singleShot(0, lambda: self.load_image(self.current_index))

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        nav_layout = QtWidgets.QHBoxLayout()
        self.prev_button = QtWidgets.QPushButton("◀ Prev")
        self.prev_button.clicked.connect(self._show_prev)
        nav_layout.addWidget(self.prev_button)

        self.image_info_label = QtWidgets.QLabel("Image 0 / 0")
        self.image_info_label.setAlignment(QtCore.Qt.AlignCenter)
        nav_layout.addWidget(self.image_info_label, 1)

        self.next_button = QtWidgets.QPushButton("Next ▶")
        self.next_button.clicked.connect(self._show_next)
        nav_layout.addWidget(self.next_button)
        layout.addLayout(nav_layout)

        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #1c1e1f; border: 1px solid #3c3f41;")
        layout.addWidget(self.image_label, 1)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setAlignment(QtCore.Qt.AlignLeft)
        layout.addWidget(self.status_label)

    # Navigation helpers --------------------------------------------------
    def _show_prev(self) -> None:
        if self.current_index > 0:
            self.load_image(self.current_index - 1)

    def _show_next(self) -> None:
        if self.current_index + 1 < len(self.image_members):
            self.load_image(self.current_index + 1)

    def _update_navigation_buttons(self) -> None:
        self.prev_button.setEnabled(self.current_index > 0)
        self.next_button.setEnabled(self.current_index + 1 < len(self.image_members))
        self.image_info_label.setText(
            f"Image {self.current_index + 1} / {max(len(self.image_members), 1)}"
        )

    # Image loading -------------------------------------------------------
    def load_image(self, index: int) -> None:
        if not (0 <= index < len(self.image_members)):
            return

        self.current_index = index
        self._update_navigation_buttons()
        self._is_loading = True
        self.status_label.setText("Loading image...")
        self._drain_queue()

        cache_key = (self.zip_path, self.image_members[index])
        self._current_cache_key = cache_key
        self.fit_to_window = True
        self.zoom_factor = 1.0

        self._load_future = self.thread_pool.submit(
            load_image_data_async,
            self.zip_path,
            self.image_members[index],
            self.max_load_size,
            None,
            self.result_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.settings.get("performance_mode", False),
        )
        self._schedule_result_poll()

    def _drain_queue(self) -> None:
        while True:
            try:
                self.result_queue.get_nowait()
            except queue.Empty:
                break

    def _schedule_result_poll(self) -> None:
        if self._result_timer_active:
            return
        self._result_timer_active = True
        QtCore.QTimer.singleShot(40, self._process_result_queue)

    def _process_result_queue(self) -> None:
        self._result_timer_active = False
        try:
            while True:
                result = self.result_queue.get_nowait()
                if result.cache_key != self._current_cache_key:
                    continue

                self._is_loading = False
                if result.success and result.data:
                    self.current_pil_image = result.data
                    self.status_label.setText("")
                    self._update_display()
                else:
                    message = result.error_message or "Failed to load image"
                    self.status_label.setText(message)
                return
        except queue.Empty:
            if self._is_loading:
                self._schedule_result_poll()

    def _update_display(self) -> None:
        if self.current_pil_image is None:
            self.image_label.clear()
            return

        img = self.current_pil_image.copy()
        if self.fit_to_window:
            target_width = max(10, self.image_label.width() - 12)
            target_height = max(10, self.image_label.height() - 12)
            img.thumbnail((target_width, target_height), self._resample_mode())
        else:
            new_width = int(img.width * self.zoom_factor)
            new_height = int(img.height * self.zoom_factor)
            if new_width > 0 and new_height > 0:
                img = img.resize((new_width, new_height), self._resample_mode())

        pixmap = pil_image_to_qpixmap(img)
        self._current_pixmap = pixmap
        self.image_label.setPixmap(pixmap)

    def _resample_mode(self) -> int:
        return (
            Image.Resampling.NEAREST
            if self.settings.get("performance_mode", False)
            else Image.Resampling.LANCZOS
        )

    # Event handling ------------------------------------------------------
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        key = event.key()
        if key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_PageUp):
            self._show_prev()
            return
        if key in (QtCore.Qt.Key_Right, QtCore.Qt.Key_PageDown):
            self._show_next()
            return
        if key == QtCore.Qt.Key_Escape:
            self.close()
            return
        if key == QtCore.Qt.Key_F:
            self.fit_to_window = not self.fit_to_window
            self._update_display()
            return
        if key == QtCore.Qt.Key_R:
            self.zoom_factor = 1.0
            self.fit_to_window = True
            self._update_display()
            return
        if key == QtCore.Qt.Key_Home:
            self.load_image(0)
            return
        if key == QtCore.Qt.Key_End:
            self.load_image(len(self.image_members) - 1)
            return
        if key == QtCore.Qt.Key_F11:
            self._toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta:
            factor = 1.2 if delta > 0 else 1 / 1.2
            self.zoom_factor = max(0.1, min(10.0, self.zoom_factor * factor))
            self.fit_to_window = False
            self._update_display()
        super().wheelEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.fit_to_window:
            self._update_display()

    def _toggle_fullscreen(self) -> None:
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            self.showFullScreen()
        else:
            self.showNormal()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._is_loading = False
        if self._load_future and not self._load_future.done():
            self._load_future.cancel()
        super().closeEvent(event)
