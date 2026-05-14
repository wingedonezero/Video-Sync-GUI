"""
Format-agnostic bitmap-subtitle timing audit.

The shifter modules (``pgs_timing`` and the future VobSub equivalent)
both produce a list of display events with millisecond start/end
boundaries. This module runs the shared sanity + frame-alignment
checks against those events and returns structured results the
post-mux ``BitmapTimingAuditor`` can render.

Tier model:
* **Tier 1 (always)** — sanity checks that apply regardless of where
  the delay came from: dropped events, zero/negative/excessive
  durations, monotonicity, video-duration overflow.
* **Tier 2 (when fps is known)** — distance of each event boundary
  from the nearest frame center / boundary on the target video's
  frame grid. Always reported; the audit message tags it as
  "corrective" when the delay was frame-derived (VV) and
  "informational" when it came from audio correlation.

No corrections are applied to the file from this module. The
shifter has already produced the new bytes; this is read-only
analysis on the resulting event list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Per-event sanity bounds (ms). Bitmap subs longer than 60 s or shorter
# than 100 ms are suspicious but legal; we flag them rather than
# rejecting them.
MAX_REASONABLE_DURATION_MS = 60_000
MIN_REASONABLE_DURATION_MS = 100

# Default frame-alignment tolerance. Half a millisecond is well below
# Matroska's 1 ms default timestamp scale, so anything outside this
# was either a fractional-frame source or a non-frame-aligned shift.
DEFAULT_FRAME_TOLERANCE_MS = 0.5


DelaySourceKind = Literal[
    "vv-frame",
    "vv-correlation-fallback",
    "correlation",
    "zero",
]

FormatTag = Literal["PGS", "VobSub"]


@dataclass(frozen=True, slots=True)
class BitmapEvent:
    """One visible-subtitle window. Format-agnostic."""

    start_ms: float
    end_ms: float | None  # ``None`` = open-ended trailing event (no terminator)
    source_tag: str = ""  # short identifier for logs (e.g. "pcs#42")


@dataclass(frozen=True, slots=True)
class Tier1SanityResult:
    """Tier 1 — sanity counts that always apply."""

    events_total: int
    events_dropped_pre_shift: int  # from shifter (negative-shift policy)
    events_clamped_start: int  # start was clamped to 0 instead of dropped
    events_overflow_video: int  # end > video_duration_ms (if known)
    events_zero_duration: int
    events_negative_duration: int
    events_excessive_duration: int  # > MAX_REASONABLE_DURATION_MS
    events_below_min_duration: int  # < MIN_REASONABLE_DURATION_MS (closed events only)
    monotonicity_violations: int  # consecutive starts not strictly non-decreasing
    video_duration_known: bool

    @property
    def has_any(self) -> bool:
        return (
            self.events_dropped_pre_shift
            + self.events_clamped_start
            + self.events_overflow_video
            + self.events_zero_duration
            + self.events_negative_duration
            + self.events_excessive_duration
            + self.monotonicity_violations
        ) > 0


@dataclass(frozen=True, slots=True)
class Tier2FrameAlignmentResult:
    """Tier 2 — distance from each event boundary to the nearest frame edge."""

    target_fps: float
    frame_period_ms: float
    tolerance_ms: float
    starts_total: int
    starts_aligned: int
    ends_total: int  # closed events only
    ends_aligned: int
    mean_start_distance_ms: float
    max_start_distance_ms: float
    p95_start_distance_ms: float
    mean_end_distance_ms: float
    max_end_distance_ms: float
    p95_end_distance_ms: float

    @property
    def all_starts_aligned(self) -> bool:
        return self.starts_total > 0 and self.starts_aligned == self.starts_total

    @property
    def all_ends_aligned(self) -> bool:
        return self.ends_total in (0, self.ends_aligned)


@dataclass(frozen=True, slots=True)
class BitmapAuditResult:
    """One bitmap track's audit packet — what the post-mux auditor consumes."""

    track_label: str  # e.g. "Source 2 / track 5 / PGS / eng"
    format_tag: FormatTag
    delay_source_kind: DelaySourceKind
    requested_delay_ms: float
    applied_delay_ms: int
    target_fps: float | None
    tier1: Tier1SanityResult
    tier2: Tier2FrameAlignmentResult | None


def tier1_sanity(
    events: list[BitmapEvent],
    *,
    video_duration_ms: float | None = None,
    events_dropped_pre_shift: int = 0,
    events_clamped_start: int = 0,
) -> Tier1SanityResult:
    """Run Tier 1 checks on a list of post-shift events."""
    overflow = 0
    zero_dur = 0
    neg_dur = 0
    excess_dur = 0
    below_min = 0
    monotonicity_violations = 0

    last_start: float | None = None
    for ev in events:
        if last_start is not None and ev.start_ms < last_start:
            monotonicity_violations += 1
        last_start = ev.start_ms

        if ev.end_ms is None:
            # Open-ended trailing event — skip duration checks entirely.
            continue

        if video_duration_ms is not None and ev.end_ms > video_duration_ms:
            overflow += 1

        dur = ev.end_ms - ev.start_ms
        if dur == 0:
            zero_dur += 1
        elif dur < 0:
            neg_dur += 1
        elif dur > MAX_REASONABLE_DURATION_MS:
            excess_dur += 1
        elif dur < MIN_REASONABLE_DURATION_MS:
            below_min += 1

    return Tier1SanityResult(
        events_total=len(events),
        events_dropped_pre_shift=events_dropped_pre_shift,
        events_clamped_start=events_clamped_start,
        events_overflow_video=overflow,
        events_zero_duration=zero_dur,
        events_negative_duration=neg_dur,
        events_excessive_duration=excess_dur,
        events_below_min_duration=below_min,
        monotonicity_violations=monotonicity_violations,
        video_duration_known=video_duration_ms is not None,
    )


def _percentile(values: list[float], pct: float) -> float:
    """Compute a percentile without importing numpy — fine for hundreds of events."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(round((pct / 100.0) * (len(s) - 1)))
    return s[max(0, min(len(s) - 1, idx))]


def tier2_frame_alignment(
    events: list[BitmapEvent],
    target_fps: float,
    *,
    tolerance_ms: float = DEFAULT_FRAME_TOLERANCE_MS,
) -> Tier2FrameAlignmentResult:
    """Compute per-boundary distance from the nearest frame center.

    The reported distance is ``ms - round(ms / frame_period) * frame_period``
    in absolute value — i.e., how far each event boundary sits from the
    nearest integer multiple of the frame period. For fps=23.976
    (frame_period = 41.708 ms), an event starting at exactly 1001 ms
    reports distance 0; an event at 1002 ms reports distance 0.292 ms
    (1002 mod 41.708 = 41.416, nearer the next frame).
    """
    if target_fps <= 0:
        raise ValueError("target_fps must be > 0")

    frame_period = 1000.0 / target_fps

    start_distances: list[float] = []
    end_distances: list[float] = []

    for ev in events:
        s_dist = _distance_to_nearest_frame(ev.start_ms, frame_period)
        start_distances.append(s_dist)
        if ev.end_ms is not None:
            end_distances.append(_distance_to_nearest_frame(ev.end_ms, frame_period))

    starts_aligned = sum(1 for d in start_distances if d <= tolerance_ms)
    ends_aligned = sum(1 for d in end_distances if d <= tolerance_ms)

    return Tier2FrameAlignmentResult(
        target_fps=target_fps,
        frame_period_ms=frame_period,
        tolerance_ms=tolerance_ms,
        starts_total=len(start_distances),
        starts_aligned=starts_aligned,
        ends_total=len(end_distances),
        ends_aligned=ends_aligned,
        mean_start_distance_ms=(
            sum(start_distances) / len(start_distances) if start_distances else 0.0
        ),
        max_start_distance_ms=max(start_distances, default=0.0),
        p95_start_distance_ms=_percentile(start_distances, 95.0),
        mean_end_distance_ms=(
            sum(end_distances) / len(end_distances) if end_distances else 0.0
        ),
        max_end_distance_ms=max(end_distances, default=0.0),
        p95_end_distance_ms=_percentile(end_distances, 95.0),
    )


def _distance_to_nearest_frame(ts_ms: float, frame_period_ms: float) -> float:
    """Absolute distance from ``ts_ms`` to the nearest integer multiple of frame_period_ms."""
    frame_idx = round(ts_ms / frame_period_ms)
    nearest = frame_idx * frame_period_ms
    return abs(ts_ms - nearest)
