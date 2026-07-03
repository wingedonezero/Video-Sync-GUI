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
* **Tier 2 (when an exact frame grid is known)** — frame-alignment check
  using the same model as text-sub ``frame_audit``: for each event
  endpoint, compute the source frame ``F_src = clock.frame_of(source_pts)``
  on the exact integer container grid (:class:`FrameClock`), the expected
  output frame ``F_target = F_src + frame_shift``, and the actual output
  frame ``F_actual = clock.frame_of(shifted_pts)``. An event is "correct"
  iff ``F_actual == F_target``. VFR / MPEG-2 / interlaced targets have no
  such grid — callers pass no clock and Tier 2 is skipped.

**Audit-only model** — the shifter applies only the uniform shift
(matches mkvmerge ``--sync`` byte-for-byte). When ``F_actual`` does
not match ``F_target`` for some events, that's reported as drift,
not silently corrected. This keeps palette-update segments and other
intra-event timing in lockstep with their event endpoints by
construction (everything moves by exactly the same delta), at the
cost of leaving rare-edge events on the same drifted frame mkvmerge
would have produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from vsg_core.subtitles.frame_utils.frame_clock import FrameClock

# Per-event sanity bounds (ms). Bitmap subs longer than 60 s or shorter
# than 100 ms are suspicious but legal; we flag them rather than
# rejecting them.
MAX_REASONABLE_DURATION_MS = 60_000
MIN_REASONABLE_DURATION_MS = 100


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
    """Per-endpoint frame-alignment record (start or end of one event).

    Audit-only — the shifter does not apply per-event corrections. The
    ``would_be_correction_ms`` field reports the ms shift that *would*
    be needed to land the event on its target frame, for diagnostic
    purposes. When zero, the uniform shift already landed the event
    correctly.
    """

    event_index: int
    role: Literal["start", "end"]
    source_ms: float  # pre-shift PTS
    shifted_ms: float  # after uniform shift (== the value written to file)
    source_frame: int  # F_src
    target_frame: int  # F_src + frame_shift
    actual_frame: int  # F_actual = floor(shifted_ms / period)
    on_target: bool  # actual_frame == target_frame
    would_be_correction_ms: int  # minimum integer-ms shift that would re-align


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
    """Tier 2 — frame-alignment audit outcome (read-only).

    Counts how many event endpoints landed on their expected video
    frame after the uniform shift. Nothing is rewritten in the .sup
    based on this audit — the output bytes already match what
    mkvmerge ``--sync`` would produce. The drift counts and magnitudes
    are reported so the user can see when an event will render on a
    frame other than the source-relative target (typically only
    happens for non-integer-frame shifts at fps where the frame period
    is not a clean integer-ms ratio).
    """

    target_fps: float
    frame_period_ms: float
    frame_shift: int  # round(delay_ms / period); the intended frame translation
    starts_total: int
    starts_on_target: int  # F_actual == F_target
    ends_total: int  # closed events only
    ends_on_target: int
    starts_drifted: int  # starts_total - starts_on_target
    ends_drifted: int  # ends_total - ends_on_target
    max_start_drift_ms: int  # largest minimum nudge that would re-align a start
    max_end_drift_ms: int
    endpoints: tuple[EndpointAudit, ...] = field(default_factory=tuple)

    @property
    def all_starts_on_target(self) -> bool:
        return self.starts_total > 0 and self.starts_on_target == self.starts_total

    @property
    def all_ends_on_target(self) -> bool:
        return self.ends_total in (0, self.ends_on_target)


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
    frame_alignment_audit_enabled: bool = False  # was Tier 2 requested?


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


def frame_of(ts_ms: float, clock: FrameClock) -> int:
    """Return the video frame ``ts_ms`` renders against.

    Delegates to :meth:`FrameClock.frame_of` — the exact integer container
    grid, "first real frame at or after the timestamp" (player display
    semantics). The previous float-grid form (``floor(ts / (1000/fps))``)
    was 1ms wrong at ~4% of NTSC frames, the exact defect FrameClock was
    built to eliminate.
    """
    return clock.frame_of(ts_ms)


def integer_ms_window_for_frame(
    target_frame: int, clock: FrameClock
) -> tuple[int, int]:
    """Return ``(lo_ms, hi_ms)`` — the inclusive integer-ms range
    whose values all satisfy ``frame_of(ms, clock) == target_frame``.

    On the exact grid a timestamp maps to frame ``n`` iff it lies in
    ``(frame_ms(n-1), frame_ms(n)]``, so the integer window is
    ``[frame_ms(n-1) + 1, frame_ms(n)]``.
    """
    hi = clock.frame_ms(target_frame)
    lo = clock.frame_ms(target_frame - 1) + 1 if target_frame > 0 else 0
    return lo, hi


def pick_integer_ms_in_frame(
    desired_ms: float, target_frame: int, clock: FrameClock
) -> int | None:
    """Pick the integer ms inside ``target_frame``'s window closest to ``desired_ms``.

    Returns ``None`` if the frame contains no integer ms (only possible
    for sub-1ms frame periods, i.e. fps > 1000 — not a real case).
    """
    lo, hi = integer_ms_window_for_frame(target_frame, clock)
    if lo > hi:
        return None
    if desired_ms <= lo:
        return lo
    if desired_ms >= hi:
        return hi
    return int(round(desired_ms))
