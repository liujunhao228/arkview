#!/usr/bin/env python3
"""
Test script to verify PySide implementation of Arkview.
"""

import sys
import os

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'python'))

try:
    from arkview import pyside_main
    print("Successfully imported PySide main module")
    
    # Attempt to run the application
    print("Attempting to start PySide application...")
    pyside_main.main()
    
except ImportError as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"Error running PySide application: {e}")
    import traceback
    traceback.print_exc()