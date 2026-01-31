# tests/test_subtitle_data.py
# -*- coding: utf-8 -*-
"""
Comprehensive tests for the unified SubtitleData system.

Tests:
1. ASS parsing and round-trip
2. SRT parsing and conversion
3. Sync plugin system
4. Operations (stepping, style ops)
5. Float ms precision through pipeline
"""
import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_ass_parsing_and_roundtrip():
    """Test ASS file parsing and writing preserves data."""
    print("\n=== Test: ASS Parsing and Round-trip ===")

    # Create a test ASS file
    ass_content = """[Script Info]
; Test file
Title: Test Subtitle
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: 1920
PlayResY: 1080

[Aegisub Project Garbage]
Last Style Storage: Default
Audio File: test.wav
Video File: test.mkv

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1
Style: Signs,Times New Roman,36,&H00FFFF00,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,8,20,20,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.23,0:00:04.56,Default,,0,0,0,,Hello, world!
Dialogue: 0,0:00:05.00,0:00:08.50,Default,,0,0,0,,This is a test subtitle.
Comment: 0,0:00:10.00,0:00:12.00,Default,,0,0,0,,This is a comment.
Dialogue: 1,0:00:15.00,0:00:18.99,Signs,,0,0,0,,{\\pos(100,200)}Sign text here

"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.ass', delete=False, encoding='utf-8') as f:
        f.write(ass_content)
        temp_input = f.name

    try:
        from vsg_core.subtitles.data import SubtitleData

        # Parse
        data = SubtitleData.from_file(temp_input)

        # Verify parsing
        print(f"  Source format: {data.source_format}")
        print(f"  Events: {len(data.events)}")
        print(f"  Styles: {len(data.styles)}")
        print(f"  Script Info entries: {len(data.script_info)}")

        assert len(data.events) == 4, f"Expected 4 events, got {len(data.events)}"
        assert len(data.styles) == 2, f"Expected 2 styles, got {len(data.styles)}"
        assert 'Default' in data.styles
        assert 'Signs' in data.styles

        # Check timing precision (centiseconds -> ms)
        event0 = data.events[0]
        print(f"  Event 0 timing: {event0.start_ms}ms -> {event0.end_ms}ms")
        assert event0.start_ms == 1230.0, f"Expected 1230.0, got {event0.start_ms}"
        assert event0.end_ms == 4560.0, f"Expected 4560.0, got {event0.end_ms}"

        # Check comment detection
        assert data.events[2].is_comment == True
        assert data.events[0].is_comment == False

        # Check style parsing
        default_style = data.styles['Default']
        print(f"  Default style: {default_style.fontname}, {default_style.fontsize}pt")
        assert default_style.fontname == 'Arial'
        assert default_style.fontsize == 48.0

        signs_style = data.styles['Signs']
        assert signs_style.bold == -1  # True in ASS
        assert signs_style.alignment == 8

        # Check Script Info
        assert data.script_info.get('PlayResX') == '1920'
        assert data.script_info.get('PlayResY') == '1080'

        # Write back and verify
        with tempfile.NamedTemporaryFile(suffix='.ass', delete=False) as f:
            temp_output = f.name

        data.save_ass(temp_output)

        # Re-parse and verify
        data2 = SubtitleData.from_file(temp_output)

        assert len(data2.events) == len(data.events)
        assert len(data2.styles) == len(data.styles)
        assert data2.events[0].start_ms == data.events[0].start_ms
        assert data2.events[0].text == data.events[0].text

        print("  PASSED: Round-trip preserves all data")

        os.unlink(temp_output)

    finally:
        os.unlink(temp_input)

    return True


def test_srt_parsing():
    """Test SRT file parsing."""
    print("\n=== Test: SRT Parsing ===")

    srt_content = """1
00:00:01,234 --> 00:00:04,567
Hello, world!

2
00:00:05,000 --> 00:00:08,500
This is a test subtitle.
With multiple lines.

3
00:00:10,123 --> 00:00:12,999
<i>Italic text</i>
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        f.write(srt_content)
        temp_input = f.name

    try:
        from vsg_core.subtitles.data import SubtitleData

        data = SubtitleData.from_file(temp_input)

        print(f"  Source format: {data.source_format}")
        print(f"  Events: {len(data.events)}")

        assert len(data.events) == 3, f"Expected 3 events, got {len(data.events)}"

        # Check timing (ms precision)
        event0 = data.events[0]
        print(f"  Event 0 timing: {event0.start_ms}ms -> {event0.end_ms}ms")
        assert event0.start_ms == 1234.0, f"Expected 1234.0, got {event0.start_ms}"
        assert event0.end_ms == 4567.0, f"Expected 4567.0, got {event0.end_ms}"

        # Check multi-line text
        event1 = data.events[1]
        assert '\n' in event1.text or '\\N' in event1.text, "Multi-line text not preserved"

        print("  PASSED: SRT parsing works correctly")

    finally:
        os.unlink(temp_input)

    return True


def test_sync_plugin_registry():
    """Test sync plugin registry and timebase-frame-locked plugin."""
    print("\n=== Test: Sync Plugin Registry ===")

    from vsg_core.subtitles.sync_modes import get_sync_plugin, list_sync_plugins

    # List available plugins
    plugins = list_sync_plugins()
    print(f"  Registered plugins: {list(plugins.keys())}")

    assert 'timebase-frame-locked-timestamps' in plugins
    assert 'time-based' in plugins

    # Get plugin instance
    plugin = get_sync_plugin('timebase-frame-locked-timestamps')
    assert plugin is not None
    assert plugin.name == 'timebase-frame-locked-timestamps'

    # Get time-based plugin
    tb_plugin = get_sync_plugin('time-based')
    assert tb_plugin is not None
    assert tb_plugin.name == 'time-based'

    print("  PASSED: Plugin registry works correctly")
    return True


def test_time_based_sync():
    """Test time-based sync mode."""
    print("\n=== Test: Time-Based Sync Mode ===")

    from vsg_core.subtitles.data import SubtitleData, SubtitleEvent, SubtitleStyle
    from collections import OrderedDict

    # Create test data
    data = SubtitleData()
    data.styles = OrderedDict([('Default', SubtitleStyle.default())])
    data.events = [
        SubtitleEvent(start_ms=1000.0, end_ms=2000.0, text="Event 1"),
        SubtitleEvent(start_ms=3000.0, end_ms=4000.0, text="Event 2"),
        SubtitleEvent(start_ms=5000.0, end_ms=6000.0, text="Event 3"),
    ]

    original_starts = [e.start_ms for e in data.events]

    # Apply sync with raw values mode
    result = data.apply_sync(
        mode='time-based',
        total_delay_ms=500.5,  # Use float to test precision
        global_shift_ms=500.5,
        config={'time_based_use_raw_values': True}
    )

    print(f"  Result: {result.success}, events affected: {result.events_affected}")

    assert result.success
    assert result.events_affected == 3

    # Verify timing adjustments
    for i, event in enumerate(data.events):
        expected = original_starts[i] + 500.5
        print(f"  Event {i}: {original_starts[i]} -> {event.start_ms}")
        assert event.start_ms == expected, f"Expected {expected}, got {event.start_ms}"

    # Check operation record
    assert len(data.operations) == 1
    assert data.operations[0].operation == 'sync'

    print("  PASSED: Time-based sync works correctly")
    return True


def test_float_precision_through_pipeline():
    """Test that float precision is maintained until final save."""
    print("\n=== Test: Float Precision Through Pipeline ===")

    from vsg_core.subtitles.data import SubtitleData, SubtitleEvent, SubtitleStyle
    from collections import OrderedDict
    import tempfile

    # Create test data with precise float timing
    data = SubtitleData()
    data.styles = OrderedDict([('Default', SubtitleStyle.default())])
    data.script_info = OrderedDict([
        ('ScriptType', 'v4.00+'),
        ('PlayResX', '1920'),
        ('PlayResY', '1080'),
    ])

    # Use timing that would lose precision if rounded early
    # 1234.567ms should stay as float until save
    data.events = [
        SubtitleEvent(start_ms=1234.567, end_ms=5678.901, text="Precision test"),
    ]

    # Apply multiple operations
    result1 = data.apply_sync(
        mode='time-based',
        total_delay_ms=100.333,
        global_shift_ms=100.333,
        config={'time_based_use_raw_values': True}
    )

    # Apply another delay
    result2 = data.apply_sync(
        mode='time-based',
        total_delay_ms=50.666,
        global_shift_ms=50.666,
        config={'time_based_use_raw_values': True}
    )

    # Check precision is maintained
    event = data.events[0]
    expected = 1234.567 + 100.333 + 50.666
    print(f"  After operations: start_ms = {event.start_ms}")
    print(f"  Expected: {expected}")

    # Should be very close (floating point precision)
    assert abs(event.start_ms - expected) < 0.001, f"Precision lost: {event.start_ms} vs {expected}"

    # Save and verify rounding happens only at save
    with tempfile.NamedTemporaryFile(suffix='.ass', delete=False) as f:
        temp_output = f.name

    try:
        data.save_ass(temp_output)

        # Read raw file to check timing format
        with open(temp_output, 'r') as f:
            content = f.read()

        print(f"  Output file written")

        # ASS times should be rounded to centiseconds
        # 1234.567 + 100.333 + 50.666 = 1385.566 -> 1385.56 ms -> 138.556 cs -> 138 cs = 0:00:01.38
        # Actually: floor(1385.566 / 10) = 138 cs

        # Re-parse to check
        data2 = SubtitleData.from_file(temp_output)

        # After round-trip, should be floored to centisecond boundary
        # 138 cs = 1380 ms
        print(f"  After round-trip: start_ms = {data2.events[0].start_ms}")

        # The start time should now be a multiple of 10 (centiseconds)
        assert data2.events[0].start_ms % 10 == 0, "Should be rounded to centiseconds"

        print("  PASSED: Float precision maintained until save, rounding happens at save")

    finally:
        os.unlink(temp_output)

    return True


def test_style_operations():
    """Test style operations."""
    print("\n=== Test: Style Operations ===")

    from vsg_core.subtitles.data import SubtitleData, SubtitleEvent, SubtitleStyle
    from collections import OrderedDict

    # Create test data
    data = SubtitleData()
    data.styles = OrderedDict([
        ('Default', SubtitleStyle(name='Default', fontname='Arial', fontsize=48.0)),
        ('Signs', SubtitleStyle(name='Signs', fontname='Times New Roman', fontsize=36.0)),
    ])
    data.events = [
        SubtitleEvent(start_ms=1000.0, end_ms=2000.0, text="Test", style='Default'),
    ]

    # Test size multiplier
    result = data.apply_size_multiplier(1.5)

    print(f"  Size multiplier result: {result.success}")
    assert result.success

    # Check sizes were multiplied
    assert data.styles['Default'].fontsize == 72.0, f"Expected 72.0, got {data.styles['Default'].fontsize}"
    assert data.styles['Signs'].fontsize == 54.0, f"Expected 54.0, got {data.styles['Signs'].fontsize}"

    print("  PASSED: Style operations work correctly")
    return True


def test_validation():
    """Test data validation."""
    print("\n=== Test: Data Validation ===")

    from vsg_core.subtitles.data import SubtitleData, SubtitleEvent, SubtitleStyle
    from collections import OrderedDict

    # Create test data with issues
    data = SubtitleData()
    data.styles = OrderedDict([('Default', SubtitleStyle.default())])
    data.events = [
        SubtitleEvent(start_ms=2000.0, end_ms=1000.0, text="Bad timing"),  # end < start
        SubtitleEvent(start_ms=-100.0, end_ms=1000.0, text="Negative"),    # negative start
        SubtitleEvent(start_ms=1000.0, end_ms=2000.0, text="OK", style='Unknown'),  # unknown style
    ]

    warnings = data.validate()

    print(f"  Validation warnings: {len(warnings)}")
    for w in warnings:
        print(f"    - {w}")

    assert len(warnings) == 3, f"Expected 3 warnings, got {len(warnings)}"

    print("  PASSED: Validation detects issues")
    return True


def test_timebase_frame_locked_sync():
    """Test timebase-frame-locked-timestamps sync mode."""
    print("\n=== Test: TimeBase Frame-Locked Sync Mode ===")

    from vsg_core.subtitles.data import SubtitleData, SubtitleEvent, SubtitleStyle
    from vsg_core.subtitles.sync_modes import get_sync_plugin
    from collections import OrderedDict

    # Get the plugin
    plugin = get_sync_plugin('timebase-frame-locked-timestamps')
    assert plugin is not None
    print(f"  Plugin: {plugin.name}")
    print(f"  Description: {plugin.description}")

    # Create test data
    data = SubtitleData()
    data.styles = OrderedDict([('Default', SubtitleStyle.default())])
    data.events = [
        SubtitleEvent(start_ms=1000.0, end_ms=2000.0, text="Event 1"),
        SubtitleEvent(start_ms=3000.0, end_ms=4000.0, text="Event 2"),
        SubtitleEvent(start_ms=5000.0, end_ms=6000.0, text="Event 3"),
    ]

    original_starts = [e.start_ms for e in data.events]

    # Test without target video (should fail gracefully)
    result = data.apply_sync(
        mode='timebase-frame-locked-timestamps',
        total_delay_ms=500.0,
        global_shift_ms=500.0,
        target_fps=23.976,
        target_video=None,  # No video
    )

    print(f"  Without video: success={result.success}")
    assert result.success == False, "Should fail without target video"
    assert "Target video required" in result.error

    # Test with fake video path (will use fallback calculation)
    # Since we don't have a real video, VideoTimestamps will fail
    # but the plugin should still apply delay
    result2 = data.apply_sync(
        mode='timebase-frame-locked-timestamps',
        total_delay_ms=500.0,
        global_shift_ms=500.0,
        target_fps=23.976,
        target_video="/fake/video.mkv",  # Fake path - VTS will fail, falls back to simple calc
    )

    print(f"  With video (fallback mode): success={result2.success}")
    print(f"  Events affected: {result2.events_affected}")

    # The sync should work even without real VideoTimestamps
    assert result2.success, f"Sync should succeed with fallback: {result2.error}"

    # Verify timing was adjusted
    for i, event in enumerate(data.events):
        print(f"  Event {i}: {original_starts[i]} -> {event.start_ms}")
        # Should be close to original + delay (may have frame snapping adjustments)
        assert event.start_ms >= original_starts[i], "Event should be delayed"

    print("  PASSED: TimeBase Frame-Locked sync works correctly")
    return True


def test_mkvmerge_sync_mode():
    """Test time-based sync in mkvmerge mode (no subtitle modification)."""
    print("\n=== Test: MKVMerge Sync Mode ===")

    from vsg_core.subtitles.data import SubtitleData, SubtitleEvent, SubtitleStyle
    from collections import OrderedDict

    # Create test data
    data = SubtitleData()
    data.styles = OrderedDict([('Default', SubtitleStyle.default())])
    data.events = [
        SubtitleEvent(start_ms=1000.0, end_ms=2000.0, text="Event 1"),
        SubtitleEvent(start_ms=3000.0, end_ms=4000.0, text="Event 2"),
    ]

    original_starts = [e.start_ms for e in data.events]

    # Apply sync in default mode (mkvmerge handles sync)
    result = data.apply_sync(
        mode='time-based',
        total_delay_ms=500.0,
        global_shift_ms=500.0,
        config={'time_based_use_raw_values': False}  # Default: mkvmerge mode
    )

    print(f"  Result: success={result.success}")
    print(f"  Events affected: {result.events_affected}")
    print(f"  Summary: {result.summary}")

    assert result.success
    assert result.events_affected == 0, "MKVMerge mode should not modify events"

    # Verify events are unchanged
    for i, event in enumerate(data.events):
        assert event.start_ms == original_starts[i], "Events should not be modified in mkvmerge mode"

    print("  PASSED: MKVMerge sync mode works correctly")
    return True


def test_json_export():
    """Test JSON debug export."""
    print("\n=== Test: JSON Debug Export ===")

    from vsg_core.subtitles.data import SubtitleData, SubtitleEvent, SubtitleStyle
    from collections import OrderedDict
    import tempfile
    import json

    # Create test data
    data = SubtitleData()
    data.script_info = OrderedDict([
        ('Title', 'Test'),
        ('PlayResX', '1920'),
        ('PlayResY', '1080'),
    ])
    data.styles = OrderedDict([('Default', SubtitleStyle.default())])
    data.events = [
        SubtitleEvent(start_ms=1234.567, end_ms=5678.901, text="Test event"),
    ]

    # Apply an operation to have a record
    data.apply_sync(
        mode='time-based',
        total_delay_ms=100.0,
        global_shift_ms=100.0,
        config={'time_based_use_raw_values': True}
    )

    # Export to JSON
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        temp_output = f.name

    try:
        data.save_json(temp_output)

        # Read and verify JSON
        with open(temp_output) as f:
            json_data = json.load(f)

        print(f"  JSON keys: {list(json_data.keys())}")
        print(f"  Events in JSON: {len(json_data['events'])}")
        print(f"  Operations recorded: {len(json_data['operations'])}")

        assert 'events' in json_data
        assert 'styles' in json_data
        assert 'operations' in json_data
        assert len(json_data['events']) == 1
        assert len(json_data['operations']) == 1

        # Check float precision in JSON
        event_data = json_data['events'][0]
        print(f"  Event timing in JSON: {event_data['start_ms']} -> {event_data['end_ms']}")
        assert event_data['start_ms'] == 1334.567, f"Float not preserved: {event_data['start_ms']}"

        print("  PASSED: JSON export works correctly")

    finally:
        import os
        os.unlink(temp_output)

    return True


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("UNIFIED SUBTITLEDATA SYSTEM TESTS")
    print("=" * 60)

    tests = [
        test_ass_parsing_and_roundtrip,
        test_srt_parsing,
        test_sync_plugin_registry,
        test_time_based_sync,
        test_timebase_frame_locked_sync,
        test_mkvmerge_sync_mode,
        test_float_precision_through_pipeline,
        test_style_operations,
        test_json_export,
        test_validation,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\n  FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
