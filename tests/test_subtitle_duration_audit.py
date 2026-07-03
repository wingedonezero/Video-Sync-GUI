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


# ----------------------------------------------------------------------
# Opt-in clamp to video end
# ----------------------------------------------------------------------

from vsg_core.subtitles.operations.duration_audit import (  # noqa: E402
    clamp_events_to_video_end,
)


def test_clamp_end_past_video_to_centisecond() -> None:
    # Video ends at 5003.667ms -> clamp target is the last centisecond
    # at-or-before it: 5000ms.
    events = [_ev(1000, 2000), _ev(4000, 9000)]
    r = clamp_events_to_video_end(events, video_duration_ms=5003.667)
    assert r.clamp_target_ms == 5000
    assert r.events_clamped == 1
    assert r.events_dropped == 0
    assert events[0].end_ms == 2000  # untouched
    assert events[1].end_ms == 5000.0
    assert r.actions[0].action == "clamped"
    assert r.actions[0].new_end_ms == 5000.0


def test_clamp_leaves_lines_within_video_alone() -> None:
    events = [_ev(0, 1000), _ev(2000, 5000)]
    r = clamp_events_to_video_end(events, video_duration_ms=5000)
    assert r.touched == 0
    assert [e.end_ms for e in events] == [1000, 5000]


def test_drop_line_starting_past_video_end() -> None:
    events = [_ev(1000, 2000), _ev(5100, 9000)]
    r = clamp_events_to_video_end(events, video_duration_ms=5000)
    assert r.events_dropped == 1
    assert r.events_clamped == 0
    assert len(events) == 1
    assert events[0].start_ms == 1000
    assert r.actions[0].action == "dropped"


def test_comments_never_touched() -> None:
    # Comment past video end stays; comment starting past end stays.
    events = [
        _ev(1000, 999_000, comment=True),
        _ev(8000, 9000, comment=True),
        _ev(4000, 9000),
    ]
    r = clamp_events_to_video_end(events, video_duration_ms=5000)
    assert r.events_clamped == 1
    assert r.events_dropped == 0
    assert len(events) == 3
    assert events[0].end_ms == 999_000  # comment untouched
    assert events[1].start_ms == 8000  # comment untouched
    assert events[2].end_ms == 5000.0


def test_clamp_into_zero_duration_drops_instead() -> None:
    # Line starts inside the final sub-centisecond sliver: clamping the end
    # to 5000 would make end <= start -> drop, never a zero-length event.
    events = [_ev(5002, 9000)]
    r = clamp_events_to_video_end(events, video_duration_ms=5003.667)
    assert r.events_dropped == 1
    assert r.events_clamped == 0
    assert len(events) == 0


def test_audit_carries_clamp_result() -> None:
    events = [_ev(4000, 9000)]
    clamp = clamp_events_to_video_end(events, video_duration_ms=5000)
    r = audit_subtitle_duration(
        events, video_duration_ms=5000, track_label="t", clamp_result=clamp
    )
    assert r.clamp_applied
    assert r.events_clamped == 1
    assert r.events_dropped == 0
    assert r.events_overflow == 0  # post-clamp: nothing past the video


def test_audit_without_clamp_unchanged() -> None:
    r = audit_subtitle_duration([_ev(1000, 5125)], 5000, "t")
    assert not r.clamp_applied
    assert r.events_overflow == 1
