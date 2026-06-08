# vsg_core/subtitles/frame_utils/surgical_rounding.py
"""
Surgical frame-aware rounding for subtitle timestamps.

When rounding a timestamp to the output precision (centiseconds for ASS, 1ms for
SRT) would land it on a different video frame than the exact value, this uses
ceil instead of floor. Only timestamps that need it are adjusted; everything
else is identical to plain floor.

Algorithm (per timestamp):
1. Floor is the default (matches Aegisub and ASS convention).
2. If floor still lands on the exact value's frame -> keep floor.
3. Otherwise try ceil; if that lands on the frame -> use ceil (+one tick).
4. Otherwise snap to the centisecond sitting on the target frame itself.

For an event, the end is coordinated with the start: when the start was bumped
floor->ceil, the end is bumped too if that preserves the original duration and
stays on its own frame.

Frames come from an exact :class:`FrameClock` (integer grid from the fps
fraction). There is no millisecond tolerance: a value is on a frame or it is
not, judged against the real grid. Whole-frame sync shifts are made exact at the
apply step (see :class:`FrameShift`), so frame-locked values reach this code
sitting exactly on a frame with no slop to absorb.

Shared by:
- ass_writer.py / srt_writer.py (applies the fix at save time)
- frame_audit.py (predicts/reports fixes)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..data import SubtitleEvent
    from .frame_clock import FrameClock


@dataclass(slots=True)
class SurgicalRoundResult:
    """Result of surgical rounding for a single timestamp."""

    centisecond_ms: int  # Final rounded value in ms (centisecond-aligned, ASS path)
    rounded_ms: int  # Final rounded value in ms (precision-aligned, generic path)
    was_adjusted: bool  # True if ceil/snap was used instead of floor
    target_frame: int  # Frame the exact time maps to
    floor_frame: int  # Frame floor rounding would produce
    method: str  # "floor", "ceil", "coordinated_ceil", or "snap"


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


def surgical_round_single(
    exact_ms: float,
    clock: FrameClock,
    precision_ms: int = 10,
) -> SurgicalRoundResult:
    """
    Surgically round a single timestamp to the given precision.

    Uses floor by default. Switches to ceil (or a snap) only when floor would
    land on a different real frame than the exact value.

    Args:
        exact_ms: Exact time in milliseconds (float, after offset applied)
        clock: Exact CFR frame grid for the target video
        precision_ms: Rounding granularity — 10 for ASS (centiseconds),
                      1 for SRT/ms-based formats. Defaults to 10 so existing
                      ASS call sites are unchanged.

    Returns:
        SurgicalRoundResult with the rounded value and metadata
    """
    p = precision_ms
    target_frame = clock.frame_of(exact_ms)

    # Try floor first (current default behavior)
    floor_val = math.floor(exact_ms / p) * p
    floor_frame = clock.frame_of(floor_val)

    if floor_frame == target_frame:
        return SurgicalRoundResult(
            centisecond_ms=math.floor(exact_ms / 10) * 10,
            rounded_ms=floor_val,
            was_adjusted=False,
            target_frame=target_frame,
            floor_frame=floor_frame,
            method="floor",
        )

    # Floor failed — try ceil
    ceil_val = math.ceil(exact_ms / p) * p
    if clock.frame_of(ceil_val) == target_frame:
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
    real_target = clock.frame_ms(target_frame)
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
    clock: FrameClock,
    precision_ms: int = 10,
) -> SurgicalEventResult:
    """
    Surgically round an event's start and end with coordination.

    Coordination rule: if start was adjusted (floor->ceil) and end's floor is
    already correct, try ceil for end too. Use ceil(end) only if it:
    1. Still maps to the correct frame
    2. Preserves the original floor-floor duration

    This prevents unnecessary duration changes caused by adjusting only one
    side of the event.

    Args:
        start_ms: Exact start time in milliseconds
        end_ms: Exact end time in milliseconds
        clock: Exact CFR frame grid for the target video
        precision_ms: Rounding granularity (10 for ASS, 1 for SRT)

    Returns:
        SurgicalEventResult with both rounded values and coordination info
    """
    p = precision_ms

    start_result = surgical_round_single(start_ms, clock, p)
    end_result = surgical_round_single(end_ms, clock, p)

    # Coordination: if start was adjusted and end was NOT adjusted
    coordination_applied = False
    if start_result.was_adjusted and not end_result.was_adjusted:
        floor_start = math.floor(start_ms / p) * p
        floor_end = math.floor(end_ms / p) * p
        original_floor_duration = floor_end - floor_start

        ceil_end = math.ceil(end_ms / p) * p
        end_target_frame = clock.frame_of(end_ms)

        if clock.frame_of(ceil_end) == end_target_frame:
            # Ceil end is on the correct frame — check duration
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
    clock: FrameClock,
    precision_ms: int = 10,
) -> tuple[dict[int, SurgicalEventResult], SurgicalBatchStats]:
    """
    Apply surgical rounding to all non-comment events.

    Args:
        events: Sequence of SubtitleEvent objects
        clock: Exact CFR frame grid for the target video
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
            clock,
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
