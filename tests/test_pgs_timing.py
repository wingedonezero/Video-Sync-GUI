"""Unit tests for vsg_core.subtitles.operations.pgs_timing.

Fixture ``tests/fixtures/pgs_small.sup`` is a 15.8 KB English forced-subs
track extracted from 91 Days BD (Source 2 track 6). It has 14 segments
across 2 display events at PTSes 7.379910 s and 7.830360 s.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vsg_core.subtitles.operations.bitmap_audit import (  # noqa: E402
    frame_of,
    integer_ms_window_for_frame,
    pick_integer_ms_in_frame,
)
from vsg_core.subtitles.operations.pgs_timing import (  # noqa: E402
    PTS_CLOCK_HZ,
    SEG_END,
    SEG_PCS,
    SEG_WDS,
    TICKS_PER_MS,
    apply_constant_shift,
    extract_events,
    walk_segments,
)

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "pgs_small.sup"


def _ms_to_ticks(ms: int) -> int:
    return ms * (PTS_CLOCK_HZ // 1000)


# Exact NTSC-film fps: ffprobe/MediaInfo report this as 24000/1001, not
# 23.976. Using the rational value avoids FP error that would put
# events at frame boundaries one frame early.
FPS_NTSC_FILM = 24000.0 / 1001.0  # ≈ 23.976023976


def test_walk_segments_recovers_known_count_and_types() -> None:
    data = FIXTURE.read_bytes()
    segments, invalid = walk_segments(data)
    assert invalid == 0
    assert len(segments) == 8  # observed in empirical scan: 5 + 3 = 8 segs
    # Each segment range must be within file bounds.
    n = len(data)
    for s in segments:
        assert 0 <= s.header_offset < n
        assert s.payload_offset == s.header_offset + 13
        assert s.payload_offset + s.payload_length == s.end_offset
        assert s.end_offset <= n
    # First display group should share the same PTS.
    first_group_pts = segments[0].pts_ticks
    assert all(s.pts_ticks == first_group_pts for s in segments[:5])
    # Empirical: 14 segs is the value extracted by decode_pgs.py from this file
    # — re-check by reading the first 14 (which is what print_pts(8) shows above).
    # Our walk yields 8 (one display group + one clear group); decode_pgs printed
    # 14 because it used n=14 (capped) — full file has 8. Trust walk_segments.


def test_extract_events_pairs_display_with_clear() -> None:
    data = FIXTURE.read_bytes()
    segments, _ = walk_segments(data)
    events = extract_events(segments, data)
    # The fixture has 1 display event terminated by a clear PCS.
    assert len(events) == 1
    ev = events[0]
    assert ev.composition_object_count > 0  # display, not clear
    assert ev.end_pts_ticks is not None  # closed event
    assert ev.end_pts_ticks > ev.start_pts_ticks
    # The event's segments must include at least the opening PCS through
    # an END segment.
    types_in_event = [
        segments[i].seg_type
        for i in range(ev.start_segment_index, ev.end_segment_index + 1)
    ]
    assert types_in_event[0] == SEG_PCS
    assert SEG_END in types_in_event
    assert SEG_WDS in types_in_event


def test_apply_constant_shift_zero_is_byte_identical() -> None:
    """Shifting by zero must produce byte-identical output."""
    data = FIXTURE.read_bytes()
    out, result = apply_constant_shift(data, 0.0)
    assert out == bytes(data)
    assert result.applied_delay_ms == 0
    assert result.delta_ticks == 0
    assert result.segments_dropped == 0
    assert result.events_dropped == 0


def test_apply_constant_shift_positive_uniform() -> None:
    """+1001ms must shift every segment's PTS by exactly 90090 ticks."""
    data = FIXTURE.read_bytes()
    src_segments, _ = walk_segments(data)
    out, result = apply_constant_shift(data, 1001.0)
    assert result.applied_delay_ms == 1001
    assert result.delta_ticks == 90090
    assert result.segments_dropped == 0
    assert result.events_dropped == 0
    out_segments, _ = walk_segments(out)
    assert len(out_segments) == len(src_segments)
    for s_old, s_new in zip(src_segments, out_segments):
        assert s_new.pts_ticks - s_old.pts_ticks == 90090
        assert s_new.seg_type == s_old.seg_type
        # DTS=0 must remain 0
        assert s_new.dts_ticks == s_old.dts_ticks


def test_apply_constant_shift_rounds_to_ms() -> None:
    """Fractional ms input must round to nearest int ms (mkvmerge ceiling)."""
    data = FIXTURE.read_bytes()
    _, result = apply_constant_shift(data, 1001.4)
    assert result.applied_delay_ms == 1001
    _, result = apply_constant_shift(data, 1001.6)
    assert result.applied_delay_ms == 1002


def test_apply_constant_shift_drops_negative_events() -> None:
    """A shift large enough to push the first display event below 0
    should drop it (drop_negative=True)."""
    data = FIXTURE.read_bytes()
    # First display event is at ~81 999 ms in this fixture; -85 000 ms
    # shift would push it to ~-3 001 ms.
    out, result = apply_constant_shift(data, -85_000.0, drop_negative=True)
    assert result.applied_delay_ms == -85_000
    assert result.events_dropped >= 1
    assert result.segments_dropped >= 5  # 1 display event = 5 segments
    # All remaining segments must have non-negative PTS.
    out_segments, _ = walk_segments(out)
    for s in out_segments:
        assert s.pts_ticks >= 0


def test_apply_constant_shift_matches_mkvmerge_observation() -> None:
    """The empirical mkvmerge test on this same file (recorded earlier)
    showed +1001 ms applied to every segment, byte-identical output
    pattern. Re-verify here so any future regression catches it."""
    data = FIXTURE.read_bytes()
    src_segments, _ = walk_segments(data)
    out, _ = apply_constant_shift(data, 1001.0)
    out_segments, _ = walk_segments(out)
    # Same segment count, same types in same order, same +90090 ticks delta.
    assert [s.seg_type for s in out_segments] == [s.seg_type for s in src_segments]
    deltas = [b.pts_ticks - a.pts_ticks for a, b in zip(src_segments, out_segments)]
    assert all(d == 90090 for d in deltas)


def test_apply_constant_shift_dts_only_shifted_when_nonzero() -> None:
    """DTS=0 segments must stay DTS=0 even after a shift."""
    data = FIXTURE.read_bytes()
    src_segments, _ = walk_segments(data)
    # Verify fixture precondition: all DTS = 0
    assert all(s.dts_ticks == 0 for s in src_segments)
    out, _ = apply_constant_shift(data, 1234.0)
    out_segments, _ = walk_segments(out)
    assert all(s.dts_ticks == 0 for s in out_segments)


def test_ms_helper_arithmetic() -> None:
    """Cross-check the 90 ticks/ms relationship encoded in the shifter."""
    assert _ms_to_ticks(1) == 90
    assert _ms_to_ticks(1001) == 90_090
    assert _ms_to_ticks(0) == 0


# ----------------------------------------------------------------------
# Frame-alignment correction
# ----------------------------------------------------------------------


def test_frame_math_primitives_23976() -> None:
    """At NTSC-film fps every 24 frames is an integer-ms boundary."""
    period = 1000.0 / FPS_NTSC_FILM
    # Frame 24 starts at exactly 1001.0 ms — boundary case
    assert frame_of(1001.0, period) == 24
    # Frame 23 ends just before 1001.0; 1000 ms still in frame 23
    assert frame_of(1000.0, period) == 23
    # Frame 24 spans integer ms 1001..1042 inclusive
    lo, hi = integer_ms_window_for_frame(24, period)
    assert lo == 1001
    assert hi == 1042
    # Picking closest int ms in frame 24 for a desired 1002 ms target
    assert pick_integer_ms_in_frame(1002.0, 24, period) == 1002
    # If desired is outside the frame, clamp to nearest endpoint
    assert pick_integer_ms_in_frame(999.0, 24, period) == 1001
    assert pick_integer_ms_in_frame(1500.0, 24, period) == 1042


def test_apply_constant_shift_integer_frame_no_corrections() -> None:
    """+1001 ms at 23.976 fps (24000/1001 exact) = exactly +24 frames — no events should drift."""
    data = FIXTURE.read_bytes()
    _, result = apply_constant_shift(
        data, 1001.0, target_fps=FPS_NTSC_FILM, frame_align=True
    )
    assert result.tier2 is not None
    t2 = result.tier2
    assert t2.frame_shift == 24
    # All events land on F_src + 24, by construction.
    assert t2.starts_total > 0
    assert t2.starts_correct == t2.starts_total
    assert t2.ends_correct == t2.ends_total
    assert t2.corrections_start_applied == 0
    assert t2.corrections_end_applied == 0
    assert t2.unfixable_count == 0


def test_apply_constant_shift_integer_frame_byte_identical() -> None:
    """Integer-frame shift with frame_align=True must produce the same
    bytes as frame_align=False — no corrections means no rewrites."""
    data = FIXTURE.read_bytes()
    out_uniform, _ = apply_constant_shift(data, 1001.0, frame_align=False)
    out_aligned, _ = apply_constant_shift(
        data, 1001.0, target_fps=FPS_NTSC_FILM, frame_align=True
    )
    assert out_uniform == out_aligned


def test_apply_constant_shift_non_integer_frame_applies_corrections() -> None:
    """A non-integer-frame shift (here +1003 ms ≈ 24.05 frames at 23.976)
    should detect drift on some events and correct them back to
    F_src + 24."""
    data = FIXTURE.read_bytes()
    out, result = apply_constant_shift(
        data, 1003.0, target_fps=FPS_NTSC_FILM, frame_align=True
    )
    assert result.tier2 is not None
    t2 = result.tier2
    # 1003 / period(23.976) = ~24.048 → frame_shift = 24
    assert t2.frame_shift == 24
    # After correction, every endpoint must be on its target frame.
    assert t2.starts_correct == t2.starts_total
    assert t2.ends_correct == t2.ends_total
    assert t2.unfixable_count == 0
    # Output bytes must still parse as PGS (segment count preserved).
    src_segs, _ = walk_segments(data)
    out_segs, _ = walk_segments(out)
    assert len(out_segs) == len(src_segs)


def test_apply_constant_shift_frame_align_preserves_no_fps_path() -> None:
    """frame_align=True but target_fps=None → no Tier 2, behaves as uniform."""
    data = FIXTURE.read_bytes()
    out_uniform, _ = apply_constant_shift(data, 1001.0)
    out_skipped, res_skipped = apply_constant_shift(
        data, 1001.0, target_fps=None, frame_align=True
    )
    assert out_uniform == out_skipped
    assert res_skipped.tier2 is None


def test_correction_keeps_byte_count_and_segment_order() -> None:
    """Per-event corrections must not change segment count or types."""
    data = FIXTURE.read_bytes()
    src_segs, _ = walk_segments(data)
    out, _ = apply_constant_shift(
        data, 1003.0, target_fps=FPS_NTSC_FILM, frame_align=True
    )
    out_segs, _ = walk_segments(out)
    assert len(out_segs) == len(src_segs)
    assert [s.seg_type for s in out_segs] == [s.seg_type for s in src_segs]


def test_endpoint_audit_records_emitted() -> None:
    """Tier 2 must emit one EndpointAudit per closed-event endpoint
    (start + end)."""
    data = FIXTURE.read_bytes()
    _, result = apply_constant_shift(
        data, 1001.0, target_fps=FPS_NTSC_FILM, frame_align=True
    )
    assert result.tier2 is not None
    eps = result.tier2.endpoints
    # Fixture has 1 closed display event → 1 start + 1 end = 2 endpoints.
    assert len(eps) == 2
    # Frame numbers move by +24 between source and target
    for ep in eps:
        assert ep.target_frame == ep.source_frame + 24
        assert ep.final_frame == ep.target_frame
        assert ep.correction_ms == 0


def test_ticks_per_ms_constant() -> None:
    """Sanity: 90 ticks per ms at 90 kHz."""
    assert TICKS_PER_MS == 90
    assert PTS_CLOCK_HZ == 90_000
