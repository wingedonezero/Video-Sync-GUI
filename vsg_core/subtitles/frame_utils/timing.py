# vsg_core/subtitles/frame_utils/timing.py
"""
Frame/time conversion functions for subtitle synchronization.

Contains:
- CFR timing modes (floor, middle, aegisub)
- VFR (VideoTimestamps-based) timing
- VFR cache management
"""

from __future__ import annotations

import gc
import math
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.models import AppSettings

# ============================================================================
# MODE 0: FRAME START (For Correlation-Frame-Snap - STABLE & DETERMINISTIC)
# ============================================================================


def time_to_frame_floor(time_ms: float, fps: float) -> int:
    """
    MODE: Frame START (stable, deterministic).

    Convert timestamp to frame number using FLOOR with epsilon protection.
    This gives the frame that is currently displaying at the given time.

    This is the preferred method for sync math because:
    - Deterministic (no rounding ambiguity at boundaries)
    - Stable under floating point drift
    - Maps to actual frame boundaries (frame N starts at N * frame_duration)

    Args:
        time_ms: Timestamp in milliseconds
        fps: Frame rate (e.g., 23.976)

    Returns:
        Frame number (which frame is displaying at this time)

    Examples at 23.976 fps (frame_duration = 41.708ms):
        time_to_frame_floor(0.0, 23.976) -> 0
        time_to_frame_floor(41.707, 23.976) -> 0 (still in frame 0)
        time_to_frame_floor(41.708, 23.976) -> 1 (frame 1 starts)
        time_to_frame_floor(1000.999, 23.976) -> 23 (FP drift protected)
        time_to_frame_floor(1001.0, 23.976) -> 24
    """
    frame_duration_ms = 1000.0 / fps
    # Add small epsilon to protect against FP errors where time_ms is slightly under frame boundary
    epsilon = 1e-6
    return int((time_ms + epsilon) / frame_duration_ms)


def frame_to_time_floor(frame_num: int, fps: float) -> float:
    """
    MODE: Frame START (stable, deterministic).

    Convert frame number to its START timestamp (exact, no rounding).

    This is the preferred method for sync math because:
    - Frame N starts at exactly N * frame_duration
    - No rounding (exact calculation)
    - Guarantees frame-aligned timing

    Args:
        frame_num: Frame number
        fps: Frame rate (e.g., 23.976)

    Returns:
        Timestamp in milliseconds (frame START time, as float for precision)

    Examples at 23.976 fps (frame_duration = 41.708ms):
        frame_to_time_floor(0, 23.976) -> 0.0
        frame_to_time_floor(1, 23.976) -> 41.708
        frame_to_time_floor(24, 23.976) -> 1001.0
        frame_to_time_floor(100, 23.976) -> 4170.8
    """
    frame_duration_ms = 1000.0 / fps
    return frame_num * frame_duration_ms


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
    - Calculation: 24.5 x 41.708 = 1022ms
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
    - Exact calculation: 24 x 41.708 = 1001.001ms
    - Round UP to next centisecond: ceil(1001.001 / 10) x 10 = 1010ms
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
# Thread-safe: accessed from ThreadPoolExecutor workers
_vfr_cache = {}
_vfr_cache_lock = threading.Lock()


def clear_vfr_cache():
    """
    Clear the VFR cache to release VideoTimestamps instances.

    This should be called on application shutdown or when clearing resources
    to prevent nanobind reference leaks.
    """
    global _vfr_cache
    with _vfr_cache_lock:
        _vfr_cache.clear()
    gc.collect()  # Force garbage collection to release nanobind objects


def get_vfr_timestamps(
    video_path: str, fps: float, runner, settings: AppSettings | None = None
):
    """
    Get appropriate timestamp handler based on video type.

    For CFR videos: Uses lightweight FPSTimestamps (just calculations)
    For VFR videos: Uses VideoTimestamps (analyzes actual video)

    Args:
        video_path: Path to video file
        fps: Frame rate
        runner: CommandRunner for logging
        settings: AppSettings with videotimestamps_rounding setting
    """
    try:
        from fractions import Fraction

        from video_timestamps import (
            FPSTimestamps,
            RoundingMethod,
        )

        # Get rounding method from settings (default: ROUND)
        rounding_str = (
            settings.videotimestamps_rounding.upper()
            if settings is not None
            else "ROUND"
        )

        if rounding_str == "FLOOR":
            rounding_method = RoundingMethod.FLOOR
        else:  # 'ROUND' or default
            rounding_method = RoundingMethod.ROUND

        # Create cache key that includes rounding method
        cache_key = f"{video_path}_{rounding_str}"

        # Thread-safe cache access
        with _vfr_cache_lock:
            if cache_key in _vfr_cache:
                return _vfr_cache[cache_key]

        # Try to detect if video is VFR by checking if it's a real video file
        # For now, use FPSTimestamps (lightweight) for CFR videos
        # This just does math, doesn't analyze the video file

        # Convert FPS to exact fraction for NTSC drop-frame rates
        # NTSC standards use fractional rates (N*1000/1001) to avoid color/audio drift
        if abs(fps - 23.976) < 0.001:
            fps_frac = Fraction(
                24000, 1001
            )  # 23.976fps - NTSC film (24fps slowed down)
        elif abs(fps - 29.97) < 0.01:
            fps_frac = Fraction(
                30000, 1001
            )  # 29.97fps - NTSC video (30fps slowed down)
        elif abs(fps - 59.94) < 0.01:
            fps_frac = Fraction(
                60000, 1001
            )  # 59.94fps - NTSC high fps (60fps slowed down)
        else:
            # Use decimal FPS as fraction for non-NTSC rates (PAL, web video, etc.)
            fps_frac = Fraction(int(fps * 1000), 1000).limit_denominator(10000)

        # Use FPSTimestamps for CFR (constant framerate) - lightweight!
        time_scale = Fraction(1000)  # milliseconds
        vts = FPSTimestamps(rounding_method, time_scale, fps_frac)

        runner._log_message(
            f"[VideoTimestamps] Using FPSTimestamps for CFR video at {fps:.3f} fps"
        )
        runner._log_message(f"[VideoTimestamps] RoundingMethod: {rounding_str}")

        # Thread-safe cache write
        with _vfr_cache_lock:
            _vfr_cache[cache_key] = vts
        return vts

    except ImportError:
        runner._log_message(
            "[VideoTimestamps] WARNING: VideoTimestamps not installed. Install with: pip install VideoTimestamps"
        )
        return None
    except Exception as e:
        runner._log_message(
            f"[VideoTimestamps] WARNING: Failed to create timestamps handler: {e}"
        )
        return None
