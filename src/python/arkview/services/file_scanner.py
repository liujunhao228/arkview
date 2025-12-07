"""
File scanning service - handles ZIP file discovery and analysis.
"""

import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from PySide6.QtCore import QObject, Signal, Slot

from ..models import ZipFileInfo, ScanProgress, ScanResult
from ..infrastructure import ZipScanner


class FileScannerService(QObject):
    """Service for scanning and analyzing ZIP files."""
    
    # Signals
    scan_completed = Signal(object)  # ScanResult
    scan_progress = Signal(object)   # ScanProgress
    scan_error = Signal(str)          # error message
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.config = config
        self.zip_scanner = ZipScanner()
        self._stop_requested = False
        
    def scan_directory(self, directory: str) -> None:
        """Scan directory for ZIP files."""
        try:
            # Get all ZIP files
            zip_files = [str(p) for p in Path(directory).glob("**/*.zip")]
            total_files = len(zip_files)

            if total_files == 0:
                self.scan_completed.emit(ScanResult(0, 0, []))
                return

            # Batch processing parameters
            batch_size = max(1, self.config["BATCH_SCAN_SIZE"])
            ui_update_interval = max(1, self.config["BATCH_UPDATE_INTERVAL"])
            
            # Processing state
            processed = 0
            valid_found = 0
            zip_file_infos: List[ZipFileInfo] = []

            # Process ZIP files in batches
            for start in range(0, total_files, batch_size):
                if self._stop_requested:
                    break

                batch_paths = zip_files[start:start + batch_size]
                try:
                    batch_results = self.zip_scanner.batch_analyze_zips(
                        batch_paths, collect_members=False
                    )
                except Exception as e:
                    self.scan_error.emit(str(e))
                    return

                # Process analysis results
                for zip_path, is_valid, members, mod_time, file_size, image_count in batch_results:
                    processed += 1
                    
                    zip_info = ZipFileInfo(
                        path=zip_path,
                        members=members if is_valid else None,
                        modification_time=mod_time or 0.0,
                        file_size=file_size or 0,
                        image_count=image_count,
                        is_valid=is_valid
                    )
                    
                    zip_file_infos.append(zip_info)
                    
                    if is_valid:
                        valid_found += 1

                    # Update progress
                    if processed % ui_update_interval == 0 or processed >= total_files:
                        progress = ScanProgress(processed, total_files, valid_found)
                        self.scan_progress.emit(progress)

            # Send final result
            result = ScanResult(valid_found, processed, zip_file_infos)
            self.scan_completed.emit(result)
            
        except Exception as e:
            self.scan_error.emit(str(e))
            
    def stop_scan(self) -> None:
        """Request to stop the current scan."""
        self._stop_requested = True
        
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
            print(f"Error analyzing ZIP file {zip_path}: {e}")
            return None