# vsg_core/subtitles/frame_utils/surgical_rounding.py
"""
Surgical frame-aware rounding for subtitle timestamps.

When floor rounding to centiseconds (10ms precision) would land a timestamp
on the wrong frame, uses ceil instead. Only adjusts timestamps that need it;
all others remain identical to plain floor behavior.

Algorithm:
1. Floor is default (matches Aegisub and ASS convention)
2. Check if floor lands on the correct frame
3. If not, use ceil (minimal adjustment: +10ms)
4. Coordinate end with start to preserve duration when safe

This module provides shared logic used by both:
- ass_writer.py (applies the fix at save time)
- frame_audit.py (predicts fixes for reporting)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..data import SubtitleEvent

EPSILON = 1e-6


@dataclass(slots=True)
class SurgicalRoundResult:
    """Result of surgical rounding for a single timestamp."""

    centisecond_ms: int  # Final rounded value in ms (centisecond-aligned, ASS path)
    rounded_ms: int  # Final rounded value in ms (precision-aligned, generic path)
    was_adjusted: bool  # True if ceil was used instead of floor
    target_frame: int  # Frame the exact time maps to
    floor_frame: int  # Frame floor rounding would produce
    method: str  # "floor", "ceil", or "coordinated_ceil"


@dataclass(slots=True)
class SurgicalEventResult:
    """Result of surgical rounding for a single event (start + end)."""

    start: SurgicalRoundResult
    end: SurgicalRoundResult
    duration_preserved: bool  # Output duration equals floor-floor duration
    coordination_applied: bool  # End was coordinated with start


@dataclass(slots=True)
class SurgicalBatchStats:
    """Aggregate statistics from surgical rounding across all events."""

    total_events: int = 0
    total_timing_points: int = 0  # events * 2 (start + end)
    starts_adjusted: int = 0
    ends_adjusted: int = 0
    ends_coordinated: int = 0  # Subset of ends_adjusted done via coordination
    durations_preserved: int = 0
    durations_changed: int = 0
    points_identical_to_floor: int = 0
    points_different_from_floor: int = 0
    events_with_adjustments: int = 0  # Events where at least one point changed


def _real_frame_ms(n: int, frame_duration_ms: float) -> int:
    """Presentation time (ms) of real video frame ``n``.

    Container muxers (MakeMKV, mkvmerge) store CFR frame timestamps rounded to
    the millisecond — ``round(n * frame_duration)`` — NOT the exact
    ``n * frame_duration`` line. PGS subtitle timestamps land on these real
    frames, so the rounding check must compare against them.
    """
    return int(n * frame_duration_ms + 0.5)


# A frame-exact timestamp can sit a fraction of a millisecond off a real frame:
# container frames are millisecond-rounded, and a whole-frame shift applied as
# float milliseconds (N * frame_duration) leaves up to ~1ms of slop. Treat a
# value within this tolerance ABOVE a real frame as sitting ON that frame, so the
# slop never tips it onto the next frame. It is far below the 10ms centisecond
# grid, so it never absorbs a genuinely mid-frame value; a no-shift PGS value has
# zero slop and is unaffected either way.
_ON_FRAME_TOLERANCE_MS = 1.5


def _time_to_frame(time_ms: float, frame_duration_ms: float) -> int:
    """Index of the first real video frame at or after ``time_ms``.

    This is the frame a timestamp actually renders against: a player shows a
    subtitle on a frame whose presentation time is >= the start, and the
    exclusive end frame is always this value minus one — so a single
    "first frame at or after" mapping is correct for both start and end checks.

    Crucially it measures against the *real* (millisecond-rounded) frame grid,
    not the synthetic ``int(t / frame_duration)`` line. The two disagree by up to
    ~0.5ms right at each frame boundary, which is exactly where a PGS timestamp
    sits (it IS the frame, just at an odd millisecond). The old formula therefore
    read a floored PGS value as having drifted to a different frame when it had
    not, triggering an unwanted ceil. Against the real grid a value already on a
    frame stays on it under floor; genuinely off-frame (shifted) values still
    drift and get corrected exactly as before.

    ``_ON_FRAME_TOLERANCE_MS`` of sub-millisecond slop above a real frame is
    pulled back onto that frame so a float-ms frame shift can't slip a frame.
    """
    # Pull back by the on-frame tolerance, then walk to the true boundary. The
    # real frame grid is monotonic and within ~1ms of the estimate, so 1-2 steps.
    t = time_ms - _ON_FRAME_TOLERANCE_MS
    n = int(t / frame_duration_ms)
    while _real_frame_ms(n, frame_duration_ms) >= t:
        n -= 1
    while _real_frame_ms(n, frame_duration_ms) < t:
        n += 1
    return n


def surgical_round_single(
    exact_ms: float,
    frame_duration_ms: float,
    precision_ms: int = 10,
) -> SurgicalRoundResult:
    """
    Surgically round a single timestamp to the given precision.

    Uses floor by default. Only switches to ceil when floor
    would land on the wrong frame.

    Args:
        exact_ms: Exact time in milliseconds (float, after offset applied)
        frame_duration_ms: Duration of one frame in milliseconds
        precision_ms: Rounding granularity — 10 for ASS (centiseconds),
                      1 for SRT/ms-based formats.  Defaults to 10 so all
                      existing ASS call sites are unchanged.

    Returns:
        SurgicalRoundResult with the rounded value and metadata
    """
    p = precision_ms
    target_frame = _time_to_frame(exact_ms, frame_duration_ms)

    # Try floor first (current default behavior)
    floor_val = math.floor(exact_ms / p) * p
    floor_frame = _time_to_frame(floor_val, frame_duration_ms)

    if floor_frame == target_frame:
        return SurgicalRoundResult(
            centisecond_ms=math.floor(exact_ms / 10) * 10,
            rounded_ms=floor_val,
            was_adjusted=False,
            target_frame=target_frame,
            floor_frame=floor_frame,
            method="floor",
        )

    # Floor failed - try ceil
    ceil_val = math.ceil(exact_ms / p) * p
    if _time_to_frame(ceil_val, frame_duration_ms) == target_frame:
        return SurgicalRoundResult(
            centisecond_ms=math.ceil(exact_ms / 10) * 10,
            rounded_ms=ceil_val,
            was_adjusted=True,
            target_frame=target_frame,
            floor_frame=floor_frame,
            method="ceil",
        )

    # Fallback: neither floor nor ceil of the exact value lands on the target
    # frame; snap to the centisecond sitting on the target real frame itself.
    real_target = _real_frame_ms(target_frame, frame_duration_ms)
    fallback_val = math.floor(real_target / p) * p
    return SurgicalRoundResult(
        centisecond_ms=math.floor(real_target / 10) * 10,
        rounded_ms=fallback_val,
        was_adjusted=True,
        target_frame=target_frame,
        floor_frame=floor_frame,
        method="snap",
    )


def surgical_round_event(
    start_ms: float,
    end_ms: float,
    frame_duration_ms: float,
    precision_ms: int = 10,
) -> SurgicalEventResult:
    """
    Surgically round an event's start and end with coordination.

    Coordination rule: If start was adjusted (floor->ceil) and end's floor
    is already correct, try ceil for end too. Use ceil(end) only if it:
    1. Still maps to the correct frame
    2. Preserves the original floor-floor duration

    This prevents unnecessary duration changes caused by adjusting only
    one side of the event.

    Args:
        start_ms: Exact start time in milliseconds
        end_ms: Exact end time in milliseconds
        frame_duration_ms: Duration of one frame in milliseconds
        precision_ms: Rounding granularity (10 for ASS, 1 for SRT)

    Returns:
        SurgicalEventResult with both rounded values and coordination info
    """
    p = precision_ms

    # Round start
    start_result = surgical_round_single(start_ms, frame_duration_ms, p)

    # Round end independently first
    end_result = surgical_round_single(end_ms, frame_duration_ms, p)

    # Coordination: if start was adjusted and end was NOT adjusted
    coordination_applied = False
    if start_result.was_adjusted and not end_result.was_adjusted:
        # What would floor-floor duration have been?
        floor_start = math.floor(start_ms / p) * p
        floor_end = math.floor(end_ms / p) * p
        original_floor_duration = floor_end - floor_start

        # Try ceil for end too
        ceil_end = math.ceil(end_ms / p) * p
        end_target_frame = _time_to_frame(end_ms, frame_duration_ms)

        if _time_to_frame(ceil_end, frame_duration_ms) == end_target_frame:
            # Ceil end is on correct frame — check duration
            coordinated_duration = ceil_end - start_result.rounded_ms
            if coordinated_duration == original_floor_duration:
                end_result = SurgicalRoundResult(
                    centisecond_ms=math.ceil(end_ms / 10) * 10,
                    rounded_ms=ceil_end,
                    was_adjusted=True,
                    target_frame=end_target_frame,
                    floor_frame=end_result.floor_frame,
                    method="coordinated_ceil",
                )
                coordination_applied = True

    # Check duration preservation against floor-floor baseline
    floor_start = math.floor(start_ms / p) * p
    floor_end = math.floor(end_ms / p) * p
    floor_duration = floor_end - floor_start
    output_duration = end_result.rounded_ms - start_result.rounded_ms
    duration_preserved = output_duration == floor_duration

    return SurgicalEventResult(
        start=start_result,
        end=end_result,
        duration_preserved=duration_preserved,
        coordination_applied=coordination_applied,
    )


def surgical_round_batch(
    events: Sequence[SubtitleEvent],
    frame_duration_ms: float,
    precision_ms: int = 10,
) -> tuple[dict[int, SurgicalEventResult], SurgicalBatchStats]:
    """
    Apply surgical rounding to all non-comment events.

    Args:
        events: Sequence of SubtitleEvent objects
        frame_duration_ms: Duration of one frame in milliseconds
        precision_ms: Rounding granularity (10 for ASS, 1 for SRT)

    Returns:
        Tuple of (results_by_index, aggregate_stats).
        results_by_index maps event index -> SurgicalEventResult
        (only for non-comment events that were analyzed).
    """
    results: dict[int, SurgicalEventResult] = {}
    stats = SurgicalBatchStats()

    for idx, event in enumerate(events):
        if event.is_comment:
            continue

        stats.total_events += 1
        stats.total_timing_points += 2

        result = surgical_round_event(
            event.start_ms,
            event.end_ms,
            frame_duration_ms,
            precision_ms,
        )
        results[idx] = result

        if result.start.was_adjusted:
            stats.starts_adjusted += 1
        if result.end.was_adjusted:
            stats.ends_adjusted += 1
        if result.coordination_applied:
            stats.ends_coordinated += 1
        if result.duration_preserved:
            stats.durations_preserved += 1
        else:
            stats.durations_changed += 1

        # Track identity with floor
        if result.start.was_adjusted:
            stats.points_different_from_floor += 1
        else:
            stats.points_identical_to_floor += 1
        if result.end.was_adjusted:
            stats.points_different_from_floor += 1
        else:
            stats.points_identical_to_floor += 1

        if result.start.was_adjusted or result.end.was_adjusted:
            stats.events_with_adjustments += 1

    return results, stats
