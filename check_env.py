#!/usr/bin/env python
import sys
import os

print("=== Current Python Environment ===")
print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}")
print(f"sys.prefix: {sys.prefix}")
print(f"sys.base_prefix: {sys.base_prefix}")

in_venv = hasattr(sys, 'real_prefix') or (
    hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
)
print(f"In virtual environment: {in_venv}")
print(f"VIRTUAL_ENV env var: {os.environ.get('VIRTUAL_ENV', 'Not set')}")

print("\n=== Checking Dependencies ===")
deps = ['torch', 'demucs', 'numpy', 'PySide6']
for dep in deps:
    try:
        mod = __import__(dep)
        location = getattr(mod, '__file__', 'built-in')
        print(f"✓ {dep}: {location}")
    except ImportError as e:
        print(f"✗ {dep}: NOT FOUND ({e})")
