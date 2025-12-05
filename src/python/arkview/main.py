"""Main Arkview application powered by PySide6."""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from .core import (
    ZipScanner,
    ZipFileManager,
    LRUCache,
    load_image_data_async,
    RUST_AVAILABLE,
    _format_size,
)
from .ui import SettingsDialog, ImageViewerWindow
from .gallery import GalleryView
from .qtcommon import PreviewLabel, pil_image_to_qpixmap

CONFIG: Dict[str, Any] = {
    "IMAGE_EXTENSIONS": {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.ico'},
    "THUMBNAIL_SIZE": (280, 280),
    "PERFORMANCE_THUMBNAIL_SIZE": (180, 180),
    "GALLERY_THUMB_SIZE": (220, 220),
    "GALLERY_PREVIEW_SIZE": (480, 480),
    "BATCH_SCAN_SIZE": 50,
    "BATCH_UPDATE_INTERVAL": 20,
    "MAX_THUMBNAIL_LOAD_SIZE": 10 * 1024 * 1024,
    "PERFORMANCE_MAX_THUMBNAIL_LOAD_SIZE": 3 * 1024 * 1024,
    "MAX_VIEWER_LOAD_SIZE": 100 * 1024 * 1024,
    "PERFORMANCE_MAX_VIEWER_LOAD_SIZE": 30 * 1024 * 1024,
    "CACHE_MAX_ITEMS_NORMAL": 50,
    "CACHE_MAX_ITEMS_PERFORMANCE": 25,
    "WINDOW_SIZE": "1050x750",
    "VIEWER_ZOOM_FACTOR": 1.2,
    "VIEWER_MAX_ZOOM": 10.0,
    "VIEWER_MIN_ZOOM": 0.1,
    "PREVIEW_UPDATE_DELAY": 250,
    "THREAD_POOL_WORKERS": min(8, (os.cpu_count() or 1) + 4),
    "APP_VERSION": "4.0 - Rust-Python Hybrid",
}


def parse_human_size(size_str: str) -> Optional[int]:
    """Parse human-readable size like `10MB` into bytes."""
    size_str = size_str.strip().upper()
    if not size_str:
        return None
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([KMGT])?B?$", size_str)
    if not match:
        if size_str.isdigit():
            return int(size_str)
        return -1

    value = float(match.group(1))
    unit = match.group(2)
    multipliers = {'G': 1024 ** 3, 'M': 1024 ** 2, 'K': 1024, None: 1}
    return int(value * multipliers.get(unit, 1))


def format_datetime(timestamp: float) -> str:
    try:
        return QtCore.QDateTime.fromSecsSinceEpoch(int(timestamp)).toString("yyyy-MM-dd HH:mm:ss")
    except Exception:
        return "N/A"


class MainApp(QtWidgets.QMainWindow):
    """Main Arkview window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Arkview {CONFIG['APP_VERSION']}")
        self.resize(1050, 750)
        self.setMinimumSize(720, 520)
        self.setAcceptDrops(True)

        self.zip_scanner = ZipScanner()
        self.zip_manager = ZipFileManager()
        self.cache = LRUCache(CONFIG["CACHE_MAX_ITEMS_NORMAL"])
        self.preview_queue: queue.Queue = queue.Queue()
        self.thread_pool = ThreadPoolExecutor(max_workers=CONFIG["THREAD_POOL_WORKERS"])

        self.app_settings: Dict[str, Any] = {
            "performance_mode": False,
            "viewer_enabled": True,
            "preload_next_thumbnail": CONFIG.get("PRELOAD_NEXT_THUMBNAIL", True),
            "max_thumbnail_size": CONFIG["MAX_THUMBNAIL_LOAD_SIZE"],
        }
        self._viewer_max_load = CONFIG["MAX_VIEWER_LOAD_SIZE"]
        self._apply_settings()

        self.zip_files: Dict[str, Tuple[Optional[List[str]], float, int, int]] = {}
        self.current_selected_zip: Optional[str] = None
        self.current_preview_index: Optional[int] = None
        self.current_preview_members: Optional[List[str]] = None
        self.current_preview_cache_key: Optional[Tuple[str, str]] = None
        self.current_preview_future = None
        self.preview_pixmap: Optional[QtGui.QPixmap] = None
        self._preview_timer_active = False

        self.scan_thread: Optional[threading.Thread] = None
        self.scan_stop_event = threading.Event()

        self.current_view = "explorer"
        self.gallery_widget: Optional[GalleryView] = None

        self._setup_ui()
        self._setup_menu()
        self._setup_shortcuts()

        if RUST_AVAILABLE:
            self.setWindowTitle(f"{self.windowTitle()} [Rust Accelerated]")

    # ------------------------------------------------------------------ UI
    def _setup_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        switch_layout = QtWidgets.QHBoxLayout()
        view_label = QtWidgets.QLabel("View:")
        view_label.setStyleSheet("font-weight: bold;")
        switch_layout.addWidget(view_label)

        self.explorer_view_button = QtWidgets.QPushButton("📋 Resource Explorer")
        self.explorer_view_button.setCheckable(True)
        self.explorer_view_button.clicked.connect(lambda: self._switch_view("explorer"))
        switch_layout.addWidget(self.explorer_view_button)

        self.gallery_view_button = QtWidgets.QPushButton("🎞️ Gallery")
        self.gallery_view_button.setCheckable(True)
        self.gallery_view_button.clicked.connect(lambda: self._switch_view("gallery"))
        switch_layout.addWidget(self.gallery_view_button)
        switch_layout.addStretch(1)
        main_layout.addLayout(switch_layout)

        self.view_stack = QtWidgets.QStackedWidget()
        self.explorer_view = self._build_explorer_view()
        self.gallery_view_container = self._build_gallery_view()
        self.view_stack.addWidget(self.explorer_view)
        self.view_stack.addWidget(self.gallery_view_container)
        main_layout.addWidget(self.view_stack, 1)

        bottom_widget = QtWidgets.QWidget()
        bottom_layout = QtWidgets.QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(8)

        scan_button = QtWidgets.QPushButton("📁 Scan Directory")
        scan_button.clicked.connect(self._scan_directory)
        button_layout.addWidget(scan_button)

        view_button = QtWidgets.QPushButton("👁️ View")
        view_button.clicked.connect(self._open_viewer)
        button_layout.addWidget(view_button)

        clear_button = QtWidgets.QPushButton("🗑️ Clear")
        clear_button.clicked.connect(self._clear_list)
        button_layout.addWidget(clear_button)

        settings_button = QtWidgets.QPushButton("⚙️ Settings")
        settings_button.clicked.connect(self._show_settings)
        button_layout.addWidget(settings_button)

        bottom_layout.addLayout(button_layout)
        bottom_layout.addStretch(1)
        main_layout.addWidget(bottom_widget)

        self.status_label = QtWidgets.QLabel("Ready")
        self.statusBar().addPermanentWidget(self.status_label)

        self._update_view_buttons()
        self._update_view_visibility()
        self._reset_preview()
        self._refresh_gallery()

    def _build_explorer_view(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        layout.addWidget(splitter, 1)

        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_label = QtWidgets.QLabel("📦 Archives")
        left_label.setStyleSheet("font-weight: bold;")
        left_layout.addWidget(left_label)

        self.zip_list_widget = QtWidgets.QListWidget()
        self.zip_list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.zip_list_widget.itemSelectionChanged.connect(self._on_zip_selected)
        self.zip_list_widget.setStyleSheet(
            "QListWidget { background-color: #1f2123; color: #f8f9fa; border: 1px solid #2f3336; }"
            "QListWidget::item:selected { background: #00bc8c; color: #101214; }"
        )
        left_layout.addWidget(self.zip_list_widget, 1)
        splitter.addWidget(left_widget)

        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_label = QtWidgets.QLabel("🖼️  Preview")
        right_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(right_label)

        nav_layout = QtWidgets.QHBoxLayout()
        self.preview_prev_button = QtWidgets.QPushButton("◀ Prev")
        self.preview_prev_button.setEnabled(False)
        self.preview_prev_button.clicked.connect(self._preview_prev)
        nav_layout.addWidget(self.preview_prev_button)

        self.preview_info_label = QtWidgets.QLabel("")
        self.preview_info_label.setAlignment(QtCore.Qt.AlignCenter)
        nav_layout.addWidget(self.preview_info_label, 1)

        self.preview_next_button = QtWidgets.QPushButton("Next ▶")
        self.preview_next_button.setEnabled(False)
        self.preview_next_button.clicked.connect(self._preview_next)
        nav_layout.addWidget(self.preview_next_button)
        right_layout.addLayout(nav_layout)

        self.preview_label = PreviewLabel()
        self.preview_label.setCursor(QtCore.Qt.PointingHandCursor)
        self.preview_label.clicked.connect(self._open_viewer)
        self.preview_label.scrolled.connect(self._on_preview_scroll)
        right_layout.addWidget(self.preview_label, 1)

        details_group = QtWidgets.QGroupBox("ℹ️  Details")
        details_layout = QtWidgets.QVBoxLayout(details_group)
        self.details_text = QtWidgets.QTextEdit()
        self.details_text.setReadOnly(True)
        details_layout.addWidget(self.details_text)
        right_layout.addWidget(details_group)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        return container

    def _build_gallery_view(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.gallery_widget = GalleryView(
            container,
            self.zip_files,
            self.app_settings,
            self.cache,
            self.thread_pool,
            self.zip_manager,
            CONFIG,
            self._ensure_members_loaded,
            self._on_gallery_selection,
            self._open_viewer_from_gallery,
        )
        layout.addWidget(self.gallery_widget)
        return container

    def _setup_menu(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        file_menu.addAction("Scan Directory", self._scan_directory)
        file_menu.addAction("Add ZIP File", self._add_zip_file)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction("Settings", self._show_settings)
        view_menu.addAction("Clear List", self._clear_list)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("About", self._show_about)

    def _setup_shortcuts(self) -> None:
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+G"), self, activated=lambda: self._switch_view("gallery"))
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+E"), self, activated=lambda: self._switch_view("explorer"))
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Tab), self, activated=self._handle_tab_switch)

    # ---------------------------------------------------------- Qt events
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if self.current_view == "gallery" and self.gallery_widget:
            if self.gallery_widget.handle_keypress(event):
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".zip"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            return
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if path.lower().endswith(".zip"):
                    self._add_zip_entry(path)

    # --------------------------------------------------------- View logic
    def _handle_tab_switch(self) -> None:
        if self.current_view == "explorer":
            self._switch_view("gallery")
        else:
            self._switch_view("explorer")

    def _switch_view(self, view: str) -> None:
        if view not in {"explorer", "gallery"}:
            return
        if self.current_view == view:
            return
        self.current_view = view
        self._update_view_buttons()
        self._update_view_visibility()
        if view == "gallery" and self.gallery_widget:
            self.gallery_widget.populate()

    def _update_view_buttons(self) -> None:
        self.explorer_view_button.setChecked(self.current_view == "explorer")
        self.gallery_view_button.setChecked(self.current_view == "gallery")

    def _update_view_visibility(self) -> None:
        if self.current_view == "explorer":
            self.view_stack.setCurrentWidget(self.explorer_view)
        else:
            self.view_stack.setCurrentWidget(self.gallery_view_container)

    def _refresh_gallery(self) -> None:
        if self.gallery_widget:
            self.gallery_widget.populate()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    # ------------------------------------------------------ File handling
    def _scan_directory(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Directory to Scan")
        if not directory:
            return
        self._set_status("Scanning...")
        self.scan_stop_event.clear()
        self.scan_thread = threading.Thread(
            target=self._scan_directory_worker,
            args=(directory,),
            daemon=True,
        )
        self.scan_thread.start()

    def _scan_directory_worker(self, directory: str) -> None:
        try:
            zip_files = [str(p) for p in Path(directory).glob("**/*.zip")]
            total_files = len(zip_files)
            if total_files == 0:
                self._run_on_main_thread(self._set_status, "No ZIP files found")
                return

            batch_size = max(1, CONFIG["BATCH_SCAN_SIZE"])
            ui_update_interval = max(1, CONFIG["BATCH_UPDATE_INTERVAL"])
            pending_entries: List[Tuple[str, Optional[List[str]], Optional[float], Optional[int], Optional[int]]] = []
            processed = 0
            valid_found = 0

            def flush_pending() -> None:
                if not pending_entries:
                    return
                batch = pending_entries.copy()
                pending_entries.clear()
                self._run_on_main_thread(self._add_zip_entries_bulk, batch)

            for start in range(0, total_files, batch_size):
                if self.scan_stop_event.is_set():
                    break
                batch_paths = zip_files[start:start + batch_size]
                try:
                    batch_results = self.zip_scanner.batch_analyze_zips(batch_paths, collect_members=False)
                except Exception as exc:
                    self._run_on_main_thread(
                        lambda: QtWidgets.QMessageBox.critical(self, "Error", f"Scan error: {exc}")
                    )
                    self._run_on_main_thread(self._set_status, "Scan failed")
                    return
                for zip_path, is_valid, members, mod_time, file_size, image_count in batch_results:
                    processed += 1
                    if is_valid:
                        pending_entries.append((zip_path, members, mod_time, file_size, image_count))
                        valid_found += 1
                if len(pending_entries) >= batch_size:
                    flush_pending()
                if processed % ui_update_interval == 0 or processed >= total_files:
                    self._run_on_main_thread(
                        self._set_status,
                        f"Scanning... {processed}/{total_files} files processed",
                    )

            flush_pending()
            final_message = (
                "Scan canceled" if self.scan_stop_event.is_set()
                else f"Found {valid_found} valid archives (of {processed} scanned)"
            )
            self._run_on_main_thread(self._set_status, final_message)
        except Exception as exc:
            self._run_on_main_thread(
                lambda: QtWidgets.QMessageBox.critical(self, "Error", f"Scan error: {exc}")
            )
            self._run_on_main_thread(self._set_status, "Scan failed")

    def _add_zip_file(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select ZIP File",
            filter="ZIP Files (*.zip);;All Files (*)",
        )
        if file_path:
            self._analyze_and_add(file_path)

    def _analyze_and_add(self, zip_path: str) -> None:
        is_valid, members, mod_time, file_size, image_count = self.zip_scanner.analyze_zip(zip_path)
        if is_valid and members:
            self._add_zip_entry(zip_path, members, mod_time, file_size, image_count)
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Not Valid",
                f"'{os.path.basename(zip_path)}' does not contain only images.",
            )

    def _add_zip_entry(
        self,
        zip_path: str,
        members: Optional[List[str]] = None,
        mod_time: Optional[float] = None,
        file_size: Optional[int] = None,
        image_count: Optional[int] = None,
    ) -> None:
        self._add_zip_entries_bulk([(zip_path, members, mod_time, file_size, image_count)])

    def _add_zip_entries_bulk(
        self,
        entries: List[Tuple[str, Optional[List[str]], Optional[float], Optional[int], Optional[int]]],
    ) -> None:
        if not entries:
            return
        for zip_path, members, mod_time, file_size, image_count in entries:
            if zip_path in self.zip_files:
                continue
            resolved_members = members
            resolved_mod_time = mod_time
            resolved_file_size = file_size
            resolved_image_count = image_count

            if resolved_members is None and resolved_image_count is None:
                is_valid, resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count = self.zip_scanner.analyze_zip(zip_path)
                if not is_valid or not resolved_members:
                    continue
            elif resolved_members is None and (resolved_mod_time is None or resolved_file_size is None):
                is_valid, resolved_members, resolved_mod_time, resolved_file_size, resolved_image_count = self.zip_scanner.analyze_zip(zip_path)
                if not is_valid:
                    continue

            if resolved_image_count is None:
                resolved_image_count = len(resolved_members) if resolved_members else 0
            entry_mod_time = resolved_mod_time or 0
            entry_file_size = resolved_file_size or 0
            self.zip_files[zip_path] = (resolved_members, entry_mod_time, entry_file_size, resolved_image_count)

            display_text = os.path.basename(zip_path)
            if entry_file_size:
                display_text += f" ({_format_size(entry_file_size)})"
            item = QtWidgets.QListWidgetItem(display_text)
            item.setData(QtCore.Qt.UserRole, zip_path)
            self.zip_list_widget.addItem(item)
        self._refresh_gallery()

    def _run_on_main_thread(self, func: Callable, *args, **kwargs) -> None:
        QtCore.QTimer.singleShot(0, lambda: func(*args, **kwargs))

    # ----------------------------------------------------------- Selection
    def _on_zip_selected(self) -> None:
        selected = self.zip_list_widget.selectedItems()
        if not selected:
            self._reset_preview()
            return
        zip_path = selected[0].data(QtCore.Qt.UserRole)
        if not zip_path:
            self._reset_preview()
            return
        self.current_selected_zip = zip_path
        entry = self.zip_files.get(zip_path)
        if not entry:
            self._reset_preview("Entry missing")
            return
        members, mod_time, file_size, image_count = entry
        if members is None:
            members = self._ensure_members_loaded(zip_path)
            if not members:
                self._reset_preview("No images found")
                return
            members, mod_time, file_size, image_count = self.zip_files[zip_path]
        if not members:
            self._reset_preview("No images found")
            return
        self._update_details(zip_path, mod_time, file_size, image_count)
        self._load_preview(zip_path, members, 0)

    def _ensure_members_loaded(self, zip_path: str) -> Optional[List[str]]:
        entry = self.zip_files.get(zip_path)
        if not entry:
            return None
        members, mod_time, file_size, image_count = entry
        if members is not None:
            return members
        is_valid, members, mod_time, file_size, image_count = self.zip_scanner.analyze_zip(zip_path)
        if is_valid and members:
            self.zip_files[zip_path] = (members, mod_time or 0, file_size or 0, len(members))
            return members
        return None

    def _update_details(self, zip_path: str, mod_time: float, file_size: int, image_count: int) -> None:
        details = [
            f"Archive: {os.path.basename(zip_path)}",
            f"Images: {image_count}",
            f"Size: {_format_size(file_size)}",
        ]
        if mod_time:
            details.append(f"Modified: {format_datetime(mod_time)}")
        self.details_text.setPlainText("\n".join(details))

    # ----------------------------------------------------------- Preview UI
    def _load_preview(self, zip_path: str, members: List[str], index: int) -> None:
        if not members or not (0 <= index < len(members)):
            return
        if self.current_preview_future and not self.current_preview_future.done():
            self.current_preview_future.cancel()
        self._drain_preview_queue()

        self.current_selected_zip = zip_path
        self.current_preview_members = members
        self.current_preview_index = index
        cache_key = (zip_path, members[index])
        self.current_preview_cache_key = cache_key

        self.preview_info_label.setText(f"Image {index + 1} / {len(members)}")
        self.preview_prev_button.setEnabled(index > 0)
        self.preview_next_button.setEnabled(index + 1 < len(members))

        target_size = (
            CONFIG["PERFORMANCE_THUMBNAIL_SIZE"] if self.app_settings.get("performance_mode")
            else CONFIG["THUMBNAIL_SIZE"]
        )
        self.preview_label.setPixmap(QtGui.QPixmap())
        self.preview_label.setText("Loading preview...")

        self.current_preview_future = self.thread_pool.submit(
            load_image_data_async,
            zip_path,
            members[index],
            self.app_settings["max_thumbnail_size"],
            target_size,
            self.preview_queue,
            self.cache,
            cache_key,
            self.zip_manager,
            self.app_settings.get("performance_mode", False),
        )
        self._schedule_preview_check()

    def _drain_preview_queue(self) -> None:
        while True:
            try:
                self.preview_queue.get_nowait()
            except queue.Empty:
                break

    def _schedule_preview_check(self) -> None:
        if self._preview_timer_active:
            return
        self._preview_timer_active = True
        QtCore.QTimer.singleShot(30, self._check_preview_result)

    def _check_preview_result(self) -> None:
        self._preview_timer_active = False
        expected_key = self.current_preview_cache_key
        if expected_key is None:
            return
        try:
            while True:
                result = self.preview_queue.get_nowait()
                if result.cache_key != expected_key:
                    continue
                if result.success and result.data:
                    pixmap = pil_image_to_qpixmap(result.data)
                    self.preview_pixmap = pixmap
                    self.preview_label.setPixmap(pixmap)
                    self.preview_label.setText("")
                else:
                    message = result.error_message or "Preview failed"
                    self.preview_label.setText(message)
                    self.preview_label.setPixmap(QtGui.QPixmap())
                return
        except queue.Empty:
            if self.current_preview_future and not self.current_preview_future.done():
                self._schedule_preview_check()

    def _reset_preview(self, message: str = "Select a ZIP file") -> None:
        if self.current_preview_future and not self.current_preview_future.done():
            self.current_preview_future.cancel()
        self.current_preview_future = None
        self.current_preview_members = None
        self.current_preview_index = None
        self.current_preview_cache_key = None
        self._drain_preview_queue()
        self.preview_label.setPixmap(QtGui.QPixmap())
        self.preview_label.setText(message)
        self.preview_info_label.setText("")
        self.preview_prev_button.setEnabled(False)
        self.preview_next_button.setEnabled(False)

    def _on_preview_scroll(self, direction: int) -> None:
        if direction > 0:
            self._preview_prev()
        else:
            self._preview_next()

    def _preview_prev(self) -> None:
        if not self.current_selected_zip or not self.current_preview_members:
            return
        index = (self.current_preview_index or 0) - 1
        if index >= 0:
            self._load_preview(self.current_selected_zip, self.current_preview_members, index)

    def _preview_next(self) -> None:
        if not self.current_selected_zip or not self.current_preview_members:
            return
        index = (self.current_preview_index or 0) + 1
        if index < len(self.current_preview_members):
            self._load_preview(self.current_selected_zip, self.current_preview_members, index)

    # -------------------------------------------------------- Viewer launch
    def _open_viewer(self) -> None:
        if not self.current_selected_zip:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select an archive first.")
            return
        if not self.app_settings.get("viewer_enabled", True):
            QtWidgets.QMessageBox.information(self, "Disabled", "Multi-image viewer is disabled in settings.")
            return
        entry = self.zip_files.get(self.current_selected_zip)
        if not entry:
            QtWidgets.QMessageBox.warning(self, "Missing Entry", "Selected archive is no longer available.")
            return
        members = entry[0]
        if members is None:
            members = self._ensure_members_loaded(self.current_selected_zip)
            if not members:
                QtWidgets.QMessageBox.critical(self, "Error", "Unable to load archive contents.")
                return
        index = self.current_preview_index or 0
        viewer_queue = queue.Queue()
        viewer = ImageViewerWindow(
            self,
            self.current_selected_zip,
            members,
            index,
            self.app_settings,
            self.cache,
            viewer_queue,
            self.thread_pool,
            self.zip_manager,
            self._viewer_max_load,
        )
        viewer.exec()

    def _open_viewer_from_gallery(self, zip_path: str, members: List[str], index: int) -> None:
        if not self.app_settings.get("viewer_enabled", True):
            QtWidgets.QMessageBox.information(self, "Disabled", "Multi-image viewer is disabled in settings.")
            return
        viewer_queue = queue.Queue()
        viewer = ImageViewerWindow(
            self,
            zip_path,
            members,
            index,
            self.app_settings,
            self.cache,
            viewer_queue,
            self.thread_pool,
            self.zip_manager,
            self._viewer_max_load,
        )
        viewer.exec()

    def _on_gallery_selection(self, zip_path: str, members: List[str], index: int) -> None:
        self.current_selected_zip = zip_path
        self.current_preview_members = members
        self.current_preview_index = index
        entry = self.zip_files.get(zip_path)
        if entry:
            _, mod_time, file_size, image_count = entry
            self._update_details(zip_path, mod_time, file_size, image_count)
        if self.current_view == "explorer":
            self._load_preview(zip_path, members, index)

    # --------------------------------------------------------- Settings/etc
    def _show_settings(self) -> None:
        dialog = SettingsDialog(self, self.app_settings)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.app_settings.update(dialog.result_settings)
            self._apply_settings()
            self._refresh_gallery()

    def _apply_settings(self) -> None:
        if self.app_settings.get("performance_mode"):
            self.app_settings["max_thumbnail_size"] = CONFIG["PERFORMANCE_MAX_THUMBNAIL_LOAD_SIZE"]
            self._viewer_max_load = CONFIG["PERFORMANCE_MAX_VIEWER_LOAD_SIZE"]
            self.cache.resize(CONFIG["CACHE_MAX_ITEMS_PERFORMANCE"])
        else:
            self.app_settings["max_thumbnail_size"] = CONFIG["MAX_THUMBNAIL_LOAD_SIZE"]
            self._viewer_max_load = CONFIG["MAX_VIEWER_LOAD_SIZE"]
            self.cache.resize(CONFIG["CACHE_MAX_ITEMS_NORMAL"])

    def _clear_list(self) -> None:
        self.zip_list_widget.clear()
        self.zip_files.clear()
        self.current_selected_zip = None
        self._reset_preview()
        self.details_text.clear()
        self._refresh_gallery()

    def _show_about(self) -> None:
        about_text = f"""Arkview {CONFIG['APP_VERSION']}
High-Performance Archived Image Viewer

Hybrid Rust-Python Architecture
{ 'Rust Acceleration: Enabled' if RUST_AVAILABLE else 'Rust Acceleration: Not Available' }

Archive browsing and image preview utility.
BSD-2-Clause License"""
        QtWidgets.QMessageBox.about(self, "About Arkview", about_text)

    # -------------------------------------------------------------- Closing
    def _on_closing(self) -> None:
        self.scan_stop_event.set()
        if self.scan_thread and self.scan_thread.is_alive():
            self.scan_thread.join(timeout=1)
        self.zip_manager.close_all()
        self.thread_pool.shutdown(wait=False)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._on_closing()
        super().closeEvent(event)


def main() -> int:
    """Application entry point."""
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Arkview")
    window = MainApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
