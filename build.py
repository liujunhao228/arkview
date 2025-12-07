#!/usr/bin/env python3
"""
Build script for Arkview
Supports building wheel packages and standalone executables
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


def build_rust_extension():
    """Build the Rust extension using maturin"""
    print("Building Rust extension with maturin...")
    
    # Ensure we're in the project root
    project_root = Path(__file__).parent.absolute()
    os.chdir(project_root)
    
    # Run maturin develop to build the extension
    try:
        result = subprocess.run([
            sys.executable, "-m", "maturin", "develop"
        ], check=True, capture_output=True, text=True)
        print("Rust extension built successfully!")
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error building Rust extension: {e}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False


def build_wheel():
    """Build wheel package using maturin"""
    print("Building wheel package with maturin...")
    
    # First ensure Rust extension is built
    if not build_rust_extension():
        print("Rust extension build failed!")
        return False
    
    # Run maturin build
    try:
        subprocess.run([
            sys.executable, "-m", "maturin", "build", "--release"
        ], check=True)
        print("Wheel package built successfully!")
        print("Output files are in the 'target/wheels' directory")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error building wheel package: {e}")
        return False


def build_with_pyinstaller_exe():
    """Use PyInstaller to build standalone executable (single file)"""
    print("Building standalone executable with PyInstaller (single file)...")
    
    # First ensure Rust extension is built
    if not build_rust_extension():
        print("Rust extension build failed!")
        return False
    
    # Get project root directory
    project_root = Path(__file__).parent.absolute()
    
    # Create temporary entry script
    entry_script = project_root / "entry_for_packaging.py"
    with open(entry_script, "w", encoding="utf-8") as f:
        f.write('''#!/usr/bin/env python3
"""
Arkview entry script for PyInstaller packaging
"""

import sys
import os

def main():
    try:
        # Try relative import (development environment)
        from arkview.ui.main_window import MainWindow
    except ImportError:
        # If that fails, try absolute import (packaged environment)
        try:
            from ui.main_window import MainWindow
        except ImportError as e:
            print(f"Cannot import Arkview main window: {e}")
            sys.exit(1)
    
    # Import required modules
    from PySide6.QtWidgets import QApplication
    import sys
    
    # Create and run the application
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    main_window = MainWindow()
    main_window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
''')

    # Use PyInstaller to package
    try:
        pyinstaller_cmd = [
            sys.executable, "-m", "PyInstaller",
            "--name", "arkview",
            "--windowed",  # GUI app doesn't need console window
            "--onefile",   # Package as single file
            "--add-data", f"{project_root / 'README.md'}{os.pathsep}.",  # Add README file
            "--hidden-import", "PySide6.QtXml",  # Ensure necessary Qt modules are included
            "--hidden-import", "PIL._tkinter_finder",
            str(entry_script)
        ]

        print("Packaging with PyInstaller...")
        if not run_command(pyinstaller_cmd):
            return False

        print("PyInstaller packaging completed!")
        print("Executable file is located at dist/arkview.exe (Windows) or dist/arkview (Linux/macOS)")

        # Copy README to dist directory
        dist_readme = Path("dist") / "README.md"
        if not dist_readme.exists():
            shutil.copy(project_root / "README.md", dist_readme)

        return True
    finally:
        # Clean up temporary file
        if entry_script.exists():
            entry_script.unlink()


def build_with_pyinstaller_dir():
    """Use PyInstaller to build standalone executable (directory mode)"""
    print("Building standalone executable with PyInstaller (directory mode)...")

    # First ensure Rust extension is built
    if not build_rust_extension():
        print("Rust extension build failed!")
        return False

    # Get project root directory
    project_root = Path(__file__).parent.absolute()

    # Create temporary entry script
    entry_script = project_root / "entry_for_packaging.py"
    with open(entry_script, "w", encoding="utf-8") as f:
        f.write('''#!/usr/bin/env python3
"""
Arkview entry script for PyInstaller packaging
"""

import sys
import os

def main():
    try:
        # Try relative import (development environment)
        from arkview.ui.main_window import MainWindow
    except ImportError:
        # If that fails, try absolute import (packaged environment)
        try:
            from ui.main_window import MainWindow
        except ImportError as e:
            print(f"Cannot import Arkview main window: {e}")
            sys.exit(1)
    
    # Import required modules
    from PySide6.QtWidgets import QApplication
    import sys
    
    # Create and run the application
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    main_window = MainWindow()
    main_window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
''')

    # Use PyInstaller to package
    try:
        pyinstaller_cmd = [
            sys.executable, "-m", "PyInstaller",
            "--name", "arkview",
            "--windowed",  # GUI app doesn't need console window
            "--onedir",    # Package as directory
            "--add-data", f"{project_root / 'README.md'}{os.pathsep}.",  # Add README file
            "--hidden-import", "PySide6.QtXml",  # Ensure necessary Qt modules are included
            "--hidden-import", "PIL._tkinter_finder",
            str(entry_script)
        ]

        print("Packaging with PyInstaller...")
        if not run_command(pyinstaller_cmd):
            return False

        print("PyInstaller packaging completed!")
        print("Executable directory is located at dist/arkview/")

        # Copy README to dist directory
        dist_dir = Path("dist") / "arkview"
        dist_readme = dist_dir / "README.md"
        if not dist_readme.exists():
            dist_dir.mkdir(exist_ok=True)
            shutil.copy(project_root / "README.md", dist_readme)

        return True
    finally:
        # Clean up temporary file
        if entry_script.exists():
            entry_script.unlink()


def run_command(cmd):
    """Run command and handle errors"""
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python build.py wheel    # Build wheel package")
        print("  python build.py exe      # Build standalone executable (single file)")
        print("  python build.py dir      # Build standalone executable (directory)")
        return

    command = sys.argv[1].lower()

    if command == "wheel":
        build_wheel()
    elif command == "exe":
        build_with_pyinstaller_exe()
    elif command == "dir":
        build_with_pyinstaller_dir()
    else:
        print(f"Unknown command: {command}")
        print("Supported commands: wheel, exe, dir")


if __name__ == "__main__":
    main()