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

    centisecond_ms: int  # Final rounded value in ms (centisecond-aligned)
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


def _time_to_frame(time_ms: float, frame_duration_ms: float) -> int:
    """Convert time to frame number (floor with epsilon protection)."""
    return int((time_ms + EPSILON) / frame_duration_ms)


def surgical_round_single(
    exact_ms: float,
    frame_duration_ms: float,
) -> SurgicalRoundResult:
    """
    Surgically round a single timestamp to centiseconds.

    Uses floor by default. Only switches to ceil when floor
    would land on the wrong frame.

    Args:
        exact_ms: Exact time in milliseconds (float, after offset applied)
        frame_duration_ms: Duration of one frame in milliseconds

    Returns:
        SurgicalRoundResult with the rounded value and metadata
    """
    target_frame = _time_to_frame(exact_ms, frame_duration_ms)

    # Try floor first (current default behavior)
    floor_cs = math.floor(exact_ms / 10) * 10
    floor_frame = _time_to_frame(floor_cs, frame_duration_ms)

    if floor_frame == target_frame:
        return SurgicalRoundResult(
            centisecond_ms=floor_cs,
            was_adjusted=False,
            target_frame=target_frame,
            floor_frame=floor_frame,
            method="floor",
        )

    # Floor failed - try ceil
    ceil_cs = math.ceil(exact_ms / 10) * 10
    if _time_to_frame(ceil_cs, frame_duration_ms) == target_frame:
        return SurgicalRoundResult(
            centisecond_ms=ceil_cs,
            was_adjusted=True,
            target_frame=target_frame,
            floor_frame=floor_frame,
            method="ceil",
        )

    # Fallback: ceil of frame start boundary
    frame_start = target_frame * frame_duration_ms
    fallback_cs = math.ceil(frame_start / 10) * 10
    return SurgicalRoundResult(
        centisecond_ms=fallback_cs,
        was_adjusted=True,
        target_frame=target_frame,
        floor_frame=floor_frame,
        method="ceil",
    )


def surgical_round_event(
    start_ms: float,
    end_ms: float,
    frame_duration_ms: float,
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

    Returns:
        SurgicalEventResult with both rounded values and coordination info
    """
    # Round start
    start_result = surgical_round_single(start_ms, frame_duration_ms)

    # Round end independently first
    end_result = surgical_round_single(end_ms, frame_duration_ms)

    # Coordination: if start was adjusted and end was NOT adjusted
    coordination_applied = False
    if start_result.was_adjusted and not end_result.was_adjusted:
        # What would floor-floor duration have been?
        floor_start = math.floor(start_ms / 10) * 10
        floor_end = math.floor(end_ms / 10) * 10
        original_floor_duration = floor_end - floor_start

        # Try ceil for end too
        ceil_end = math.ceil(end_ms / 10) * 10
        end_target_frame = _time_to_frame(end_ms, frame_duration_ms)

        if _time_to_frame(ceil_end, frame_duration_ms) == end_target_frame:
            # Ceil end is on correct frame — check duration
            coordinated_duration = ceil_end - start_result.centisecond_ms
            if coordinated_duration == original_floor_duration:
                end_result = SurgicalRoundResult(
                    centisecond_ms=ceil_end,
                    was_adjusted=True,
                    target_frame=end_target_frame,
                    floor_frame=end_result.floor_frame,
                    method="coordinated_ceil",
                )
                coordination_applied = True

    # Check duration preservation against floor-floor baseline
    floor_start = math.floor(start_ms / 10) * 10
    floor_end = math.floor(end_ms / 10) * 10
    floor_duration = floor_end - floor_start
    output_duration = end_result.centisecond_ms - start_result.centisecond_ms
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
) -> tuple[dict[int, SurgicalEventResult], SurgicalBatchStats]:
    """
    Apply surgical rounding to all non-comment events.

    Args:
        events: Sequence of SubtitleEvent objects
        frame_duration_ms: Duration of one frame in milliseconds

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
