"""
File management service - handles ZIP file operations and member loading.
"""

from typing import List, Optional, Dict, Any, Set
from PySide6.QtCore import QObject, Signal, Slot

from ..models import ZipFileInfo
from ..infrastructure import ZipScanner, ZipFileManager


class FileManagementService(QObject):
    """Service for managing ZIP files and their members."""
    
    # Signals
    members_loaded = Signal(str, object)  # zip_path, members list
    error_occurred = Signal(str)           # error message
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.config = config
        self.zip_scanner = ZipScanner()
        self.zip_manager = ZipFileManager()
        self._loading_members: Set[str] = set()
        
    def get_zip_file_manager(self) -> ZipFileManager:
        """Get the ZIP file manager instance."""
        return self.zip_manager
        
    def load_zip_members(self, zip_path: str) -> None:
        """Load members of a ZIP file asynchronously."""
        if zip_path in self._loading_members:
            return
            
        self._loading_members.add(zip_path)
        
        try:
            is_valid, members, mod_time, file_size, image_count = self.zip_scanner.analyze_zip(
                zip_path, collect_members=True
            )
            
            if is_valid and members:
                self.members_loaded.emit(zip_path, members)
            else:
                self.error_occurred.emit(f"No valid images found in {zip_path}")
                
        except Exception as e:
            self.error_occurred.emit(f"Error loading members for {zip_path}: {str(e)}")
        finally:
            self._loading_members.discard(zip_path)
            
    def is_loading_members(self, zip_path: str) -> bool:
        """Check if members are currently being loaded for a ZIP file."""
        return zip_path in self._loading_members
        
    def close_zip_file(self, zip_path: str) -> None:
        """Close a ZIP file."""
        self.zip_manager.close_zipfile(zip_path)
        
    def close_all_zip_files(self) -> None:
        """Close all open ZIP files."""
        self.zip_manager.close_all()
        
    def analyze_zip_file(self, zip_path: str, collect_members: bool = True) -> Optional[ZipFileInfo]:
        """Analyze a single ZIP file."""
        try:
            is_valid, members, mod_time, file_size, image_count = self.zip_scanner.analyze_zip(
                zip_path, collect_members
            )
            
            return ZipFileInfo(
                path=zip_path,
                members=members if is_valid else None,
                modification_time=mod_time or 0.0,
                file_size=file_size or 0,
                image_count=image_count,
                is_valid=is_valid
            )
        except Exception as e:
            self.error_occurred.emit(f"Error analyzing {zip_path}: {str(e)}")
            return None