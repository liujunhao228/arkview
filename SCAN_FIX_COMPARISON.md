# PySide Scanning Fix - Before and After Comparison

## Problem Summary
The PySide version of Arkview experienced hanging or non-responsive UI during directory scanning because worker threads were using `QTimer.singleShot(0, lambda: ...)` to communicate with the main thread, causing closure/lambda capture issues and race conditions.

## Code Changes

### 1. Signal Definitions

#### BEFORE:
```python
class MainApp(QMainWindow):
    """Main Arkview Application with PySide UI."""
    
    # Custom signals
    update_status = Signal(str)
    update_preview = Signal(object)  # (pil_image, str_error)
```

#### AFTER:
```python
class MainApp(QMainWindow):
    """Main Arkview Application with PySide UI."""
    
    # Custom signals
    update_status = Signal(str)
    update_preview = Signal(object)  # (pil_image, str_error)
    add_zip_entries_signal = Signal(list)  # ✅ List of tuples for bulk adding
    show_error_signal = Signal(str, str)   # ✅ (title, message)
```

### 2. Signal Connections

#### BEFORE:
```python
# Connect signals
self.update_status.connect(self._on_update_status)
self.update_preview.connect(self._on_update_preview)
```

#### AFTER:
```python
# Connect signals
self.update_status.connect(self._on_update_status)
self.update_preview.connect(self._on_update_preview)
self.add_zip_entries_signal.connect(self._add_zip_entries_bulk)  # ✅ NEW
self.show_error_signal.connect(self._show_error)                # ✅ NEW
```

### 3. Worker Thread - No Files Found

#### BEFORE:
```python
if total_files == 0:
    # ❌ Wrapping signal in QTimer - unnecessary and problematic
    QTimer.singleShot(0, lambda: self.update_status.emit("No ZIP files found"))
    return
```

#### AFTER:
```python
if total_files == 0:
    # ✅ Direct signal emission - thread-safe
    self.update_status.emit("No ZIP files found")
    return
```

### 4. Worker Thread - Batch Flushing

#### BEFORE:
```python
def flush_pending():
    if not pending_entries:
        return
    batch = pending_entries.copy()
    pending_entries.clear()
    # ❌ Lambda captures 'batch' by reference - may cause issues
    QTimer.singleShot(0, lambda: self._add_zip_entries_bulk(batch))
```

#### AFTER:
```python
def flush_pending():
    if not pending_entries:
        return
    batch = pending_entries.copy()
    pending_entries.clear()
    # ✅ Signal captures batch immediately by value
    self.add_zip_entries_signal.emit(batch)
```

### 5. Worker Thread - Error Handling

#### BEFORE:
```python
except Exception as e:
    # ❌ Wrapping signals in QTimer with lambdas
    QTimer.singleShot(0, lambda: self._show_error("Error", f"Scan error: {e}"))
    QTimer.singleShot(0, lambda: self.update_status.emit("Scan failed"))
    return
```

#### AFTER:
```python
except Exception as e:
    # ✅ Direct signal emissions
    self.show_error_signal.emit("Error", f"Scan error: {e}")
    self.update_status.emit("Scan failed")
    return
```

### 6. Worker Thread - Progress Updates

#### BEFORE:
```python
if processed % ui_update_interval == 0 or processed >= total_files:
    # ❌ Lambda captures variables by reference - values may change!
    QTimer.singleShot(0, lambda: self.update_status.emit(
        f"Scanning... {processed}/{total_files} files processed"
    ))
```

#### AFTER:
```python
if processed % ui_update_interval == 0 or processed >= total_files:
    # ✅ Explicitly capture current values to avoid closure issues
    current_processed = processed
    current_total = total_files
    self.update_status.emit(f"Scanning... {current_processed}/{current_total} files processed")
```

### 7. Worker Thread - Final Message

#### BEFORE:
```python
final_message = (
    "Scan canceled" if self.scan_stop_event.is_set()
    else f"Found {valid_found} valid archives (of {processed} scanned)"
)
# ❌ Wrapping signal in QTimer
QTimer.singleShot(0, lambda: self.update_status.emit(final_message))
```

#### AFTER:
```python
final_message = (
    "Scan canceled" if self.scan_stop_event.is_set()
    else f"Found {valid_found} valid archives (of {processed} scanned)"
)
# ✅ Direct signal emission
self.update_status.emit(final_message)
```

## Why This Fix Works

### Qt Signal Mechanism
1. **Thread-Safe by Design**: Qt automatically detects cross-thread signal emissions
2. **Queued Connections**: Signals from worker threads are automatically queued
3. **Value Capture**: Signal parameters are captured by value at emission time
4. **Event Loop Integration**: Signals are delivered through Qt's event loop

### Lambda Closure Problem (OLD CODE)
```python
for i in range(5):
    QTimer.singleShot(0, lambda: print(i))  # Will print "4" five times!
```

By the time the lambdas execute, `i` is 4 (the final value from the loop).

### Signal Value Capture (NEW CODE)
```python
for i in range(5):
    self.signal.emit(i)  # Will print 0, 1, 2, 3, 4 correctly
```

Signals capture parameters immediately when `emit()` is called.

## Testing

Run the test script to verify the fix:
```bash
python test_signal_fix.py
```

Expected output:
```
✅ All tests passed!

The signal-based approach correctly:
  1. Emits signals from worker thread
  2. Receives all signals in main thread
  3. Processes all entries without data loss
  4. Avoids closure/lambda capture issues
```

## Performance Impact
- **Before**: Potential hanging, data loss, race conditions
- **After**: Reliable, fast, no hanging, all data received correctly

## Compatibility
This fix maintains full backward compatibility - no API changes, only internal implementation improvements.
