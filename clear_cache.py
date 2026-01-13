#!/usr/bin/env python3
"""
Clear Python bytecode cache to ensure latest code is used.
Run this after updating code if you experience import or behavior issues.
"""
import shutil
from pathlib import Path

project_root = Path(__file__).parent
removed_count = 0

print("Clearing Python bytecode cache...")

# Remove all __pycache__ directories
for pycache_dir in project_root.rglob("__pycache__"):
    try:
        shutil.rmtree(pycache_dir)
        removed_count += 1
        print(f"  Removed: {pycache_dir.relative_to(project_root)}")
    except Exception as e:
        print(f"  Failed to remove {pycache_dir}: {e}")

# Remove all .pyc files
for pyc_file in project_root.rglob("*.pyc"):
    try:
        pyc_file.unlink()
        removed_count += 1
        print(f"  Removed: {pyc_file.relative_to(project_root)}")
    except Exception as e:
        print(f"  Failed to remove {pyc_file}: {e}")

print(f"\n✓ Cache cleared! Removed {removed_count} items.")
print("Please restart your application now.")
