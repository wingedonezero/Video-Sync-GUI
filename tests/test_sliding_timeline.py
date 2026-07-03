# tests/test_sliding_timeline.py
"""Timeline-integrity probe for the sliding-window matcher.

Models the real-world failure this guards against (Full Dive, 2026-07):
a WEB encode dropped one frame slot right after frame 0 but kept the
remaining timestamps, so frame index n sits at wall-clock slot n+1. The
matcher's index-space answer (+24f) then disagrees with the wall-clock
truth (+23f) at every position, and index * frame_duration silently
overshoots by one frame.
"""

from __future__ import annotations

from vsg_core.subtitles.sync_mode_plugins.video_verified.sliding_core import (
    probe_timeline_integrity,
)

FPS = 24000 / 1001
FRAME_DUR_S = 1001 / 24000


def clean_pts(n: int) -> float:
    return n * FRAME_DUR_S


def gap_after_frame0_pts(n: int) -> float:
    """Full Dive shape: one slot missing after frame 0."""
    return n * FRAME_DUR_S if n == 0 else (n + 1) * FRAME_DUR_S


class TestCleanTimeline:
    def test_clean_cfr_is_ok(self):
        probe = probe_timeline_integrity(34094, FPS, 0.0, clean_pts)
        assert probe.ok is True
        assert probe.missing_slots == 0
        assert probe.first_divergence_index is None
        assert not probe.has_gaps

    def test_nonzero_origin_is_still_ok(self):
        # A constant pts origin (handled by the origin fix) is not a gap.
        probe = probe_timeline_integrity(34094, FPS, 3.0, lambda n: 3.0 + clean_pts(n))
        assert probe.ok is True
        assert probe.missing_slots == 0

    def test_tiny_clip(self):
        assert probe_timeline_integrity(1, FPS, 0.0, clean_pts).ok is True
        assert probe_timeline_integrity(0, FPS, 0.0, clean_pts).ok is True


class TestGapDetection:
    def test_fulldive_gap_after_frame0(self):
        probe = probe_timeline_integrity(34046, FPS, 0.0, gap_after_frame0_pts)
        assert probe.ok is False
        assert probe.missing_slots == 1
        assert probe.first_divergence_index == 1
        assert probe.has_gaps

    def test_midfile_gap(self):
        def pts(n: int) -> float:
            return n * FRAME_DUR_S if n < 17000 else (n + 1) * FRAME_DUR_S

        probe = probe_timeline_integrity(34046, FPS, 0.0, pts)
        assert probe.ok is False
        assert probe.missing_slots == 1
        assert probe.first_divergence_index == 17000

    def test_multiple_gaps_counts_total(self):
        def pts(n: int) -> float:
            slots = n
            if n >= 100:
                slots += 1
            if n >= 20000:
                slots += 2
            return slots * FRAME_DUR_S

        probe = probe_timeline_integrity(34046, FPS, 0.0, pts)
        assert probe.ok is False
        assert probe.missing_slots == 3
        assert probe.first_divergence_index == 100

    def test_extra_frames_negative_slots(self):
        # Duplicated timestamp region: more frames than wall-clock slots.
        def pts(n: int) -> float:
            return (n if n < 500 else n - 1) * FRAME_DUR_S

        probe = probe_timeline_integrity(34046, FPS, 0.0, pts)
        assert probe.ok is False
        assert probe.missing_slots == -1
        assert probe.first_divergence_index == 500


class TestUnavailableTimestamps:
    def test_no_pts_returns_unknown(self):
        probe = probe_timeline_integrity(34046, FPS, 0.0, lambda n: None)
        assert probe.ok is None
        assert not probe.has_gaps  # unknown is not a positive gap claim

    def test_partial_pts_still_reports_gap_total(self):
        # Last frame readable, middles not: binary search degrades
        # gracefully but the total missing count is still correct.
        def pts(n: int) -> float | None:
            if n in (0, 34045):
                return gap_after_frame0_pts(n)
            return None

        probe = probe_timeline_integrity(34046, FPS, 0.0, pts)
        assert probe.ok is False
        assert probe.missing_slots == 1


class _FakeFrame:
    def __init__(self, t: float):
        self.props = {"_AbsoluteTime": t}


class _FakeClip:
    """Minimal clip stub: get_frame(n).props['_AbsoluteTime']."""

    def __init__(self, pts_fn):
        self._pts_fn = pts_fn

    def get_frame(self, n: int) -> _FakeFrame:
        return _FakeFrame(self._pts_fn(n))


class TestVisualVerifyTimeMapping:
    """visual_verify time->frame lookup must survive pts gaps too."""

    def test_clean_cfr_unchanged(self):
        from vsg_core.subtitles.frame_utils.visual_verify import (
            _time_to_frame_idx,
        )

        clip = _FakeClip(clean_pts)
        t = 400.0
        expected = int(t * FPS)
        assert _time_to_frame_idx(t, FPS, 34094, None, clip=clip) == expected
        # And without a clip (legacy path) it's identical.
        assert _time_to_frame_idx(t, FPS, 34094, None) == expected

    def test_gapped_source_corrects_one_frame(self):
        from vsg_core.subtitles.frame_utils.visual_verify import (
            _time_to_frame_idx,
        )

        clip = _FakeClip(gap_after_frame0_pts)
        # Wall-clock 406.282s: index math says 9741, but with the gap the
        # frame actually displayed then is index 9740.
        t = 9741 * FRAME_DUR_S + 0.0001
        assert int(t * FPS) == 9741
        assert _time_to_frame_idx(t, FPS, 34046, None, clip=clip) == 9740

    def test_no_timestamps_falls_back_to_index(self):
        from vsg_core.subtitles.frame_utils.visual_verify import (
            _time_to_frame_idx,
        )

        clip = _FakeClip(lambda n: None)
        t = 400.0
        assert _time_to_frame_idx(t, FPS, 34094, None, clip=clip) == int(t * FPS)


class TestOffsetSemantics:
    """The matcher-side arithmetic this probe justifies."""

    def test_fulldive_index_vs_wallclock(self):
        # Matched pair from the real job: source (ffms2 idx 4917, gapped)
        # against target idx 4941. Index math says +24f; timestamps say +23f.
        src_idx, tgt_idx = 4917, 4941
        index_offset = tgt_idx - src_idx
        assert index_offset == 24

        wallclock_ms = (clean_pts(tgt_idx) - gap_after_frame0_pts(src_idx)) * 1000.0
        wallclock_frames = round(wallclock_ms / (FRAME_DUR_S * 1000.0))
        assert wallclock_frames == 23

    def test_clean_files_index_equals_wallclock(self):
        src_idx, tgt_idx = 4917, 4941
        wallclock_ms = (clean_pts(tgt_idx) - clean_pts(src_idx)) * 1000.0
        assert round(wallclock_ms / (FRAME_DUR_S * 1000.0)) == tgt_idx - src_idx
