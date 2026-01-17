# vsg_core/subtitles/timing.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from collections import defaultdict
import pysubs2
from .metadata_preserver import SubtitleMetadata

def fix_subtitle_timing(subtitle_path: str, config: dict, runner) -> dict:
    """
    Applies various timing corrections to a subtitle file based on config.

    Order of operations (critical for correctness):
    1. Fix long durations first (trim excess display time)
    2. Fix overlaps (adjust end times to prevent overlap)
    3. Fix short durations last (extend to minimum reading time)

    This order ensures we don't create new problems while fixing others.
    """
    # Skip binary subtitle formats
    from pathlib import Path
    file_ext = Path(subtitle_path).suffix.lower()
    if file_ext in ['.sub', '.idx', '.sup']:
        # These are binary formats that can't be processed
        runner._log_message(f"[TimingFix] Skipping binary subtitle format: {file_ext}")
        return {}

    # Only process text-based subtitle formats
    if file_ext not in ['.srt', '.ass', '.ssa', '.vtt']:
        runner._log_message(f"[TimingFix] Unsupported subtitle format: {file_ext}")
        return {}

    try:
        # Capture original metadata before pysubs2 processing
        metadata = SubtitleMetadata(subtitle_path)
        metadata.capture()

        subs = pysubs2.load(subtitle_path, encoding='utf-8')
        report = defaultdict(int)

        # 1. Fix long durations FIRST
        # This trims subtitles that stay on screen too long for their text length
        if config.get('timing_fix_long_durations', False):
            fixed_count = fix_long_durations(
                subs,
                config.get('timing_max_cps', 20.0),
                config.get('timing_min_duration_ms', 500)
            )
            if fixed_count > 0:
                report['long_durations_fixed'] = fixed_count

        # 2. Fix overlaps SECOND
        # Now that long durations are trimmed, fix any overlapping subtitles
        if config.get('timing_fix_overlaps', False):
            fixed_count = fix_overlaps(
                subs,
                config.get('timing_overlap_min_gap_ms', 1)
            )
            if fixed_count > 0:
                report['overlaps_fixed'] = fixed_count

        # 3. Fix short durations LAST
        # Finally, ensure all subtitles have minimum reading time
        # This won't create overlaps because we already fixed those
        if config.get('timing_fix_short_durations', False):
            fixed_count = fix_short_durations(
                subs,
                config.get('timing_min_duration_ms', 500)
            )
            if fixed_count > 0:
                report['short_durations_fixed'] = fixed_count

        if report:
            subs.save(subtitle_path, encoding='utf-8')
            runner._log_message(f"[TimingFix] Fixed {sum(report.values())} timing issues in '{subtitle_path}'")

            # Validate and restore lost metadata
            metadata.validate_and_restore(runner)

        return dict(report)

    except Exception as e:
        runner._log_message(f"[TimingFix] ERROR: Could not process file '{subtitle_path}': {e}")
        return {}


def fix_overlaps(subs: pysubs2.SSAFile, min_gap_ms: int = 1) -> int:
    """
    Fixes overlapping subtitles by adjusting the end time of the earlier subtitle.

    Args:
        subs: The subtitle file object
        min_gap_ms: Minimum gap in milliseconds between subtitles

    Returns:
        Number of overlaps fixed
    """
    fixed_count = 0
    events = sorted(subs.events, key=lambda e: e.start)  # Ensure chronological order

    for i in range(len(events) - 1):
        current = events[i]
        next_sub = events[i + 1]

        # Check if current subtitle overlaps with the next one
        if current.end > next_sub.start:
            # Adjust end time to create the minimum gap
            new_end = next_sub.start - min_gap_ms

            # Only adjust if it doesn't make the subtitle too short
            # (preserve at least 100ms duration as emergency minimum)
            if new_end > current.start + 100:
                current.end = new_end
                fixed_count += 1

    return fixed_count


def fix_short_durations(subs: pysubs2.SSAFile, min_duration_ms: int = 500) -> int:
    """
    Fixes subtitles with display time shorter than the minimum duration.
    Extends the end time to meet the minimum.

    Args:
        subs: The subtitle file object
        min_duration_ms: Minimum duration in milliseconds

    Returns:
        Number of short durations fixed
    """
    fixed_count = 0
    events = sorted(subs.events, key=lambda e: e.start)

    for i, event in enumerate(events):
        duration = event.end - event.start

        # Check if duration is positive but too short
        if 0 < duration < min_duration_ms:
            # Calculate the new end time
            new_end = event.start + min_duration_ms

            # Check if extending would overlap with next subtitle
            if i + 1 < len(events):
                next_event = events[i + 1]
                # Leave at least 1ms gap to prevent overlap
                max_allowed_end = next_event.start - 1
                new_end = min(new_end, max_allowed_end)

            # Only extend if we can meaningfully improve the duration
            if new_end > event.end:
                event.end = new_end
                fixed_count += 1

    return fixed_count


def fix_long_durations(subs: pysubs2.SSAFile, max_cps: float = 20.0, min_duration_ms: int = 500) -> int:
    """
    Fixes subtitles that stay on screen longer than necessary based on reading speed.
    Trims the end time while respecting the minimum duration.

    Args:
        subs: The subtitle file object
        max_cps: Maximum characters per second (reading speed)
        min_duration_ms: Minimum duration to preserve

    Returns:
        Number of long durations fixed
    """
    if max_cps <= 0:
        return 0

    fixed_count = 0

    for event in subs.events:
        # Get the plain text without formatting tags
        plain_text = event.plaintext
        num_chars = len(plain_text.replace(' ', ''))  # Don't count spaces

        if num_chars > 0:
            # Calculate the ideal duration based on reading speed
            ideal_duration_ms = (num_chars / max_cps) * 1000

            # Add a small buffer (10%) for comfortable reading
            ideal_duration_ms *= 1.1

            # Ensure we don't go below minimum duration
            ideal_duration_ms = max(ideal_duration_ms, min_duration_ms)

            current_duration = event.end - event.start

            # Only trim if current duration is significantly longer than ideal
            # (add 100ms tolerance to avoid unnecessary adjustments)
            if current_duration > ideal_duration_ms + 100:
                event.end = event.start + int(ideal_duration_ms)
                fixed_count += 1

    return fixed_count


def calculate_reading_time(text: str, cps: float = 20.0) -> int:
    """
    Helper function to calculate optimal reading time for text.

    Args:
        text: The subtitle text
        cps: Characters per second reading speed

    Returns:
        Optimal duration in milliseconds
    """
    if cps <= 0:
        return 1000  # Default 1 second if invalid CPS

    # Count characters excluding spaces
    char_count = len(text.replace(' ', ''))

    # Calculate time in milliseconds
    time_ms = (char_count / cps) * 1000

    # Add 10% buffer for comfortable reading
    time_ms *= 1.1

    # Minimum 500ms for very short text
    return max(int(time_ms), 500)
