# vsg_core/subtitles/operations/stepping.py
# -*- coding: utf-8 -*-
"""
Stepping operation for SubtitleData.

Adjusts subtitle timestamps based on EDL (Edit Decision List) from audio stepping.
When audio undergoes stepping correction, subtitles need matching adjustments.

NOTE: This operation needs refactoring/testing. The feature doesn't work correctly
in all cases. The boundary mode handling (start/midpoint/majority) and cumulative
offset calculation may need review. See original stepping_adjust.py (now removed)
for reference implementation details.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..data import SubtitleData, OperationResult, OperationRecord


def apply_stepping(
    data: 'SubtitleData',
    edl_segments: List[Any],
    boundary_mode: str = 'start',
    runner=None
) -> 'OperationResult':
    """
    Apply stepping correction EDL to subtitle timestamps.

    The EDL contains AudioSegment entries that define delay changes across the timeline.
    For each subtitle, we calculate the cumulative offset at its timestamp and shift it.

    Args:
        data: SubtitleData to modify
        edl_segments: List of AudioSegment objects from stepping correction
        boundary_mode: How to handle boundary-spanning subs ('start', 'midpoint', 'majority')
        runner: CommandRunner for logging (optional)

    Returns:
        OperationResult with statistics
    """
    from ..data import OperationResult, OperationRecord

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    # Validate EDL
    if not edl_segments or len(edl_segments) == 0:
        log("[Stepping] No EDL provided, skipping")
        return OperationResult(
            success=True,
            operation='stepping',
            summary='No EDL provided'
        )

    # Sort EDL by start time
    sorted_edl = sorted(edl_segments, key=lambda seg: seg.start_s)

    # Counters
    adjusted_count = 0
    max_adjustment_ms = 0.0
    spanning_count = 0

    # Process each event
    for event in data.events:
        # Get timing in seconds
        start_s = event.start_ms / 1000.0
        end_s = event.end_ms / 1000.0

        # Calculate cumulative offset (raw float ms)
        offset_ms = _get_offset_at_time(start_s, end_s, sorted_edl, boundary_mode)

        # Check if spans boundary
        if _spans_boundary(start_s, end_s, sorted_edl):
            spanning_count += 1

        # Apply offset (keep as float - no rounding)
        if offset_ms != 0.0:
            event.start_ms += offset_ms
            event.end_ms += offset_ms
            adjusted_count += 1
            max_adjustment_ms = max(max_adjustment_ms, abs(offset_ms))

    # Record operation
    record = OperationRecord(
        operation='stepping',
        timestamp=datetime.now(),
        parameters={
            'edl_segments': len(sorted_edl),
            'boundary_mode': boundary_mode,
        },
        events_affected=adjusted_count,
        summary=f"Adjusted {adjusted_count}/{len(data.events)} events, max {max_adjustment_ms:+.1f}ms"
    )
    data.operations.append(record)

    log(f"[Stepping] Adjusted {adjusted_count}/{len(data.events)} events using '{boundary_mode}' mode")
    log(f"[Stepping] Max adjustment: {max_adjustment_ms:+.1f}ms")
    if spanning_count > 0:
        log(f"[Stepping] {spanning_count} event(s) span stepping boundaries")

    return OperationResult(
        success=True,
        operation='stepping',
        events_affected=adjusted_count,
        summary=record.summary,
        details={
            'max_adjustment_ms': max_adjustment_ms,
            'spanning_boundaries': spanning_count,
            'edl_segments': len(sorted_edl),
        }
    )


def _spans_boundary(start_s: float, end_s: float, edl: List) -> bool:
    """Check if subtitle spans a stepping boundary."""
    if len(edl) <= 1:
        return False

    for segment in edl[1:]:  # Skip first segment
        if start_s < segment.start_s < end_s:
            return True
    return False


def _get_offset_at_time(start_s: float, end_s: float, edl: List, mode: str = 'start') -> float:
    """
    Calculate cumulative offset (in float ms) for a subtitle.

    Args:
        start_s: Subtitle start time in seconds
        end_s: Subtitle end time in seconds
        edl: Sorted list of AudioSegment objects
        mode: 'start', 'majority', or 'midpoint'

    Returns:
        Cumulative offset in float milliseconds (no rounding)
    """

    def get_cumulative_offset_at_time(time_s: float) -> float:
        """Calculate cumulative offset at a specific time."""
        if time_s < edl[0].start_s:
            return 0.0

        cumulative_offset = 0.0
        base_delay = getattr(edl[0], 'delay_raw', float(edl[0].delay_ms))

        for i in range(1, len(edl)):
            segment = edl[i]
            if segment.start_s <= time_s:
                segment_delay_raw = getattr(segment, 'delay_raw', float(segment.delay_ms))
                cumulative_offset += (segment_delay_raw - base_delay)
                base_delay = segment_delay_raw
            else:
                break

        return cumulative_offset

    if mode == 'start':
        return get_cumulative_offset_at_time(start_s)

    elif mode == 'midpoint':
        midpoint_s = (start_s + end_s) / 2.0
        return get_cumulative_offset_at_time(midpoint_s)

    elif mode == 'majority':
        duration = end_s - start_s
        if duration <= 0:
            return get_cumulative_offset_at_time(start_s)

        # Track duration in each delay region
        region_durations = {}

        # Build boundaries within subtitle range
        boundaries = [seg.start_s for seg in edl] + [end_s]
        boundaries = sorted(set([b for b in boundaries if start_s <= b <= end_s]))

        if not boundaries or (len(boundaries) == 1 and boundaries[0] == end_s):
            return get_cumulative_offset_at_time(start_s)

        # Calculate duration in each region
        current_time = start_s
        for boundary in boundaries:
            if boundary <= start_s:
                continue

            region_delay = get_cumulative_offset_at_time(current_time)
            segment_duration = min(boundary, end_s) - current_time

            if region_delay not in region_durations:
                region_durations[region_delay] = 0
            region_durations[region_delay] += segment_duration

            current_time = boundary
            if current_time >= end_s:
                break

        # Return delay with most duration
        if region_durations:
            return max(region_durations.keys(), key=lambda d: region_durations[d])

        return get_cumulative_offset_at_time(start_s)

    else:
        # Unknown mode, default to start
        return get_cumulative_offset_at_time(start_s)
