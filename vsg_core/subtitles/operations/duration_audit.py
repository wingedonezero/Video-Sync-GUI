# vsg_core/subtitles/operations/duration_audit.py
"""
Read-only text-subtitle "does it end past the video?" audit.

The pipeline owns the subtitle data: after sync, ``SubtitleEvent.end_ms``
holds the final on-screen end time, so we compare those end times directly
against the reference (Source 1) video duration — no extraction or container
probing. The result is the text-sub counterpart of the bitmap
``Tier1SanityResult`` overflow count; the post-mux ``SubtitleDurationAuditor``
renders it in the final audit.

**Read-only** — nothing is clamped. A clamp (if ever wanted) is a separate,
opt-in step.

Timeline precondition: ``events`` must carry their FINAL timing in the same
timeline as ``video_duration_ms`` (the reference video). That holds for the
video-verified sync path (the per-source delay is baked into the event times)
and whenever the effective subtitle delay is zero. It is the caller's job to
only audit events that satisfy this. (In ``ALLOW_NEGATIVE`` sync mode there is
never a global shift, so a baked or zero-delay subtitle is already in the
reference timeline.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.subtitles.data import SubtitleEvent

# A line ending more than this past the video is flagged. ~1 video frame at
# 23.976 fps: ignores centisecond-rounding coincidence, catches anything
# actually visible on screen.
OVERFLOW_THRESHOLD_MS = 42.0


@dataclass(frozen=True, slots=True)
class SubtitleDurationAuditResult:
    """One text-sub track's end-time-vs-video audit packet."""

    track_label: str
    video_duration_ms: float | None
    events_total: int
    events_overflow: int  # end_ms beyond video by > OVERFLOW_THRESHOLD_MS
    events_start_past_video: int  # start_ms at/after video end (fully orphaned)
    max_end_ms: float  # latest non-comment event end
    overflow_ms: float  # max_end_ms - video_duration_ms (signed; 0 if unknown)

    @property
    def video_duration_known(self) -> bool:
        return self.video_duration_ms is not None

    @property
    def has_overflow(self) -> bool:
        return self.events_overflow > 0


def audit_subtitle_duration(
    events: list[SubtitleEvent],
    video_duration_ms: float | None,
    track_label: str,
) -> SubtitleDurationAuditResult:
    """Compare non-comment event end times against the video duration.

    ``events`` must already carry their final timing (see the module
    precondition). Comment lines are ignored.
    """
    ends = [e.end_ms for e in events if not e.is_comment]
    starts = [e.start_ms for e in events if not e.is_comment]
    max_end = max(ends) if ends else 0.0

    if video_duration_ms is None:
        return SubtitleDurationAuditResult(
            track_label=track_label,
            video_duration_ms=None,
            events_total=len(ends),
            events_overflow=0,
            events_start_past_video=0,
            max_end_ms=max_end,
            overflow_ms=0.0,
        )

    overflow = sum(1 for e in ends if e - video_duration_ms > OVERFLOW_THRESHOLD_MS)
    start_past = sum(1 for s in starts if s >= video_duration_ms)
    return SubtitleDurationAuditResult(
        track_label=track_label,
        video_duration_ms=video_duration_ms,
        events_total=len(ends),
        events_overflow=overflow,
        events_start_past_video=start_past,
        max_end_ms=max_end,
        overflow_ms=max_end - video_duration_ms,
    )
