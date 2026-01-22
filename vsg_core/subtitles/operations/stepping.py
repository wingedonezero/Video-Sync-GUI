# vsg_core/subtitles/operations/stepping.py
# -*- coding: utf-8 -*-
"""
Stepping adjustment operation for SubtitleData.

Adjusts subtitle timestamps to match stepping corrections applied to audio.
When audio undergoes stepping correction (inserting/removing segments),
subtitles from the same source need their timestamps adjusted to stay in sync.
"""
from __future__ import annotations
from typing import List, TYPE_CHECKING
import math

if TYPE_CHECKING:
    from ..data import SubtitleData, OperationResult, OperationRecord


def apply_stepping_to_data(data: 'SubtitleData', edl: List,
                           boundary_mode: str = 'start') -> 'OperationResult':
    """
    Apply stepping correction EDL (Edit Decision List) to subtitle timestamps.

    The EDL contains AudioSegment entries that define delay changes across the timeline.
    For each subtitle, we calculate the cumulative offset at its timestamp and shift it.

    Args:
        data: SubtitleData object to modify
        edl: List of AudioSegment objects from stepping correction
        boundary_mode: How to handle boundary-spanning subs ('start', 'midpoint', 'majority')

    Returns:
        OperationResult with statistics
    """
    from ..data import OperationResult, OperationRecord

    # Validate EDL
    if not edl or len(edl) == 0:
        return OperationResult(
            success=True,
            operation='stepping',
            summary='No EDL provided, skipping adjustment'
        )

    # Sort EDL by start time
    sorted_edl = sorted(edl, key=lambda seg: seg.start_s)

    # Counters
    adjusted_count = 0
    max_adjustment_ms = 0.0
    spanning_count = 0

    # Process each event
    for event in data.events:
        original_start_s = event.start_ms / 1000.0
        original_end_s = event.end_ms / 1000.0

        # Calculate cumulative offset
        offset_ms = _get_offset_at_time(original_start_s, original_end_s, sorted_edl, boundary_mode)

        # Check if spans boundary
        if _spans_boundary(original_start_s, original_end_s, sorted_edl):
            spanning_count += 1

        # Apply offset (keep as float for precision)
        if abs(offset_ms) > 0.001:  # Non-zero offset
            event.start_ms += offset_ms
            event.end_ms += offset_ms
            adjusted_count += 1
            max_adjustment_ms = max(max_adjustment_ms, abs(offset_ms))

    # Record operation
    record = OperationRecord(
        operation='stepping',
        parameters={
            'edl_segments': len(sorted_edl),
            'boundary_mode': boundary_mode,
        },
        events_affected=adjusted_count,
        summary=f'Adjusted {adjusted_count}/{len(data.events)} events, max {max_adjustment_ms:+.1f}ms'
    )
    data.operations.append(record)

    return OperationResult(
        success=True,
        operation='stepping',
        events_affected=adjusted_count,
        summary=record.summary,
        details={
            'total_events': len(data.events),
            'adjusted_count': adjusted_count,
            'max_adjustment_ms': max_adjustment_ms,
            'edl_segments': len(sorted_edl),
            'spanning_boundaries': spanning_count,
            'boundary_mode': boundary_mode,
        }
    )


def _spans_boundary(start_s: float, end_s: float, edl: List) -> bool:
    """Check if a subtitle spans across a stepping boundary."""
    if len(edl) <= 1:
        return False

    for segment in edl[1:]:
        if start_s < segment.start_s < end_s:
            return True
    return False


def _get_offset_at_time(start_s: float, end_s: float, edl: List, mode: str = 'start') -> float:
    """
    Calculate the cumulative offset (in milliseconds) for a subtitle.

    Returns float for precision - rounding happens at final output.
    """

    def get_cumulative_offset_at_time(time_s: float) -> float:
        """Calculate cumulative offset from stepping corrections."""
        if time_s < edl[0].start_s:
            return 0.0

        cumulative_offset = 0.0
        base_delay = getattr(edl[0], 'delay_raw', float(getattr(edl[0], 'delay_ms', 0)))

        for i in range(1, len(edl)):
            segment = edl[i]
            if segment.start_s <= time_s:
                segment_delay_raw = getattr(segment, 'delay_raw', float(getattr(segment, 'delay_ms', 0)))
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

        region_durations = {}
        boundaries = [seg.start_s for seg in edl] + [end_s]
        boundaries = sorted(set([b for b in boundaries if start_s <= b <= end_s]))

        if not boundaries or (len(boundaries) == 1 and boundaries[0] == end_s):
            return get_cumulative_offset_at_time(start_s)

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

        if region_durations:
            return max(region_durations.items(), key=lambda x: x[1])[0]
        else:
            return get_cumulative_offset_at_time(start_s)

    else:
        return get_cumulative_offset_at_time(start_s)
