"""Common Qt helpers for Arkview."""

from __future__ import annotations

from PIL import Image, ImageQt
from PySide6 import QtCore, QtGui, QtWidgets


def pil_image_to_qpixmap(image: Image.Image) -> QtGui.QPixmap:
    """Convert a PIL Image into a QPixmap suitable for display."""
    if image.mode not in ("RGB", "RGBA", "L", "LA"):
        image = image.convert("RGBA")
    elif image.mode in ("L", "LA"):
        image = image.convert("RGBA")
    qt_image = ImageQt.ImageQt(image)
    return QtGui.QPixmap.fromImage(qt_image)


class PreviewLabel(QtWidgets.QLabel):
    """Clickable label that also emits scroll events for preview navigation."""

    clicked = QtCore.Signal()
    scrolled = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        self.setMinimumHeight(220)
        self.setStyleSheet(
            "background-color: #2a2d2e; color: #f8f9fa; border: 1px solid #3c3f41;"
        )

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta:
            self.scrolled.emit(1 if delta > 0 else -1)
        super().wheelEvent(event)
