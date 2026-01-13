#!/usr/bin/env python3
"""
Diagnose where Python is importing vsg_core from.
"""
import sys
from pathlib import Path

print("Python Import Diagnostics")
print("=" * 70)

print("\n1. Python executable:")
print(f"   {sys.executable}")

print("\n2. Python path (where Python looks for modules):")
for i, path in enumerate(sys.path, 1):
    print(f"   {i}. {path}")

print("\n3. Attempting to import vsg_core...")
try:
    import vsg_core
    print(f"   ✓ Import successful")
    print(f"   Location: {vsg_core.__file__}")

    print("\n4. Checking config module...")
    from vsg_core import config
    print(f"   ✓ config imported from: {config.__file__}")

    print("\n5. Checking if _ensure_types_coerced exists...")
    from vsg_core.config import AppConfig
    if hasattr(AppConfig, '_ensure_types_coerced'):
        print(f"   ✓ _ensure_types_coerced method EXISTS (code is updated)")
    else:
        print(f"   ✗ _ensure_types_coerced method MISSING (code is OLD!)")
        print(f"   → You're importing old code from somewhere!")

    print("\n6. Testing AppConfig initialization...")
    try:
        test_config = AppConfig('test_diagnostic.json')
        print(f"   ✓ AppConfig created successfully")

        # Check a value type
        val = test_config.settings.get('scan_chunk_count')
        print(f"   scan_chunk_count type: {type(val).__name__} (should be 'int')")

        if type(val).__name__ == 'int':
            print(f"   ✓ Types are correct!")
        else:
            print(f"   ✗ Type is wrong - still using old code!")

    except Exception as e:
        print(f"   ✗ Error creating AppConfig: {e}")

except ImportError as e:
    print(f"   ✗ Import failed: {e}")
except Exception as e:
    print(f"   ✗ Unexpected error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("RECOMMENDATIONS:")
print("=" * 70)

expected_location = Path(__file__).parent / "vsg_core"
print(f"\nExpected location: {expected_location}")
print("\nIf vsg_core is being imported from somewhere else:")
print("1. Uninstall any system-wide installation: pip uninstall video-sync-gui")
print("2. Make sure you're running from the correct directory")
print("3. Add the project directory to PYTHONPATH")
