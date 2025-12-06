#!/usr/bin/env python3
"""
Arkview 构建和打包脚本
支持多种打包方式，包括PyInstaller和cx_Freeze
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path

def run_command(cmd, cwd=None, check=True):
    """运行命令并检查返回码"""
    print(f"运行命令: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=cwd, check=check)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {' '.join(cmd)}")
        if check:
            sys.exit(1)
        return False

def clean_build_artifacts():
    """清理之前的构建产物"""
    print("清理构建产物...")
    dirs_to_clean = ["build", "dist"]
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"已删除 {dir_name} 目录")

def build_rust_extension():
    """构建Rust扩展"""
    print("构建Rust扩展...")
    return run_command(["maturin", "develop", "--release"])

def build_with_pyinstaller():
    """使用PyInstaller构建独立可执行文件"""
    print("使用PyInstaller构建独立可执行文件...")
    
    # 首先确保Rust扩展已构建
    if not build_rust_extension():
        print("Rust扩展构建失败!")
        return False
    
    # 获取项目根目录
    project_root = Path(__file__).parent.absolute()
    
    # 创建临时入口脚本
    entry_script = project_root / "entry_for_packaging.py"
    with open(entry_script, "w", encoding="utf-8") as f:
        f.write('''#!/usr/bin/env python3
"""
Arkview入口脚本，用于PyInstaller打包
"""

import sys
import os

def main():
    try:
        # 尝试相对导入（开发环境）
        from arkview.pyside_main import main as arkview_main
    except ImportError:
        # 如果失败，尝试绝对导入（打包环境）
        try:
            import arkview.pyside_main
            arkview_main = arkview.pyside_main.main
        except ImportError as e:
            print(f"无法导入Arkview主模块: {e}")
            sys.exit(1)
    
    # 运行主程序
    arkview_main()

if __name__ == "__main__":
    main()
''')
    
    # 使用PyInstaller打包
    try:
        pyinstaller_cmd = [
            sys.executable, "-m", "PyInstaller",
            "--name", "arkview",
            "--windowed",  # GUI应用不需要控制台窗口
            "--onefile",   # 打包成单个文件
            "--add-data", f"{project_root / 'README.md'}{os.pathsep}.",  # 添加README文件
            "--hidden-import", "PySide6.QtXml",  # 确保包含必要的Qt模块
            "--hidden-import", "PIL._tkinter_finder",
            str(entry_script)
        ]
        
        print("正在使用PyInstaller打包...")
        if not run_command(pyinstaller_cmd):
            return False
            
        print("PyInstaller打包完成!")
        print("可执行文件位于 dist/arkview.exe (Windows) 或 dist/arkview (Linux/macOS)")
        
        # 复制README到dist目录
        dist_readme = Path("dist") / "README.md"
        if not dist_readme.exists():
            shutil.copy(project_root / "README.md", dist_readme)
            
        return True
    finally:
        # 清理临时文件
        if entry_script.exists():
            entry_script.unlink()

def build_with_pyinstaller_dir():
    """使用PyInstaller构建独立可执行文件(目录模式)"""
    print("使用PyInstaller构建独立可执行文件(目录模式)...")
    
    # 首先确保Rust扩展已构建
    if not build_rust_extension():
        print("Rust扩展构建失败!")
        return False
    
    # 获取项目根目录
    project_root = Path(__file__).parent.absolute()
    
    # 创建临时入口脚本
    entry_script = project_root / "entry_for_packaging.py"
    with open(entry_script, "w", encoding="utf-8") as f:
        f.write('''#!/usr/bin/env python3
"""
Arkview入口脚本，用于PyInstaller打包
"""

import sys
import os

def main():
    try:
        # 尝试相对导入（开发环境）
        from arkview.pyside_main import main as arkview_main
    except ImportError:
        # 如果失败，尝试绝对导入（打包环境）
        try:
            import arkview.pyside_main
            arkview_main = arkview.pyside_main.main
        except ImportError as e:
            print(f"无法导入Arkview主模块: {e}")
            sys.exit(1)
    
    # 运行主程序
    arkview_main()

if __name__ == "__main__":
    main()
''')
    
    # 使用PyInstaller打包为目录
    try:
        pyinstaller_cmd = [
            sys.executable, "-m", "PyInstaller",
            "--name", "arkview",
            "--windowed",  # GUI应用不需要控制台窗口
            "--onedir",    # 打包成目录
            "--add-data", f"{project_root / 'README.md'}{os.pathsep}.",  # 添加README文件
            "--hidden-import", "PySide6.QtXml",  # 确保包含必要的Qt模块
            "--hidden-import", "PIL._tkinter_finder",
            str(entry_script)
        ]
        
        print("正在使用PyInstaller打包...")
        if not run_command(pyinstaller_cmd):
            return False
            
        print("PyInstaller打包完成!")
        print("可执行文件位于 dist/arkview/")
        
        # 复制README到dist目录
        dist_dir = Path("dist") / "arkview"
        dist_readme = dist_dir / "README.md"
        if not dist_readme.exists():
            shutil.copy(project_root / "README.md", dist_readme)
            
        return True
    finally:
        # 清理临时文件
        if entry_script.exists():
            entry_script.unlink()

def build_wheel():
    """使用maturin构建wheel包"""
    print("使用maturin构建wheel包...")
    clean_build_artifacts()
    return run_command(["maturin", "build", "--release"])

def main():
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python build.py clean         - 清理构建产物")
        print("  python build.py exe           - 构建独立可执行文件(单文件)")
        print("  python build.py dir           - 构建独立可执行文件(目录模式)")
        print("  python build.py wheel         - 构建wheel包")
        print("  python build.py all           - 构建所有包")
        sys.exit(1)
    
    if sys.argv[1] == "clean":
        clean_build_artifacts()
    elif sys.argv[1] == "exe":
        if not build_with_pyinstaller():
            sys.exit(1)
    elif sys.argv[1] == "dir":
        if not build_with_pyinstaller_dir():
            sys.exit(1)
    elif sys.argv[1] == "wheel":
        if not build_wheel():
            sys.exit(1)
    elif sys.argv[1] == "all":
        success = build_wheel() and build_with_pyinstaller() and build_with_pyinstaller_dir()
        if not success:
            sys.exit(1)
    else:
        print("未知参数，请使用 'clean'、'exe'、'dir'、'wheel' 或 'all'")
        sys.exit(1)

if __name__ == "__main__":
    main()