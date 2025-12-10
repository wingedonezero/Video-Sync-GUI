# vsg_core/subtitles/frame_sync.py
# -*- coding: utf-8 -*-
"""
Frame-perfect subtitle synchronization module.

Applies time-based delays to subtitles while snapping timestamps to exact
frame boundaries to preserve frame-alignment for typesetting and moving signs.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any
import pysubs2


def snap_to_frame(time_ms: float, fps: float) -> int:
    """
    Snap a millisecond timestamp to the nearest frame boundary.

    Args:
        time_ms: Timestamp in milliseconds
        fps: Target video frame rate (e.g., 23.976)

    Returns:
        Snapped timestamp in milliseconds (as integer)

    Example:
        >>> snap_to_frame(1150.0, 23.976)
        1167  # Snapped to frame 28
    """
    if fps <= 0:
        return int(round(time_ms))

    frame_duration_ms = 1000.0 / fps
    frame_num = round(time_ms / frame_duration_ms)
    snapped_ms = int(round(frame_num * frame_duration_ms))

    return snapped_ms


def apply_frame_perfect_sync(
    subtitle_path: str,
    delay_ms: int,
    target_fps: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Apply frame-perfect synchronization to subtitle file.

    This function:
    1. Loads the subtitle file with pysubs2
    2. Applies the time-based delay offset to each event
    3. Snaps both start and end times to exact frame boundaries
    4. Saves the modified subtitle file

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        delay_ms: Time offset to apply in milliseconds (can be negative)
        target_fps: Target video frame rate for snapping
        runner: CommandRunner for logging
        config: Optional config dict (for future extensions)

    Returns:
        Dict with report statistics:
            - total_events: Number of subtitle events processed
            - adjusted_events: Number of events that had non-zero adjustment
            - avg_start_snap_ms: Average snap adjustment for start times
            - avg_end_snap_ms: Average snap adjustment for end times
            - max_snap_offset_ms: Maximum snap offset encountered
            - target_fps: FPS used for snapping
            - delay_applied_ms: Delay that was applied
    """
    config = config or {}

    runner._log_message(f"[Frame-Perfect Sync] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[Frame-Perfect Sync] Target FPS: {target_fps:.3f}")
    runner._log_message(f"[Frame-Perfect Sync] Delay to apply: {delay_ms:+d} ms")

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
            'avg_start_snap_ms': 0.0,
            'avg_end_snap_ms': 0.0,
            'max_snap_offset_ms': 0.0,
            'target_fps': target_fps,
            'delay_applied_ms': delay_ms
        }

    # Track statistics
    adjusted_count = 0
    start_snap_offsets = []
    end_snap_offsets = []

    runner._log_message(f"[Frame-Perfect Sync] Processing {len(subs.events)} subtitle events...")

    # Process each event
    for event in subs.events:
        original_start = event.start
        original_end = event.end

        # Skip empty events (shouldn't happen, but be safe)
        if original_start == original_end:
            continue

        # Apply time-based delay
        adjusted_start = original_start + delay_ms
        adjusted_end = original_end + delay_ms

        # Snap to frame boundaries
        snapped_start = snap_to_frame(adjusted_start, target_fps)
        snapped_end = snap_to_frame(adjusted_end, target_fps)

        # Ensure end is always after start (handle edge cases)
        if snapped_end <= snapped_start:
            # Duration collapsed - preserve at least 1 frame
            frame_duration_ms = 1000.0 / target_fps
            snapped_end = snapped_start + int(round(frame_duration_ms))

        # Track snap offsets for reporting
        start_snap_offset = abs(snapped_start - adjusted_start)
        end_snap_offset = abs(snapped_end - adjusted_end)
        start_snap_offsets.append(start_snap_offset)
        end_snap_offsets.append(end_snap_offset)

        # Update event
        event.start = snapped_start
        event.end = snapped_end

        # Count as adjusted if delay was non-zero
        if delay_ms != 0:
            adjusted_count += 1

    # Calculate statistics
    avg_start_snap = sum(start_snap_offsets) / len(start_snap_offsets) if start_snap_offsets else 0.0
    avg_end_snap = sum(end_snap_offsets) / len(end_snap_offsets) if end_snap_offsets else 0.0
    max_snap = max(start_snap_offsets + end_snap_offsets) if (start_snap_offsets or end_snap_offsets) else 0.0

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
    runner._log_message(f"[Frame-Perfect Sync]   - Avg start snap: {avg_start_snap:.2f} ms")
    runner._log_message(f"[Frame-Perfect Sync]   - Avg end snap: {avg_end_snap:.2f} ms")
    runner._log_message(f"[Frame-Perfect Sync]   - Max snap offset: {max_snap:.2f} ms")

    return {
        'total_events': len(subs.events),
        'adjusted_events': adjusted_count,
        'avg_start_snap_ms': round(avg_start_snap, 2),
        'avg_end_snap_ms': round(avg_end_snap, 2),
        'max_snap_offset_ms': round(max_snap, 2),
        'target_fps': target_fps,
        'delay_applied_ms': delay_ms
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
