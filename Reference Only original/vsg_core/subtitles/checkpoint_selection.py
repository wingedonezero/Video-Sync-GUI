# vsg_core/subtitles/checkpoint_selection.py
# -*- coding: utf-8 -*-
"""
Smart checkpoint selection for subtitle sync verification.

Selects representative dialogue events while avoiding OP/ED sequences.
"""
from typing import List


def select_smart_checkpoints(subtitle_events: List, runner) -> List:
    """
    Smart checkpoint selection: avoid OP/ED, prefer dialogue events.

    Strategy:
    - Filter out first/last 2 minutes (OP/ED likely)
    - Prefer longer duration events (likely dialogue, not signs)
    - Use repeatable selection based on event count
    - Return 3 checkpoints: early (1/6), middle (1/2), late (5/6)

    Args:
        subtitle_events: List of subtitle events to select from
        runner: CommandRunner for logging

    Returns:
        List of selected subtitle events (typically 3)
    """
    total_events = len(subtitle_events)
    if total_events == 0:
        return []

    # Calculate video duration to determine safe zones
    first_start = subtitle_events[0].start
    last_end = subtitle_events[-1].end
    duration_ms = last_end - first_start

    # Define safe zone: skip first/last 2 minutes (120000ms)
    op_zone_ms = 120000  # First 2 minutes
    ed_zone_ms = 120000  # Last 2 minutes

    safe_start_ms = first_start + op_zone_ms
    safe_end_ms = last_end - ed_zone_ms

    # If video is too short, just use middle third
    if duration_ms < (op_zone_ms + ed_zone_ms):
        safe_start_ms = first_start + (duration_ms // 3)
        safe_end_ms = last_end - (duration_ms // 3)

    # Filter events in safe zone
    safe_events = [e for e in subtitle_events if safe_start_ms <= e.start <= safe_end_ms]

    if len(safe_events) < 3:
        # Not enough safe events, fall back to middle third of all events
        start_idx = total_events // 3
        end_idx = 2 * total_events // 3
        safe_events = subtitle_events[start_idx:end_idx]
        runner._log_message(f"[Checkpoint Selection] Using middle third (not enough events in safe zone)")

    if len(safe_events) == 0:
        # Last resort: use first/mid/last of all events
        return [subtitle_events[0], subtitle_events[total_events // 2], subtitle_events[-1]]

    # Prefer longer duration events (dialogue over signs)
    # Sort by duration descending, take top 40%
    sorted_by_duration = sorted(safe_events, key=lambda e: e.end - e.start, reverse=True)
    top_events = sorted_by_duration[:max(3, len(sorted_by_duration) * 40 // 100)]

    # Sort these back by start time for temporal ordering
    top_events_sorted = sorted(top_events, key=lambda e: e.start)

    if len(top_events_sorted) >= 3:
        # Pick early (1/6), middle (1/2), late (5/6)
        early = top_events_sorted[len(top_events_sorted) // 6]
        middle = top_events_sorted[len(top_events_sorted) // 2]
        late = top_events_sorted[5 * len(top_events_sorted) // 6]
        checkpoints = [early, middle, late]
    elif len(top_events_sorted) == 2:
        checkpoints = top_events_sorted
    else:
        checkpoints = top_events_sorted

    runner._log_message(f"[Checkpoint Selection] Selected {len(checkpoints)} dialogue events:")
    for i, e in enumerate(checkpoints):
        duration = e.end - e.start
        runner._log_message(f"  {i+1}. Time: {e.start}ms, Duration: {duration}ms")

    return checkpoints
