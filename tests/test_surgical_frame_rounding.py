"""Regression tests for real-frame-aware surgical rounding.

PGS subtitle timestamps land exactly on real (millisecond-rounded) video frames
but at odd milliseconds. The frame-drift check must compare against the real
frame grid ``round(n * frame_duration)`` — not the synthetic
``int(t / frame_duration)`` line — so that flooring a frame-exact value keeps it
on its frame instead of being ceil'd one frame off.

Values used below were measured straight from the test MKV
(``ATOM THE BEGINNING BD/1.mkv``) around OCR line 0293.
"""

from vsg_core.subtitles.frame_utils.surgical_rounding import (
    _real_frame_ms,
    _time_to_frame,
    surgical_round_event,
    surgical_round_single,
)

FPS = 24000 / 1001  # 23.976
FD = 1000.0 / FPS  # 41.70833... ms per frame


# --- the real frame grid is round(n * frame_duration) -----------------------


def test_real_frames_match_container_grid():
    assert _real_frame_ms(32325, FD) == 1348222
    assert _real_frame_ms(32324, FD) == 1348180
    assert _real_frame_ms(32326, FD) == 1348264
    assert _real_frame_ms(1828, FD) == 76243


def test_floor_keeps_pgs_value_on_its_real_frame():
    # 1348222 sits on real frame 32325; its centisecond floor (1348220) maps to
    # the SAME real frame. The old int(t/fd) formula reported 32324 -> the bug.
    assert _time_to_frame(1348222.0, FD) == _time_to_frame(1348220.0, FD) == 32325


# --- the bug: PGS frame-exact ends/starts must floor, not ceil --------------


def test_pgs_end_0293_floors_not_ceils():
    # line 0293 clear time -> 28.22, NOT 28.23
    r = surgical_round_single(1348222.0, FD)
    assert r.centisecond_ms == 1348220
    assert r.method == "floor"
    assert not r.was_adjusted


def test_pgs_start_floors_not_ceils():
    r = surgical_round_single(76243.0, FD)
    assert r.centisecond_ms == 76240
    assert r.method == "floor"
    assert not r.was_adjusted


def test_all_pgs_frame_exact_values_floor():
    # Every PGS timestamp is exactly on a real frame -> floor keeps it there.
    for ms in (17309, 19186, 76243, 91258, 1346470, 1348222):
        r = surgical_round_single(float(ms), FD)
        assert r.method == "floor", (ms, r.method, r.centisecond_ms)
        assert not r.was_adjusted


def test_event_0293_floors_both_and_preserves_frame_span():
    r = surgical_round_event(1346470.0, 1348222.0, FD)
    assert r.start.centisecond_ms == 1346470  # already on the 10ms grid
    assert r.end.centisecond_ms == 1348220  # 28.22, not 28.23
    exact_span = _time_to_frame(1348222.0, FD) - _time_to_frame(1346470.0, FD)
    out_span = _time_to_frame(float(r.end.rounded_ms), FD) - _time_to_frame(
        float(r.start.rounded_ms), FD
    )
    assert out_span == exact_span


# --- no regression for native ASS or genuinely off-frame values -------------


def test_native_ass_cs_aligned_unchanged():
    # ASS files only ever hold 10ms-aligned times; surgical must be a no-op.
    for ms in (17300, 76240, 1348220, 1348230):
        r = surgical_round_single(float(ms), FD)
        assert r.centisecond_ms == ms
        assert not r.was_adjusted


def test_mid_frame_value_floors_like_before():
    # A value comfortably inside a frame floors to its centisecond (unchanged).
    r = surgical_round_single(76263.0, FD)  # ~20ms into a frame
    assert r.centisecond_ms == 76260
    assert not r.was_adjusted


def test_genuine_drift_still_corrected():
    # A start a few ms past a real frame really does render on the NEXT frame;
    # floor would drop it a frame, so surgical must still fire (its real job).
    r = surgical_round_single(76246.0, FD)
    assert r.was_adjusted
    assert _time_to_frame(float(r.rounded_ms), FD) == _time_to_frame(76246.0, FD)


def test_whole_frame_shift_lands_on_intended_frame():
    # A frame-exact PGS start shifted by +10 WHOLE frames, applied as float ms,
    # lands ~0.08ms past the intended frame (1838). The on-frame tolerance
    # absorbs that slop so it stays on 1838 instead of slipping to 1839.
    shifted = 76243.0 + 10 * FD  # +417.083 ms
    r = surgical_round_single(shifted, FD)
    assert _real_frame_ms(1838, FD) == 76660
    assert _time_to_frame(float(r.rounded_ms), FD) == 1838


def test_invariant_output_always_renders_on_same_real_frame():
    # The core guarantee for every case: the rounded value renders on the same
    # real frame as the exact input.
    for ms in (1348222.0, 76243.0, 76263.0, 76246.0, 17300.0, 17309.0, 1346470.0):
        r = surgical_round_single(ms, FD)
        assert _time_to_frame(float(r.rounded_ms), FD) == _time_to_frame(ms, FD), ms
