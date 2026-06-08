"""Regression tests for exact-grid surgical rounding + whole-frame snapping.

PGS subtitle timestamps land exactly on real (millisecond-rounded) video frames
but at odd milliseconds. The frame grid is computed with EXACT integer
arithmetic from the fps fraction (:class:`FrameClock`) — not float
``int(n*fd+0.5)``, which is 1ms wrong at every frame whose exact time ends on a
half-millisecond. There is no rounding tolerance: a value is on a frame or it is
not. Whole-frame sync shifts are made exact at apply time (:class:`FrameShift`),
so frame-locked values reach the rounder sitting exactly on a frame.

Values used below were measured straight from the test MKV
(``ATOM THE BEGINNING BD/1.mkv``, 24000/1001) around OCR line 0293.
"""

from vsg_core.subtitles.frame_utils.frame_clock import FrameClock, FrameShift
from vsg_core.subtitles.frame_utils.surgical_rounding import (
    surgical_round_event,
    surgical_round_single,
)

CLOCK = FrameClock(24000, 1001)  # 23.976


# --- the exact grid matches the real container grid -------------------------


def test_exact_grid_matches_container_grid():
    assert CLOCK.frame_ms(32325) == 1348222
    assert CLOCK.frame_ms(32324) == 1348180
    assert CLOCK.frame_ms(32326) == 1348264
    assert CLOCK.frame_ms(1828) == 76243
    assert CLOCK.frame_ms(1838) == 76660


def test_exact_grid_rounds_half_ms_frames_up_where_float_failed():
    # Frame 12 is exactly 500.5ms; the container stores 501. The old float model
    # int(n*fd+0.5) yielded 500 — this is the 1ms error the tolerance masked.
    assert CLOCK.frame_ms(12) == 501
    assert CLOCK.frame_ms(36) == 1502
    assert CLOCK.frame_ms(60) == 2503


def test_floor_keeps_pgs_value_on_its_real_frame():
    # 1348222 sits on real frame 32325; its centisecond floor (1348220) maps to
    # the SAME real frame.
    assert CLOCK.frame_of(1348222.0) == CLOCK.frame_of(1348220.0) == 32325


# --- PGS frame-exact ends/starts must floor, not ceil -----------------------


def test_pgs_end_0293_floors_not_ceils():
    # line 0293 clear time -> 28.22, NOT 28.23
    r = surgical_round_single(1348222.0, CLOCK)
    assert r.centisecond_ms == 1348220
    assert r.method == "floor"
    assert not r.was_adjusted


def test_pgs_start_floors_not_ceils():
    r = surgical_round_single(76243.0, CLOCK)
    assert r.centisecond_ms == 76240
    assert r.method == "floor"
    assert not r.was_adjusted


def test_all_pgs_frame_exact_values_floor():
    # Every PGS timestamp is exactly on a real frame -> floor keeps it there.
    for ms in (17309, 19186, 76243, 91258, 1346470, 1348222):
        r = surgical_round_single(float(ms), CLOCK)
        assert r.method == "floor", (ms, r.method, r.centisecond_ms)
        assert not r.was_adjusted


def test_event_0293_floors_both_and_preserves_frame_span():
    r = surgical_round_event(1346470.0, 1348222.0, CLOCK)
    assert r.start.centisecond_ms == 1346470  # already on the 10ms grid
    assert r.end.centisecond_ms == 1348220  # 28.22, not 28.23
    exact_span = CLOCK.frame_of(1348222.0) - CLOCK.frame_of(1346470.0)
    out_span = CLOCK.frame_of(float(r.end.rounded_ms)) - CLOCK.frame_of(
        float(r.start.rounded_ms)
    )
    assert out_span == exact_span


# --- no regression for native ASS or genuinely off-frame values -------------


def test_native_ass_cs_aligned_unchanged():
    # ASS files only ever hold 10ms-aligned times; surgical must be a no-op.
    for ms in (17300, 76240, 1348220, 1348230):
        r = surgical_round_single(float(ms), CLOCK)
        assert r.centisecond_ms == ms
        assert not r.was_adjusted


def test_mid_frame_value_floors_like_before():
    # A value comfortably inside a frame floors to its centisecond (unchanged).
    r = surgical_round_single(76263.0, CLOCK)  # ~20ms into a frame
    assert r.centisecond_ms == 76260
    assert not r.was_adjusted


def test_genuine_drift_still_corrected():
    # A start a few ms past a real frame really does render on the NEXT frame;
    # floor would drop it a frame, so surgical must still fire (its real job).
    r = surgical_round_single(76246.0, CLOCK)
    assert r.was_adjusted
    assert CLOCK.frame_of(float(r.rounded_ms)) == CLOCK.frame_of(76246.0)


def test_invariant_output_always_renders_on_same_real_frame():
    # The core guarantee for every case: the rounded value renders on the same
    # real frame as the exact input.
    for ms in (1348222.0, 76243.0, 76263.0, 76246.0, 17300.0, 17309.0, 1346470.0):
        r = surgical_round_single(ms, CLOCK)
        assert CLOCK.frame_of(float(r.rounded_ms)) == CLOCK.frame_of(ms), ms


# --- exact whole-frame snap (replaces the old float-shift + tolerance) -------


def test_is_on_frame_classifies_pgs_vs_mid_frame():
    assert CLOCK.is_on_frame(76243.0)  # PGS frame value
    assert CLOCK.is_on_frame(1348222.0)
    assert not CLOCK.is_on_frame(76263.0)  # mid-frame
    assert not CLOCK.is_on_frame(76246.0)


def test_frame_shift_snaps_on_frame_value_exactly():
    # A frame-exact PGS start (frame 1828) shifted +10 whole frames lands exactly
    # on real frame 1838 — no float slop, no tolerance needed.
    shift = FrameShift(CLOCK, 10)
    out = shift.shifted_ms(76243.0, flat_delay_ms=10 * CLOCK.frame_duration_ms)
    assert out == CLOCK.frame_ms(1838) == 76660
    # and it rounds (floors) cleanly onto 1838
    r = surgical_round_single(out, CLOCK)
    assert CLOCK.frame_of(float(r.rounded_ms)) == 1838
    assert not r.was_adjusted


def test_frame_shift_leaves_mid_frame_value_flat():
    # Mid-frame values are not snapped; they take the flat delay.
    shift = FrameShift(CLOCK, 4)
    flat = 4 * CLOCK.frame_duration_ms
    out = shift.shifted_ms(76263.0, flat_delay_ms=flat)
    assert out == 76263.0 + flat


def test_frame_shift_preserves_frame_span_across_shift():
    # Both endpoints of an event move by the same whole-frame count, so the
    # frame span is preserved exactly (a 3-frame sub stays 3 frames).
    shift = FrameShift(CLOCK, 4)
    flat = 4 * CLOCK.frame_duration_ms
    start = 76243.0  # frame 1828
    end = float(CLOCK.frame_ms(1831))  # frame 1831
    new_start = shift.shifted_ms(start, flat)
    new_end = shift.shifted_ms(end, flat)
    exact_span = CLOCK.frame_of(end) - CLOCK.frame_of(start)
    out_span = CLOCK.frame_of(new_end) - CLOCK.frame_of(new_start)
    assert exact_span == 3
    assert out_span == exact_span
