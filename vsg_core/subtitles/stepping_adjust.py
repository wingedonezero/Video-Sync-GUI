# vsg_core/subtitles/stepping_adjust.py
# -*- coding: utf-8 -*-
"""
Adjusts subtitle timestamps to match stepping corrections applied to audio.

When audio undergoes stepping correction (inserting/removing segments), subtitles
from the same source need their timestamps adjusted to stay in sync.
"""
from __future__ import annotations
from typing import List
from pathlib import Path
import pysubs2
from .metadata_preserver import SubtitleMetadata


def apply_stepping_to_subtitles(subtitle_path: str, edl: List, runner, config: dict = None) -> dict:
    """
    Apply stepping correction EDL (Edit Decision List) to subtitle timestamps.

    The EDL contains AudioSegment entries that define delay changes across the timeline.
    For each subtitle, we calculate the cumulative offset at its timestamp and shift it.

    Args:
        subtitle_path: Path to the subtitle file
        edl: List of AudioSegment objects from stepping correction
        runner: Runner object for logging
        config: Configuration dictionary (optional, for boundary mode setting)

    Returns:
        dict: Report with statistics about the adjustment

    Example EDL:
        AudioSegment(start_s=0.0,    delay_ms=0)       # No offset at start
        AudioSegment(start_s=134.968, delay_ms=1001)   # +1001ms inserted
        AudioSegment(start_s=711.594, delay_ms=969)    # -32ms removed (cumulative)
        AudioSegment(start_s=814.687, delay_ms=1970)   # +1001ms inserted (cumulative)
    """
    # Skip binary subtitle formats
    file_ext = Path(subtitle_path).suffix.lower()
    if file_ext in ['.sub', '.idx', '.sup']:
        runner._log_message(f"[SteppingAdjust] Skipping binary subtitle format: {file_ext}")
        return {}

    # Only process text-based subtitle formats
    if file_ext not in ['.srt', '.ass', '.ssa', '.vtt']:
        runner._log_message(f"[SteppingAdjust] Unsupported subtitle format: {file_ext}")
        return {}

    # Validate EDL
    if not edl or len(edl) == 0:
        runner._log_message(f"[SteppingAdjust] No EDL provided, skipping adjustment")
        return {}

    try:
        # Capture original metadata before pysubs2 processing
        metadata = SubtitleMetadata(subtitle_path)
        metadata.capture()

        # Load subtitles
        subs = pysubs2.load(subtitle_path, encoding='utf-8')

        if len(subs) == 0:
            runner._log_message(f"[SteppingAdjust] No subtitles found in file")
            return {}

        # Sort EDL by start time (should already be sorted, but just in case)
        sorted_edl = sorted(edl, key=lambda seg: seg.start_s)

        # Get boundary mode from config (default to 'start')
        boundary_mode = 'start'
        if config:
            boundary_mode = config.get('stepping_boundary_mode', 'start')

        # Counters for report
        adjusted_count = 0
        max_adjustment_ms = 0
        spanning_count = 0  # Count subs that span boundaries

        # Process each subtitle
        for event in subs:
            # Get original timestamps (pysubs2 uses milliseconds)
            original_start_ms = event.start
            original_end_ms = event.end
            original_start_s = original_start_ms / 1000.0
            original_end_s = original_end_ms / 1000.0

            # Calculate cumulative offset based on boundary mode
            offset_ms = _get_offset_at_time(original_start_s, original_end_s, sorted_edl, boundary_mode)

            # Check if this subtitle spans a boundary (for stats)
            if _spans_boundary(original_start_s, original_end_s, sorted_edl):
                spanning_count += 1

            # Apply offset
            if offset_ms != 0:
                event.start += offset_ms
                event.end += offset_ms
                adjusted_count += 1
                max_adjustment_ms = max(max_adjustment_ms, abs(offset_ms))

        # Save adjusted subtitles
        subs.save(subtitle_path, encoding='utf-8')

        # Validate and restore lost metadata
        metadata.validate_and_restore(runner)

        # Build report
        report = {
            'total_subtitles': len(subs),
            'adjusted_count': adjusted_count,
            'max_adjustment_ms': max_adjustment_ms,
            'edl_segments': len(sorted_edl),
            'spanning_boundaries': spanning_count,
            'boundary_mode': boundary_mode
        }

        runner._log_message(
            f"[SteppingAdjust] Adjusted {adjusted_count}/{len(subs)} subtitles using '{boundary_mode}' mode. "
            f"Max adjustment: {max_adjustment_ms:+d}ms"
        )
        if spanning_count > 0:
            runner._log_message(
                f"[SteppingAdjust] {spanning_count} subtitle(s) span stepping boundaries"
            )

        return report

    except Exception as e:
        runner._log_message(f"[SteppingAdjust] Error adjusting subtitles: {e}")
        return {'error': str(e)}


def _spans_boundary(start_s: float, end_s: float, edl: List) -> bool:
    """
    Check if a subtitle spans across a stepping boundary.

    Args:
        start_s: Subtitle start time in seconds
        end_s: Subtitle end time in seconds
        edl: Sorted list of AudioSegment objects

    Returns:
        bool: True if subtitle spans a boundary
    """
    if len(edl) <= 1:
        return False

    # Check if any boundary falls within [start_s, end_s]
    for segment in edl[1:]:  # Skip first segment (always at 0.0s)
        if start_s < segment.start_s < end_s:
            return True
    return False


def _get_offset_at_time(start_s: float, end_s: float, edl: List, mode: str = 'start') -> int:
    """
    Calculate the cumulative offset (in milliseconds) for a subtitle.

    The EDL defines delay changes at specific points. The mode determines how
    to handle subtitles that span multiple delay regions.

    Args:
        start_s: Subtitle start time in seconds
        end_s: Subtitle end time in seconds
        edl: Sorted list of AudioSegment objects
        mode: Boundary spanning mode - 'start', 'majority', or 'midpoint'

    Returns:
        int: Cumulative offset in milliseconds
    """
    # Helper function to get delay at a specific time
    def get_delay_at_time(time_s: float) -> int:
        if time_s < edl[0].start_s:
            return 0

        current_offset = 0
        for segment in edl:
            if segment.start_s <= time_s:
                current_offset = segment.delay_ms
            else:
                break
        return current_offset

    if mode == 'start':
        # Use start time only (original behavior)
        return get_delay_at_time(start_s)

    elif mode == 'midpoint':
        # Use the middle timestamp
        midpoint_s = (start_s + end_s) / 2.0
        return get_delay_at_time(midpoint_s)

    elif mode == 'majority':
        # Calculate which region the subtitle spends the most time in
        duration = end_s - start_s
        if duration <= 0:
            return get_delay_at_time(start_s)

        # Track duration in each delay region
        region_durations = {}

        # Build a list of all relevant boundaries
        boundaries = [seg.start_s for seg in edl] + [end_s]
        boundaries = sorted(set([b for b in boundaries if start_s <= b <= end_s]))

        # If no boundaries within subtitle range, it's entirely in one region
        if not boundaries or (len(boundaries) == 1 and boundaries[0] == end_s):
            return get_delay_at_time(start_s)

        # Calculate duration in each region
        current_time = start_s
        for boundary in boundaries:
            if boundary <= start_s:
                continue

            # Find which delay applies to this region
            region_delay = get_delay_at_time(current_time)

            # Calculate duration in this region
            segment_duration = min(boundary, end_s) - current_time

            if region_delay not in region_durations:
                region_durations[region_delay] = 0
            region_durations[region_delay] += segment_duration

            current_time = boundary
            if current_time >= end_s:
                break

        # Return the delay with the most duration
        if region_durations:
            return max(region_durations.items(), key=lambda x: x[1])[0]
        else:
            return get_delay_at_time(start_s)

    else:
        # Unknown mode, default to start
        return get_delay_at_time(start_s)
