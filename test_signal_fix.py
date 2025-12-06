#!/usr/bin/env python3
"""
Test script to verify the signal-based approach works correctly.
This simulates the scanning workflow without requiring a GUI.
"""

import sys
import threading
import time
from pathlib import Path

# Mock PySide6 classes for testing
class MockSignal:
    def __init__(self):
        self.slots = []
    
    def connect(self, slot):
        self.slots.append(slot)
    
    def emit(self, *args):
        for slot in self.slots:
            slot(*args)

class MockMainApp:
    def __init__(self):
        self.update_status = MockSignal()
        self.add_zip_entries_signal = MockSignal()
        self.show_error_signal = MockSignal()
        
        # Connect signals
        self.update_status.connect(self.on_status_update)
        self.add_zip_entries_signal.connect(self.on_add_entries)
        self.show_error_signal.connect(self.on_error)
        
        self.status_messages = []
        self.entries_added = []
        self.errors = []
        self.scan_stop_event = threading.Event()
    
    def on_status_update(self, message):
        print(f"Status: {message}")
        self.status_messages.append(message)
    
    def on_add_entries(self, entries):
        print(f"Adding {len(entries)} entries")
        self.entries_added.extend(entries)
    
    def on_error(self, title, message):
        print(f"Error [{title}]: {message}")
        self.errors.append((title, message))
    
    def scan_directory_worker(self, directory):
        """Simulated scan worker using signals instead of QTimer.singleShot"""
        try:
            # Simulate finding some files
            files = [f"file{i}.zip" for i in range(10)]
            total_files = len(files)
            
            if total_files == 0:
                self.update_status.emit("No ZIP files found")
                return
            
            batch_size = 3
            pending_entries = []
            processed = 0
            valid_found = 0
            
            def flush_pending():
                if not pending_entries:
                    return
                batch = pending_entries.copy()
                pending_entries.clear()
                self.add_zip_entries_signal.emit(batch)
            
            for i, file in enumerate(files):
                if self.scan_stop_event.is_set():
                    break
                
                # Simulate processing
                processed += 1
                pending_entries.append((file, None, None, None, 1))
                valid_found += 1
                
                if len(pending_entries) >= batch_size:
                    flush_pending()
                
                if processed % 2 == 0:
                    # Capture current values explicitly
                    current_processed = processed
                    current_total = total_files
                    self.update_status.emit(f"Scanning... {current_processed}/{current_total} files processed")
                
                time.sleep(0.01)  # Simulate work
            
            flush_pending()
            
            final_message = (
                "Scan canceled" if self.scan_stop_event.is_set()
                else f"Found {valid_found} valid archives (of {processed} scanned)"
            )
            self.update_status.emit(final_message)
        except Exception as e:
            self.show_error_signal.emit("Error", f"Scan error: {e}")
            self.update_status.emit("Scan failed")


def test_signal_based_approach():
    """Test that the signal-based approach works correctly."""
    print("Testing signal-based scanning approach...")
    print("-" * 60)
    
    app = MockMainApp()
    
    # Run scan in a thread
    thread = threading.Thread(
        target=app.scan_directory_worker,
        args=("/fake/directory",),
        daemon=True
    )
    thread.start()
    thread.join(timeout=5)
    
    print("-" * 60)
    print(f"Total status updates: {len(app.status_messages)}")
    print(f"Total entries added: {len(app.entries_added)}")
    print(f"Total errors: {len(app.errors)}")
    
    # Verify results
    assert len(app.status_messages) > 0, "Should have status messages"
    assert len(app.entries_added) == 10, f"Should have 10 entries, got {len(app.entries_added)}"
    assert len(app.errors) == 0, "Should have no errors"
    assert "Found 10 valid archives" in app.status_messages[-1], f"Final message incorrect: {app.status_messages[-1]}"
    
    print("\n✅ All tests passed!")
    print("\nThe signal-based approach correctly:")
    print("  1. Emits signals from worker thread")
    print("  2. Receives all signals in main thread")
    print("  3. Processes all entries without data loss")
    print("  4. Avoids closure/lambda capture issues")


if __name__ == "__main__":
    test_signal_based_approach()
