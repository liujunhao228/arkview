#!/usr/bin/env python3
"""
Test script to verify the scanning hang fix.
"""

import os
import tempfile
import zipfile
from src.python.arkview.core import ZipScanner

def test_scanning_fix():
    """Test that the scanning fixes work properly."""
    print("Testing scanning hang fixes...")
    
    # Initialize the scanner
    scanner = ZipScanner()
    
    # Test 1: Large file size check
    print("\n1. Testing large file size check...")
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
        # Create a large fake file (though it won't be a real zip)
        temp_file.write(b'A' * (600 * 1024 * 1024))  # 600MB file
        large_file_path = temp_file.name
    
    try:
        result = scanner.analyze_zip(large_file_path, collect_members=False)
        print(f"   Large file result: {result}")
        assert result[0] == False, "Large file should be rejected"
        print("   ✓ Large file correctly rejected")
    finally:
        os.unlink(large_file_path)
    
    # Test 2: Valid ZIP with images
    print("\n2. Testing valid ZIP with images...")
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
        # Create a valid ZIP with some fake image data
        with zipfile.ZipFile(temp_zip.name, 'w') as zipf:
            # Add a fake PNG file
            fake_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\x00\x00\x00\x00IEND\xaeB`\x82'
            zipf.writestr('image1.png', fake_png)
            zipf.writestr('image2.jpg', fake_png)
        valid_zip_path = temp_zip.name
    
    try:
        result = scanner.analyze_zip(valid_zip_path, collect_members=True)
        print(f"   Valid ZIP result: Valid={result[0]}, Members={result[1]}, Count={result[4]}")
        assert result[0] == True, "Valid ZIP should be accepted"
        assert result[4] == 2, "Should have 2 images"
        print("   ✓ Valid ZIP correctly processed")
    finally:
        os.unlink(valid_zip_path)
    
    # Test 3: ZIP with non-image files
    print("\n3. Testing ZIP with non-image files...")
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
        with zipfile.ZipFile(temp_zip.name, 'w') as zipf:
            zipf.writestr('image1.png', b'fake png data')
            zipf.writestr('document.txt', b'text file')
        mixed_zip_path = temp_zip.name
    
    try:
        result = scanner.analyze_zip(mixed_zip_path, collect_members=True)
        print(f"   Mixed ZIP result: Valid={result[0]}")
        assert result[0] == False, "Mixed ZIP should be rejected"
        print("   ✓ Mixed ZIP correctly rejected")
    finally:
        os.unlink(mixed_zip_path)
    
    # Test 4: Empty ZIP
    print("\n4. Testing empty ZIP...")
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
        with zipfile.ZipFile(temp_zip.name, 'w'):
            pass  # Create empty ZIP
        empty_zip_path = temp_zip.name
    
    try:
        result = scanner.analyze_zip(empty_zip_path, collect_members=True)
        print(f"   Empty ZIP result: Valid={result[0]}")
        assert result[0] == False, "Empty ZIP should be rejected"
        print("   ✓ Empty ZIP correctly rejected")
    finally:
        os.unlink(empty_zip_path)
    
    print("\n✓ All tests passed! Scanning hang fixes work correctly.")
    return True

if __name__ == "__main__":
    test_scanning_fix()