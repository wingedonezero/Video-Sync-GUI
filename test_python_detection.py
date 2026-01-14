#!/usr/bin/env python
"""Test script to verify Python executable detection for subprocesses"""
import sys
import os
from pathlib import Path

print("=" * 60)
print("Python Environment Detection Test")
print("=" * 60)
print()

# Current Python info
print("Current Python:")
print(f"  sys.executable: {sys.executable}")
print(f"  sys.prefix: {sys.prefix}")
print(f"  sys.base_prefix: {sys.base_prefix}")
print()

# Check if we're in a venv
in_venv = hasattr(sys, 'real_prefix') or (
    hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
)
print(f"Running in venv: {in_venv}")
print()

# Simulate the _get_venv_python() function
def _get_venv_python():
    """Test version of the function from source_separation.py"""
    # First priority: if we're running from a venv, sys.executable is correct
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        return sys.executable

    # Backup: Look for .venv in the project directory
    project_root = Path(__file__).resolve().parent
    venv_python = project_root / '.venv' / 'bin' / 'python'
    if venv_python.is_file():
        return str(venv_python)

    # Last resort: use whatever Python we're running with
    return sys.executable

detected_python = _get_venv_python()
print("Detected Python for subprocesses:")
print(f"  {detected_python}")
print()

# Check if detected Python exists
if os.path.isfile(detected_python):
    print(f"✓ Python executable exists")
else:
    print(f"✗ Python executable NOT FOUND")
print()

# Check for .venv directory
venv_dir = Path(__file__).resolve().parent / '.venv'
print(f"Looking for .venv at: {venv_dir}")
if venv_dir.is_dir():
    print(f"✓ .venv directory exists")
    venv_python = venv_dir / 'bin' / 'python'
    if venv_python.is_file():
        print(f"✓ .venv/bin/python exists")
    else:
        print(f"✗ .venv/bin/python NOT FOUND")
else:
    print(f"✗ .venv directory NOT FOUND - you need to run ./setup_env.sh first!")
print()

print("=" * 60)
if not in_venv:
    print("WARNING: Not running in a venv!")
    print("Make sure to:")
    print("  1. Run: ./setup_env.sh (option 1 for Full Setup)")
    print("  2. Then run: ./run.sh")
else:
    print("SUCCESS: Running in a properly activated venv!")
print("=" * 60)
