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


def apply_stepping_to_subtitles(subtitle_path: str, edl: List, runner) -> dict:
    """
    Apply stepping correction EDL (Edit Decision List) to subtitle timestamps.

    The EDL contains AudioSegment entries that define delay changes across the timeline.
    For each subtitle, we calculate the cumulative offset at its timestamp and shift it.

    Args:
        subtitle_path: Path to the subtitle file
        edl: List of AudioSegment objects from stepping correction
        runner: Runner object for logging

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
        # Load subtitles
        subs = pysubs2.load(subtitle_path, encoding='utf-8')

        if len(subs) == 0:
            runner._log_message(f"[SteppingAdjust] No subtitles found in file")
            return {}

        # Sort EDL by start time (should already be sorted, but just in case)
        sorted_edl = sorted(edl, key=lambda seg: seg.start_s)

        # Counters for report
        adjusted_count = 0
        max_adjustment_ms = 0

        # Process each subtitle
        for event in subs:
            # Get original timestamps (pysubs2 uses milliseconds)
            original_start_ms = event.start
            original_end_ms = event.end

            # Calculate cumulative offset at this subtitle's start time
            offset_ms = _get_offset_at_time(original_start_ms / 1000.0, sorted_edl)

            # Apply offset
            if offset_ms != 0:
                event.start += offset_ms
                event.end += offset_ms
                adjusted_count += 1
                max_adjustment_ms = max(max_adjustment_ms, abs(offset_ms))

        # Save adjusted subtitles
        subs.save(subtitle_path, encoding='utf-8')

        # Build report
        report = {
            'total_subtitles': len(subs),
            'adjusted_count': adjusted_count,
            'max_adjustment_ms': max_adjustment_ms,
            'edl_segments': len(sorted_edl)
        }

        runner._log_message(
            f"[SteppingAdjust] Adjusted {adjusted_count}/{len(subs)} subtitles. "
            f"Max adjustment: {max_adjustment_ms:+d}ms"
        )

        return report

    except Exception as e:
        runner._log_message(f"[SteppingAdjust] Error adjusting subtitles: {e}")
        return {'error': str(e)}


def _get_offset_at_time(time_s: float, edl: List) -> int:
    """
    Calculate the cumulative offset (in milliseconds) at a given time.

    The EDL defines delay changes at specific points. We find which segment
    the given time falls into and return that segment's delay.

    Args:
        time_s: Time in seconds
        edl: Sorted list of AudioSegment objects

    Returns:
        int: Cumulative offset in milliseconds
    """
    # If time is before first segment, no offset
    if time_s < edl[0].start_s:
        return 0

    # Find the appropriate segment
    # We want the last segment whose start_s <= time_s
    current_offset = 0
    for segment in edl:
        if segment.start_s <= time_s:
            current_offset = segment.delay_ms
        else:
            # We've passed the time, use previous segment's delay
            break

    return current_offset
