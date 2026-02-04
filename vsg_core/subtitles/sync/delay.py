# vsg_core/subtitles/sync/delay.py
"""
Core delay application logic for subtitle synchronization.

This module consolidates the duplicate delay application loop found in:
- time_based.py (lines 98-117)
- duration_align.py (lines 315-335)
- correlation_frame_snap.py (lines 213-233)
- video_verified.py (lines 1122-1140)
- subtitle_anchored_frame_snap.py (lines 322-342)
- correlation_guided_frame_anchor.py (lines 390-430)
- timebase_frame_locked.py (lines 149-190)
- subtitles_step.py (bitmap subtitle handling)

All timing is float ms internally - rounding happens only at final save.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..data import SubtitleData


@dataclass(frozen=True, slots=True)
class DelayResult:
    """Result of applying delay to subtitle events."""

    events_modified: int
    events_skipped: int
    total_events: int


def apply_delay(
    subtitle_data: SubtitleData,
    delay_ms: float,
    *,
    exclude_styles: list[str] | None = None,
    include_styles: list[str] | None = None,
    skip_comments: bool = True,
    log: Callable[[str], None] | None = None,
) -> DelayResult:
    """
    Apply a delay offset to subtitle events.

    This is the core delay application used by all sync modes.
    Modifies subtitle_data in place, populates SyncEventData on each event.

    Args:
        subtitle_data: SubtitleData to modify
        delay_ms: Delay in milliseconds (positive = later, negative = earlier)
        exclude_styles: If set, skip events with these styles
        include_styles: If set, only modify events with these styles
                       (mutually exclusive with exclude_styles)
        skip_comments: If True (default), skip comment events
        log: Optional logging function (passed from step)

    Returns:
        DelayResult with counts of modified/skipped events
    """
    from ..data import SyncEventData

    if log:
        log(f"[Delay] Applying {delay_ms:+.3f}ms to events")

    modified = 0
    skipped = 0
    total = len(subtitle_data.events)

    for event in subtitle_data.events:
        # Skip comments if configured
        if skip_comments and event.is_comment:
            skipped += 1
            continue

        # Check style exclusion/inclusion
        if exclude_styles and event.style in exclude_styles:
            skipped += 1
            continue

        if include_styles and event.style not in include_styles:
            skipped += 1
            continue

        # Store original values
        original_start = event.start_ms
        original_end = event.end_ms

        # Apply delay
        event.start_ms += delay_ms
        event.end_ms += delay_ms

        # Populate per-event sync metadata
        event.sync = SyncEventData(
            original_start_ms=original_start,
            original_end_ms=original_end,
            start_adjustment_ms=delay_ms,
            end_adjustment_ms=delay_ms,
            snapped_to_frame=False,
        )

        modified += 1

    if log:
        log(f"[Delay] Modified {modified} events, skipped {skipped}")

    return DelayResult(
        events_modified=modified,
        events_skipped=skipped,
        total_events=total,
    )
