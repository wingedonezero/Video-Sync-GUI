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
from dataclasses import dataclass
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
            TimeType,
            VideoTimestamps,
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


def frame_to_time_vfr(
    frame_num: int,
    video_path: str,
    fps: float,
    runner,
    settings: AppSettings | None = None,
) -> int | None:
    """
    MODE: VFR (VideoTimestamps-based).

    For CFR videos: Uses FPSTimestamps (lightweight calculation)
    For VFR videos: Uses VideoTimestamps (analyzes video container)

    Args:
        frame_num: Frame number
        video_path: Path to video file
        fps: Frame rate (used for CFR mode)
        runner: CommandRunner for logging
        settings: AppSettings with timing settings

    Returns:
        Timestamp in milliseconds, or None if VideoTimestamps unavailable
    """
    try:
        from video_timestamps import TimeType

        vts = get_vfr_timestamps(video_path, fps, runner, settings)
        if vts is None:
            return None

        # Get exact timestamp for this frame
        # Use EXACT time (precise frame display window) - NOT START!
        # EXACT gives [current, next[ which matches video player behavior
        time_ms = vts.frame_to_time(frame_num, TimeType.EXACT)
        return int(time_ms)

    except Exception as e:
        runner._log_message(f"[VideoTimestamps] WARNING: frame_to_time_vfr failed: {e}")
        return None


def time_to_frame_vfr(
    time_ms: float,
    video_path: str,
    fps: float,
    runner,
    settings: AppSettings | None = None,
) -> int | None:
    """
    MODE: VFR using VideoTimestamps.

    Converts timestamp to frame using appropriate timestamps handler.

    Args:
        time_ms: Timestamp in milliseconds
        video_path: Path to video file
        fps: Frame rate (used for CFR mode)
        runner: CommandRunner for logging
        settings: AppSettings with timing settings

    Returns:
        Frame number, or None if VideoTimestamps unavailable
    """
    try:
        from fractions import Fraction

        from video_timestamps import TimeType

        vts = get_vfr_timestamps(video_path, fps, runner, settings)
        if vts is None:
            return None

        # Convert time_ms to Fraction (required by VideoTimestamps)
        time_frac = Fraction(int(time_ms), 1)

        # Convert time to frame using EXACT (precise frame display window)
        # EXACT gives [current, next[ which matches video player behavior
        frame_num = vts.time_to_frame(time_frac, TimeType.EXACT)
        return frame_num

    except Exception as e:
        runner._log_message(f"[VideoTimestamps] WARNING: time_to_frame_vfr failed: {e}")
        return None


# ============================================================================
# FRAME REMAP: Preserve centisecond position within frames during sync
# ============================================================================


@dataclass(frozen=True, slots=True)
class FrameRemapResult:
    """Result of frame remap calculation for a single timestamp."""

    original_ms: float  # Original timestamp in milliseconds
    original_frame: int  # Frame number in source video
    original_position_cs: int  # Centisecond position within frame (0-4 typically)
    target_frame: int  # Frame number in target video (after offset)
    target_ms: float  # Calculated target timestamp in milliseconds
    target_cs: int  # Final centisecond value for ASS
    was_adjusted: bool  # True if boundary adjustment was needed


def calculate_frame_position(time_ms: float, fps: float) -> tuple[int, int]:
    """
    Calculate which frame a timestamp is in and its centisecond position within that frame.

    Args:
        time_ms: Timestamp in milliseconds
        fps: Frame rate (e.g., 23.976)

    Returns:
        Tuple of (frame_number, position_in_frame_cs)

    Example at 23.976 fps (frame_duration ≈ 41.708ms, ≈ 4.17cs):
        time_ms=1020 → frame 24 (starts at 1001ms ≈ 100cs), position = 102cs - 100cs = 2cs
    """
    frame_duration_ms = 1000.0 / fps
    frame_duration_cs = frame_duration_ms / 10.0

    # Which frame is this timestamp in?
    frame_num = int(time_ms / frame_duration_ms)

    # What centisecond does this frame start at?
    frame_start_cs = int(frame_num * frame_duration_cs)

    # What's the timestamp's centisecond value?
    time_cs = int(time_ms / 10)

    # Position within frame (in centiseconds)
    position_cs = time_cs - frame_start_cs

    return frame_num, position_cs


def remap_time_to_target_frame(
    time_ms: float,
    frame_offset: int,
    fps: float,
) -> FrameRemapResult:
    """
    Remap a timestamp to target video while preserving centisecond position within frame.

    Instead of adding a delay (which can cause boundary crossings due to rounding),
    this calculates which frame the timestamp belongs to, applies the frame offset,
    and preserves the centisecond position within that frame.

    Args:
        time_ms: Original timestamp in milliseconds
        frame_offset: Frame offset from video verified (e.g., -24)
        fps: Frame rate (e.g., 23.976)

    Returns:
        FrameRemapResult with all calculation details

    Example at 23.976 fps with frame_offset=-24:
        time_ms=1020 (102cs, frame 24, 2cs into frame)
        → target frame 0, 2cs into frame
        → target_cs=2, target_ms=20
    """
    frame_duration_ms = 1000.0 / fps
    frame_duration_cs = frame_duration_ms / 10.0

    # Step 1: Find source frame and position
    source_frame, position_cs = calculate_frame_position(time_ms, fps)

    # Step 2: Calculate target frame
    target_frame = source_frame + frame_offset

    # Handle negative frames (clamp to 0)
    if target_frame < 0:
        target_frame = 0
        position_cs = 0  # Start at beginning of frame 0

    # Step 3: Calculate target centisecond
    target_frame_start_cs = int(target_frame * frame_duration_cs)
    target_cs = target_frame_start_cs + position_cs

    # Step 4: Convert back to ms
    target_ms = target_cs * 10.0

    return FrameRemapResult(
        original_ms=time_ms,
        original_frame=source_frame,
        original_position_cs=position_cs,
        target_frame=target_frame,
        target_ms=target_ms,
        target_cs=target_cs,
        was_adjusted=False,  # Pure remap, no adjustment needed
    )


def apply_sync_with_frame_remap(
    start_ms: float,
    end_ms: float,
    frame_offset: int,
    fps: float,
) -> tuple[FrameRemapResult, FrameRemapResult]:
    """
    Apply sync to start and end times using frame remap to preserve positions.

    This ensures:
    - Duration in frames is preserved (end_frame - start_frame stays constant)
    - Centisecond position within each frame is preserved
    - No boundary crossing from rounding errors

    Args:
        start_ms: Original start timestamp in milliseconds
        end_ms: Original end timestamp in milliseconds
        frame_offset: Frame offset from video verified
        fps: Frame rate

    Returns:
        Tuple of (start_result, end_result) FrameRemapResults
    """
    start_result = remap_time_to_target_frame(start_ms, frame_offset, fps)
    end_result = remap_time_to_target_frame(end_ms, frame_offset, fps)

    return start_result, end_result


def verify_frame_boundary(
    time_ms: float,
    delay_ms: float,
    fps: float,
) -> tuple[int, bool]:
    """
    Verify if applying a delay would cause a frame boundary crossing after ASS rounding.

    This is the "hybrid" approach: apply delay normally, then check if floor rounding
    to centiseconds would put us in a different frame than expected.

    Args:
        time_ms: Original timestamp in milliseconds
        delay_ms: Delay to apply (from video verified)
        fps: Frame rate

    Returns:
        Tuple of (adjusted_centiseconds, was_adjusted)
        - adjusted_centiseconds: The centisecond value to use (possibly adjusted)
        - was_adjusted: True if adjustment was made to prevent boundary crossing
    """
    frame_duration_ms = 1000.0 / fps

    # Calculate new time and expected frame after applying delay
    new_time_ms = time_ms + delay_ms
    expected_frame = int(new_time_ms / frame_duration_ms)

    # Handle negative times
    if new_time_ms < 0:
        return 0, True

    # What would floor rounding give us?
    floored_cs = int(new_time_ms / 10)  # floor division
    floored_ms = floored_cs * 10.0
    actual_frame = int(floored_ms / frame_duration_ms)

    if actual_frame == expected_frame:
        # Floor rounding keeps us in the correct frame
        return floored_cs, False
    else:
        # Floor crossed a boundary - use ceil to stay in correct frame
        ceiled_cs = int(math.ceil(new_time_ms / 10))
        return ceiled_cs, True
