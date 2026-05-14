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
* **Tier 2 (when fps is known)** — frame-alignment check using the
  same model as text-sub ``frame_audit``: for each event endpoint,
  compute the source frame ``F_src = floor(source_pts / period)``,
  the expected output frame ``F_target = F_src + frame_shift``, and
  the actual output frame ``F_actual = floor(shifted_pts / period)``.
  An event is "correct" iff ``F_actual == F_target``. Drifted events
  may be fixed by the shifter (it rewrites those segment PTSes to the
  nearest integer ms inside ``F_target``'s window).

No corrections are applied to the file from this module — the
correction is performed by the shifter and the resulting counts are
fed in here for reporting. This file only contains the math + result
shape so the auditor and shifter agree on terminology.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# Per-event sanity bounds (ms). Bitmap subs longer than 60 s or shorter
# than 100 ms are suspicious but legal; we flag them rather than
# rejecting them.
MAX_REASONABLE_DURATION_MS = 60_000
MIN_REASONABLE_DURATION_MS = 100

# Tiny floor-bias to ensure that PTS == N * period maps to frame N
# rather than frame N-1 due to floating-point drift.
FRAME_EPSILON_MS = 1e-6


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
class EndpointAudit:
    """Per-endpoint frame-alignment record (start or end of one event)."""

    event_index: int
    role: Literal["start", "end"]
    source_ms: float  # pre-shift PTS
    shifted_ms: float  # after uniform shift, before per-event correction
    final_ms: float  # after correction (= shifted_ms when no fix needed)
    source_frame: int  # F_src
    target_frame: int  # F_src + frame_shift
    actual_frame_pre_fix: int  # F_actual before correction
    final_frame: int  # F_actual after correction (should equal target_frame)
    correction_ms: int  # final_ms - shifted_ms (typically 0, ±1, or ± up to period-1)


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
    """Tier 2 — frame-alignment + correction outcome.

    All counts refer to *final* state: ``events_*_correct`` is the count
    of endpoints that landed on ``F_target`` after any per-event
    correction was applied. ``corrections_*_applied`` reports how many
    needed a nudge to get there.
    """

    target_fps: float
    frame_period_ms: float
    frame_shift: int  # round(delay_ms / period); preserved frame translation
    starts_total: int
    starts_correct: int  # F_actual == F_target after correction
    ends_total: int  # closed events only
    ends_correct: int
    corrections_start_applied: int
    corrections_end_applied: int
    max_start_correction_ms: int
    max_end_correction_ms: int
    duration_changes_count: int  # events whose duration in ms changed due to fixes
    max_duration_delta_ms: int  # absolute max |new_dur - old_dur|
    unfixable_count: int  # events where correction couldn't land target_frame
    endpoints: tuple[EndpointAudit, ...] = field(default_factory=tuple)

    @property
    def all_starts_correct(self) -> bool:
        return self.starts_total > 0 and self.starts_correct == self.starts_total

    @property
    def all_ends_correct(self) -> bool:
        return self.ends_total in (0, self.ends_correct)


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
    frame_align_enabled: bool = False  # was the correction step requested?


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


# ----------------------------------------------------------------------
# Frame-math primitives shared with the shifter
# ----------------------------------------------------------------------


def frame_of(ts_ms: float, frame_period_ms: float) -> int:
    """Return the video frame index that contains ``ts_ms``.

    Uses ``floor((ts_ms + ε) / period)``. The epsilon avoids snapping
    a PTS that lands *exactly* on a frame start to the previous frame
    due to float rounding.
    """
    return int((ts_ms + FRAME_EPSILON_MS) / frame_period_ms)


def integer_ms_window_for_frame(
    target_frame: int, frame_period_ms: float
) -> tuple[int, int]:
    """Return ``(lo_ms, hi_ms)`` — the inclusive integer-ms range
    whose values all satisfy ``frame_of(ms, period) == target_frame``.

    For a typical fps (period > 1 ms) this always returns a non-empty
    range. Callers that pick an ms in this range are guaranteed to land
    in ``target_frame``.
    """
    frame_start_ms = target_frame * frame_period_ms
    frame_end_ms = (target_frame + 1) * frame_period_ms
    lo = int(math.ceil(frame_start_ms - FRAME_EPSILON_MS))
    # Largest integer ms still strictly inside [frame_start, frame_end).
    # `frame_end - ε` then floor → ceil(... - 1) catches the boundary
    # case where frame_end is itself an integer ms (which belongs to the
    # next frame, not this one).
    hi = int(math.ceil(frame_end_ms - FRAME_EPSILON_MS)) - 1
    return lo, hi


def pick_integer_ms_in_frame(
    desired_ms: float, target_frame: int, frame_period_ms: float
) -> int | None:
    """Pick the integer ms inside ``target_frame``'s window closest to ``desired_ms``.

    Returns ``None`` if the frame contains no integer ms (only possible
    for sub-1ms frame periods, i.e. fps > 1000 — not a real case).
    """
    lo, hi = integer_ms_window_for_frame(target_frame, frame_period_ms)
    if lo > hi:
        return None
    if desired_ms <= lo:
        return lo
    if desired_ms >= hi:
        return hi
    return int(round(desired_ms))
