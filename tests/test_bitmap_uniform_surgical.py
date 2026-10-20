"""Uniform surgical rounding for image subtitles (PGS / VobSub).

A bitmap track moves by ONE whole-millisecond delay; every segment of every
event shifts together, so palette updates stay in lockstep. The whole ms is
chosen like surgical rounding: rounded down or up so every event start/end
lands on its intended Source 1 frame. Measured on real tracks
(Tests/frame_table_validation/bitmap_shift_rounding.py): plain rounding left
up to 30% of a frame-matched track and up to 42% of a correlation-delayed track
a frame off; the chosen delay put 100% on frame.
"""

from __future__ import annotations

import math
import sys
from fractions import Fraction
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vsg_core.subtitles.frame_utils.frame_clock import FrameClock  # noqa: E402
from vsg_core.subtitles.frame_utils.frame_table import FrameTable  # noqa: E402
from vsg_core.subtitles.operations.bitmap_audit import (  # noqa: E402
    FrameMapping,
    choose_uniform_delay,
)
from vsg_core.subtitles.operations.pgs_timing import (  # noqa: E402
    apply_constant_shift as pgs_shift,
    walk_segments,
)
from vsg_core.subtitles.operations.vobsub_timing import (  # noqa: E402
    apply_constant_shift as vobsub_shift,
)

FILM = FrameClock(24000, 1001)
VIDEO = FrameClock(30000, 1001)
PERIOD = 1001 / 24
FIXTURE_PGS = PROJECT_ROOT / "tests" / "fixtures" / "pgs_small.sup"
FIXTURE_IDX = PROJECT_ROOT / "tests" / "fixtures" / "vobsub_small.idx"
FIXTURE_SUB = PROJECT_ROOT / "tests" / "fixtures" / "vobsub_small.sub"


def _disc(clock: FrameClock, n: int) -> FrameTable:
    """A Blu-ray remux's frame times: frame k at round(k * period) from 0."""
    return FrameTable.from_timestamps([float(clock.frame_ms(i)) for i in range(n)], "t")


def test_frame_matched_offset_that_rounds_up_is_fixed():
    """Separate disc, +618 frames (25775.75 ms): plain round (25776) lands ~30% late."""
    source, target = _disc(FILM, 4000), _disc(FILM, 4700)
    mapping = FrameMapping(source=source, target=target, frame_offset=618)
    events = [source.times_ms[k] for k in range(0, 3900, 7)]
    choice = choose_uniform_delay(events, 618 * PERIOD, mapping)
    assert choice.plain_round_ms == 25776 and choice.applied_ms == 25775
    assert choice.method == "floor" and choice.on_target == choice.total
    assert choice.plain_on_target < choice.total


def test_unverified_whole_frame_delay_also_rounds_down():
    table = _disc(FILM, 4000)
    mapping = FrameMapping(
        source=table, target=table, fps=Fraction(24000, 1001), whole_frame_delay=True
    )
    for n in range(1, 120):
        events = [table.times_ms[k] for k in range(0, 3800, 11)]
        choice = choose_uniform_delay(events, n * PERIOD, mapping)
        assert choice.on_target == choice.total, n
        assert choice.applied_ms == math.floor(round(n * PERIOD, 6)), n


def test_correlation_delays_land_on_the_exact_delay_frame():
    table = _disc(VIDEO, 6000)
    mapping = FrameMapping(source=table, target=table, fps=Fraction(30000, 1001))
    events = [float(t) for t in range(1000, 190000, 397)]  # whole-ms bitmap times
    for i in range(0, 4000):
        delay = round(-2000 + i * 1.0007, 4)
        choice = choose_uniform_delay(events, delay, mapping)
        assert choice.on_target == choice.total, delay


def test_float_noise_does_not_move_a_millisecond():
    table = _disc(FILM, 2000)
    mapping = FrameMapping(source=table, target=table)
    choice = choose_uniform_delay([1000.0, 5000.0], 1386.9999999999998, mapping)
    assert choice.method == "exact" and choice.applied_ms == 1387


def test_tie_break_follows_the_rule():
    table = _disc(FILM, 100)
    frame_based = FrameMapping(source=table, target=table, frame_offset=5)
    correlation = FrameMapping(source=table, target=table)
    assert choose_uniform_delay([], 208.54, frame_based).applied_ms == 208
    assert choose_uniform_delay([], 120.4, correlation).applied_ms == 121


def test_pgs_every_segment_moves_by_the_same_amount():
    """The palette-update guarantee: one delta for every segment, order unchanged."""
    data = FIXTURE_PGS.read_bytes()
    mapping = FrameMapping(
        source=FILM, target=FILM, fps=Fraction(24000, 1001), whole_frame_delay=True
    )
    out, res = pgs_shift(
        data, 5 * PERIOD, frame_mapping=mapping, frame_alignment_audit=True
    )
    assert res.delay_choice is not None
    assert res.applied_delay_ms == res.delay_choice.applied_ms == 208
    before, _ = walk_segments(data)
    after, _ = walk_segments(out)
    assert [s.seg_type for s in after] == [s.seg_type for s in before]
    deltas = {a.pts_ticks - b.pts_ticks for a, b in zip(after, before, strict=True)}
    assert deltas == {208 * 90}
    assert res.tier2 is not None
    assert res.tier2.starts_drifted == 0 and res.tier2.ends_drifted == 0


def test_pgs_without_a_grid_keeps_plain_rounding():
    data = FIXTURE_PGS.read_bytes()
    _, res = pgs_shift(data, 5 * PERIOD)
    assert res.applied_delay_ms == 209 and res.delay_choice is None


def test_vobsub_correlation_delay_is_chosen_surgically():
    text = FIXTURE_IDX.read_text(encoding="latin-1")
    sub = FIXTURE_SUB.read_bytes()
    mapping = FrameMapping(source=VIDEO, target=VIDEO, fps=Fraction(30000, 1001))
    for i in range(200):
        delay = round(-5.674 + i * 0.731, 3)
        _, res = vobsub_shift(
            text, sub, delay, frame_mapping=mapping, frame_alignment_audit=True
        )
        assert res.delay_choice is not None
        assert res.delay_choice.on_target == res.delay_choice.total, delay
        assert res.tier2 is not None
        assert res.tier2.starts_drifted == 0 and res.tier2.ends_drifted == 0, delay
