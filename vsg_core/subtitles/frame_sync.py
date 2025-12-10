# vsg_core/subtitles/frame_sync.py
# -*- coding: utf-8 -*-
"""
Frame-perfect subtitle synchronization module.

Shifts subtitles by FRAME COUNT instead of milliseconds to preserve
frame-perfect alignment for typesetting and moving signs from release groups.

Supports multiple timing modes:
- 'middle': Half-frame offset (targets middle of frame window)
- 'aegisub': Aegisub-style (ceil to centisecond)
- 'vfr': VideoTimestamps-based (for variable framerate)
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Optional
import pysubs2
import math


# ============================================================================
# MODE 1: MIDDLE OF FRAME (Current Implementation)
# ============================================================================

def time_to_frame_middle(time_ms: float, fps: float) -> int:
    """
    MODE: Middle of frame window.

    Convert timestamp to frame number, accounting for +0.5 offset.

    Args:
        time_ms: Timestamp in milliseconds
        fps: Frame rate (e.g., 23.976)

    Returns:
        Frame number
    """
    frame_duration_ms = 1000.0 / fps
    return round(time_ms / frame_duration_ms - 0.5)


def frame_to_time_middle(frame_num: int, fps: float) -> int:
    """
    MODE: Middle of frame window.

    Targets the middle of the frame's display window with +0.5 offset.

    Example at 23.976 fps:
    - Frame 24 displays from 1001.001ms to 1042.709ms
    - Calculation: 24.5 × 41.708 = 1022ms
    - After centisecond rounding: 1020ms (safely in frame 24)

    Args:
        frame_num: Frame number
        fps: Frame rate (e.g., 23.976)

    Returns:
        Timestamp in milliseconds
    """
    frame_duration_ms = 1000.0 / fps
    return int(round((frame_num + 0.5) * frame_duration_ms))


# ============================================================================
# MODE 2: AEGISUB-STYLE (Ceil to Centisecond)
# ============================================================================

def time_to_frame_aegisub(time_ms: float, fps: float) -> int:
    """
    MODE: Aegisub-style timing.

    Convert timestamp to frame using floor division (which frame is currently displaying).

    Args:
        time_ms: Timestamp in milliseconds
        fps: Frame rate

    Returns:
        Frame number
    """
    frame_duration_ms = 1000.0 / fps
    return int(time_ms / frame_duration_ms)


def frame_to_time_aegisub(frame_num: int, fps: float) -> int:
    """
    MODE: Aegisub-style timing.

    Matches Aegisub's algorithm: Calculate exact frame start, then round UP
    to the next centisecond to ensure timestamp falls within the frame.

    Example at 23.976 fps:
    - Frame 24 starts at 1001.001ms
    - Exact calculation: 24 × 41.708 = 1001.001ms
    - Round UP to next centisecond: ceil(1001.001 / 10) × 10 = 1010ms
    - Result: 1010ms (safely in frame 24: 1001-1043ms)

    Args:
        frame_num: Frame number
        fps: Frame rate

    Returns:
        Timestamp in milliseconds
    """
    frame_duration_ms = 1000.0 / fps
    exact_time_ms = frame_num * frame_duration_ms

    # Round UP to next centisecond (ASS format precision)
    # This ensures the timestamp is guaranteed to fall within the frame
    centiseconds = math.ceil(exact_time_ms / 10)
    return centiseconds * 10


# ============================================================================
# MODE 3: VFR (VideoTimestamps-based)
# ============================================================================

# Cache for VideoTimestamps instances to avoid re-parsing video
_vfr_cache = {}

def get_vfr_timestamps(video_path: str, fps: float, runner):
    """
    Get appropriate timestamp handler based on video type.

    For CFR videos: Uses lightweight FPSTimestamps (just calculations)
    For VFR videos: Uses VideoTimestamps (analyzes actual video)
    """
    try:
        from video_timestamps import FPSTimestamps, VideoTimestamps, TimeType, RoundingMethod
        from fractions import Fraction

        # Check cache first
        if video_path in _vfr_cache:
            return _vfr_cache[video_path]

        # Try to detect if video is VFR by checking if it's a real video file
        # For now, use FPSTimestamps (lightweight) for CFR videos
        # This just does math, doesn't analyze the video file

        # Convert FPS to fraction (e.g., 23.976 = 24000/1001)
        if abs(fps - 23.976) < 0.001:
            fps_frac = Fraction(24000, 1001)
        elif abs(fps - 29.97) < 0.01:
            fps_frac = Fraction(30000, 1001)
        elif abs(fps - 59.94) < 0.01:
            fps_frac = Fraction(60000, 1001)
        else:
            # Use decimal FPS as fraction
            fps_frac = Fraction(int(fps * 1000), 1000).limit_denominator(10000)

        # Use FPSTimestamps for CFR (constant framerate) - lightweight!
        time_scale = Fraction(1000)  # milliseconds
        vts = FPSTimestamps(RoundingMethod.ROUND, time_scale, fps_frac)

        runner._log_message(f"[Frame-Perfect Sync] Using FPSTimestamps for CFR video at {fps:.3f} fps")

        _vfr_cache[video_path] = vts
        return vts

    except ImportError:
        runner._log_message("[Frame-Perfect Sync] WARNING: VideoTimestamps not installed. Install with: pip install VideoTimestamps")
        return None
    except Exception as e:
        runner._log_message(f"[Frame-Perfect Sync] WARNING: Failed to create timestamps handler: {e}")
        return None


def frame_to_time_vfr(frame_num: int, video_path: str, fps: float, runner) -> Optional[int]:
    """
    MODE: VFR (VideoTimestamps-based).

    For CFR videos: Uses FPSTimestamps (lightweight calculation)
    For VFR videos: Uses VideoTimestamps (analyzes video container)

    Args:
        frame_num: Frame number
        video_path: Path to video file
        fps: Frame rate (used for CFR mode)
        runner: CommandRunner for logging

    Returns:
        Timestamp in milliseconds, or None if VideoTimestamps unavailable
    """
    try:
        from video_timestamps import TimeType

        vts = get_vfr_timestamps(video_path, fps, runner)
        if vts is None:
            return None

        # Get exact timestamp for this frame
        # Use START time (beginning of frame)
        time_ms = vts.frame_to_time(frame_num, TimeType.START)
        return int(time_ms)

    except Exception as e:
        runner._log_message(f"[Frame-Perfect Sync] WARNING: frame_to_time_vfr failed: {e}")
        return None


def time_to_frame_vfr(time_ms: float, video_path: str, fps: float, runner) -> Optional[int]:
    """
    MODE: VFR using VideoTimestamps.

    Converts timestamp to frame using appropriate timestamps handler.

    Args:
        time_ms: Timestamp in milliseconds
        video_path: Path to video file
        fps: Frame rate (used for CFR mode)
        runner: CommandRunner for logging

    Returns:
        Frame number, or None if VideoTimestamps unavailable
    """
    try:
        vts = get_vfr_timestamps(video_path, fps, runner)
        if vts is None:
            return None

        # Convert time to frame
        frame_num = vts.time_to_frame(time_ms)
        return frame_num

    except Exception as e:
        runner._log_message(f"[Frame-Perfect Sync] WARNING: time_to_frame_vfr failed: {e}")
        return None


# ============================================================================
# LEGACY ALIASES (for backwards compatibility)
# ============================================================================

def time_to_frame(time_ms: float, fps: float) -> int:
    """Legacy alias for time_to_frame_middle"""
    return time_to_frame_middle(time_ms, fps)


def frame_to_time(frame_num: int, fps: float) -> int:
    """Legacy alias for frame_to_time_middle"""
    return frame_to_time_middle(frame_num, fps)


def apply_frame_perfect_sync(
    subtitle_path: str,
    delay_ms: int,
    target_fps: float,
    runner,
    config: dict = None,
    video_path: str = None
) -> Dict[str, Any]:
    """
    Apply frame-perfect synchronization using FRAME-BASED shifting.

    Supports multiple timing modes:
    - 'middle': Half-frame offset (default, targets middle of frame window)
    - 'aegisub': Aegisub-style (rounds UP to centisecond)
    - 'vfr': VideoTimestamps-based (for variable framerate)

    Algorithm:
    1. Convert delay_ms to frame count (round to nearest whole frame)
    2. For each subtitle event:
       - Convert timestamp to frame number (using selected mode)
       - Add frame offset
       - Convert back to timestamp (using selected mode)
    3. Save modified subtitle file

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        delay_ms: Time offset in milliseconds (converted to frames)
        target_fps: Target video frame rate (ignored for VFR mode)
        runner: CommandRunner for logging
        config: Optional config dict with 'frame_sync_mode' key
        video_path: Path to video file (required for VFR mode)

    Returns:
        Dict with report statistics
    """
    config = config or {}

    # Determine timing mode
    timing_mode = config.get('frame_sync_mode', 'middle')  # default to middle

    runner._log_message(f"[Frame-Perfect Sync] Mode: {timing_mode}")
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

    # Select conversion functions based on mode
    if timing_mode == 'aegisub':
        time_to_frame_func = time_to_frame_aegisub
        frame_to_time_func = frame_to_time_aegisub
    elif timing_mode == 'vfr':
        if not video_path:
            runner._log_message(f"[Frame-Perfect Sync] ERROR: VFR mode requires video_path")
            return {'error': 'VFR mode requires video_path'}
        # VFR functions need video_path, handle differently
        time_to_frame_func = None  # Will use lambda below
        frame_to_time_func = None
    else:  # 'middle' or default
        time_to_frame_func = time_to_frame_middle
        frame_to_time_func = frame_to_time_middle

    # Process each event using FRAME-BASED shifting
    for event in subs.events:
        original_start = event.start
        original_end = event.end

        # Skip empty events
        if original_start == original_end:
            continue

        # Convert to frame numbers (mode-specific)
        if timing_mode == 'vfr':
            start_frame = time_to_frame_vfr(original_start, video_path, target_fps, runner)
            end_frame = time_to_frame_vfr(original_end, video_path, target_fps, runner)
            if start_frame is None or end_frame is None:
                runner._log_message(f"[Frame-Perfect Sync] ERROR: VFR conversion failed, falling back to middle mode")
                start_frame = time_to_frame_middle(original_start, target_fps)
                end_frame = time_to_frame_middle(original_end, target_fps)
                # Switch to middle mode functions for remaining processing
                timing_mode = 'middle'
                time_to_frame_func = time_to_frame_middle
                frame_to_time_func = frame_to_time_middle
        else:
            start_frame = time_to_frame_func(original_start, target_fps)
            end_frame = time_to_frame_func(original_end, target_fps)

        # Apply frame shift
        new_start_frame = start_frame + frame_shift
        new_end_frame = end_frame + frame_shift

        # Convert back to timestamps (mode-specific)
        if timing_mode == 'vfr':
            new_start_ms = frame_to_time_vfr(new_start_frame, video_path, target_fps, runner)
            new_end_ms = frame_to_time_vfr(new_end_frame, video_path, target_fps, runner)
            if new_start_ms is None or new_end_ms is None:
                runner._log_message(f"[Frame-Perfect Sync] ERROR: VFR conversion failed")
                continue
        else:
            new_start_ms = frame_to_time_func(new_start_frame, target_fps)
            new_end_ms = frame_to_time_func(new_end_frame, target_fps)

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
