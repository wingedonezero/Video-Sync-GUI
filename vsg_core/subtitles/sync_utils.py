# vsg_core/subtitles/sync_utils.py
"""
Shared utilities for subtitle sync operations.

Extracts common patterns used across multiple sync plugins to avoid duplication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from .data import SubtitleData
    from .frame_utils.frame_clock import FrameClock
    from .frame_utils.frame_table import FrameGrid, FrameShift, FrameTable


def build_frame_shift(
    load_source: Callable[[], FrameTable | None],
    target: FrameGrid | None,
    target_clock: FrameClock | None,
    details: Mapping[str, Any],  # Any: sliding-matcher details dict (JSON-like)
    global_shift_ms: float,
    log: Callable[[str], None],
    warn: Callable[[str], None],
    *,
    fallback: bool = False,
) -> FrameShift | None:
    """Construct an exact whole-frame shift, or None when a flat delay is correct.

    Eligible only when: the offset really came from sliding frame matching (not
    a correlation fallback), there is no sub-frame global shift, both videos'
    real frame timestamps are available, and the matched frame offset holds
    on both timelines (``matched_frame_range``: no holes, same rate, agrees
    with the measured wall-clock offset) - file-wide, or up to a break that
    comes after every picture the matcher compared, past which times take the
    flat delay. Different start offsets are fine — frames are paired by index,
    so each snap lands on the real target frame time. Anything else returns None and events take the flat
    millisecond delay exactly as before. Shared by the cached dispatcher path
    and the inline plugin path. ``load_source`` reads the source video's frame
    timestamps; it is only called once the cheap gates pass.

    If real frame times cannot be read at all, the old CFR-formula snap (with
    its old rules) is the backup — that should never happen for progressive
    sources, so it is reported through ``warn`` (final audit warning). When
    real times DO show the offset is wrong (holes, rate mismatch), there is no
    fallback: the flat delay is the correct answer there.
    """
    from .frame_grids import matched_frame_range
    from .frame_utils.frame_table import FrameShift, FrameTable

    if fallback or details.get("reason") != "sliding-matched":
        return None
    if global_shift_ms != 0.0:
        return None
    if not isinstance(target, FrameTable):
        return _formula_frame_shift(
            target_clock, details, log, warn, "Source 1's real frame times unreadable"
        )
    source = load_source()
    if source is None:
        return _formula_frame_shift(
            target_clock, details, log, warn, "the source's real frame times unreadable"
        )
    match = matched_frame_range(source, target, details, log, allow_tail=True)
    if match is None:
        return None
    return FrameShift(
        source=source, target=target, frames=match.frames, source_end=match.source_end
    )


def _formula_frame_shift(
    clock: FrameClock | None,
    details: Mapping[str, Any],  # Any: sliding-matcher details dict (JSON-like)
    log: Callable[[str], None],
    warn: Callable[[str], None],
    why: str,
) -> FrameShift | None:
    """The pre-real-timestamp snap: Source 1's CFR formula, shared PTS origin only."""
    from .frame_utils.frame_table import FrameShift

    frames = details.get("frame_offset")
    if clock is None or not isinstance(frames, int):
        log(f"[Sync]   No exact frame snap: {why}")
        return None
    if details.get("pts_delta_frames", 0) != 0:
        log(f"[Sync]   No exact frame snap: {why}; files start at different times")
        return None
    warn(
        f"Exact frame snap fell back to the {clock.label} ({why}) - "
        f"check frame-locked subtitles"
    )
    return FrameShift(source=clock, target=clock, frames=frames)


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
    is given (a verified whole-frame offset between two real frame timelines),
    any timestamp sitting exactly on a source frame ``k`` moves to the real time
    of Source 1 frame ``k + N``, so frame-locked subtitles (PGS/OCR) land dead-on
    the target frame instead of ~1ms off from a float-millisecond shift.
    Timestamps not on a frame still take the flat ``delay_ms``. The caller only
    passes a ``frame_shift`` when ``build_frame_shift`` verified it; otherwise
    it is ``None`` and behaviour is the flat delay exactly as before.

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
