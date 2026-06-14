"""Unit tests for the read-only text-subtitle duration audit."""

from vsg_core.subtitles.data import SubtitleEvent
from vsg_core.subtitles.operations.duration_audit import (
    OVERFLOW_THRESHOLD_MS,
    audit_subtitle_duration,
)


def _ev(start_ms: float, end_ms: float, *, comment: bool = False) -> SubtitleEvent:
    return SubtitleEvent(start_ms=start_ms, end_ms=end_ms, text="x", is_comment=comment)


def test_no_overflow_when_all_within_video() -> None:
    events = [_ev(0, 1000), _ev(2000, 3000)]
    r = audit_subtitle_duration(events, video_duration_ms=5000, track_label="t")
    assert r.events_overflow == 0
    assert r.events_start_past_video == 0
    assert r.max_end_ms == 3000
    assert r.overflow_ms == 3000 - 5000
    assert not r.has_overflow


def test_overflow_flagged_past_threshold() -> None:
    # ends 125 ms past video -> flagged (well over ~1 frame)
    events = [_ev(1000, 5125)]
    r = audit_subtitle_duration(events, video_duration_ms=5000, track_label="t")
    assert r.events_overflow == 1
    assert r.overflow_ms == 125
    assert r.has_overflow


def test_within_threshold_not_flagged() -> None:
    # ends just under one frame past the video end -> not flagged (rounding noise)
    end = 5000 + OVERFLOW_THRESHOLD_MS - 1
    r = audit_subtitle_duration(
        [_ev(1000, end)], video_duration_ms=5000, track_label="t"
    )
    assert r.events_overflow == 0
    # still reported as a (small) positive delta for the watchlist log
    assert r.overflow_ms == OVERFLOW_THRESHOLD_MS - 1


def test_comments_ignored() -> None:
    events = [_ev(0, 9999, comment=True), _ev(0, 1000)]
    r = audit_subtitle_duration(events, video_duration_ms=5000, track_label="t")
    assert r.events_total == 1  # comment line excluded from the count
    assert r.events_overflow == 0
    assert r.max_end_ms == 1000


def test_start_past_video_counted() -> None:
    # a line that starts entirely after the video ends (fully orphaned)
    r = audit_subtitle_duration(
        [_ev(6000, 7000)], video_duration_ms=5000, track_label="t"
    )
    assert r.events_start_past_video == 1
    assert r.events_overflow == 1


def test_unknown_video_duration_no_flags() -> None:
    r = audit_subtitle_duration([_ev(0, 9999)], video_duration_ms=None, track_label="t")
    assert not r.video_duration_known
    assert r.events_overflow == 0
    assert r.overflow_ms == 0.0
    assert r.max_end_ms == 9999


def test_empty_track() -> None:
    r = audit_subtitle_duration([], video_duration_ms=5000, track_label="t")
    assert r.events_total == 0
    assert r.max_end_ms == 0.0
    assert r.events_overflow == 0
