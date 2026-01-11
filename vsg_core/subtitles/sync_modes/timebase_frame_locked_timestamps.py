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
    stats: Dict[str, int],
    sample_indices: set
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
        sample_indices: Set of event indices to log (for sampling across file)

    Modifies event.start and event.end in place.
    """
    try:
        from video_timestamps import TimeType

        original_start = event.start  # int (milliseconds)
        original_end = event.end      # int (milliseconds)
        original_duration = original_end - original_start

        # 1. Snap START to TARGET frame boundary
        start_frac = Fraction(int(event.start), 1)
        start_frame = vts.time_to_frame(start_frac, TimeType.EXACT)  # Which frame does start land in?
        snapped_start_frac = vts.frame_to_time(start_frame, TimeType.START)  # Exact frame start (Fraction)

        # Convert Fraction to float for calculations, then to int for pysubs2
        snapped_start_ms = int(float(snapped_start_frac))

        # 2. Preserve duration
        start_delta = snapped_start_ms - original_start
        snapped_end_ms = original_end + start_delta

        # 3. Safety check: Ensure end is in a later frame than start
        end_frac = Fraction(int(snapped_end_ms), 1)
        end_frame = vts.time_to_frame(end_frac, TimeType.EXACT)

        end_adjusted = False
        if end_frame <= start_frame:
            # End is in same or earlier frame - push to next frame START
            snapped_end_frac = vts.frame_to_time(start_frame + 1, TimeType.START)
            snapped_end_ms = int(float(snapped_end_frac))
            stats['duration_adjusted'] += 1
            end_adjusted = True

        # Apply snapped times
        event.start = snapped_start_ms
        event.end = snapped_end_ms

        # Track statistics
        start_changed = (start_delta != 0)
        end_delta = event.end - (original_end + start_delta)
        end_changed = (abs(end_delta) > 0.5)
        duration_preserved = (abs((event.end - event.start) - original_duration) < 0.5)

        if start_changed:
            stats['start_snapped'] += 1
        else:
            stats['start_already_aligned'] += 1
        if end_changed:
            stats['end_snapped'] += 1
        if not duration_preserved:
            stats['duration_changed'] += 1

        # Log sample events distributed across the file
        if stats['events_processed'] in sample_indices and (start_changed or end_changed):
            percent = (stats['events_processed'] / stats['total_events']) * 100
            runner._log_message(
                f"[FrameLocked] Sample at {percent:.0f}% (event #{stats['events_processed']}): "
                f"start {original_start}ms→{event.start}ms (Δ{start_delta:+d}ms, frame {start_frame}), "
                f"end {original_end}ms→{event.end}ms (Δ{event.end - original_end:+d}ms, frame {end_frame})"
                + (f" [end adjusted]" if end_adjusted else "")
            )

        stats['events_processed'] += 1

    except Exception as e:
        runner._log_message(f"[FrameLocked] WARNING: Frame snap failed for event at {event.start}ms: {e}")
        import traceback
        runner._log_message(f"[FrameLocked] Traceback: {traceback.format_exc()}")
        # Keep original times if snapping fails


def _validate_post_ass_quantization(
    subs,
    vts,
    runner,
    stats: Dict[str, int],
    log_corrections: bool = False,
    original_timestamps: list = None
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
        log_corrections: If True, log every correction with details. If False, only log summary.
        original_timestamps: List of dicts with original start/end/text before ANY modifications

    Modifies event times in place if quantization broke frame alignment.
    """
    try:
        from video_timestamps import TimeType

        for idx, event in enumerate(subs.events, start=1):
            # Get ORIGINAL pre-sync timestamps for logging comparison
            orig_data = original_timestamps[idx - 1] if original_timestamps else None
            orig_start = orig_data['start'] if orig_data else None
            orig_end = orig_data['end'] if orig_data else None

            # Capture current state (after first save, before post-ASS fixes)
            before_fix_start = event.start
            before_fix_end = event.end

            # Get subtitle text for logging (truncate if too long)
            subtitle_text = event.text.replace('\n', ' ').replace('\\N', ' ')
            if len(subtitle_text) > 60:
                subtitle_text = subtitle_text[:57] + '...'

            # Check if start is at or after its TARGET frame start boundary
            start_frac = Fraction(int(event.start), 1)
            start_frame = vts.time_to_frame(start_frac, TimeType.EXACT)
            frame_start_frac = vts.frame_to_time(start_frame, TimeType.START)
            frame_start_ms = int(float(frame_start_frac))

            # If start is before frame boundary, snap forward
            if event.start < frame_start_ms:
                event.start = frame_start_ms
                post_delta = event.start - before_fix_start
                # Only count and log if actually changed
                if post_delta != 0:
                    stats['post_ass_start_fixed'] += 1
                    if log_corrections and orig_start is not None:
                        total_delta = event.start - orig_start
                        runner._log_message(
                            f"[FrameLocked] Post-ASS fix #{idx}: Start"
                        )
                        runner._log_message(
                            f"[FrameLocked]   Original: {orig_start}ms → Final: {event.start}ms (total Δ{total_delta:+d}ms)"
                        )
                        runner._log_message(
                            f"[FrameLocked]   Post-ASS: {before_fix_start}ms → {event.start}ms (Δ{post_delta:+d}ms, frame {start_frame})"
                        )
                        runner._log_message(f"[FrameLocked]   Text: \"{subtitle_text}\"")

            # Check if end is after start (safety check)
            if event.end <= event.start:
                # Push end to next frame
                next_frame_frac = vts.frame_to_time(start_frame + 1, TimeType.START)
                event.end = int(float(next_frame_frac))
                post_delta = event.end - before_fix_end
                # Only count and log if actually changed
                if post_delta != 0:
                    stats['post_ass_end_fixed'] += 1
                    if log_corrections and orig_end is not None:
                        total_delta = event.end - orig_end
                        runner._log_message(
                            f"[FrameLocked] Post-ASS fix #{idx}: End"
                        )
                        runner._log_message(
                            f"[FrameLocked]   Original: {orig_end}ms → Final: {event.end}ms (total Δ{total_delta:+d}ms)"
                        )
                        runner._log_message(
                            f"[FrameLocked]   Post-ASS: {before_fix_end}ms → {event.end}ms (Δ{post_delta:+d}ms, frame {start_frame + 1})"
                        )
                        runner._log_message(f"[FrameLocked]   Text: \"{subtitle_text}\"")

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

    runner._log_message(f"[FrameLocked] === Time-Based + Frame-Locked Timestamps Sync ===")
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

    # Capture ORIGINAL timestamps before ANY modifications (for logging comparison)
    original_timestamps = [
        {'start': event.start, 'end': event.end, 'text': event.text}
        for event in subs.events
    ]

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

    # Calculate sample indices distributed across the file
    # Sample at 10%, 20%, 30%, ..., 100% (up to 10 samples max, or all events if < 10)
    total_events = len(subs.events)
    if total_events <= 10:
        # Show all events if there are 10 or fewer
        sample_indices = set(range(total_events))
    else:
        # Sample at 10% intervals (10%, 20%, ..., 100%)
        sample_indices = set()
        for pct in range(10, 101, 10):
            idx = int((pct / 100.0) * total_events) - 1
            if idx >= 0 and idx < total_events:
                sample_indices.add(idx)

    stats = {
        'total_events': total_events,
        'events_processed': 0,
        'start_snapped': 0,
        'start_already_aligned': 0,
        'end_snapped': 0,
        'duration_changed': 0,
        'duration_adjusted': 0,
        'post_ass_start_fixed': 0,
        'post_ass_end_fixed': 0,
        'frame_aligned_delay_ms': float(frame_aligned_delay),
        'raw_delay_ms': total_delay_with_global_ms,
        'alignment_delta_ms': float(frame_aligned_delay) - total_delay_with_global_ms
    }

    for event in subs.events:
        _frame_snap_subtitle_event(event, vts, runner, stats, sample_indices)

    runner._log_message(f"[FrameLocked] Snapping complete:")
    runner._log_message(f"[FrameLocked]   - Start times adjusted: {stats['start_snapped']}/{stats['total_events']}")
    runner._log_message(f"[FrameLocked]   - Start times already aligned: {stats['start_already_aligned']}/{stats['total_events']}")
    runner._log_message(f"[FrameLocked]   - End times adjusted: {stats['end_snapped']}/{stats['total_events']}")
    runner._log_message(f"[FrameLocked]   - Durations changed: {stats['duration_changed']}/{stats['total_events']}")
    runner._log_message(f"[FrameLocked]   - Safety adjustments (end→next frame): {stats['duration_adjusted']}/{stats['total_events']}")

    # Step 4: Save to ASS (pysubs2 auto-quantizes to centiseconds)
    runner._log_message(f"[FrameLocked] Saving subtitle file (ASS centisecond quantization will occur)...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[FrameLocked] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Validate and restore metadata
    metadata.validate_and_restore(runner, expected_delay_ms=delay_int)

    # Step 5: Reload and validate frame alignment (post-ASS-quantization check)
    enable_post_correction = config.get('framelocked_enable_post_ass_correction', True)
    log_post_corrections = config.get('framelocked_log_post_ass_corrections', False)

    if enable_post_correction:
        runner._log_message(f"[FrameLocked] Reloading subtitle for post-ASS validation...")
        try:
            subs_reloaded = pysubs2.load(subtitle_path, encoding='utf-8')
        except Exception as e:
            runner._log_message(f"[FrameLocked] WARNING: Failed to reload for validation: {e}")
            return stats  # Return stats from initial processing

        if log_post_corrections:
            runner._log_message(f"[FrameLocked] Post-ASS detailed logging enabled")

        _validate_post_ass_quantization(subs_reloaded, vts, runner, stats, log_post_corrections, original_timestamps)

        # Step 6: Re-save if fixes were applied
        if stats['post_ass_start_fixed'] > 0 or stats['post_ass_end_fixed'] > 0:
            runner._log_message(f"[FrameLocked] Post-ASS fixes applied - re-saving:")
            runner._log_message(f"[FrameLocked]   - Start times fixed: {stats['post_ass_start_fixed']}")
            runner._log_message(f"[FrameLocked]   - End times fixed: {stats['post_ass_end_fixed']}")

            try:
                subs_reloaded.save(subtitle_path, encoding='utf-8')
                # Re-validate and restore metadata after second save
                metadata.validate_and_restore(runner, expected_delay_ms=delay_int)
            except Exception as e:
                runner._log_message(f"[FrameLocked] WARNING: Failed to re-save: {e}")
        else:
            runner._log_message(f"[FrameLocked] Post-ASS validation: Frame alignment maintained (no fixes needed)")
    else:
        runner._log_message(f"[FrameLocked] Post-ASS correction disabled (skipping validation)")

    runner._log_message(f"[FrameLocked] === Sync Complete ===")

    return stats
