# vsg_core/subtitles/frame_sync.py
# -*- coding: utf-8 -*-
"""
Frame-perfect subtitle synchronization module.

Shifts subtitles by FRAME COUNT instead of milliseconds to preserve
frame-perfect alignment for typesetting and moving signs from release groups.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any
import pysubs2


def time_to_frame(time_ms: float, fps: float) -> int:
    """
    Convert timestamp in milliseconds to frame number.

    Since frame_to_time() adds a 0.5 frame offset, we need to subtract it
    here to get back the original frame number.

    Args:
        time_ms: Timestamp in milliseconds
        fps: Frame rate (e.g., 23.976)

    Returns:
        Frame number (accounting for half-frame offset)
    """
    frame_duration_ms = 1000.0 / fps
    # Subtract 0.5 frames to account for the offset added by frame_to_time()
    return round(time_ms / frame_duration_ms - 0.5)


def frame_to_time(frame_num: int, fps: float) -> int:
    """
    Convert frame number to timestamp in milliseconds.

    Uses half-frame offset to target the middle of the frame's display window
    instead of the boundary. This prevents centisecond rounding in ASS format
    from shifting subtitles to the wrong frame.

    Example at 23.976 fps:
    - Frame 24 displays from 1001.001ms to 1042.709ms (41.7ms window)
    - Without offset: 24 * 41.708 = 1001ms → rounds to 1000ms (frame 23!)
    - With +0.5 offset: 24.5 * 41.708 = 1022ms → rounds to 1020ms (frame 24 ✓)

    Args:
        frame_num: Frame number
        fps: Frame rate (e.g., 23.976)

    Returns:
        Timestamp in milliseconds (middle of frame display window)
    """
    frame_duration_ms = 1000.0 / fps
    # Add 0.5 frames to target the middle of the frame's display window
    # This ensures centisecond rounding (10ms precision) keeps us in the correct frame
    return int(round((frame_num + 0.5) * frame_duration_ms))


def apply_frame_perfect_sync(
    subtitle_path: str,
    delay_ms: int,
    target_fps: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Apply frame-perfect synchronization using FRAME-BASED shifting.

    This preserves frame-perfect alignment by shifting by whole frame counts
    instead of millisecond values, which is critical for release group ASS subs.

    Algorithm:
    1. Convert delay_ms to frame count (round to nearest whole frame)
    2. For each subtitle event:
       - Convert timestamp to frame number
       - Add frame offset
       - Convert back to timestamp at exact frame boundary
    3. Save modified subtitle file

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        delay_ms: Time offset in milliseconds (converted to frames)
        target_fps: Target video frame rate
        runner: CommandRunner for logging
        config: Optional config dict

    Returns:
        Dict with report statistics:
            - total_events: Number of subtitle events processed
            - adjusted_events: Number of events shifted
            - frame_shift: Number of frames shifted by
            - delay_applied_ms: Original delay in milliseconds
            - effective_delay_ms: Actual delay after frame rounding
            - target_fps: FPS used
    """
    config = config or {}

    runner._log_message(f"[Frame-Perfect Sync] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[Frame-Perfect Sync] Target FPS: {target_fps:.3f}")
    runner._log_message(f"[Frame-Perfect Sync] Delay to apply: {delay_ms:+d} ms")

    # Convert delay to frame count
    frame_duration_ms = 1000.0 / target_fps
    frame_shift = round(delay_ms / frame_duration_ms)
    effective_delay_ms = frame_shift * frame_duration_ms

    runner._log_message(f"[Frame-Perfect Sync] Frame duration: {frame_duration_ms:.3f} ms")
    runner._log_message(f"[Frame-Perfect Sync] Frame shift: {frame_shift:+d} frames")
    runner._log_message(f"[Frame-Perfect Sync] Effective delay: {effective_delay_ms:+.1f} ms")

    if abs(delay_ms - effective_delay_ms) > 0.5:
        runner._log_message(f"[Frame-Perfect Sync] NOTE: Rounded {delay_ms}ms to {effective_delay_ms:.1f}ms ({abs(delay_ms - effective_delay_ms):.1f}ms difference)")

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Frame-Perfect Sync] ERROR: Failed to load subtitle file: {e}")
        return {'error': str(e)}

    if not subs.events:
        runner._log_message(f"[Frame-Perfect Sync] WARNING: No subtitle events found in file")
        return {
            'total_events': 0,
            'adjusted_events': 0,
            'frame_shift': frame_shift,
            'delay_applied_ms': delay_ms,
            'effective_delay_ms': int(round(effective_delay_ms)),
            'target_fps': target_fps
        }

    adjusted_count = 0
    runner._log_message(f"[Frame-Perfect Sync] Processing {len(subs.events)} subtitle events...")

    # Process each event using FRAME-BASED shifting
    for event in subs.events:
        original_start = event.start
        original_end = event.end

        # Skip empty events
        if original_start == original_end:
            continue

        # Convert to frame numbers
        start_frame = time_to_frame(original_start, target_fps)
        end_frame = time_to_frame(original_end, target_fps)

        # Apply frame shift
        new_start_frame = start_frame + frame_shift
        new_end_frame = end_frame + frame_shift

        # Convert back to timestamps at exact frame boundaries
        new_start_ms = frame_to_time(new_start_frame, target_fps)
        new_end_ms = frame_to_time(new_end_frame, target_fps)

        # Ensure end is after start
        if new_end_ms <= new_start_ms:
            new_end_ms = new_start_ms + int(round(frame_duration_ms))

        # Update event
        event.start = new_start_ms
        event.end = new_end_ms

        if frame_shift != 0:
            adjusted_count += 1

    # Save modified subtitle
    runner._log_message(f"[Frame-Perfect Sync] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Frame-Perfect Sync] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Log results
    runner._log_message(f"[Frame-Perfect Sync] ✓ Successfully processed {len(subs.events)} events")
    runner._log_message(f"[Frame-Perfect Sync]   - Events adjusted: {adjusted_count}")
    runner._log_message(f"[Frame-Perfect Sync]   - Frame shift applied: {frame_shift:+d} frames")

    return {
        'total_events': len(subs.events),
        'adjusted_events': adjusted_count,
        'frame_shift': frame_shift,
        'delay_applied_ms': delay_ms,
        'effective_delay_ms': int(round(effective_delay_ms)),
        'target_fps': target_fps
    }


def detect_video_fps(video_path: str, runner) -> float:
    """
    Detect frame rate from video file using ffprobe.

    Args:
        video_path: Path to video file
        runner: CommandRunner for executing ffprobe

    Returns:
        Frame rate as float (e.g., 23.976), or 23.976 as fallback
    """
    import subprocess
    import json

    runner._log_message(f"[Frame-Perfect Sync] Detecting FPS from: {Path(video_path).name}")

    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate',
            '-of', 'json',
            str(video_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            runner._log_message(f"[Frame-Perfect Sync] WARNING: ffprobe failed, using default 23.976 fps")
            return 23.976

        data = json.loads(result.stdout)
        r_frame_rate = data['streams'][0]['r_frame_rate']

        # Parse fraction (e.g., "24000/1001" -> 23.976)
        if '/' in r_frame_rate:
            num, denom = r_frame_rate.split('/')
            fps = float(num) / float(denom)
        else:
            fps = float(r_frame_rate)

        runner._log_message(f"[Frame-Perfect Sync] Detected FPS: {fps:.3f} ({r_frame_rate})")
        return fps

    except Exception as e:
        runner._log_message(f"[Frame-Perfect Sync] WARNING: FPS detection failed: {e}")
        runner._log_message(f"[Frame-Perfect Sync] Using default: 23.976 fps")
        return 23.976
