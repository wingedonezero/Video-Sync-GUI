#!/usr/bin/env python3
"""
Test script to verify config types are correct.
Run this to diagnose type coercion issues.
"""
from vsg_core.config import AppConfig

print("Testing AppConfig type coercion...")
print("=" * 60)

config = AppConfig()

# Test keys that commonly cause QSpinBox issues
test_keys = [
    ('scan_chunk_count', int),
    ('scan_chunk_duration', int),
    ('min_match_pct', float),
    ('scan_start_percentage', float),
    ('scan_end_percentage', float),
    ('log_compact', bool),
    ('log_autoscroll', bool),
    ('filter_bandpass_order', int),
    ('filter_lowpass_taps', int),
    ('sub_anchor_search_range_ms', int),
]

print("\n1. Testing config.get() access:")
all_correct = True
for key, expected_type in test_keys:
    value = config.get(key)
    actual_type = type(value)
    status = "✓" if actual_type == expected_type else "✗"
    print(f"  {status} {key}: {value} (type: {actual_type.__name__}, expected: {expected_type.__name__})")
    if actual_type != expected_type:
        all_correct = False

print("\n2. Testing direct dict access (how UI accesses):")
for key, expected_type in test_keys:
    value = config.settings.get(key)
    actual_type = type(value)
    status = "✓" if actual_type == expected_type else "✗"
    print(f"  {status} {key}: {value} (type: {actual_type.__name__}, expected: {expected_type.__name__})")
    if actual_type != expected_type:
        all_correct = False
        print(f"      ERROR: This will cause QSpinBox.setValue() to fail!")

if all_correct:
    print("\n✓ SUCCESS: All config values have correct types")
    print("✓ Settings dialog should work now")
else:
    print("\n✗ FAILURE: Some values have wrong types")
    print("✗ Try running clear_cache.py and restarting the application")
