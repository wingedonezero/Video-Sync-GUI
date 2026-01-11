# vsg_core/subtitles/sync_modes/timebase_frame_locked_timestamps.py
# -*- coding: utf-8 -*-
"""
Time-based + VideoTimestamps frame-locked subtitle synchronization mode.

This mode builds on the existing time-based sync logic and enhances it with
VideoTimestamps for deterministic frame-accurate alignment:

1. Start from time-based mode (audio correlation → global delay → raw offset)
2. Frame-align the global shift using TARGET video (integer number of frames)
3. Frame-snap each subtitle event using TARGET VideoTimestamps
4. Preserve durations while ensuring frame correctness
5. Post-ASS-quantization validation with safety checks

CRITICAL RULE: VideoTimestamps MUST use TARGET video only (never SOURCE).
The TARGET video defines the authoritative frame timeline.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
import pysubs2
import math
from fractions import Fraction
from ..metadata_preserver import SubtitleMetadata
from ..frame_utils import get_vfr_timestamps


def _frame_align_global_shift(
    global_delay_ms: float,
    target_video: str,
    target_fps: float,
    runner,
    config: dict
) -> float:
    """
    Convert global delay to a frame-aligned value using TARGET VideoTimestamps.

    This ensures the global shift is an integer number of TARGET frames,
    preventing fractional-frame drift over long content.

    Args:
        global_delay_ms: Raw global delay from correlation (milliseconds)
        target_video: Path to TARGET video file
        target_fps: TARGET video frame rate
        runner: CommandRunner for logging
        config: Config dict with VideoTimestamps settings

    Returns:
        Frame-aligned delay in milliseconds (exact TARGET frame start time)
    """
    try:
        from video_timestamps import TimeType

        # Get VideoTimestamps handler for TARGET video
        vts = get_vfr_timestamps(target_video, target_fps, runner, config)
        if vts is None:
            runner._log_message("[FrameLocked] WARNING: VideoTimestamps unavailable, using raw delay")
            return global_delay_ms

        # Convert delay to TARGET frame index
        delay_frac = Fraction(int(global_delay_ms), 1)
        target_frame = vts.time_to_frame(delay_frac, TimeType.EXACT)

        # Convert back to exact TARGET frame START time
        frame_aligned_ms = vts.frame_to_time(target_frame, TimeType.START)

        runner._log_message(f"[FrameLocked] Raw global delay: {global_delay_ms:+.3f}ms")
        runner._log_message(f"[FrameLocked] Aligned to TARGET frame {target_frame}: {float(frame_aligned_ms):+.3f}ms")
        runner._log_message(f"[FrameLocked] Frame alignment delta: {float(frame_aligned_ms) - global_delay_ms:+.3f}ms")

        return float(frame_aligned_ms)

    except Exception as e:
        runner._log_message(f"[FrameLocked] WARNING: Frame alignment failed: {e}")
        runner._log_message(f"[FrameLocked] Falling back to raw delay")
        return global_delay_ms


def _frame_snap_subtitle_event(
    event,
    vts,
    runner,
    stats: Dict[str, int]
):
    """
    Frame-snap a single subtitle event using TARGET VideoTimestamps.

    Process:
    1. Snap start time to TARGET frame START boundary
    2. Preserve duration by adjusting end with same delta
    3. Safety check: If end lands in same/earlier frame, push to next frame

    Args:
        event: pysubs2.SSAEvent object
        vts: VideoTimestamps handler (from TARGET video)
        runner: CommandRunner for logging
        stats: Dict to track snapping statistics

    Modifies event.start and event.end in place.
    """
    try:
        from video_timestamps import TimeType

        original_start = event.start
        original_end = event.end
        original_duration = original_end - original_start

        # 1. Snap START to TARGET frame boundary
        start_frac = Fraction(int(event.start), 1)
        start_frame = vts.time_to_frame(start_frac, TimeType.EXACT)  # Which frame does start land in?
        snapped_start_ms = vts.frame_to_time(start_frame, TimeType.START)  # Exact frame start

        # 2. Preserve duration
        start_delta = float(snapped_start_ms) - original_start
        snapped_end_ms = original_end + start_delta

        # 3. Safety check: Ensure end is in a later frame than start
        end_frac = Fraction(int(snapped_end_ms), 1)
        end_frame = vts.time_to_frame(end_frac, TimeType.EXACT)

        if end_frame <= start_frame:
            # End is in same or earlier frame - push to next frame START
            snapped_end_ms = vts.frame_to_time(start_frame + 1, TimeType.START)
            stats['duration_adjusted'] += 1
            runner._log_message(
                f"[FrameLocked] Event at {original_start}ms: End pushed to next frame "
                f"(was frame {end_frame}, now frame {start_frame + 1})"
            )

        # Apply snapped times
        event.start = int(snapped_start_ms)
        event.end = int(snapped_end_ms)

        # Track statistics
        if abs(start_delta) > 0.5:  # If start moved more than 0.5ms
            stats['start_snapped'] += 1
        if abs((event.end - event.start) - original_duration) > 0.5:  # If duration changed
            stats['duration_changed'] += 1

    except Exception as e:
        runner._log_message(f"[FrameLocked] WARNING: Frame snap failed for event at {event.start}ms: {e}")
        # Keep original times if snapping fails


def _validate_post_ass_quantization(
    subs,
    vts,
    runner,
    stats: Dict[str, int]
):
    """
    Validate frame alignment after ASS centisecond quantization.

    pysubs2 automatically rounds to centiseconds (10ms) when saving ASS files.
    This can break frame alignment. We re-check and fix if needed.

    Args:
        subs: pysubs2.SSAFile object (after loading from saved file)
        vts: VideoTimestamps handler (from TARGET video)
        runner: CommandRunner for logging
        stats: Dict to track validation statistics

    Modifies event times in place if quantization broke frame alignment.
    """
    try:
        from video_timestamps import TimeType

        for event in subs.events:
            original_start = event.start
            original_end = event.end

            # Check if start is at or after its TARGET frame start boundary
            start_frac = Fraction(int(event.start), 1)
            start_frame = vts.time_to_frame(start_frac, TimeType.EXACT)
            frame_start_ms = vts.frame_to_time(start_frame, TimeType.START)

            # If start is before frame boundary, snap forward
            if event.start < frame_start_ms:
                event.start = int(frame_start_ms)
                stats['post_ass_start_fixed'] += 1
                runner._log_message(
                    f"[FrameLocked] Post-ASS fix: Start {original_start}ms → {event.start}ms "
                    f"(snapped to frame {start_frame} boundary)"
                )

            # Check if end is after start (safety check)
            if event.end <= event.start:
                # Push end to next frame
                event.end = int(vts.frame_to_time(start_frame + 1, TimeType.START))
                stats['post_ass_end_fixed'] += 1
                runner._log_message(
                    f"[FrameLocked] Post-ASS fix: End {original_end}ms → {event.end}ms "
                    f"(pushed to frame {start_frame + 1})"
                )

    except Exception as e:
        runner._log_message(f"[FrameLocked] WARNING: Post-ASS validation failed: {e}")


def apply_timebase_frame_locked_sync(
    subtitle_path: str,
    total_delay_with_global_ms: float,
    raw_global_shift_ms: float,
    target_video: str,
    target_fps: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Apply time-based sync enhanced with VideoTimestamps frame locking.

    Pipeline:
    1. Load subtitle file with metadata preservation
    2. Frame-align the global shift using TARGET video
    3. Apply frame-aligned delay to all events
    4. Frame-snap each event using TARGET VideoTimestamps
    5. Save to ASS (auto-quantizes to centiseconds)
    6. Reload and validate frame alignment
    7. Re-save if fixes were needed

    Args:
        subtitle_path: Path to subtitle file (will be modified in place)
        total_delay_with_global_ms: Total delay including global shift (raw float)
        raw_global_shift_ms: Raw global shift (for breakdown logging)
        target_video: Path to TARGET video file
        target_fps: TARGET video frame rate
        runner: CommandRunner for logging
        config: Optional config dict with VideoTimestamps settings

    Returns:
        Report dict with statistics
    """
    config = config or {}

    runner._log_message(f"[FrameLocked] ========================================")
    runner._log_message(f"[FrameLocked] Time-Based + Frame-Locked Timestamps Sync")
    runner._log_message(f"[FrameLocked] ========================================")
    runner._log_message(f"[FrameLocked] Subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[FrameLocked] TARGET video: {Path(target_video).name} ({target_fps:.3f} fps)")

    # Validate VideoTimestamps is available
    try:
        from video_timestamps import FPSTimestamps, VideoTimestamps, TimeType, RoundingMethod
    except ImportError:
        runner._log_message("[FrameLocked] ERROR: VideoTimestamps not installed")
        runner._log_message("[FrameLocked] Install with: pip install VideoTimestamps")
        return {'error': 'VideoTimestamps library not installed'}

    # Get VideoTimestamps handler for TARGET video
    vts = get_vfr_timestamps(target_video, target_fps, runner, config)
    if vts is None:
        runner._log_message("[FrameLocked] ERROR: Failed to create VideoTimestamps handler")
        return {'error': 'Failed to create VideoTimestamps handler'}

    # Capture original metadata
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[FrameLocked] ERROR: Failed to load subtitle file: {e}")
        return {'error': str(e)}

    if not subs.events:
        runner._log_message(f"[FrameLocked] WARNING: No subtitle events found")
        return {
            'total_events': 0,
            'error': 'No subtitle events found'
        }

    runner._log_message(f"[FrameLocked] Loaded {len(subs.events)} subtitle events")

    # Step 1: Frame-align the global shift
    frame_aligned_delay = _frame_align_global_shift(
        total_delay_with_global_ms,
        target_video,
        target_fps,
        runner,
        config
    )

    # Step 2: Apply frame-aligned delay to all events
    delay_int = int(frame_aligned_delay)
    runner._log_message(f"[FrameLocked] Applying frame-aligned delay: {delay_int:+d}ms to all events")

    for event in subs.events:
        event.start += delay_int
        event.end += delay_int

    # Step 3: Frame-snap each event using TARGET VideoTimestamps
    runner._log_message(f"[FrameLocked] Frame-snapping {len(subs.events)} events to TARGET video frames...")

    stats = {
        'total_events': len(subs.events),
        'start_snapped': 0,
        'duration_changed': 0,
        'duration_adjusted': 0,
        'post_ass_start_fixed': 0,
        'post_ass_end_fixed': 0,
        'frame_aligned_delay_ms': float(frame_aligned_delay),
        'raw_delay_ms': total_delay_with_global_ms,
        'alignment_delta_ms': float(frame_aligned_delay) - total_delay_with_global_ms
    }

    for event in subs.events:
        _frame_snap_subtitle_event(event, vts, runner, stats)

    runner._log_message(f"[FrameLocked] Snapping complete:")
    runner._log_message(f"[FrameLocked]   - Events with start snapped: {stats['start_snapped']}/{stats['total_events']}")
    runner._log_message(f"[FrameLocked]   - Events with duration changed: {stats['duration_changed']}/{stats['total_events']}")
    runner._log_message(f"[FrameLocked]   - Events with duration adjusted (safety): {stats['duration_adjusted']}/{stats['total_events']}")

    # Step 4: Save to ASS (pysubs2 auto-quantizes to centiseconds)
    runner._log_message(f"[FrameLocked] Saving subtitle file (ASS centisecond quantization will occur)...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[FrameLocked] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Restore metadata if needed
    if metadata.validate(subtitle_path):
        runner._log_message(f"[FrameLocked] Metadata preserved successfully")
    else:
        runner._log_message(f"[FrameLocked] Restoring lost metadata...")
        metadata.restore(subtitle_path)

    # Step 5: Reload and validate frame alignment (post-ASS-quantization check)
    runner._log_message(f"[FrameLocked] Reloading subtitle for post-ASS validation...")
    try:
        subs_reloaded = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[FrameLocked] WARNING: Failed to reload for validation: {e}")
        return stats  # Return stats from initial processing

    _validate_post_ass_quantization(subs_reloaded, vts, runner, stats)

    # Step 6: Re-save if fixes were applied
    if stats['post_ass_start_fixed'] > 0 or stats['post_ass_end_fixed'] > 0:
        runner._log_message(f"[FrameLocked] Re-saving after post-ASS fixes...")
        runner._log_message(f"[FrameLocked]   - Start times fixed: {stats['post_ass_start_fixed']}")
        runner._log_message(f"[FrameLocked]   - End times fixed: {stats['post_ass_end_fixed']}")

        try:
            subs_reloaded.save(subtitle_path, encoding='utf-8')
            metadata.restore(subtitle_path)  # Restore metadata again
        except Exception as e:
            runner._log_message(f"[FrameLocked] WARNING: Failed to re-save: {e}")
    else:
        runner._log_message(f"[FrameLocked] No post-ASS fixes needed - frame alignment maintained!")

    runner._log_message(f"[FrameLocked] ========================================")
    runner._log_message(f"[FrameLocked] Sync complete!")
    runner._log_message(f"[FrameLocked] ========================================")

    return stats
