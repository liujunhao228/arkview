"""
UI package - user interface components.
"""

# Import UI components from their respective modules
from .main_window import MainWindow
from .gallery_view import GalleryViewWidget
from .slide_view import SlideViewWidget
from .settings_dialog import SettingsDialogWidget

__all__ = [
    'MainWindow',
    'GalleryViewWidget', 
    'SlideViewWidget',
    'SettingsDialogWidget'
]