# vsg_core/subtitles/sync_utils.py
"""
Shared utilities for subtitle sync operations.

Extracts common patterns used across multiple sync plugins to avoid duplication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .data import SubtitleData
    from .frame_utils.frame_clock import FrameClock, FrameShift


def build_frame_shift(
    clock: FrameClock | None,
    details: dict,
    global_shift_ms: float,
    *,
    fallback: bool = False,
) -> FrameShift | None:
    """Construct an exact whole-frame shift, or None when a flat delay is correct.

    Eligible only when: the target has an exact CFR clock, the offset really came
    from sliding frame matching (not a correlation fallback), it is a known
    integer frame count, the two videos share the same PTS origin
    (``pts_delta_frames == 0``), and there is no sub-frame global shift. Anything
    else returns None, so events take the flat millisecond delay exactly as
    before. Shared by the cached dispatcher path and the inline plugin path.
    """
    if clock is None or fallback:
        return None
    if details.get("reason") != "sliding-matched":
        return None
    frames = details.get("frame_offset")
    if not isinstance(frames, int):
        return None
    if details.get("pts_delta_frames", 0) != 0:
        return None
    if global_shift_ms != 0.0:
        return None
    from .frame_utils.frame_clock import FrameShift

    return FrameShift(clock=clock, frames=frames)


def apply_delay_to_events(
    subtitle_data: SubtitleData,
    delay_ms: float,
    snapped_to_frame: bool = False,
    *,
    frame_shift: FrameShift | None = None,
) -> int:
    """
    Apply a delay to all non-comment subtitle events.

    Updates each event's start_ms/end_ms and populates SyncEventData metadata.

    By default every event is moved by a flat ``delay_ms``. When ``frame_shift``
    is given (a pure whole-frame offset on an exact CFR grid), any timestamp that
    sits exactly on a frame is moved by *frames* — to ``clock.frame_ms(k + N)`` —
    so frame-locked subtitles (PGS/OCR) land dead-on the target frame instead of
    ~1ms off from a float-millisecond shift. Timestamps not on a frame still take
    the flat ``delay_ms``. The caller only passes a ``frame_shift`` when the move
    is genuinely whole-frame on a shared grid (frame-matched source, no sub-frame
    global shift, same PTS origin); otherwise it is ``None`` and behaviour is the
    flat delay exactly as before.

    Args:
        subtitle_data: SubtitleData containing events to modify (modified in place).
        delay_ms: Delay in milliseconds to add to each event's timestamps.
        snapped_to_frame: Whether this delay was derived from frame alignment.
        frame_shift: Optional exact whole-frame shift for on-frame values.

    Returns:
        Number of events modified (excludes comments).
    """
    from .data import SyncEventData

    events_synced = 0
    snapped_flag = snapped_to_frame or frame_shift is not None

    for event in subtitle_data.events:
        if event.is_comment:
            continue

        original_start = event.start_ms
        original_end = event.end_ms

        if frame_shift is not None:
            event.start_ms = frame_shift.shifted_ms(original_start, delay_ms)
            event.end_ms = frame_shift.shifted_ms(original_end, delay_ms)
        else:
            event.start_ms = original_start + delay_ms
            event.end_ms = original_end + delay_ms

        event.sync = SyncEventData(
            original_start_ms=original_start,
            original_end_ms=original_end,
            start_adjustment_ms=event.start_ms - original_start,
            end_adjustment_ms=event.end_ms - original_end,
            snapped_to_frame=snapped_flag,
        )

        events_synced += 1

    return events_synced
