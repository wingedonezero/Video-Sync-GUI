"""Whole-frame shifts and bitmap audits on two real frame timelines (step 2).

Frame-locked subtitles (PGS / OCR) timed on Source N move to the real time of
the Source 1 frame showing the same picture: source frame k -> target frame
k + R, where R is the frame match verified on both timelines. Cases mirror
measured files: Blu-ray remuxes start at 0 ms; the Recca SSP-Corp encode's
first frame is at 83 ms.
"""

from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from vsg_core.subtitles import frame_grids as fg
from vsg_core.subtitles.frame_utils.frame_clock import FrameClock
from vsg_core.subtitles.frame_utils.frame_table import FrameShift, FrameTable
from vsg_core.subtitles.operations.bitmap_audit import FrameMapping
from vsg_core.subtitles.sync_utils import build_frame_shift

if TYPE_CHECKING:
    from vsg_core.orchestrator.steps.context import Context

FILM = FrameClock(24000, 1001)


def _grid(clock: FrameClock, n: int, start_ms: float = 0.0) -> FrameTable:
    """Container timestamps of a clean CFR file whose first frame is at start_ms."""
    return FrameTable.from_timestamps(
        [start_ms + clock.frame_ms(i) for i in range(n)], origin="test"
    )


def _details(index_frames: int, pts_delta_frames: int, video_offset_ms: float) -> dict:
    return {
        "reason": "sliding-matched",
        "index_consensus_frames": index_frames,
        "pts_delta_frames": pts_delta_frames,
        "video_offset_ms": video_offset_ms,
    }


def _no_log(_msg: str) -> None:
    pass


# --- identical grids: same answer as the old formula snap ---------------------


def test_identical_grids_snap_like_the_formula():
    table = _grid(FILM, 5000)
    shift = build_frame_shift(
        lambda: table, table, _details(24, 0, 24 * 1001 / 24), 0.0, _no_log
    )
    assert shift is not None and shift.frames == 24
    for k in (0, 100, 1828, 4000):
        on_frame = table.times_ms[k]
        assert shift.shifted_ms(on_frame, 1001.0) == FILM.frame_ms(k + 24)


# --- source starting at 83 ms (Recca SSP-Corp) ---------------------------------


def test_start_offset_source_snaps_onto_the_real_target_frame():
    source = _grid(FILM, 3000, start_ms=83.0)  # 83 ms = ~2 frames late
    target = _grid(FILM, 3000)
    # Matcher: index offset +10 after removing the 2-frame PTS-origin difference;
    # wall-clock offset = (10 frames) - 83 ms rounded to whole frames = +8 frames.
    details = _details(10 - 2, 2, 8 * 1001 / 24)
    shift = build_frame_shift(lambda: source, target, details, 0.0, _no_log)
    assert shift is not None and shift.frames == 10
    flat = 8 * 1001 / 24
    for k in range(0, 2900, 37):
        snapped = shift.shifted_ms(source.times_ms[k], flat)
        assert snapped == target.times_ms[k + 10]
        # The old flat delay lands just BEFORE that frame for most k, so a
        # floor to centiseconds would show the sub one frame early.
        assert source.times_ms[k] + flat < snapped


def test_mid_frame_and_out_of_range_values_take_the_flat_delay():
    table = _grid(FILM, 100)
    shift = FrameShift(source=table, target=table, frames=5)
    assert shift.shifted_ms(table.times_ms[3] + 7, 200.0) == table.times_ms[3] + 207
    last = table.times_ms[99]
    assert shift.shifted_ms(last, 200.0) == last + 200.0  # k+5 past the end


# --- gates --------------------------------------------------------------------


def test_gates_that_skip_the_source_read():
    table = _grid(FILM, 500)
    reads: list[int] = []

    def load() -> FrameTable:
        reads.append(1)
        return table

    d = _details(3, 0, 3 * 1001 / 24)
    assert build_frame_shift(load, table, d, 0.0, _no_log, fallback=True) is None
    assert build_frame_shift(load, table, d, 12.5, _no_log) is None  # global shift
    assert build_frame_shift(load, FILM, d, 0.0, _no_log) is None  # no real Source 1
    assert (
        build_frame_shift(load, table, {"reason": "fallback-x"}, 0.0, _no_log) is None
    )
    assert reads == []  # the source video was never indexed for these


def test_hole_in_the_source_refuses_the_snap():
    times = [FILM.frame_ms(i) for i in range(3000)]
    times = times[:1500] + [t + 1001 for t in times[1500:]]  # 24 missing frames
    source = FrameTable.from_timestamps(times, origin="test")
    target = _grid(FILM, 3100)
    lines: list[str] = []
    shift = build_frame_shift(
        lambda: source, target, _details(4, 0, 4 * 1001 / 24), 0.0, lines.append
    )
    assert shift is None
    assert any("drift" in line for line in lines)


def test_rate_mismatch_refuses_the_snap():
    # 24/1 vs 24000/1001: the old fps gate (ratio 1.001 < 1.01) let this through.
    source = _grid(FrameClock(24, 1), 30000)
    target = _grid(FILM, 30000)
    shift = build_frame_shift(lambda: source, target, _details(0, 0, 0.0), 0.0, _no_log)
    assert shift is None


def test_offset_disagreeing_with_measured_wall_clock_is_refused():
    table = _grid(FILM, 2000)
    # Index offset says +3 frames (125 ms) but the matcher measured +1001 ms.
    shift = build_frame_shift(
        lambda: table, table, _details(3, 0, 1001.0), 0.0, _no_log
    )
    assert shift is None


# --- bitmap audit mapping ------------------------------------------------------


def test_mapping_matches_the_old_formula_audit_on_aligned_grids():
    """Old Tier 2: F_target = F_src + round(applied_ms * fps). Same on one grid."""
    table = _grid(FILM, 5000)
    mapping = FrameMapping(source=table, target=table, fps=Fraction(24000, 1001))
    for applied in range(-90000, 90001, 7):  # includes near-half-frame delays
        expected_shift = round(Fraction(applied * 24000, 1000 * 1001))
        assert mapping.nominal_shift(applied) == expected_shift
        for ms in (8342.0, 51479.0, 125125.0):
            f = mapping.source_frame(ms)
            assert f == FILM.frame_of(ms)
            assert mapping.expected_target_frame(f, applied) == f + expected_shift


def test_mapping_with_offset_start_uses_the_real_times():
    source = _grid(FILM, 3000, start_ms=83.0)
    target = _grid(FILM, 3000)
    matched = FrameMapping(source=source, target=target, frame_offset=10)
    applied = round(8 * 1001 / 24)  # the delay the shifter writes
    for k in (0, 500, 2500):
        f = matched.source_frame(source.times_ms[k])
        assert f == k  # read on the source's own timeline
        assert matched.expected_target_frame(f, applied) == k + 10


# --- notes are recorded once, whichever step reads Source 1 first --------------


def test_source1_notes_once_even_if_bitmap_step_read_it_first(monkeypatch):
    table = _grid(FILM, 300, start_ms=83.0)
    monkeypatch.setattr(fg, "build_frame_table", lambda path, temp_dir, log: table)
    ctx = SimpleNamespace(
        sources={"Source 1": "/s1.mkv", "Source 2": "/s2.mkv"},
        frame_tables={},
        frame_grid_notes=[],
        frame_grid_checked=set(),
        temp_dir=None,
    )
    c = cast("Context", ctx)
    fg.frame_table_for(c, "/s1.mkv", _no_log)  # e.g. read as a bitmap source
    fg.source1_frame_table(c, fg.Path("/s1.mkv"), FILM, _no_log)
    fg.source1_frame_table(c, fg.Path("/s1.mkv"), FILM, _no_log)
    messages = [n.message for n in ctx.frame_grid_notes]
    assert sum("first video frame is at 83 ms" in m for m in messages) == 1
    assert sum("disagrees" in m for m in messages) == 1
