"""Tests for the real-timestamp frame grid (FrameTable) and how rounding uses it.

The timestamp values below are measured from real MKVs, not modelled:

- Magikano US DVD (MPEG-2, 29.97): the OCR'd "Curse" sign. Its VobSub starts at
  1259.759 ms, one millisecond after the frame at 1259.758, so it first shows
  on the next frame (1259.792). Floor to centiseconds (1259.750) crossed back
  onto 1259.758 - one frame early - because DVDs had no frame grid.
- ANGEL_S5D1 title_t01 (MPEG-2 soft telecine): 33/50 ms frames and two holes
  (217 ms and 11,779 ms) carried into the MKV via a timestamps file.
- Recca SSP-Corp encode (H.264): first frame at 83 ms, not 0.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from vsg_core.subtitles import frame_grids as fg
from vsg_core.subtitles.data import SubtitleData, SubtitleEvent, SubtitleStyle
from vsg_core.subtitles.frame_utils.frame_audit import (
    run_frame_audit,
    write_audit_report,
)
from vsg_core.subtitles.frame_utils.frame_clock import FrameClock
from vsg_core.subtitles.frame_utils.frame_table import (
    FrameTable,
    check_timeline,
    parse_timecodes_v2,
)
from vsg_core.subtitles.frame_utils.surgical_rounding import (
    surgical_round_event,
    surgical_round_single,
)

if TYPE_CHECKING:
    from vsg_core.orchestrator.steps.context import Context
    from vsg_core.subtitles.frame_utils.frame_table import FrameGrid

# Real frame times around the "Curse" sign (Magikano DVD, mkvextract).
CURSE_FRAMES = [1259692.0, 1259725.0, 1259758.0, 1259792.0, 1259825.0, 1259859.0]
CURSE_START = 1259759.0  # VobSub start = OCR start


def _table(times: list[float], origin: str = "test") -> FrameTable:
    return FrameTable.from_timestamps(times, origin=origin)


def _formula_table(clock: FrameClock, n: int) -> FrameTable:
    """What a clean Blu-ray remux's container stores: exactly the formula."""
    return _table([float(clock.frame_ms(i)) for i in range(n)])


def _soft_telecine(cycles: int, start: float = 0.0) -> list[float]:
    """MPEG-2 soft telecine as mkvmerge stores it: 4 film frames per 166.8 ms."""
    times, t = [], start
    for _ in range(cycles):
        for dur in (50.05, 33.37, 50.05, 33.37):
            times.append(round(t))
            t += dur
    return times


# --- construction --------------------------------------------------------------


def test_from_timestamps_sorts_presentation_order():
    # B-frame streams store frames in decode order; the table must not care.
    table = _table([0.0, 83.0, 42.0, 125.0])
    assert table.times_ms == (0.0, 42.0, 83.0, 125.0)


def test_from_timestamps_rejects_duplicates_and_tiny_input():
    with pytest.raises(ValueError, match="duplicate"):
        _table([0.0, 42.0, 42.0])
    with pytest.raises(ValueError, match="at least 2"):
        _table([0.0])


def test_parse_timecodes_v2_ffms2_format():
    text = "# timecode format v2\n0.00\n50.00\n\n83.00\n"
    assert parse_timecodes_v2(text) == [0.0, 50.0, 83.0]
    with pytest.raises(ValueError):
        parse_timecodes_v2("0.00\n50.00\n")


# --- lookups -------------------------------------------------------------------


def test_frame_of_is_first_frame_at_or_after():
    table = _table(CURSE_FRAMES)
    assert table.frame_of(1259758.0) == 2  # exactly on a frame
    assert table.frame_of(1259758.5) == 3
    assert table.frame_of(CURSE_START) == 3  # the frame the VobSub shows on
    assert table.frame_of(1259750.0) == 2  # floored ASS start: one frame early


def test_times_outside_the_table():
    table = _table([83.0, 125.0, 167.0])  # Recca-style start offset
    assert table.frame_of(0.0) == 0  # everything up to the first frame shows on it
    assert table.frame_of(83.0) == 0
    assert table.frame_of(84.0) == 1
    assert table.frame_of(500.0) == 3  # past the end: virtual frame after last
    assert table.frame_ms(3) == 209.0  # extended with the edge frame period
    assert table.frame_ms(-1) == 41.0


def test_table_matches_formula_on_a_clean_grid():
    """On a clean Blu-ray remux the table and the formula give identical answers."""
    clock = FrameClock(24000, 1001)
    table = _formula_table(clock, 5000)
    for t in range(0, 208000, 7):
        assert table.frame_of(t + 0.25) == clock.frame_of(t + 0.25)
        a = surgical_round_single(t + 0.25, table)
        b = surgical_round_single(t + 0.25, clock)
        assert (a.centisecond_ms, a.method) == (b.centisecond_ms, b.method)


# --- rounding with real timestamps --------------------------------------------


def test_curse_sign_rounds_onto_the_vobsub_frame():
    table = _table(CURSE_FRAMES)
    result = surgical_round_single(CURSE_START, table)
    assert result.method == "ceil"
    assert result.centisecond_ms == 1259760
    assert table.frame_of(result.centisecond_ms) == table.frame_of(CURSE_START)


def test_soft_telecine_rounding_stays_on_frame():
    table = _table(_soft_telecine(200))
    for t in range(0, 33000, 3):
        exact = t + 0.6
        r = surgical_round_single(exact, table)
        assert table.frame_of(r.centisecond_ms) == table.frame_of(exact)


def test_rounding_twice_changes_nothing():
    """Re-running a job on already-saved subs must not move them."""
    table = _table(CURSE_FRAMES)
    first = surgical_round_event(CURSE_START, 1261503.0, table)
    second = surgical_round_event(
        float(first.start.centisecond_ms), float(first.end.centisecond_ms), table
    )
    assert second.start.centisecond_ms == first.start.centisecond_ms
    assert second.end.centisecond_ms == first.end.centisecond_ms
    assert not second.start.was_adjusted and not second.end.was_adjusted


def test_ass_writer_uses_the_table(tmp_path: Path):
    data = SubtitleData()
    data.styles = OrderedDict([("Default", SubtitleStyle.default())])
    data.events = [SubtitleEvent(start_ms=CURSE_START, end_ms=1259859.0, text="Curse")]
    out = tmp_path / "curse.ass"
    data.save(out, rounding="floor", clock=_table(CURSE_FRAMES))
    assert "0:20:59.76" in out.read_text(encoding="utf-8")
    data.save(out, rounding="floor", clock=None)  # old DVD behaviour
    assert "0:20:59.75" in out.read_text(encoding="utf-8")


def test_frame_audit_and_report_with_a_table(tmp_path: Path):
    data = SubtitleData()
    data.events = [SubtitleEvent(start_ms=CURSE_START, end_ms=1259859.0, text="Curse")]
    table = _table(CURSE_FRAMES)
    result = run_frame_audit(data, table, "floor", 0.0, "curse")
    assert result.start_early == 1
    assert result.predicted_corrections >= 1
    assert result.grid is table
    report = write_audit_report(result, tmp_path).read_text(encoding="utf-8")
    assert "real timestamps" in report
    assert "surgical(1259760ms)" in report


# --- timeline check -----------------------------------------------------------


def test_timeline_finds_the_angel_holes():
    times = _soft_telecine(400)
    hole_at = len(times) // 2
    times = times[:hole_at] + [t + 217 for t in times[hole_at:]]
    times = times[: hole_at + 10] + [t + 11779 for t in times[hole_at + 10 :]]
    check = check_timeline(_table(times))
    assert [g.frame for g in check.gaps] == [hole_at, hole_at + 10]
    first, second = check.gaps
    assert round(first.jump_ms) - 217 in (33, 50)  # hole + the frame period it hit
    assert round(second.jump_ms) - 11779 in (33, 50)
    assert check.regular_max_ms in (50.0, 51.0)  # 50.05 ms frames round both ways


def test_timeline_soft_telecine_is_not_a_gap():
    assert check_timeline(_table(_soft_telecine(400))).gaps == ()


def test_timeline_catches_one_dropped_frame():
    clock = FrameClock(24000, 1001)
    times = [float(clock.frame_ms(i)) for i in range(3000) if i != 1500]
    check = check_timeline(_table(times))
    assert len(check.gaps) == 1 and check.gaps[0].frame == 1500


def test_timeline_reports_start_offset():
    times = [83.0 + 1001 * i / 24 for i in range(500)]
    assert check_timeline(_table(times)).first_frame_ms == 83.0


# --- which jobs use the table --------------------------------------------------


class _Runner:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def _log_message(self, msg: str) -> None:
        self.lines.append(msg)


def _resolve(
    ctx: SimpleNamespace, target: str, clock: FrameClock | None, runner: _Runner
) -> FrameGrid | None:
    # Minimal stand-in: the gate only touches sources/frame_tables/notes/temp_dir.
    return fg.resolve_target_grid(
        cast("Context", ctx), Path(target), clock, runner._log_message
    )


def _ctx(n_sources: int) -> SimpleNamespace:
    return SimpleNamespace(
        sources={f"Source {i + 1}": f"/s{i + 1}.mkv" for i in range(n_sources)},
        frame_tables={},
        frame_grid_notes=[],
        frame_grid_checked=set(),
        temp_dir=None,
    )


@pytest.fixture
def fake_build(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    result: dict[str, FrameTable | None] = {"table": _table(CURSE_FRAMES)}

    def build(path: str, temp_dir: Path | None, log) -> FrameTable | None:
        calls.append(path)
        return result["table"]

    monkeypatch.setattr(fg, "build_frame_table", build)
    return SimpleNamespace(calls=calls, result=result)


def test_multi_source_dvd_target_keeps_plain_rounding(fake_build):
    grid = _resolve(_ctx(2), "/s1.mkv", None, _Runner())
    assert grid is None
    assert fake_build.calls == []  # never even reads timestamps


def test_single_source_dvd_target_uses_the_table(fake_build):
    ctx = _ctx(1)
    grid = _resolve(ctx, "/s1.mkv", None, _Runner())
    assert isinstance(grid, FrameTable)
    assert any("single-source" in n.message for n in ctx.frame_grid_notes)


def test_progressive_target_uses_the_table_and_is_read_once(fake_build):
    clock = FrameClock(24000, 1001)
    fake_build.result["table"] = _formula_table(clock, 2000)
    ctx, runner = _ctx(3), _Runner()
    for _ in range(3):  # three subtitle tracks
        grid = _resolve(ctx, "/s1.mkv", clock, runner)
        assert isinstance(grid, FrameTable)
    assert fake_build.calls == ["/s1.mkv"]
    [note] = ctx.frame_grid_notes
    assert note.severity == "info" and "matches the real timestamps" in note.message


def test_formula_disagreement_is_a_warning(fake_build):
    clock = FrameClock(30000, 1001)  # app's guess for a 23.976 file labelled 2997/100
    fake_build.result["table"] = _formula_table(FrameClock(24000, 1001), 2000)
    ctx = _ctx(2)
    _resolve(ctx, "/s1.mkv", clock, _Runner())
    [note] = ctx.frame_grid_notes
    assert note.severity == "warning" and "disagrees" in note.message


def test_unreadable_timestamps_fall_back_to_old_behaviour(fake_build):
    fake_build.result["table"] = None
    clock = FrameClock(24000, 1001)
    ctx = _ctx(2)
    assert _resolve(ctx, "/s1.mkv", clock, _Runner()) is clock
    [note] = ctx.frame_grid_notes  # never expected for progressive: final-audit warning
    assert note.severity == "warning" and "fell back to 24000/1001" in note.message
    assert _resolve(_ctx(1), "/x.mkv", None, _Runner()) is None


def test_frame_snapped_duration_change_is_not_counted():
    """Dungeon 24: a sign ending on Source 3's frame 277 (11560) is snapped to
    the BD's frame 277 (11553); centisecond storage then shortens it by 3 ms on
    the same frames. A plain off-centisecond time still counts."""
    film = FrameClock(24000, 1001)
    table = _formula_table(film, 400)
    assert table.times_ms[277] == 11553.0
    data = SubtitleData()
    data.events = [
        SubtitleEvent(start_ms=11150.0, end_ms=11553.0, text="snapped end"),
        SubtitleEvent(start_ms=11150.0, end_ms=11552.0, text="not a frame time"),
    ]
    result = run_frame_audit(data, table, "floor", 0.0, "snap")
    assert result.start_early + result.start_late + result.end_early == 0
    assert result.duration_delta_frame_time == 1
    assert result.duration_delta_10ms == 1
