# vsg_core/subtitles/sync_utils.py
"""
Shared utilities for subtitle sync operations.

Extracts common patterns used across multiple sync plugins to avoid duplication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .data import SubtitleData


def apply_delay_to_events(
    subtitle_data: SubtitleData,
    delay_ms: float,
    snapped_to_frame: bool = False,
) -> int:
    """
    Apply a flat delay to all non-comment subtitle events.

    Updates each event's start_ms/end_ms and populates SyncEventData metadata.

    Args:
        subtitle_data: SubtitleData containing events to modify (modified in place).
        delay_ms: Delay in milliseconds to add to each event's timestamps.
        snapped_to_frame: Whether this delay was derived from frame alignment.

    Returns:
        Number of events modified (excludes comments).
    """
    from .data import SyncEventData

    events_synced = 0

    for event in subtitle_data.events:
        if event.is_comment:
            continue

        original_start = event.start_ms
        original_end = event.end_ms

        event.start_ms += delay_ms
        event.end_ms += delay_ms

        event.sync = SyncEventData(
            original_start_ms=original_start,
            original_end_ms=original_end,
            start_adjustment_ms=delay_ms,
            end_adjustment_ms=delay_ms,
            snapped_to_frame=snapped_to_frame,
        )

        events_synced += 1

    return events_synced
