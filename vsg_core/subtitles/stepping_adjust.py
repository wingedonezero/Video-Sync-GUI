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
import math
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
        spanning_details = []  # Detailed info for boundary-spanning subs

        # Process each subtitle
        for idx, event in enumerate(subs):
            # Get original timestamps (pysubs2 uses milliseconds)
            original_start_ms = event.start
            original_end_ms = event.end
            original_start_s = original_start_ms / 1000.0
            original_end_s = original_end_ms / 1000.0

            # Calculate cumulative offset based on boundary mode (returns raw float)
            offset_raw = _get_offset_at_time(original_start_s, original_end_s, sorted_edl, boundary_mode)

            # Check if this subtitle spans a boundary (for stats and logging)
            spanning_info = _get_spanning_details(original_start_s, original_end_s, sorted_edl)
            if spanning_info:
                spanning_count += 1
                # Get subtitle text preview (first 40 chars, clean of tags)
                text_preview = event.plaintext[:40].replace('\n', ' ') if hasattr(event, 'plaintext') else event.text[:40].replace('\n', ' ')
                if len(event.plaintext if hasattr(event, 'plaintext') else event.text) > 40:
                    text_preview += "..."
                spanning_details.append({
                    'index': idx + 1,
                    'start_s': original_start_s,
                    'end_s': original_end_s,
                    'boundaries_crossed': spanning_info['boundaries'],
                    'delay_applied_ms': int(math.floor(offset_raw)) if offset_raw != 0.0 else 0,
                    'text': text_preview
                })

            # Apply offset with floor() at final step (single rounding point)
            if offset_raw != 0.0:
                offset_ms = int(math.floor(offset_raw))
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
                f"[SteppingAdjust] {spanning_count} subtitle(s) span stepping boundaries:"
            )
            # Log details for each spanning subtitle (limit to first 10 to avoid log spam)
            for detail in spanning_details[:10]:
                boundaries_str = ", ".join([f"{b:.1f}s" for b in detail['boundaries_crossed']])
                runner._log_message(
                    f"[SteppingAdjust]   - #{detail['index']} [{detail['start_s']:.1f}s-{detail['end_s']:.1f}s]: "
                    f"crosses [{boundaries_str}], applied {detail['delay_applied_ms']:+d}ms "
                    f"| \"{detail['text']}\""
                )
            if len(spanning_details) > 10:
                runner._log_message(
                    f"[SteppingAdjust]   ... and {len(spanning_details) - 10} more boundary-spanning subtitles"
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


def _get_spanning_details(start_s: float, end_s: float, edl: List) -> dict:
    """
    Get details about which boundaries a subtitle spans.

    Args:
        start_s: Subtitle start time in seconds
        end_s: Subtitle end time in seconds
        edl: Sorted list of AudioSegment objects

    Returns:
        dict with 'boundaries' list if subtitle spans boundaries, None otherwise
    """
    if len(edl) <= 1:
        return None

    # Find all boundaries that fall within [start_s, end_s]
    crossed_boundaries = []
    for segment in edl[1:]:  # Skip first segment (always at 0.0s)
        if start_s < segment.start_s < end_s:
            crossed_boundaries.append(segment.start_s)

    if crossed_boundaries:
        return {'boundaries': crossed_boundaries}
    return None


def _get_offset_at_time(start_s: float, end_s: float, edl: List, mode: str = 'start') -> float:
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
        float: Cumulative offset in milliseconds (raw, unrounded)
    """
    # Helper function to get cumulative offset at a specific time
    def get_cumulative_offset_at_time(time_s: float) -> float:
        """
        Calculate cumulative offset from stepping corrections (insertions/removals).

        This mimics what the audio assembly does: sum up all the (segment.delay - previous.delay)
        for segments before the given time.
        """
        if time_s < edl[0].start_s:
            return 0.0

        # Start with no offset (first segment is the baseline)
        cumulative_offset = 0.0
        base_delay = edl[0].delay_raw

        for i in range(1, len(edl)):
            segment = edl[i]
            if segment.start_s <= time_s:
                # Add the difference (this is what gets inserted/removed)
                segment_delay_raw = getattr(segment, 'delay_raw', float(segment.delay_ms))
                cumulative_offset += (segment_delay_raw - base_delay)
                base_delay = segment_delay_raw
            else:
                break

        return cumulative_offset

    if mode == 'start':
        # Use start time only (original behavior)
        return get_cumulative_offset_at_time(start_s)

    elif mode == 'midpoint':
        # Use the middle timestamp
        midpoint_s = (start_s + end_s) / 2.0
        return get_cumulative_offset_at_time(midpoint_s)

    elif mode == 'majority':
        # Calculate which region the subtitle spends the most time in
        duration = end_s - start_s
        if duration <= 0:
            return get_cumulative_offset_at_time(start_s)

        # Track duration in each delay region (keyed by raw delay)
        region_durations = {}

        # Build a list of all relevant boundaries
        boundaries = [seg.start_s for seg in edl] + [end_s]
        boundaries = sorted(set([b for b in boundaries if start_s <= b <= end_s]))

        # If no boundaries within subtitle range, it's entirely in one region
        if not boundaries or (len(boundaries) == 1 and boundaries[0] == end_s):
            return get_cumulative_offset_at_time(start_s)

        # Calculate duration in each region
        current_time = start_s
        for boundary in boundaries:
            if boundary <= start_s:
                continue

            # Find which delay applies to this region
            region_delay = get_cumulative_offset_at_time(current_time)

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
            return get_cumulative_offset_at_time(start_s)

    else:
        # Unknown mode, default to start
        return get_cumulative_offset_at_time(start_s)
