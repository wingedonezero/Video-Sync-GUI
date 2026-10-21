# tests/test_stepping_edit_plan.py
"""Stepping EDL -> sample edits: the start rule, step rules, and parity with the
assembler it replaced (a copy of its loop is kept here as the reference)."""

from __future__ import annotations

import random

import numpy as np
import pytest

from vsg_core.audio_processing import EditPlan, Silence, Take
from vsg_core.correction.stepping import AudioSegment
from vsg_core.correction.stepping.edit_plan import edl_to_edits, render_edits

SR = 48000


def _seg(start_s: float, delay_raw: float) -> AudioSegment:
    return AudioSegment(
        start_s=start_s, end_s=start_s, delay_ms=round(delay_raw), delay_raw=delay_raw
    )


def _edits(edl: list[AudioSegment], offset_ms: float = 0.0):
    return edl_to_edits(edl, SR, offset_ms, lambda _m: None)


class TestStart:
    def test_small_positive_start_is_applied(self) -> None:
        # The old assembler skipped a positive start of <= 10 ms entirely.
        assert _edits([_seg(0, 5.0)]).ops == (Silence(240), Take(0))

    def test_negative_start_cuts_to_the_nearest_sample(self) -> None:
        edits = _edits([_seg(0, -10.834789)])
        assert edits.ops == (Take(520),)
        assert edits.start_samples == -520

    def test_offset_is_added_to_the_start_only(self) -> None:
        edits = _edits([_seg(0, 5.0), _seg(10, 1005.0)], offset_ms=100.5)
        assert edits.start_delay_ms == pytest.approx(105.5)
        assert edits.ops == (
            Silence(5064),
            Take(0, 480000),
            Silence(48000),
            Take(480000),
        )


class TestSteps:
    def test_insert_cut_and_ignored_step(self) -> None:
        edl = [_seg(0, 0.0), _seg(10, 1000.0), _seg(20, 500.0), _seg(30, 505.0)]
        edits = _edits(edl)
        assert edits.ops == (
            Take(0, 480000),
            Silence(48000),
            Take(480000, 960000),
            Take(984000, 1440000),
            Take(1440000),
        )
        assert [(s.at_s, s.step_ms) for s in edits.ignored_steps] == [(30, 5.0)]

    def test_small_decrease_is_still_cut(self) -> None:
        edits = _edits([_seg(0, 100.0), _seg(10, 95.0)])
        assert edits.ops[-1] == Take(480240)
        assert not edits.ignored_steps

    def test_cut_longer_than_its_segment_is_refused(self) -> None:
        with pytest.raises(ValueError, match="shorter than"):
            _edits([_seg(0, 0.0), _seg(10, -2000.0), _seg(11, -2000.0)])

    def test_edits_form_a_valid_plan(self) -> None:
        edl = [_seg(0, -50.0), _seg(5, 450.0), _seg(9, 100.0)]
        EditPlan(_edits(edl, offset_ms=3.25).ops)  # raises if not executable


def _old_assembly(pcm: np.ndarray, edl: list[AudioSegment]) -> np.ndarray:
    """The replaced assembler's sample logic (mono), for parity."""
    out: list[np.ndarray] = []
    current = 0.0
    duration_s = len(pcm) / SR
    for i, seg in enumerate(edl):
        gap = seg.delay_raw - current
        if abs(gap) > 10 and gap > 0:
            out.append(np.zeros(int(round((gap / 1000.0) * SR)), dtype=np.int32))
        current = seg.delay_raw
        seg_end = edl[i + 1].start_s if i + 1 < len(edl) else duration_s
        s = int(round(seg.start_s * SR))
        e = int(round(seg_end * SR))
        if gap < 0:
            s += int(round((abs(gap) / 1000.0) * SR))
        if e <= s:
            continue
        chunk = pcm[s : min(e, len(pcm))]
        if chunk.size:
            out.append(chunk)
    return np.concatenate(out)


def test_parity_with_the_old_assembler() -> None:
    rng = random.Random(20261021)
    pcm = np.arange(60 * SR, dtype=np.int32)  # every sample unique
    checked = 0
    for _ in range(300):
        n = rng.randint(1, 6)
        times = sorted(rng.uniform(1, 55) for _ in range(n - 1))
        delays = [rng.uniform(-900, 900) for _ in range(n)]
        if 0 <= delays[0] <= 10:
            continue  # the one case the new start rule fixes
        edl = [_seg(0.0, delays[0])] + [
            _seg(t, d) for t, d in zip(times, delays[1:], strict=True)
        ]
        try:
            ops = _edits(edl).ops
        except ValueError:
            continue  # a cut longer than its segment: refused now
        assert np.array_equal(render_edits(pcm, 1, ops), _old_assembly(pcm, edl))
        checked += 1
    assert checked > 200


def test_render_interleaved() -> None:
    pcm = np.arange(20, dtype=np.int32)  # 10 stereo frames
    out = render_edits(pcm, 2, (Silence(1), Take(2, 4), Take(8)))
    assert out.tolist() == [0, 0, 4, 5, 6, 7, 16, 17, 18, 19]
