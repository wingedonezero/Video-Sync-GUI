# tests/test_rescale_tags.py
"""
Tests for ASS override tag rescaling in style_ops._scale_override_tags.

Validates:
1. Existing tag scaling still works (pos, move, clip, fs, bord, etc.)
2. fscx/fscy are NOT rescaled (percentage-based, avoids double-scaling)
3. New tags are rescaled (fsp, be, xshad, iclip)
4. \\t() transform blocks are recursively processed
5. Non-rescale operations don't touch event text
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vsg_core.subtitles.operations.style_ops import _scale_override_tags


# Test parameters: 720p -> 1080p style rescale
# scale = min(1920/1280, 1080/720) = min(1.5, 1.5) = 1.5
# scale_h = 1080/720 = 1.5
# For simplicity, use equal scale/scale_h and zero offsets first
SCALE = 1.5
SCALE_H = 1.5
OFFSET_X = 0.0
OFFSET_Y = 0.0

# With borders: 480p -> 1080p (letterboxed)
# scale = min(1920/720, 1080/480) = min(2.667, 2.25) = 2.25
# scale_h = 1080/480 = 2.25
# new_w = 720 * 2.25 = 1620, offset_x = (1920-1620)/2 = 150
# new_h = 480 * 2.25 = 1080, offset_y = 0
BORDER_SCALE = 2.25
BORDER_SCALE_H = 2.25
BORDER_OFFSET_X = 150.0
BORDER_OFFSET_Y = 0.0


def test_existing_pos_tag():
    """\\pos(x,y) should be scaled + offset."""
    text = "{\\pos(100,200)}Sign text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\pos(150,300)}Sign text", f"Got: {result}"
    print("  PASSED: \\pos scaling")


def test_existing_move_tag():
    """\\move(x1,y1,x2,y2,t1,t2) — positions scaled, times preserved."""
    text = "{\\move(100,200,300,400,0,500)}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\move(150,300,450,600,0,500)}Text", f"Got: {result}"
    print("  PASSED: \\move scaling")


def test_existing_clip_tag():
    """\\clip(x1,y1,x2,y2) should be scaled + offset."""
    text = "{\\clip(10,20,300,400)}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\clip(15,30,450,600)}Text", f"Got: {result}"
    print("  PASSED: \\clip scaling")


def test_existing_fs_tag():
    """\\fs should be scaled by scale_h."""
    text = "{\\fs20}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\fs30}Text", f"Got: {result}"
    print("  PASSED: \\fs scaling")


def test_existing_bord_tag():
    """\\bord should be scaled by uniform scale."""
    text = "{\\bord2}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\bord3}Text", f"Got: {result}"
    print("  PASSED: \\bord scaling")


def test_existing_blur_shad():
    """\\blur and \\shad should be scaled by scale_h."""
    text = "{\\blur4\\shad2}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\blur6\\shad3}Text", f"Got: {result}"
    print("  PASSED: \\blur and \\shad scaling")


def test_pos_with_border_offsets():
    """\\pos should include border offsets for letterboxed rescale."""
    text = "{\\pos(100,200)}Text"
    result = _scale_override_tags(
        text, BORDER_SCALE, BORDER_SCALE_H, BORDER_OFFSET_X, BORDER_OFFSET_Y
    )
    # x: 100 * 2.25 + 150 = 375, y: 200 * 2.25 + 0 = 450
    assert result == "{\\pos(375,450)}Text", f"Got: {result}"
    print("  PASSED: \\pos with border offsets")


def test_org_tag():
    """\\org(x,y) should be scaled + offset like \\pos."""
    text = "{\\org(640,360)}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\org(960,540)}Text", f"Got: {result}"
    print("  PASSED: \\org scaling")


# --- New: fscx/fscy should NOT be rescaled ---


def test_fscx_not_rescaled():
    """\\fscx is percentage-based — must NOT be rescaled."""
    text = "{\\fscx150}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\fscx150}Text", f"Got: {result}"
    print("  PASSED: \\fscx NOT rescaled")


def test_fscy_not_rescaled():
    """\\fscy is percentage-based — must NOT be rescaled."""
    text = "{\\fscy80}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\fscy80}Text", f"Got: {result}"
    print("  PASSED: \\fscy NOT rescaled")


def test_fscx_fscy_with_fs():
    """\\fs gets rescaled but \\fscx/\\fscy do not — no double-scaling."""
    text = "{\\fs20\\fscx120\\fscy80}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\fs30\\fscx120\\fscy80}Text", f"Got: {result}"
    print("  PASSED: \\fs rescaled, \\fscx/\\fscy preserved")


# --- New: added tags ---


def test_fsp_rescaled():
    """\\fsp (letter spacing) should be rescaled by scale_h."""
    text = "{\\fsp5}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\fsp7.5}Text", f"Got: {result}"
    print("  PASSED: \\fsp rescaled")


def test_be_rescaled():
    """\\be (blur edges) should be rescaled by scale_h."""
    text = "{\\be2}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\be3}Text", f"Got: {result}"
    print("  PASSED: \\be rescaled")


def test_xshad_rescaled():
    """\\xshad should be rescaled by uniform scale."""
    text = "{\\xshad4}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\xshad6}Text", f"Got: {result}"
    print("  PASSED: \\xshad rescaled")


def test_iclip_rescaled():
    """\\iclip should be rescaled identically to \\clip."""
    text = "{\\iclip(10,20,300,400)}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\iclip(15,30,450,600)}Text", f"Got: {result}"
    print("  PASSED: \\iclip rescaled")


# --- New: \\t() recursive processing ---


def test_t_with_fs():
    """Tags inside \\t() should be recursively rescaled."""
    text = "{\\t(\\fs20)}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\t(\\fs30)}Text", f"Got: {result}"
    print("  PASSED: \\t(\\fs) recursively rescaled")


def test_t_with_timing_and_tags():
    """\\t() timing params preserved, tags inside rescaled."""
    text = "{\\t(0,1000,\\fs20\\bord4)}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\t(0,1000,\\fs30\\bord6)}Text", f"Got: {result}"
    print("  PASSED: \\t(timing,tags) correctly handled")


def test_t_with_accel_and_tags():
    """\\t() with accel + tags — accel preserved, tags rescaled."""
    text = "{\\t(0,1000,2,\\fs20)}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\t(0,1000,2,\\fs30)}Text", f"Got: {result}"
    print("  PASSED: \\t(timing,accel,tags) correctly handled")


def test_t_with_clip_inside():
    """\\clip inside \\t() should be rescaled."""
    text = "{\\t(0,500,\\clip(10,20,300,400))}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\t(0,500,\\clip(15,30,450,600))}Text", f"Got: {result}"
    print("  PASSED: \\clip inside \\t() rescaled")


def test_t_with_pos_inside():
    """\\pos inside \\t() should be rescaled with offsets."""
    text = "{\\t(\\pos(100,200))}Text"
    result = _scale_override_tags(
        text, BORDER_SCALE, BORDER_SCALE_H, BORDER_OFFSET_X, BORDER_OFFSET_Y
    )
    # x: 100*2.25+150=375, y: 200*2.25+0=450
    assert result == "{\\t(\\pos(375,450))}Text", f"Got: {result}"
    print("  PASSED: \\pos inside \\t() rescaled with offsets")


def test_t_fscx_not_rescaled_inside():
    """\\fscx inside \\t() should still NOT be rescaled."""
    text = "{\\t(0,1000,\\fscx150)}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\t(0,1000,\\fscx150)}Text", f"Got: {result}"
    print("  PASSED: \\fscx inside \\t() NOT rescaled")


def test_multiple_t_blocks():
    """Multiple \\t() blocks in one override block."""
    text = "{\\fs20\\t(0,500,\\fs40)\\t(500,1000,\\bord4)}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\fs30\\t(0,500,\\fs60)\\t(500,1000,\\bord6)}Text", f"Got: {result}"
    print("  PASSED: multiple \\t() blocks")


def test_tags_before_and_after_t():
    """Tags outside \\t() should also be rescaled normally."""
    text = "{\\pos(100,200)\\t(0,500,\\fs40)\\bord2}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\pos(150,300)\\t(0,500,\\fs60)\\bord3}Text", f"Got: {result}"
    print("  PASSED: tags before and after \\t() rescaled")


def test_nested_t():
    """Nested \\t() blocks should be recursively processed."""
    text = "{\\t(0,1000,\\t(500,800,\\fs20))}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\t(0,1000,\\t(500,800,\\fs30))}Text", f"Got: {result}"
    print("  PASSED: nested \\t() recursively processed")


# --- Preservation tests ---


def test_colors_preserved():
    """Color tags should be preserved unchanged."""
    text = "{\\c&H00FF00&\\1c&HFF0000&}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\c&H00FF00&\\1c&HFF0000&}Text", f"Got: {result}"
    print("  PASSED: colors preserved")


def test_alpha_preserved():
    """Alpha tags should be preserved unchanged."""
    text = "{\\alpha&H80&}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\alpha&H80&}Text", f"Got: {result}"
    print("  PASSED: alpha preserved")


def test_fad_preserved():
    """\\fad (fade) is time-based — should NOT be rescaled."""
    text = "{\\fad(200,300)}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\fad(200,300)}Text", f"Got: {result}"
    print("  PASSED: \\fad preserved")


def test_k_tags_preserved():
    """Karaoke tags are time-based — should NOT be rescaled."""
    text = "{\\k50}Syl{\\k30}la{\\k40}ble"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{\\k50}Syl{\\k30}la{\\k40}ble", f"Got: {result}"
    print("  PASSED: karaoke tags preserved")


def test_plain_text_preserved():
    """Text without override blocks should be untouched."""
    text = "Just plain text with no tags"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == text, f"Got: {result}"
    print("  PASSED: plain text preserved")


def test_empty_block_preserved():
    """Empty override blocks should be preserved."""
    text = "{}Text"
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    assert result == "{}Text", f"Got: {result}"
    print("  PASSED: empty block preserved")


def test_complex_real_world():
    """Real-world complex typesetting line."""
    text = (
        "{\\an8\\pos(640,50)\\fad(0,500)\\fs24\\bord2\\shad1"
        "\\fscx110\\fscy90\\blur0.5\\be1\\fsp2}TITLE CARD"
    )
    result = _scale_override_tags(text, SCALE, SCALE_H, OFFSET_X, OFFSET_Y)
    # an8 = preserved, pos scaled, fad preserved, fs scaled, bord scaled,
    # shad scaled, fscx NOT scaled, fscy NOT scaled, blur scaled, be scaled, fsp scaled
    expected = (
        "{\\an8\\pos(960,75)\\fad(0,500)\\fs36\\bord3\\shad1.5"
        "\\fscx110\\fscy90\\blur0.75\\be1.5\\fsp3}TITLE CARD"
    )
    assert result == expected, f"Got: {result}"
    print("  PASSED: complex real-world line")


def run_all_tests():
    """Run all rescale tag tests."""
    print("=" * 60)
    print("RESCALE TAG PROCESSING TESTS")
    print("=" * 60)

    tests = [
        # Existing behavior
        test_existing_pos_tag,
        test_existing_move_tag,
        test_existing_clip_tag,
        test_existing_fs_tag,
        test_existing_bord_tag,
        test_existing_blur_shad,
        test_pos_with_border_offsets,
        test_org_tag,
        # fscx/fscy NOT rescaled
        test_fscx_not_rescaled,
        test_fscy_not_rescaled,
        test_fscx_fscy_with_fs,
        # New tags
        test_fsp_rescaled,
        test_be_rescaled,
        test_xshad_rescaled,
        test_iclip_rescaled,
        # \t() recursive processing
        test_t_with_fs,
        test_t_with_timing_and_tags,
        test_t_with_accel_and_tags,
        test_t_with_clip_inside,
        test_t_with_pos_inside,
        test_t_fscx_not_rescaled_inside,
        test_multiple_t_blocks,
        test_tags_before_and_after_t,
        test_nested_t,
        # Preservation
        test_colors_preserved,
        test_alpha_preserved,
        test_fad_preserved,
        test_k_tags_preserved,
        test_plain_text_preserved,
        test_empty_block_preserved,
        # Complex real-world
        test_complex_real_world,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\n  FAILED ({test.__name__}): {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
