# PySide Scanning Hang Fix

## Issue Description
The PySide version of Arkview had a critical bug where the scanning process would hang or the UI would not receive backend results during directory scanning.

## Root Cause
The problem was in `pyside_main.py` in the `_scan_directory_worker` method. The code was using `QTimer.singleShot(0, lambda: ...)` to communicate from the worker thread to the main thread. This approach had several issues:

### Problems with the Old Approach:

```python
# PROBLEMATIC CODE (OLD):
def flush_pending():
    if not pending_entries:
        return
    batch = pending_entries.copy()
    pending_entries.clear()
    # ❌ Lambda captures variables by reference, causing closure issues
    QTimer.singleShot(0, lambda: self._add_zip_entries_bulk(batch))

# Later in the loop:
# ❌ Variables can change before lambda executes
QTimer.singleShot(0, lambda: self.update_status.emit(f"Scanning... {processed}/{total_files} files processed"))
```

**Issues:**
1. **Closure Problem**: Lambda functions capture variables by reference, not by value. By the time the lambda executes on the main thread, the variables (`processed`, `total_files`, `batch`) may have changed.
2. **Race Conditions**: Multiple `QTimer.singleShot` calls from a worker thread can cause race conditions.
3. **Redundancy**: Wrapping signal emissions in `QTimer.singleShot` is redundant - Qt signals are already thread-safe.

## Solution
The fix uses Qt's native signal/slot mechanism, which is thread-safe by design:

### Changes Made:

1. **Added New Signals** (lines 99-100):
```python
class MainApp(QMainWindow):
    # Custom signals
    update_status = Signal(str)
    update_preview = Signal(object)
    add_zip_entries_signal = Signal(list)  # ✅ NEW
    show_error_signal = Signal(str, str)   # ✅ NEW
```

2. **Connected Signals to Slots** (lines 143-144):
```python
self.add_zip_entries_signal.connect(self._add_zip_entries_bulk)
self.show_error_signal.connect(self._show_error)
```

3. **Updated Worker Thread to Use Signals** (pyside_main.py lines 650-713):
```python
# CORRECT CODE (NEW):
def flush_pending():
    if not pending_entries:
        return
    batch = pending_entries.copy()
    pending_entries.clear()
    # ✅ Direct signal emission - thread-safe and captures data properly
    self.add_zip_entries_signal.emit(batch)

# In the loop:
# ✅ Capture current values explicitly to avoid closure issues
current_processed = processed
current_total = total_files
self.update_status.emit(f"Scanning... {current_processed}/{current_total} files processed")

# Error handling:
# ✅ Use signals instead of QTimer.singleShot
self.show_error_signal.emit("Error", f"Scan error: {e}")
self.update_status.emit("Scan failed")
```

## Benefits of the Fix:

1. **Thread-Safe**: Qt signals automatically handle cross-thread communication safely.
2. **No Closure Issues**: Signal emission captures data immediately, not by reference.
3. **Cleaner Code**: Direct signal usage is more idiomatic in Qt/PySide.
4. **Better Performance**: Eliminates unnecessary QTimer overhead.
5. **Reliable**: Data is guaranteed to be received in the main thread.

## Technical Details

### How Qt Signals Work Across Threads:
- Qt automatically detects when a signal is emitted from a different thread
- Signal emissions are queued and delivered to the main thread's event loop
- The receiving slot executes in the receiver's thread (main thread)
- Data passed via signals is properly copied/captured at emission time

### Comparison with Tkinter:
The original Tkinter version used:
```python
def _run_on_main_thread(self, func: Callable, *args, **kwargs):
    self.root.after(0, partial(func, *args, **kwargs))
```

The `partial` function properly captures arguments by value. The PySide version was missing this critical aspect, which is now handled by Qt's signal mechanism.

## Testing
A test script (`test_signal_fix.py`) was created to verify the fix works correctly. The test demonstrates:
- Signals emit correctly from worker threads
- All data is received without loss
- No closure/lambda capture issues
- Proper batch processing and status updates

## Files Modified
- `src/python/arkview/pyside_main.py` - Fixed scanning worker thread communication

## Migration Notes
If you're updating code:
- Replace `QTimer.singleShot(0, lambda: func(args))` with signal emissions when crossing thread boundaries
- Use `partial()` from `functools` if you must use QTimer.singleShot with arguments
- Prefer Qt signals for all cross-thread communication
