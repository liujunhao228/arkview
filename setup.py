#!/usr/bin/env python
"""
Setup script for Arkview
"""

from setuptools import setup, find_packages

setup(
    name="arkview",
    version="4.0.0",
    description="High-Performance Archived Image Viewer",
    author="Arkview Contributors",
    license="BSD-2-Clause",
    package_dir={"": "src/python"},
    packages=find_packages("src/python"),
    python_requires=">=3.8",
    install_requires=[
        "Pillow>=9.0.0",
        "PySide6>=6.5.0",
    ],
    extras_require={
        "dev": ["pytest>=7.0"],
    },
    entry_points={
        "console_scripts": [
            "arkview=arkview.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
)
