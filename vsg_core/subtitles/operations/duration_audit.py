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
class ClampAction:
    """One line the clamp touched — for logging and the final audit."""

    event_index: int
    action: str  # "clamped" | "dropped"
    start_ms: float
    end_ms: float  # pre-clamp end
    new_end_ms: float | None  # post-clamp end ("clamped" only)
    text_preview: str  # first 40 chars, newlines stripped


@dataclass(frozen=True, slots=True)
class ClampToVideoEndResult:
    """Outcome of :func:`clamp_events_to_video_end`."""

    video_duration_ms: float
    clamp_target_ms: int  # centisecond-aligned end written to clamped lines
    events_clamped: int
    events_dropped: int
    actions: tuple[ClampAction, ...]

    @property
    def touched(self) -> int:
        return self.events_clamped + self.events_dropped


def clamp_events_to_video_end(
    events: list[SubtitleEvent],
    video_duration_ms: float,
) -> ClampToVideoEndResult:
    """Clamp non-comment lines that outlast the video (opt-in fix).

    Mutates ``events`` in place:

    * A line that starts before the video's end but ends past it gets its
      end set to the largest **centisecond** at-or-before the video end —
      centisecond-aligned so the ASS writer's rounding cannot move it back
      past the video (ASS stores 10ms ticks; see the save-time rounding).
    * A line that starts at/after the video end is removed: once nothing
      outlasts the video, the container ends with the video, so such a line
      could only ever render on a held dead frame.
    * A clamp that would leave ``end <= start`` (line starts inside the
      final sub-centisecond sliver) removes the line instead of writing a
      zero-length event.
    * Comments are never touched: they are not rendered and, measured
      empirically, mkvmerge carries them without extending the container
      duration.

    Same timeline precondition as :func:`audit_subtitle_duration` — events
    must carry final timing in the reference-video timeline.
    """
    clamp_target_ms = (int(video_duration_ms) // 10) * 10

    actions: list[ClampAction] = []
    keep: list[SubtitleEvent] = []
    clamped = 0
    dropped = 0

    def preview(e: SubtitleEvent) -> str:
        text = e.text[:40].replace("\n", " ").replace("\\N", " ")
        return text + ("..." if len(e.text) > 40 else "")

    for idx, ev in enumerate(events):
        if ev.is_comment:
            keep.append(ev)
            continue
        if ev.start_ms >= video_duration_ms:
            dropped += 1
            actions.append(
                ClampAction(idx, "dropped", ev.start_ms, ev.end_ms, None, preview(ev))
            )
            continue
        if ev.end_ms > video_duration_ms:
            if clamp_target_ms <= ev.start_ms:
                dropped += 1
                actions.append(
                    ClampAction(
                        idx, "dropped", ev.start_ms, ev.end_ms, None, preview(ev)
                    )
                )
                continue
            actions.append(
                ClampAction(
                    idx,
                    "clamped",
                    ev.start_ms,
                    ev.end_ms,
                    float(clamp_target_ms),
                    preview(ev),
                )
            )
            ev.end_ms = float(clamp_target_ms)
            clamped += 1
        keep.append(ev)

    if dropped:
        events[:] = keep

    return ClampToVideoEndResult(
        video_duration_ms=video_duration_ms,
        clamp_target_ms=clamp_target_ms,
        events_clamped=clamped,
        events_dropped=dropped,
        actions=tuple(actions),
    )


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

    # Clamp-to-video-end outcome (only set when the opt-in fix ran).
    clamp_applied: bool = False
    events_clamped: int = 0
    events_dropped: int = 0

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
    clamp_result: ClampToVideoEndResult | None = None,
) -> SubtitleDurationAuditResult:
    """Compare non-comment event end times against the video duration.

    ``events`` must already carry their final timing (see the module
    precondition). Comment lines are ignored. When the opt-in clamp ran
    first, pass its ``clamp_result`` so the final audit can report what
    was fixed alongside the (now clean) end-time comparison.
    """
    ends = [e.end_ms for e in events if not e.is_comment]
    starts = [e.start_ms for e in events if not e.is_comment]
    max_end = max(ends) if ends else 0.0

    clamp_applied = clamp_result is not None
    events_clamped = clamp_result.events_clamped if clamp_result else 0
    events_dropped = clamp_result.events_dropped if clamp_result else 0

    if video_duration_ms is None:
        return SubtitleDurationAuditResult(
            track_label=track_label,
            video_duration_ms=None,
            events_total=len(ends),
            events_overflow=0,
            events_start_past_video=0,
            max_end_ms=max_end,
            overflow_ms=0.0,
            clamp_applied=clamp_applied,
            events_clamped=events_clamped,
            events_dropped=events_dropped,
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
        clamp_applied=clamp_applied,
        events_clamped=events_clamped,
        events_dropped=events_dropped,
    )
