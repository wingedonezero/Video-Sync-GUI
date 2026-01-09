# vsg_core/subtitles/frame_sync.py
# -*- coding: utf-8 -*-
"""
Subtitle synchronization module.

Provides multiple synchronization modes:
- Raw delay sync: Apply delays directly to subtitle timestamps
- Duration-align: Frame alignment via total duration difference
- Correlation + frame snap: Audio correlation with frame verification

Includes utilities for frame timing, VFR/CFR support via VideoTimestamps,
and frame validation using perceptual hashing.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import pysubs2
import math
import gc
import tempfile
from .metadata_preserver import SubtitleMetadata


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
        time_to_frame_floor(0.0, 23.976) → 0
        time_to_frame_floor(41.707, 23.976) → 0 (still in frame 0)
        time_to_frame_floor(41.708, 23.976) → 1 (frame 1 starts)
        time_to_frame_floor(1000.999, 23.976) → 23 (FP drift protected)
        time_to_frame_floor(1001.0, 23.976) → 24
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
        frame_to_time_floor(0, 23.976) → 0.0
        frame_to_time_floor(1, 23.976) → 41.708
        frame_to_time_floor(24, 23.976) → 1001.0
        frame_to_time_floor(100, 23.976) → 4170.8
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

def get_vfr_timestamps(video_path: str, fps: float, runner, config: dict = None):
    """
    Get appropriate timestamp handler based on video type.

    For CFR videos: Uses lightweight FPSTimestamps (just calculations)
    For VFR videos: Uses VideoTimestamps (analyzes actual video)

    Args:
        video_path: Path to video file
        fps: Frame rate
        runner: CommandRunner for logging
        config: Optional config dict with 'videotimestamps_rounding' setting
    """
    try:
        from video_timestamps import FPSTimestamps, VideoTimestamps, TimeType, RoundingMethod
        from fractions import Fraction

        # Get rounding method from config (default: ROUND)
        config = config or {}
        rounding_str = config.get('videotimestamps_rounding', 'round').upper()

        if rounding_str == 'FLOOR':
            rounding_method = RoundingMethod.FLOOR
        else:  # 'ROUND' or default
            rounding_method = RoundingMethod.ROUND

        # Create cache key that includes rounding method
        cache_key = f"{video_path}_{rounding_str}"

        # Check cache first
        if cache_key in _vfr_cache:
            return _vfr_cache[cache_key]

        # Try to detect if video is VFR by checking if it's a real video file
        # For now, use FPSTimestamps (lightweight) for CFR videos
        # This just does math, doesn't analyze the video file

        # Convert FPS to exact fraction for NTSC drop-frame rates
        # NTSC standards use fractional rates (N*1000/1001) to avoid color/audio drift
        if abs(fps - 23.976) < 0.001:
            fps_frac = Fraction(24000, 1001)  # 23.976fps - NTSC film (24fps slowed down)
        elif abs(fps - 29.97) < 0.01:
            fps_frac = Fraction(30000, 1001)  # 29.97fps - NTSC video (30fps slowed down)
        elif abs(fps - 59.94) < 0.01:
            fps_frac = Fraction(60000, 1001)  # 59.94fps - NTSC high fps (60fps slowed down)
        else:
            # Use decimal FPS as fraction for non-NTSC rates (PAL, web video, etc.)
            fps_frac = Fraction(int(fps * 1000), 1000).limit_denominator(10000)

        # Use FPSTimestamps for CFR (constant framerate) - lightweight!
        time_scale = Fraction(1000)  # milliseconds
        vts = FPSTimestamps(rounding_method, time_scale, fps_frac)

        runner._log_message(f"[VideoTimestamps] Using FPSTimestamps for CFR video at {fps:.3f} fps")
        runner._log_message(f"[VideoTimestamps] RoundingMethod: {rounding_str}")

        _vfr_cache[cache_key] = vts
        return vts

    except ImportError:
        runner._log_message("[VideoTimestamps] WARNING: VideoTimestamps not installed. Install with: pip install VideoTimestamps")
        return None
    except Exception as e:
        runner._log_message(f"[VideoTimestamps] WARNING: Failed to create timestamps handler: {e}")
        return None



def frame_to_time_vfr(frame_num: int, video_path: str, fps: float, runner, config: dict = None) -> Optional[int]:
    """
    MODE: VFR (VideoTimestamps-based).

    For CFR videos: Uses FPSTimestamps (lightweight calculation)
    For VFR videos: Uses VideoTimestamps (analyzes video container)

    Args:
        frame_num: Frame number
        video_path: Path to video file
        fps: Frame rate (used for CFR mode)
        runner: CommandRunner for logging
        config: Optional config dict with settings

    Returns:
        Timestamp in milliseconds, or None if VideoTimestamps unavailable
    """
    try:
        from video_timestamps import TimeType

        vts = get_vfr_timestamps(video_path, fps, runner, config)
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


def time_to_frame_vfr(time_ms: float, video_path: str, fps: float, runner, config: dict = None) -> Optional[int]:
    """
    MODE: VFR using VideoTimestamps.

    Converts timestamp to frame using appropriate timestamps handler.

    Args:
        time_ms: Timestamp in milliseconds
        video_path: Path to video file
        fps: Frame rate (used for CFR mode)
        runner: CommandRunner for logging
        config: Optional config dict with settings

    Returns:
        Frame number, or None if VideoTimestamps unavailable
    """
    try:
        from video_timestamps import TimeType
        from fractions import Fraction

        vts = get_vfr_timestamps(video_path, fps, runner, config)
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
# VAPOURSYNTH FRAME INDEXING (Fast & Accurate)
# ============================================================================

def get_vapoursynth_frame_info(video_path: str, runner) -> Optional[Tuple[int, float]]:
    """
    Get frame count and last frame timestamp using VapourSynth indexing.

    This is MUCH faster than ffprobe -count_frames after the initial index:
    - First run: ~30-60s (generates .lwi index file)
    - Subsequent runs: <1s (reads cached index)

    Handles CFR and VFR videos perfectly.

    IMPORTANT: Properly frees memory after use to prevent RAM buildup.

    Args:
        video_path: Path to video file
        runner: CommandRunner for logging

    Returns:
        Tuple of (frame_count, last_frame_timestamp_ms) or None on error
    """
    try:
        import vapoursynth as vs

        runner._log_message(f"[VapourSynth] Indexing video: {Path(video_path).name}")

        # Create new core instance for isolation
        core = vs.core

        # Load video - this auto-generates index if not present
        # Try L-SMASH first (more accurate), fall back to FFmpegSource2
        clip = None
        try:
            clip = core.lsmas.LWLibavSource(str(video_path))
            runner._log_message(f"[VapourSynth] Using LWLibavSource (L-SMASH)")
        except AttributeError:
            # L-SMASH plugin not installed
            runner._log_message(f"[VapourSynth] L-SMASH plugin not found, using FFmpegSource2")
        except Exception as e:
            runner._log_message(f"[VapourSynth] L-SMASH failed: {e}, trying FFmpegSource2")

        if clip is None:
            try:
                clip = core.ffms2.Source(str(video_path))
                runner._log_message(f"[VapourSynth] Using FFmpegSource2")
            except Exception as e:
                runner._log_message(f"[VapourSynth] ERROR: FFmpegSource2 also failed: {e}")
                del core
                gc.collect()
                return None

        # Get frame count
        frame_count = clip.num_frames
        runner._log_message(f"[VapourSynth] Frame count: {frame_count}")

        # Get last frame timestamp
        # VapourSynth uses rational time base, convert to milliseconds
        last_frame_idx = frame_count - 1
        last_frame = clip.get_frame(last_frame_idx)

        # Calculate timestamp from frame properties
        # _DurationNum / _DurationDen gives frame duration in seconds
        fps_num = clip.fps.numerator
        fps_den = clip.fps.denominator

        # Last frame timestamp = (frame_index / fps) * 1000
        last_frame_timestamp_ms = (last_frame_idx * fps_den * 1000.0) / fps_num

        runner._log_message(f"[VapourSynth] Last frame (#{last_frame_idx}) timestamp: {last_frame_timestamp_ms:.3f}ms")
        runner._log_message(f"[VapourSynth] FPS: {fps_num}/{fps_den} ({fps_num/fps_den:.3f})")

        # CRITICAL: Free memory immediately
        # VapourSynth can hold large amounts of RAM if not freed
        del clip
        del last_frame
        del core
        gc.collect()  # Force garbage collection

        runner._log_message(f"[VapourSynth] ✓ Index loaded, memory freed")

        return (frame_count, last_frame_timestamp_ms)

    except ImportError:
        runner._log_message("[VapourSynth] WARNING: VapourSynth not installed, falling back to ffprobe")
        return None
    except Exception as e:
        runner._log_message(f"[VapourSynth] ERROR: Failed to index video: {e}")
        # Ensure cleanup even on error
        try:
            del clip
            del core
        except:
            pass
        gc.collect()
        return None


def detect_scene_changes(
    video_path: str,
    start_frame: int,
    end_frame: int,
    runner,
    max_scenes: int = 10,
    threshold: float = 27.0
) -> List[int]:
    """
    Detect scene changes in a video using PySceneDetect.

    Uses ContentDetector for fast and reliable scene change detection.
    Returns the frame BEFORE each scene change (last frame of previous scene)
    as a concrete anchor point for sync verification.

    Scene changes are ideal checkpoints because:
    - Adjacent frames are distinctly different (unambiguous for matching)
    - The frame before the cut is a stable reference point
    - Frame matching at cuts is highly reliable

    Args:
        video_path: Path to video file
        start_frame: Start frame to search from
        end_frame: End frame to search to
        runner: CommandRunner for logging
        max_scenes: Maximum number of scene changes to return
        threshold: Detection threshold (lower = more sensitive, default 27.0)

    Returns:
        List of frame numbers (the frame BEFORE each scene change)
    """
    try:
        from scenedetect import detect, ContentDetector, open_video

        runner._log_message(f"[SceneDetect] Detecting scene changes in {Path(video_path).name}")
        runner._log_message(f"[SceneDetect] Using PySceneDetect (ContentDetector, threshold={threshold})")
        runner._log_message(f"[SceneDetect] Searching frames {start_frame} to {end_frame}")

        # Open video and get framerate
        video = open_video(str(video_path))
        fps = video.frame_rate
        # Close video handle to prevent resource leaks in batch processing
        del video

        # Convert frame range to time range for PySceneDetect
        start_time_sec = start_frame / fps
        end_time_sec = end_frame / fps

        runner._log_message(f"[SceneDetect] Time range: {start_time_sec:.2f}s - {end_time_sec:.2f}s (fps={fps:.3f})")

        # Detect scenes using ContentDetector
        # Returns list of (start_timecode, end_timecode) tuples for each scene
        scene_list = detect(
            str(video_path),
            ContentDetector(threshold=threshold, min_scene_len=15),
            start_time=start_time_sec,
            end_time=end_time_sec,
            show_progress=False
        )

        # Extract frame BEFORE each scene change (last frame of previous scene)
        # This is our concrete anchor point - the frame just before the cut
        scene_frames = []

        for i, (scene_start, scene_end) in enumerate(scene_list):
            if i == 0:
                # First scene - skip, no "before" frame exists for the first cut
                continue

            # scene_start is the first frame of the NEW scene (after the cut)
            # We want the frame BEFORE this (last frame of previous scene)
            cut_frame = scene_start.get_frames()
            anchor_frame = cut_frame - 1  # Frame before the scene change

            if anchor_frame >= start_frame and anchor_frame <= end_frame:
                scene_frames.append(anchor_frame)
                runner._log_message(
                    f"[SceneDetect] Scene change at frame {cut_frame} → anchor frame {anchor_frame} "
                    f"(t={anchor_frame/fps:.3f}s)"
                )

                if len(scene_frames) >= max_scenes:
                    break

        runner._log_message(f"[SceneDetect] Found {len(scene_frames)} scene change anchor frames")

        # If we didn't find enough scenes, try with lower threshold
        if len(scene_frames) < 2:
            runner._log_message(f"[SceneDetect] Few scenes found, trying with lower threshold (15.0)")

            scene_list = detect(
                str(video_path),
                ContentDetector(threshold=15.0, min_scene_len=10),
                start_time=start_time_sec,
                end_time=end_time_sec,
                show_progress=False
            )

            scene_frames = []
            for i, (scene_start, scene_end) in enumerate(scene_list):
                if i == 0:
                    continue
                cut_frame = scene_start.get_frames()
                anchor_frame = cut_frame - 1

                if anchor_frame >= start_frame and anchor_frame <= end_frame:
                    scene_frames.append(anchor_frame)
                    if len(scene_frames) >= max_scenes:
                        break

            runner._log_message(f"[SceneDetect] Found {len(scene_frames)} scenes with lower threshold")

        return scene_frames

    except ImportError as e:
        runner._log_message(f"[SceneDetect] WARNING: PySceneDetect not available: {e}")
        runner._log_message("[SceneDetect] Install with: pip install scenedetect opencv-python")
        return []
    except Exception as e:
        runner._log_message(f"[SceneDetect] ERROR: {e}")
        import traceback
        runner._log_message(f"[SceneDetect] Traceback: {traceback.format_exc()}")
        return []


def extract_frame_as_image(video_path: str, frame_number: int, runner) -> Optional[bytes]:
    """
    Extract a single frame from video as PNG image data using VapourSynth.

    Args:
        video_path: Path to video file
        frame_number: Frame index to extract (0-based)
        runner: CommandRunner for logging

    Returns:
        PNG image data as bytes, or None on error
    """
    try:
        import vapoursynth as vs
        from PIL import Image
        import numpy as np
        import io

        core = vs.core

        # Load video - try L-SMASH first, fall back to FFmpegSource2
        clip = None
        try:
            clip = core.lsmas.LWLibavSource(str(video_path))
        except (AttributeError, Exception):
            pass

        if clip is None:
            try:
                clip = core.ffms2.Source(str(video_path))
            except Exception as e:
                runner._log_message(f"[VapourSynth] ERROR: Failed to load video: {e}")
                del core
                gc.collect()
                return None

        # Validate frame number
        if frame_number < 0 or frame_number >= clip.num_frames:
            runner._log_message(f"[VapourSynth] ERROR: Frame {frame_number} out of range (0-{clip.num_frames-1})")
            del clip
            del core
            gc.collect()
            return None

        # Get frame
        frame = clip.get_frame(frame_number)

        # Convert frame to RGB for PIL
        # VapourSynth frame format is planar, need to convert to interleaved
        width = frame.width
        height = frame.height

        # Read planes (YUV or RGB depending on format)
        # Convert to RGB24 first if needed
        if frame.format.color_family == vs.YUV:
            clip_rgb = core.resize.Bicubic(clip, format=vs.RGB24, matrix_in_s="709")
            frame_rgb = clip_rgb.get_frame(frame_number)
        else:
            frame_rgb = frame

        # Extract RGB data
        # VapourSynth stores planes separately, PIL needs interleaved RGB
        r_plane = np.array(frame_rgb[0], copy=False)
        g_plane = np.array(frame_rgb[1], copy=False)
        b_plane = np.array(frame_rgb[2], copy=False)

        # Stack into RGB image
        rgb_array = np.stack([r_plane, g_plane, b_plane], axis=2)

        # Create PIL Image
        img = Image.fromarray(rgb_array, mode='RGB')

        # Convert to PNG bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_data = img_bytes.getvalue()

        # Free memory
        del frame
        del frame_rgb
        del clip
        try:
            del clip_rgb
        except:
            pass
        del core
        del img
        del rgb_array
        gc.collect()

        return img_data

    except Exception as e:
        runner._log_message(f"[VapourSynth] ERROR: Failed to extract frame {frame_number}: {e}")
        # Cleanup on error
        try:
            del clip
            del core
        except:
            pass
        gc.collect()
        return None


def compute_perceptual_hash(image_data: bytes, runner, algorithm: str = 'dhash', hash_size: int = 8) -> Optional[str]:
    """
    Compute perceptual hash from image data.

    Supports multiple algorithms with different tolerance levels:
    - dhash: Difference hash - good for compression artifacts (default)
    - phash: Perceptual hash - best for heavy re-encoding, color grading
    - average_hash: Simple averaging - fast but less accurate
    - whash: Wavelet hash - very robust but slower

    Args:
        image_data: PNG/JPEG image data as bytes
        runner: CommandRunner for logging
        algorithm: Hash algorithm to use (dhash, phash, average_hash, whash)
        hash_size: Hash size (4, 8, 16) - larger = more precise but less tolerant

    Returns:
        Hexadecimal hash string, or None on error
    """
    try:
        from PIL import Image
        import imagehash
        import io

        img = Image.open(io.BytesIO(image_data))

        # Select hash algorithm
        if algorithm == 'phash':
            hash_obj = imagehash.phash(img, hash_size=hash_size)
        elif algorithm == 'average_hash':
            hash_obj = imagehash.average_hash(img, hash_size=hash_size)
        elif algorithm == 'whash':
            hash_obj = imagehash.whash(img, hash_size=hash_size)
        else:  # dhash (default)
            hash_obj = imagehash.dhash(img, hash_size=hash_size)

        del img
        gc.collect()

        return str(hash_obj)

    except ImportError:
        runner._log_message("[Perceptual Hash] WARNING: imagehash library not installed")
        runner._log_message("[Perceptual Hash] Install with: pip install imagehash")
        return None
    except Exception as e:
        runner._log_message(f"[Perceptual Hash] ERROR: Failed to compute hash: {e}")
        return None


def validate_frame_alignment(
    source_video: str,
    target_video: str,
    subtitle_events: List,
    duration_offset_ms: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Validate that videos are frame-aligned by comparing perceptual hashes.

    Checks 3 points throughout the video:
    1. First subtitle event (~5 min in)
    2. Middle subtitle event (~45 min in)
    3. Last subtitle event (~85 min in)

    For each checkpoint:
    - Extracts 11 frames (center ± 5 frames)
    - Computes perceptual hashes
    - Compares source vs target
    - Reports match confidence

    Args:
        source_video: Path to source video
        target_video: Path to target video
        subtitle_events: List of subtitle events
        duration_offset_ms: Calculated duration offset
        runner: CommandRunner for logging
        config: Optional config dict with:
            - 'duration_align_validate': bool (enable/disable)
            - 'duration_align_validate_points': int (1 or 3)
            - 'duration_align_hash_threshold': int (max hamming distance)

    Returns:
        Dict with validation results
    """
    config = config or {}

    # Check if validation is enabled
    if not config.get('duration_align_validate', True):
        runner._log_message("[Frame Validation] Validation disabled in config")
        return {'enabled': False, 'valid': True}

    runner._log_message(f"[Frame Validation] ═══════════════════════════════════════")
    runner._log_message(f"[Frame Validation] Validating frame alignment...")

    # Get number of checkpoints to validate
    # UI sends text like "1 point (fast)" or "3 points (thorough)", extract the number
    num_points_str = config.get('duration_align_validate_points', '3 points (thorough)')
    if '1 point' in str(num_points_str):
        num_points = 1
    elif '3 points' in str(num_points_str):
        num_points = 3
    else:
        # Fallback: try to extract number or default to 3
        try:
            num_points = int(num_points_str)
        except (ValueError, TypeError):
            num_points = 3

    hash_threshold = config.get('duration_align_hash_threshold', 5)
    hash_algorithm = config.get('duration_align_hash_algorithm', 'dhash')
    # UI sends hash_size as string ("4", "8", "16"), convert to int
    hash_size_str = config.get('duration_align_hash_size', '8')
    hash_size = int(hash_size_str) if isinstance(hash_size_str, str) else hash_size_str
    strictness_pct = config.get('duration_align_strictness', 80)

    runner._log_message(f"[Frame Validation] Hash algorithm: {hash_algorithm}")
    runner._log_message(f"[Frame Validation] Hash size: {hash_size}x{hash_size}")
    runner._log_message(f"[Frame Validation] Hash threshold: {hash_threshold}")
    runner._log_message(f"[Frame Validation] Strictness: {strictness_pct}%")

    # Find non-empty subtitle events
    valid_events = [e for e in subtitle_events if e.end > e.start]
    if not valid_events:
        runner._log_message("[Frame Validation] WARNING: No valid subtitle events to validate")
        return {'enabled': True, 'valid': False, 'error': 'No valid subtitle events'}

    # Select checkpoints
    checkpoints = []
    if num_points == 1:
        # Just check first event
        checkpoints = [valid_events[0]]
    else:  # 3 points
        # First, middle, last
        first_event = valid_events[0]
        middle_event = valid_events[len(valid_events) // 2]
        last_event = valid_events[-1]
        checkpoints = [first_event, middle_event, last_event]
        runner._log_message(f"[Frame Validation] Checking 3 points:")
        runner._log_message(f"[Frame Validation]   - First subtitle @ {first_event.start}ms")
        runner._log_message(f"[Frame Validation]   - Middle subtitle @ {middle_event.start}ms")
        runner._log_message(f"[Frame Validation]   - Last subtitle @ {last_event.start}ms")

    # Detect FPS
    source_fps = detect_video_fps(source_video, runner)
    target_fps = detect_video_fps(target_video, runner)

    validation_results = {
        'enabled': True,
        'valid': True,
        'checkpoints': [],
        'total_frames_checked': 0,
        'matched_frames': 0,
        'mismatched_frames': 0
    }

    # Validate each checkpoint
    for idx, event in enumerate(checkpoints, 1):
        checkpoint_name = ['First', 'Middle', 'Last'][idx - 1] if num_points == 3 else 'First'

        runner._log_message(f"[Frame Validation] ─────────────────────────────────────")
        runner._log_message(f"[Frame Validation] Checkpoint {idx}/{len(checkpoints)}: {checkpoint_name} subtitle")

        # Get source frame for this subtitle
        source_time_ms = event.start
        # Use simple calculation instead of VFR function to avoid VideoTimestamps complexity
        source_frame = int(source_time_ms * source_fps / 1000.0)

        # Get target frame (source time + duration offset)
        target_time_ms = source_time_ms + duration_offset_ms
        target_frame = int(target_time_ms * target_fps / 1000.0)

        runner._log_message(f"[Frame Validation] Source: frame {source_frame} @ {source_time_ms}ms")
        runner._log_message(f"[Frame Validation] Target: frame {target_frame} @ {target_time_ms:.1f}ms")
        runner._log_message(f"[Frame Validation] Comparing 11 frames (center ± 5)...")

        checkpoint_result = {
            'checkpoint': checkpoint_name,
            'source_frame': source_frame,
            'target_frame': target_frame,
            'frames_checked': 0,
            'frames_matched': 0,
            'frames_mismatched': 0,
            'match_percentage': 0.0
        }

        # Compare frames: center ± 5
        for offset in range(-5, 6):
            src_frame_num = source_frame + offset
            tgt_frame_num = target_frame + offset

            # Extract frames
            src_img = extract_frame_as_image(source_video, src_frame_num, runner)
            tgt_img = extract_frame_as_image(target_video, tgt_frame_num, runner)

            if src_img is None or tgt_img is None:
                runner._log_message(f"[Frame Validation]   Frame {offset:+d}: SKIP (extraction failed)")
                continue

            # Compute hashes
            src_hash = compute_perceptual_hash(src_img, runner, hash_algorithm, hash_size)
            tgt_hash = compute_perceptual_hash(tgt_img, runner, hash_algorithm, hash_size)

            if src_hash is None or tgt_hash is None:
                runner._log_message(f"[Frame Validation]   Frame {offset:+d}: SKIP (hash failed)")
                continue

            # Compare hashes (Hamming distance)
            try:
                import imagehash
                src_hash_obj = imagehash.hex_to_hash(src_hash)
                tgt_hash_obj = imagehash.hex_to_hash(tgt_hash)
                hamming_dist = src_hash_obj - tgt_hash_obj

                checkpoint_result['frames_checked'] += 1
                validation_results['total_frames_checked'] += 1

                if hamming_dist <= hash_threshold:
                    checkpoint_result['frames_matched'] += 1
                    validation_results['matched_frames'] += 1
                    runner._log_message(f"[Frame Validation]   Frame {offset:+d}: ✓ MATCH (distance: {hamming_dist})")
                else:
                    checkpoint_result['frames_mismatched'] += 1
                    validation_results['mismatched_frames'] += 1
                    runner._log_message(f"[Frame Validation]   Frame {offset:+d}: ✗ MISMATCH (distance: {hamming_dist})")

            except Exception as e:
                runner._log_message(f"[Frame Validation]   Frame {offset:+d}: ERROR ({e})")

        # Calculate match percentage for this checkpoint
        if checkpoint_result['frames_checked'] > 0:
            match_pct = (checkpoint_result['frames_matched'] / checkpoint_result['frames_checked']) * 100
            checkpoint_result['match_percentage'] = match_pct

            runner._log_message(f"[Frame Validation] Checkpoint result: {checkpoint_result['frames_matched']}/{checkpoint_result['frames_checked']} matched ({match_pct:.1f}%)")

            # Consider checkpoint valid if >= strictness threshold
            if match_pct < strictness_pct:
                validation_results['valid'] = False
                runner._log_message(f"[Frame Validation] ⚠ WARNING: Low match rate for {checkpoint_name} subtitle ({match_pct:.1f}% < {strictness_pct}% required)!")

        validation_results['checkpoints'].append(checkpoint_result)

    # Final verdict
    runner._log_message(f"[Frame Validation] ═══════════════════════════════════════")

    if validation_results['total_frames_checked'] > 0:
        overall_match_pct = (validation_results['matched_frames'] / validation_results['total_frames_checked']) * 100
        validation_results['overall_match_percentage'] = overall_match_pct

        runner._log_message(f"[Frame Validation] OVERALL: {validation_results['matched_frames']}/{validation_results['total_frames_checked']} frames matched ({overall_match_pct:.1f}%)")

        if validation_results['valid']:
            runner._log_message(f"[Frame Validation] ✓ VALIDATION PASSED - Videos appear frame-aligned")
        else:
            runner._log_message(f"[Frame Validation] ✗ VALIDATION FAILED - Videos may NOT be frame-aligned!")
            runner._log_message(f"[Frame Validation] ⚠ Consider using audio-correlation mode instead")
    else:
        runner._log_message(f"[Frame Validation] ERROR: No frames could be validated")
        validation_results['valid'] = False

    runner._log_message(f"[Frame Validation] ═══════════════════════════════════════")

    return validation_results


# ============================================================================
# RAW DELAY MODE (No Frame Analysis)
# ============================================================================

def apply_raw_delay_sync(
    subtitle_path: str,
    total_delay_with_global_ms: float,
    raw_global_shift_ms: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Apply raw audio delay using the same logic as correlation-frame-snap mode.

    This mode does everything correlation-frame-snap does EXCEPT scene detection:
    1. Load subtitles via pysubs2
    2. Apply raw delay with floor rounding at final step
    3. Preserve metadata (Aegisub extradata, etc.)
    4. Save subtitles

    Same calculations as correlation-frame-snap's no-scene-matches path.
    Use this when you want the benefits of pysubs2 processing without frame verification.

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        total_delay_with_global_ms: Total delay including global shift (from raw_source_delays_ms)
        raw_global_shift_ms: Global shift that was applied (for logging breakdown)
        runner: CommandRunner for logging
        config: Optional config dict

    Returns:
        Dict with report statistics
    """
    config = config or {}

    # Calculate pure correlation (same as correlation-frame-snap)
    pure_correlation_ms = total_delay_with_global_ms - raw_global_shift_ms

    runner._log_message(f"[Raw Delay Sync] ═══════════════════════════════════════")
    runner._log_message(f"[Raw Delay Sync] Raw Delay Mode (no scene detection)")
    runner._log_message(f"[Raw Delay Sync] ═══════════════════════════════════════")
    runner._log_message(f"[Raw Delay Sync] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[Raw Delay Sync] Input values:")
    runner._log_message(f"[Raw Delay Sync]   Total delay (with global): {total_delay_with_global_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   Global shift:              {raw_global_shift_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   Pure correlation:          {pure_correlation_ms:+.3f}ms")

    # Capture original metadata before pysubs2 processing
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Raw Delay Sync] ERROR: Failed to load subtitle file: {e}")
        return {'error': str(e)}

    if not subs.events:
        runner._log_message(f"[Raw Delay Sync] WARNING: No subtitle events found in file")
        return {
            'success': True,
            'total_events': 0,
            'pure_correlation_ms': pure_correlation_ms,
            'global_shift_ms': raw_global_shift_ms,
            'final_offset_applied': 0
        }

    runner._log_message(f"[Raw Delay Sync] Loaded {len(subs.events)} subtitle events")

    # Calculate final offset using floor (same as correlation-frame-snap)
    final_offset_ms = total_delay_with_global_ms
    final_offset_int = int(math.floor(final_offset_ms))

    runner._log_message(f"[Raw Delay Sync] ───────────────────────────────────────")
    runner._log_message(f"[Raw Delay Sync] Final offset calculation:")
    runner._log_message(f"[Raw Delay Sync]   Pure correlation:     {pure_correlation_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   + Global shift:       {raw_global_shift_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   ─────────────────────────────────────")
    runner._log_message(f"[Raw Delay Sync]   = Total delay:        {total_delay_with_global_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   Floor applied:        {final_offset_int:+d}ms")
    runner._log_message(f"[Raw Delay Sync] ───────────────────────────────────────")

    # Apply offset to all events (same as correlation-frame-snap)
    runner._log_message(f"[Raw Delay Sync] Applying offset to {len(subs.events)} events...")

    for event in subs.events:
        event.start += final_offset_int
        event.end += final_offset_int

    # Save modified subtitle
    runner._log_message(f"[Raw Delay Sync] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Raw Delay Sync] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Validate and restore lost metadata
    metadata.validate_and_restore(runner, expected_delay_ms=final_offset_int)

    runner._log_message(f"[Raw Delay Sync] Successfully synchronized {len(subs.events)} events")
    runner._log_message(f"[Raw Delay Sync] ═══════════════════════════════════════")

    return {
        'success': True,
        'total_events': len(subs.events),
        'pure_correlation_ms': pure_correlation_ms,
        'global_shift_ms': raw_global_shift_ms,
        'final_offset_ms': final_offset_ms,
        'final_offset_applied': final_offset_int
    }


# ============================================================================
# DURATION ALIGNMENT MODE (Frame Alignment via Total Duration)
# ============================================================================

def _select_smart_checkpoints(subtitle_events: List, runner) -> List:
    """
    Smart checkpoint selection: avoid OP/ED, prefer dialogue events.

    Strategy:
    - Filter out first/last 2 minutes (OP/ED likely)
    - Prefer longer duration events (likely dialogue, not signs)
    - Use repeatable selection based on event count
    - Return 3 checkpoints: early (1/6), middle (1/2), late (5/6)
    """
    total_events = len(subtitle_events)
    if total_events == 0:
        return []

    # Calculate video duration to determine safe zones
    first_start = subtitle_events[0].start
    last_end = subtitle_events[-1].end
    duration_ms = last_end - first_start

    # Define safe zone: skip first/last 2 minutes (120000ms)
    op_zone_ms = 120000  # First 2 minutes
    ed_zone_ms = 120000  # Last 2 minutes

    safe_start_ms = first_start + op_zone_ms
    safe_end_ms = last_end - ed_zone_ms

    # If video is too short, just use middle third
    if duration_ms < (op_zone_ms + ed_zone_ms):
        safe_start_ms = first_start + (duration_ms // 3)
        safe_end_ms = last_end - (duration_ms // 3)

    # Filter events in safe zone
    safe_events = [e for e in subtitle_events if safe_start_ms <= e.start <= safe_end_ms]

    if len(safe_events) < 3:
        # Not enough safe events, fall back to middle third of all events
        start_idx = total_events // 3
        end_idx = 2 * total_events // 3
        safe_events = subtitle_events[start_idx:end_idx]
        runner._log_message(f"[Checkpoint Selection] Using middle third (not enough events in safe zone)")

    if len(safe_events) == 0:
        # Last resort: use first/mid/last of all events
        return [subtitle_events[0], subtitle_events[total_events // 2], subtitle_events[-1]]

    # Prefer longer duration events (dialogue over signs)
    # Sort by duration descending, take top 40%
    sorted_by_duration = sorted(safe_events, key=lambda e: e.end - e.start, reverse=True)
    top_events = sorted_by_duration[:max(3, len(sorted_by_duration) * 40 // 100)]

    # Sort these back by start time for temporal ordering
    top_events_sorted = sorted(top_events, key=lambda e: e.start)

    if len(top_events_sorted) >= 3:
        # Pick early (1/6), middle (1/2), late (5/6)
        early = top_events_sorted[len(top_events_sorted) // 6]
        middle = top_events_sorted[len(top_events_sorted) // 2]
        late = top_events_sorted[5 * len(top_events_sorted) // 6]
        checkpoints = [early, middle, late]
    elif len(top_events_sorted) == 2:
        checkpoints = top_events_sorted
    else:
        checkpoints = top_events_sorted

    runner._log_message(f"[Checkpoint Selection] Selected {len(checkpoints)} dialogue events:")
    for i, e in enumerate(checkpoints):
        duration = e.end - e.start
        runner._log_message(f"  {i+1}. Time: {e.start}ms, Duration: {duration}ms")

    return checkpoints


def verify_alignment_with_sliding_window(
    source_video: str,
    target_video: str,
    subtitle_events: List,
    duration_offset_ms: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Hybrid verification with TEMPORAL CONSISTENCY: Use duration offset as starting
    point, then verify with sliding window matching of MULTIPLE adjacent frames.

    Algorithm:
    1. Use duration_offset_ms as rough estimate
    2. Smart checkpoint selection (avoid OP/ED, prefer dialogue)
    3. For each checkpoint:
       - Extract 11 frames from source (center ± 5 frames)
       - Compute hashes for ALL 11 frames
       - For each candidate offset in search window:
           * Extract 11 corresponding frames from target
           * Compare ALL frame pairs (temporal consistency)
           * Calculate aggregate match score
       - Select offset with BEST aggregate score
    4. Check if all checkpoint measurements agree within tolerance
    5. Return precise offset if agreement, else indicate fallback needed

    This fixes false positives on static anime scenes by verifying temporal
    consistency across multiple frames, not just a single center frame.

    Args:
        source_video: Path to source video
        target_video: Path to target video
        subtitle_events: List of subtitle events
        duration_offset_ms: Rough offset from duration calculation
        runner: CommandRunner for logging
        config: Config dict with:
            - duration_align_verify_search_window_ms: ±search window (default: 2000)
            - duration_align_verify_agreement_tolerance_ms: tolerance (default: 100)
            - duration_align_hash_algorithm: hash method (default: 'dhash')
            - duration_align_hash_size: hash size (default: 8)
            - duration_align_hash_threshold: max hamming distance (default: 5)

    Returns:
        Dict with:
            - enabled: bool (whether verification ran)
            - valid: bool (whether measurements agree)
            - precise_offset_ms: float (median of measurements if valid)
            - measurements: List[float] (individual measurements)
            - duration_offset_ms: float (original duration offset)
            - checkpoints: List[Dict] (details for each checkpoint)
    """
    config = config or {}

    runner._log_message(f"[Hybrid Verification] ═══════════════════════════════════════")
    runner._log_message(f"[Hybrid Verification] Running TEMPORAL CONSISTENCY verification...")
    runner._log_message(f"[Hybrid Verification] Duration offset (rough): {duration_offset_ms:+.3f}ms")

    # Get config parameters
    search_window_ms = config.get('duration_align_verify_search_window_ms', 2000)
    tolerance_ms = config.get('duration_align_verify_agreement_tolerance_ms', 100)
    hash_algorithm = config.get('duration_align_hash_algorithm', 'dhash')
    hash_size = int(config.get('duration_align_hash_size', 8))
    hash_threshold = int(config.get('duration_align_hash_threshold', 5))

    runner._log_message(f"[Hybrid Verification] Search window: ±{search_window_ms}ms")
    runner._log_message(f"[Hybrid Verification] Agreement tolerance: ±{tolerance_ms}ms")
    runner._log_message(f"[Hybrid Verification] Hash: {hash_algorithm}, size={hash_size}, threshold={hash_threshold}")

    # Smart checkpoint selection (avoid OP/ED, prefer dialogue)
    checkpoints = _select_smart_checkpoints(subtitle_events, runner)

    if len(checkpoints) == 0:
        runner._log_message(f"[Hybrid Verification] ERROR: No valid checkpoints found")
        return {
            'enabled': True,
            'valid': False,
            'error': 'No valid checkpoints for verification',
            'measurements': [],
            'duration_offset_ms': duration_offset_ms
        }

    # Import frame matching utilities
    try:
        from .frame_matching import VideoReader, compute_frame_hash
    except ImportError:
        runner._log_message(f"[Hybrid Verification] ERROR: frame_matching module not available")
        return {
            'enabled': True,
            'valid': False,
            'error': 'frame_matching module not available',
            'measurements': [],
            'duration_offset_ms': duration_offset_ms
        }

    measurements = []
    checkpoint_details = []

    # Open video readers
    try:
        source_reader = VideoReader(source_video, runner)
        target_reader = VideoReader(target_video, runner)
    except Exception as e:
        runner._log_message(f"[Hybrid Verification] ERROR: Failed to open videos: {e}")
        return {
            'enabled': True,
            'valid': False,
            'error': f'Failed to open videos: {e}',
            'measurements': [],
            'duration_offset_ms': duration_offset_ms
        }

    # Process each checkpoint with TEMPORAL CONSISTENCY
    fps = source_reader.fps or 23.976
    frame_duration_ms = 1000.0 / fps
    num_frames = 11  # center ± 5

    for i, event in enumerate(checkpoints):
        checkpoint_time_ms = event.start
        runner._log_message(f"[Hybrid Verification] Checkpoint {i+1}/{len(checkpoints)}: {checkpoint_time_ms}ms")

        # Step 1: Extract and hash ALL 11 source frames
        source_frame_hashes = []  # List of (offset, hash)
        for offset in range(-5, 6):  # -5 to +5 = 11 frames
            frame_time_ms = checkpoint_time_ms + (offset * frame_duration_ms)
            frame = source_reader.get_frame_at_time(int(frame_time_ms))
            if frame is not None:
                frame_hash = compute_frame_hash(frame, hash_size=hash_size, method=hash_algorithm)
                if frame_hash is not None:
                    source_frame_hashes.append((offset, frame_hash))

        if len(source_frame_hashes) < 8:  # Need at least 8/11 frames (73%)
            runner._log_message(f"[Hybrid Verification] WARNING: Not enough source frames ({len(source_frame_hashes)}/11)")
            continue

        runner._log_message(f"[Hybrid Verification]   Extracted {len(source_frame_hashes)} source frames for temporal matching")

        # Step 2: Sliding window with AGGREGATE SCORING (temporal consistency)
        search_center_ms = checkpoint_time_ms + duration_offset_ms
        search_start_ms = search_center_ms - search_window_ms
        search_end_ms = search_center_ms + search_window_ms

        runner._log_message(f"[Hybrid Verification]   Searching {search_start_ms:.0f}ms - {search_end_ms:.0f}ms")

        # Track best match across entire search window
        best_match_offset = None
        best_aggregate_score = -1  # Higher = better
        best_matched_frames = 0

        # Search every 5 frames (skip some for performance)
        search_step_ms = 5 * frame_duration_ms
        current_search_ms = search_start_ms

        candidates_checked = 0
        while current_search_ms <= search_end_ms:
            # For this candidate offset, extract and compare ALL frames
            matched_frames = 0
            total_distance = 0

            for offset, source_hash in source_frame_hashes:
                target_time_ms = current_search_ms + (offset * frame_duration_ms)
                target_frame = target_reader.get_frame_at_time(int(target_time_ms))

                if target_frame is not None:
                    target_hash = compute_frame_hash(target_frame, hash_size=hash_size, method=hash_algorithm)
                    if target_hash is not None:
                        distance = source_hash - target_hash

                        # Frame matches if within threshold
                        if distance <= hash_threshold:
                            matched_frames += 1

                        total_distance += distance

            # Calculate aggregate score: prioritize match count, then average distance
            # Score = (matched_frames * 1000) - average_distance
            if len(source_frame_hashes) > 0:
                avg_distance = total_distance / len(source_frame_hashes)
                aggregate_score = (matched_frames * 1000) - avg_distance

                # Update best match if this is better
                if aggregate_score > best_aggregate_score:
                    best_aggregate_score = aggregate_score
                    best_match_offset = current_search_ms - checkpoint_time_ms
                    best_matched_frames = matched_frames

            current_search_ms += search_step_ms
            candidates_checked += 1

        runner._log_message(f"[Hybrid Verification]   Checked {candidates_checked} candidate offsets")

        # Step 3: Validate temporal consistency (need ≥70% frame matches)
        min_required_matches = int(len(source_frame_hashes) * 0.70)  # 70% threshold

        if best_match_offset is not None and best_matched_frames >= min_required_matches:
            match_percent = (best_matched_frames / len(source_frame_hashes)) * 100
            measurements.append(best_match_offset)
            runner._log_message(f"[Hybrid Verification]   ✓ Match: offset={best_match_offset:+.1f}ms, {best_matched_frames}/{len(source_frame_hashes)} frames ({match_percent:.0f}%)")
            checkpoint_details.append({
                'checkpoint_ms': checkpoint_time_ms,
                'offset_ms': best_match_offset,
                'matched_frames': best_matched_frames,
                'total_frames': len(source_frame_hashes),
                'match_percent': match_percent,
                'matched': True
            })
        else:
            match_percent = (best_matched_frames / len(source_frame_hashes) * 100) if best_matched_frames else 0
            runner._log_message(f"[Hybrid Verification]   ✗ No temporal consistency: {best_matched_frames}/{len(source_frame_hashes)} frames ({match_percent:.0f}% < 70%)")
            checkpoint_details.append({
                'checkpoint_ms': checkpoint_time_ms,
                'offset_ms': best_match_offset,
                'matched_frames': best_matched_frames,
                'total_frames': len(source_frame_hashes),
                'match_percent': match_percent,
                'matched': False
            })

    # Clean up video readers
    del source_reader
    del target_reader
    gc.collect()

    # Check if measurements agree
    if len(measurements) < 2:
        runner._log_message(f"[Hybrid Verification] FAILED: Not enough successful measurements ({len(measurements)}/3)")
        return {
            'enabled': True,
            'valid': False,
            'measurements': measurements,
            'duration_offset_ms': duration_offset_ms,
            'checkpoints': checkpoint_details,
            'error': 'Not enough successful measurements'
        }

    # Calculate statistics
    median_offset = sorted(measurements)[len(measurements) // 2]
    max_deviation = max(abs(m - median_offset) for m in measurements)

    runner._log_message(f"[Hybrid Verification] Measurements: {[f'{m:+.1f}ms' for m in measurements]}")
    runner._log_message(f"[Hybrid Verification] Median offset: {median_offset:+.1f}ms")
    runner._log_message(f"[Hybrid Verification] Max deviation: {max_deviation:.1f}ms")
    runner._log_message(f"[Hybrid Verification] Duration offset: {duration_offset_ms:+.1f}ms")
    runner._log_message(f"[Hybrid Verification] Difference: {abs(median_offset - duration_offset_ms):.1f}ms")

    # Check agreement
    if max_deviation <= tolerance_ms:
        runner._log_message(f"[Hybrid Verification] ✓ PASS: All measurements agree within ±{tolerance_ms}ms")
        return {
            'enabled': True,
            'valid': True,
            'precise_offset_ms': median_offset,
            'measurements': measurements,
            'duration_offset_ms': duration_offset_ms,
            'max_deviation_ms': max_deviation,
            'checkpoints': checkpoint_details
        }
    else:
        runner._log_message(f"[Hybrid Verification] ✗ FAIL: Measurements disagree (max deviation: {max_deviation:.1f}ms > {tolerance_ms}ms)")
        return {
            'enabled': True,
            'valid': False,
            'precise_offset_ms': median_offset,
            'measurements': measurements,
            'duration_offset_ms': duration_offset_ms,
            'max_deviation_ms': max_deviation,
            'checkpoints': checkpoint_details,
            'error': 'Measurements disagree - videos may have different cuts or VFR'
        }


def apply_duration_align_sync(
    subtitle_path: str,
    source_video: str,
    target_video: str,
    global_shift_ms: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Align subtitles by total video duration difference (frame alignment).

    Algorithm:
    1. Get total duration of source video (where subs are from)
    2. Get total duration of target video (Source 1)
    3. Calculate duration_offset = target_duration - source_duration
    4. Apply duration_offset to all subtitle times
    5. Apply global_shift_ms on top (if any)

    Example:
    - Source video: 23:40.003 (1420003ms)
    - Target video: 23:41.002 (1421002ms)
    - Duration offset: +999ms
    - Global shift: +1000ms
    - Total shift: +1999ms

    This aligns subtitles to the target video's frame timing,
    then adds global shift to sync with other tracks.

    Args:
        subtitle_path: Path to subtitle file
        source_video: Path to video that subs were originally timed to
        target_video: Path to target video (Source 1)
        global_shift_ms: Global shift from delays (raw_global_shift_ms)
        runner: CommandRunner for logging
        config: Optional config dict

    Returns:
        Dict with report statistics
    """
    try:
        from video_timestamps import FPSTimestamps, VideoTimestamps
        from fractions import Fraction
    except ImportError:
        runner._log_message("[Duration Align] ERROR: VideoTimestamps not installed. Install with: pip install VideoTimestamps")
        return {'error': 'VideoTimestamps library not installed'}

    config = config or {}

    runner._log_message(f"[Duration Align] Mode: Frame alignment via total duration difference")
    runner._log_message(f"[Duration Align] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[Duration Align] Source video: {Path(source_video).name}")
    runner._log_message(f"[Duration Align] Target video: {Path(target_video).name}")

    # Try VapourSynth first (fast + accurate), fallback to ffprobe
    use_vapoursynth = config.get('duration_align_use_vapoursynth', True)

    source_frame_count = None
    source_duration_ms = None
    target_frame_count = None
    target_duration_ms = None

    if use_vapoursynth:
        runner._log_message(f"[Duration Align] Using VapourSynth for frame indexing (fast after first run)")

        # Get source video info
        source_info = get_vapoursynth_frame_info(source_video, runner)
        if source_info:
            source_frame_count, source_duration_ms = source_info
        else:
            runner._log_message(f"[Duration Align] VapourSynth failed for source, falling back to ffprobe")

        # Get target video info
        target_info = get_vapoursynth_frame_info(target_video, runner)
        if target_info:
            target_frame_count, target_duration_ms = target_info
        else:
            runner._log_message(f"[Duration Align] VapourSynth failed for target, falling back to ffprobe")

    # Fallback to ffprobe if VapourSynth failed or disabled
    if source_frame_count is None or target_frame_count is None:
        runner._log_message(f"[Duration Align] Using ffprobe for frame counting (slower, but reliable)")

        # Detect FPS of both videos
        source_fps = detect_video_fps(source_video, runner)
        target_fps = detect_video_fps(target_video, runner)

        # Get exact frame count from videos (frame-accurate, not container duration)
        import subprocess
        import json

        try:
            # Get source video frame count
            cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                   '-show_entries', 'stream=nb_read_frames', '-print_format', 'json', source_video]
            result = subprocess.run(cmd, capture_output=True, text=True)
            source_info = json.loads(result.stdout)
            source_frame_count = int(source_info['streams'][0]['nb_read_frames'])

            # Get target video frame count
            cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                   '-show_entries', 'stream=nb_read_frames', '-print_format', 'json', target_video]
            result = subprocess.run(cmd, capture_output=True, text=True)
            target_info = json.loads(result.stdout)
            target_frame_count = int(target_info['streams'][0]['nb_read_frames'])

        except Exception as e:
            runner._log_message(f"[Duration Align] ERROR: Failed to get frame counts: {e}")
            return {'error': str(e)}

        runner._log_message(f"[Duration Align] Source frame count: {source_frame_count}")
        runner._log_message(f"[Duration Align] Target frame count: {target_frame_count}")

        # Calculate exact duration from last frame timestamp using VideoTimestamps
        # Last frame index = total_frames - 1 (zero-indexed)
        source_last_frame = source_frame_count - 1
        target_last_frame = target_frame_count - 1

        source_duration_ms = frame_to_time_vfr(source_last_frame, source_video, source_fps, runner, config)
        target_duration_ms = frame_to_time_vfr(target_last_frame, target_video, target_fps, runner, config)

        if source_duration_ms is None or target_duration_ms is None:
            runner._log_message(f"[Duration Align] ERROR: Failed to get last frame timestamps")
            return {'error': 'Failed to get last frame timestamps'}

    # Report frame counts
    runner._log_message(f"[Duration Align] Source frame count: {source_frame_count}")
    runner._log_message(f"[Duration Align] Target frame count: {target_frame_count}")

    # Calculate duration offset
    duration_offset_ms = target_duration_ms - source_duration_ms

    source_last_frame = source_frame_count - 1
    target_last_frame = target_frame_count - 1

    runner._log_message(f"[Duration Align] Source last frame (#{source_last_frame}): {source_duration_ms}ms")
    runner._log_message(f"[Duration Align] Target last frame (#{target_last_frame}): {target_duration_ms}ms")
    runner._log_message(f"[Duration Align] Duration offset: {duration_offset_ms:+.3f}ms")
    runner._log_message(f"[Duration Align] Global shift: {global_shift_ms:+.3f}ms")

    # Total shift = duration offset + global shift
    total_shift_ms = duration_offset_ms + global_shift_ms
    runner._log_message(f"[Duration Align] Total shift to apply: {total_shift_ms:+.3f}ms")

    # Capture original metadata
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Duration Align] ERROR: Failed to load subtitle file: {e}")
        return {'error': str(e)}

    if not subs.events:
        runner._log_message(f"[Duration Align] WARNING: No subtitle events found")
        return {
            'total_events': 0,
            'duration_offset_ms': duration_offset_ms,
            'global_shift_ms': global_shift_ms,
            'total_shift_ms': total_shift_ms
        }

    runner._log_message(f"[Duration Align] Loaded {len(subs.events)} subtitle events")

    # VALIDATE/VERIFY: Check if videos are actually frame-aligned
    # Check if hybrid verification mode is enabled
    use_hybrid_verification = config.get('duration_align_verify_with_frames', False)

    if use_hybrid_verification:
        # HYBRID MODE: Duration + sliding window frame matching
        verification_result = verify_alignment_with_sliding_window(
            source_video,
            target_video,
            subs.events,
            duration_offset_ms,
            runner,
            config
        )

        if verification_result.get('valid'):
            # Use precise offset from frame matching
            precise_offset = verification_result['precise_offset_ms']
            runner._log_message(f"[Duration Align] ✓ Using precise offset from hybrid verification: {precise_offset:+.3f}ms")

            # Update total shift with precise offset
            total_shift_ms = precise_offset + global_shift_ms
            runner._log_message(f"[Duration Align] Updated total shift: {total_shift_ms:+.3f}ms")

            validation_result = verification_result
        else:
            # Hybrid verification failed - handle based on fallback mode
            fallback_mode = config.get('duration_align_fallback_mode', 'none')

            runner._log_message(f"[Duration Align] ⚠⚠⚠ HYBRID VERIFICATION FAILED ⚠⚠⚠")
            runner._log_message(f"[Duration Align] Reason: {verification_result.get('error', 'Unknown')}")

            if fallback_mode == 'abort':
                runner._log_message(f"[Duration Align] ABORTING: Fallback mode is 'abort'")
                return {
                    'error': f"Hybrid verification failed: {verification_result.get('error', 'Unknown')}",
                    'validation': verification_result
                }
            elif fallback_mode == 'duration-offset':
                runner._log_message(f"[Duration Align] Using duration offset (fallback)")
                runner._log_message(f"[Duration Align] Total shift: {total_shift_ms:+.3f}ms")
                validation_result = verification_result
                validation_result['warning'] = 'Hybrid verification failed - using duration offset'
            elif fallback_mode == 'auto-fallback':
                fallback_target = config.get('duration_align_fallback_target', 'not-implemented')
                runner._log_message(f"[Duration Align] AUTO-FALLBACK: Would switch to '{fallback_target}' mode")
                runner._log_message(f"[Duration Align] (Auto-fallback not yet implemented, using duration offset)")
                validation_result = verification_result
                validation_result['warning'] = 'Hybrid verification failed - using duration offset'
            else:  # 'none' - warn but continue with duration offset
                runner._log_message(f"[Duration Align] Continuing with duration offset...")
                validation_result = verification_result
                validation_result['warning'] = 'Hybrid verification failed - using duration offset'
    else:
        # STANDARD MODE: Simple hash validation
        validation_result = validate_frame_alignment(
            source_video,
            target_video,
            subs.events,
            duration_offset_ms,
            runner,
            config
        )

        # If validation failed, handle based on fallback mode
        if validation_result.get('enabled') and not validation_result.get('valid'):
            fallback_mode = config.get('duration_align_fallback_mode', 'none')

            runner._log_message(f"[Duration Align] ⚠⚠⚠ VALIDATION FAILED ⚠⚠⚠")
            runner._log_message(f"[Duration Align] Videos may NOT be frame-aligned!")
            runner._log_message(f"[Duration Align] Sync may be INCORRECT - consider using audio-correlation mode")

            if fallback_mode == 'abort':
                runner._log_message(f"[Duration Align] ABORTING: Fallback mode is 'abort'")
                runner._log_message(f"[Duration Align] Either fix validation settings or switch to different sync mode")
                return {
                    'error': 'Frame alignment validation failed (fallback mode: abort)',
                    'validation': validation_result
                }
            elif fallback_mode == 'duration-offset':
                runner._log_message(f"[Duration Align] Using duration offset (fallback)")
                validation_result['warning'] = 'Frame alignment validation failed - using duration offset'
            elif fallback_mode == 'auto-fallback':
                fallback_target = config.get('duration_align_fallback_target', 'not-implemented')
                runner._log_message(f"[Duration Align] AUTO-FALLBACK: Would switch to '{fallback_target}' mode")
                runner._log_message(f"[Duration Align] (Auto-fallback not yet implemented, continuing with duration-align)")
                validation_result['warning'] = 'Frame alignment validation failed - sync may be incorrect'
            else:  # 'none' - warn but continue
                runner._log_message(f"[Duration Align] Continuing anyway... (you can abort if needed)")
                validation_result['warning'] = 'Frame alignment validation failed - sync may be incorrect'

    # Apply total shift to all events
    for event in subs.events:
        event.start = event.start + total_shift_ms
        event.end = event.end + total_shift_ms

    # Save modified subtitle
    runner._log_message(f"[Duration Align] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Duration Align] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Validate and restore metadata
    metadata.validate_and_restore(runner, expected_delay_ms=int(round(total_shift_ms)))

    # Log results
    runner._log_message(f"[Duration Align] ✓ Successfully synchronized {len(subs.events)} events")
    runner._log_message(f"[Duration Align]   - Duration offset: {duration_offset_ms:+.3f}ms")
    runner._log_message(f"[Duration Align]   - Global shift: {global_shift_ms:+.3f}ms")
    runner._log_message(f"[Duration Align]   - Total shift applied: {total_shift_ms:+.3f}ms")

    result = {
        'total_events': len(subs.events),
        'source_duration_ms': source_duration_ms,
        'target_duration_ms': target_duration_ms,
        'duration_offset_ms': duration_offset_ms,
        'global_shift_ms': global_shift_ms,
        'total_shift_ms': total_shift_ms,
        'validation': validation_result
    }

    # Add warning if validation failed
    if validation_result.get('enabled') and not validation_result.get('valid'):
        result['warning'] = 'Frame alignment validation failed - sync may be incorrect'

    return result


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

    runner._log_message(f"[FPS Detection] Detecting FPS from: {Path(video_path).name}")

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
            runner._log_message(f"[FPS Detection] WARNING: ffprobe failed, using default 23.976 fps")
            return 23.976

        data = json.loads(result.stdout)
        r_frame_rate = data['streams'][0]['r_frame_rate']

        # Parse fraction (e.g., "24000/1001" -> 23.976)
        if '/' in r_frame_rate:
            num, denom = r_frame_rate.split('/')
            fps = float(num) / float(denom)
        else:
            fps = float(r_frame_rate)

        runner._log_message(f"[FPS Detection] Detected FPS: {fps:.3f} ({r_frame_rate})")
        return fps

    except Exception as e:
        runner._log_message(f"[FPS Detection] WARNING: FPS detection failed: {e}")
        runner._log_message(f"[FPS Detection] Using default: 23.976 fps")
        return 23.976


def detect_video_properties(video_path: str, runner) -> Dict[str, Any]:
    """
    Detect comprehensive video properties for sync strategy selection.

    Detects FPS, interlacing, field order, telecine, duration, and frame count.
    Used to determine if special handling is needed (deinterlace, scaling, etc.)

    Args:
        video_path: Path to video file
        runner: CommandRunner for logging

    Returns:
        Dict with:
            - fps: float (e.g., 23.976)
            - fps_fraction: tuple (num, denom) e.g., (24000, 1001)
            - interlaced: bool
            - field_order: str ('progressive', 'tff', 'bff', 'unknown')
            - scan_type: str ('progressive', 'interlaced', 'telecine', 'unknown')
            - duration_ms: float
            - frame_count: int (estimated)
            - detection_source: str (what method was used)
    """
    import subprocess
    import json

    runner._log_message(f"[VideoProps] Detecting properties for: {Path(video_path).name}")

    # Default/fallback values
    props = {
        'fps': 23.976,
        'fps_fraction': (24000, 1001),
        'interlaced': False,
        'field_order': 'progressive',
        'scan_type': 'progressive',
        'duration_ms': 0.0,
        'frame_count': 0,
        'detection_source': 'fallback',
    }

    try:
        # Use ffprobe to get comprehensive stream info
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate,avg_frame_rate,field_order,nb_frames,duration,codec_name',
            '-show_entries', 'stream_side_data=',
            '-of', 'json',
            str(video_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            runner._log_message(f"[VideoProps] WARNING: ffprobe failed, using defaults")
            return props

        data = json.loads(result.stdout)

        if not data.get('streams'):
            runner._log_message(f"[VideoProps] WARNING: No video streams found")
            return props

        stream = data['streams'][0]
        props['detection_source'] = 'ffprobe'

        # Parse FPS from r_frame_rate (more reliable than avg_frame_rate)
        r_frame_rate = stream.get('r_frame_rate', '24000/1001')
        if '/' in r_frame_rate:
            num, denom = r_frame_rate.split('/')
            num, denom = int(num), int(denom)
            props['fps'] = num / denom
            props['fps_fraction'] = (num, denom)
        else:
            props['fps'] = float(r_frame_rate)
            props['fps_fraction'] = (int(float(r_frame_rate) * 1000), 1000)

        # Parse field_order for interlacing detection
        field_order = stream.get('field_order', 'progressive')

        if field_order in ('tt', 'tb'):
            props['interlaced'] = True
            props['field_order'] = 'tff'  # Top Field First
            props['scan_type'] = 'interlaced'
        elif field_order in ('bb', 'bt'):
            props['interlaced'] = True
            props['field_order'] = 'bff'  # Bottom Field First
            props['scan_type'] = 'interlaced'
        elif field_order == 'progressive':
            props['interlaced'] = False
            props['field_order'] = 'progressive'
            props['scan_type'] = 'progressive'
        else:
            # Unknown - might need deeper analysis
            props['field_order'] = 'unknown'

        # Parse duration
        duration_str = stream.get('duration')
        if duration_str:
            props['duration_ms'] = float(duration_str) * 1000.0

        # Parse frame count (if available)
        nb_frames = stream.get('nb_frames')
        if nb_frames and nb_frames != 'N/A':
            props['frame_count'] = int(nb_frames)
        elif props['duration_ms'] > 0 and props['fps'] > 0:
            # Estimate frame count from duration
            props['frame_count'] = int(props['duration_ms'] * props['fps'] / 1000.0)

        # Log detected properties
        runner._log_message(f"[VideoProps] FPS: {props['fps']:.3f} ({props['fps_fraction'][0]}/{props['fps_fraction'][1]})")
        runner._log_message(f"[VideoProps] Scan type: {props['scan_type']}, Field order: {props['field_order']}")
        runner._log_message(f"[VideoProps] Duration: {props['duration_ms']:.0f}ms, Frames: {props['frame_count']}")

        # Additional telecine detection for NTSC content
        # 29.97fps with film content often indicates telecine
        if abs(props['fps'] - 29.97) < 0.01:
            # Could be true 29.97, interlaced TV, or telecined film
            # We'll note this for potential special handling
            if props['interlaced']:
                runner._log_message(f"[VideoProps] NOTE: 29.97i content - may be interlaced TV or hard telecine")
            else:
                runner._log_message(f"[VideoProps] NOTE: 29.97p content - may be soft telecine or native 30p")

        return props

    except Exception as e:
        runner._log_message(f"[VideoProps] WARNING: Detection failed: {e}")
        return props


def compare_video_properties(source_props: Dict[str, Any], target_props: Dict[str, Any], runner) -> Dict[str, Any]:
    """
    Compare video properties between source and target to determine sync strategy.

    Args:
        source_props: Properties dict from detect_video_properties() for source
        target_props: Properties dict from detect_video_properties() for target
        runner: CommandRunner for logging

    Returns:
        Dict with:
            - strategy: str ('frame-based', 'timestamp-based', 'deinterlace', 'scale')
            - fps_match: bool
            - fps_ratio: float (source_fps / target_fps)
            - interlace_mismatch: bool
            - needs_deinterlace: bool
            - needs_scaling: bool
            - scale_factor: float (for PAL speedup etc.)
            - warnings: list of warning strings
    """
    runner._log_message(f"[VideoProps] ─────────────────────────────────────────")
    runner._log_message(f"[VideoProps] Comparing source vs target properties...")

    result = {
        'strategy': 'frame-based',  # Default: current mode works
        'fps_match': True,
        'fps_ratio': 1.0,
        'interlace_mismatch': False,
        'needs_deinterlace': False,
        'needs_scaling': False,
        'scale_factor': 1.0,
        'warnings': [],
    }

    source_fps = source_props['fps']
    target_fps = target_props['fps']

    # Check FPS match (within 0.1% tolerance)
    fps_diff_pct = abs(source_fps - target_fps) / target_fps * 100
    result['fps_ratio'] = source_fps / target_fps

    if fps_diff_pct < 0.1:
        # FPS matches
        result['fps_match'] = True
        runner._log_message(f"[VideoProps] FPS: MATCH ({source_fps:.3f} ≈ {target_fps:.3f})")
    else:
        result['fps_match'] = False
        runner._log_message(f"[VideoProps] FPS: MISMATCH ({source_fps:.3f} vs {target_fps:.3f}, diff={fps_diff_pct:.2f}%)")

        # Check for PAL speedup (23.976 → 25 = 4.17% faster)
        if 1.04 < result['fps_ratio'] < 1.05:
            result['needs_scaling'] = True
            result['scale_factor'] = target_fps / source_fps  # e.g., 23.976/25 = 0.959
            result['strategy'] = 'scale'
            result['warnings'].append(f"PAL speedup detected (ratio={result['fps_ratio']:.4f}), subtitles need scaling")
            runner._log_message(f"[VideoProps] PAL speedup detected - will need subtitle scaling")
        elif 0.95 < 1/result['fps_ratio'] < 0.96:
            # Reverse PAL (25 → 23.976)
            result['needs_scaling'] = True
            result['scale_factor'] = target_fps / source_fps
            result['strategy'] = 'scale'
            result['warnings'].append(f"Reverse PAL detected, subtitles need scaling")
            runner._log_message(f"[VideoProps] Reverse PAL detected - will need subtitle scaling")
        else:
            # Different framerates, use timestamp-based
            result['strategy'] = 'timestamp-based'
            result['warnings'].append(f"Different framerates - frame-based matching may be unreliable")
            runner._log_message(f"[VideoProps] Different framerates - timestamp-based matching recommended")

    # Check interlacing
    source_interlaced = source_props['interlaced']
    target_interlaced = target_props['interlaced']

    if source_interlaced != target_interlaced:
        result['interlace_mismatch'] = True
        runner._log_message(f"[VideoProps] Interlacing: MISMATCH (source={source_interlaced}, target={target_interlaced})")

    if source_interlaced or target_interlaced:
        result['needs_deinterlace'] = True
        if result['strategy'] == 'frame-based':
            result['strategy'] = 'deinterlace'
        result['warnings'].append(f"Interlaced content detected - frame hashing may be less reliable")
        runner._log_message(f"[VideoProps] Interlaced content - will need deinterlace for frame matching")

    # Summary
    runner._log_message(f"[VideoProps] Recommended strategy: {result['strategy']}")
    if result['warnings']:
        for warn in result['warnings']:
            runner._log_message(f"[VideoProps] WARNING: {warn}")
    runner._log_message(f"[VideoProps] ─────────────────────────────────────────")

    return result


# ============================================================================
# CORRELATION + FRAME SNAP MODE
# ============================================================================
# This mode uses audio correlation as the authoritative offset, then verifies
# frame alignment and applies ±1 frame correction if needed.
#
# CRITICAL MATH NOTES:
# - raw_source_delays_ms[source_key] ALREADY INCLUDES global_shift (baked in during analysis)
# - For frame verification, we need PURE correlation (subtract global_shift back out)
# - Videos are in their ORIGINAL state during verification (global_shift not applied yet)
# - Final offset uses the value with global_shift baked in + frame correction
# ============================================================================


def verify_correlation_with_frame_snap(
    source_video: str,
    target_video: str,
    subtitle_events: List,
    pure_correlation_delay_ms: float,
    fps: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Verify frame alignment and calculate precise ms refinement from anchor frames.

    This function checks if the correlation-based offset aligns frames correctly
    by comparing perceptual hashes of frames at multiple checkpoints, then
    calculates a PRECISE ms refinement from verified frame times (like duration mode).

    IMPORTANT: pure_correlation_delay_ms should be the PURE correlation delay
    WITHOUT global_shift, because we're comparing against original videos.

    Algorithm (Anchor-Based Offset Calculation):
    1. Select checkpoints at 10%, 50%, 90% of subtitle duration
    2. At each checkpoint:
       - Get the source frame at checkpoint time
       - Use correlation to predict target frame location
       - Search ±1 frame around prediction to find matching frame
       - Verify boundary (adjacent frames should be different)
       - Calculate: offset = target_frame_time - source_frame_time
       - Refinement = offset - correlation (how much correlation was off)
    3. If checkpoints agree on refinement (within tolerance), use average
    4. Return precise ms refinement (NOT quantized to frame_duration!)

    This approach mimics duration-align's success: calculate offset from verified
    frame times rather than snapping to frame boundaries.

    Args:
        source_video: Path to source video (where subs were authored)
        target_video: Path to target video (Source 1)
        subtitle_events: List of subtitle events (for determining duration)
        pure_correlation_delay_ms: PURE correlation delay (WITHOUT global_shift)
        fps: Frame rate of videos
        runner: CommandRunner for logging
        config: Configuration dict

    Returns:
        Dict with:
            - valid: bool (whether verification passed)
            - frame_delta: int (best frame adjustment: -1, 0, or +1) [legacy, for logging]
            - frame_correction_ms: float (PRECISE ms refinement from anchor frames)
            - checkpoint_deltas: List[int] (delta found at each checkpoint)
            - anchor_offsets_ms: List[float] (precise offset from each checkpoint)
            - details: Dict (per-checkpoint results)
    """
    config = config or {}

    runner._log_message(f"[Correlation+FrameSnap] ═══════════════════════════════════════")
    runner._log_message(f"[Correlation+FrameSnap] Verifying frame alignment...")
    runner._log_message(f"[Correlation+FrameSnap] Pure correlation delay: {pure_correlation_delay_ms:+.3f}ms")
    runner._log_message(f"[Correlation+FrameSnap] (This is correlation only, WITHOUT global shift)")

    frame_duration_ms = 1000.0 / fps
    runner._log_message(f"[Correlation+FrameSnap] FPS: {fps:.3f} → frame duration: {frame_duration_ms:.3f}ms")

    # Get config parameters
    hash_algorithm = config.get('correlation_snap_hash_algorithm', 'dhash')
    hash_size = int(config.get('correlation_snap_hash_size', 8))
    hash_threshold = int(config.get('correlation_snap_hash_threshold', 5))

    runner._log_message(f"[Correlation+FrameSnap] Hash: {hash_algorithm}, size={hash_size}, threshold={hash_threshold}")

    # Determine checkpoint times from subtitle events
    if not subtitle_events:
        runner._log_message(f"[Correlation+FrameSnap] ERROR: No subtitle events provided")
        return {
            'valid': False,
            'error': 'No subtitle events',
            'frame_delta': 0,
            'frame_correction_ms': 0.0
        }

    # Get subtitle duration range
    min_sub_time = min(event.start for event in subtitle_events)
    max_sub_time = max(event.end for event in subtitle_events)
    sub_duration = max_sub_time - min_sub_time

    runner._log_message(f"[Correlation+FrameSnap] Subtitle range: {min_sub_time}ms - {max_sub_time}ms ({sub_duration}ms)")

    # =========================================================================
    # SLIDING WINDOW SCENE ALIGNMENT
    # 1. Detect scene changes in SOURCE only (frame before cut = CENTER)
    # 2. Get 7-frame window: [CENTER-3, CENTER-2, CENTER-1, CENTER, CENTER+1, CENTER+2, CENTER+3]
    # 3. Use correlation to predict where CENTER lands in TARGET
    # 4. Slide the window in TARGET to find best frame hash alignment
    # 5. Refinement = matched_position - predicted_position
    # =========================================================================

    use_scene_checkpoints = config.get('correlation_snap_use_scene_changes', True)
    refinements_ms = []  # Refinements calculated from sliding window alignment

    # Get sliding window parameters from config
    window_radius = int(config.get('correlation_snap_window_radius', 3))  # 3 = 7 frame window
    search_range_frames = int(config.get('correlation_snap_search_range', 5))  # Search ±N frames

    # Import frame matching utilities
    try:
        from .frame_matching import VideoReader, compute_frame_hash
    except ImportError:
        runner._log_message(f"[Correlation+FrameSnap] ERROR: frame_matching module not available")
        return {
            'valid': False,
            'error': 'frame_matching module not available',
            'frame_delta': 0,
            'frame_correction_ms': 0.0
        }

    if use_scene_checkpoints:
        runner._log_message(f"[Correlation+FrameSnap] ─────────────────────────────────────────")
        runner._log_message(f"[Correlation+FrameSnap] Sliding Window Scene Alignment")
        runner._log_message(f"[Correlation+FrameSnap] Window: {window_radius*2+1} frames (center ±{window_radius})")
        runner._log_message(f"[Correlation+FrameSnap] Search range: ±{search_range_frames} frames around prediction")

        # Convert time range to frame range for source
        start_frame = int(min_sub_time * fps / 1000.0)
        end_frame = int(max_sub_time * fps / 1000.0)

        runner._log_message(f"[Correlation+FrameSnap] Detecting scene changes in SOURCE video...")
        source_scene_frames = detect_scene_changes(source_video, start_frame, end_frame, runner, max_scenes=5)

        if source_scene_frames:
            runner._log_message(f"[Correlation+FrameSnap] Found {len(source_scene_frames)} scene anchors in source")

            # Open video readers for frame extraction
            source_reader = None
            target_reader = None
            try:
                source_reader = VideoReader(source_video, runner)
                target_reader = VideoReader(target_video, runner)
            except Exception as e:
                runner._log_message(f"[Correlation+FrameSnap] ERROR: Failed to open videos: {e}")
                # Clean up any reader that was created before the error
                if source_reader:
                    source_reader.close()
                if target_reader:
                    target_reader.close()
                return {
                    'valid': False,
                    'error': f'Failed to open videos: {e}',
                    'frame_delta': 0,
                    'frame_correction_ms': 0.0
                }

            # Process each scene anchor with sliding window
            for scene_idx, center_frame in enumerate(source_scene_frames[:3]):  # Max 3 scenes
                runner._log_message(f"[Correlation+FrameSnap] ─────────────────────────────────────────")
                runner._log_message(f"[Correlation+FrameSnap] Scene {scene_idx+1}: CENTER = frame {center_frame}")

                # Calculate center time using CFR formula (more reliable than VFR lookup here)
                center_time_ms = center_frame * 1000.0 / fps
                runner._log_message(f"[Correlation+FrameSnap]   Center time: {center_time_ms:.3f}ms")

                # Build source window: [center-3, center-2, center-1, CENTER, center+1, center+2, center+3]
                source_window_frames = list(range(center_frame - window_radius, center_frame + window_radius + 1))
                runner._log_message(f"[Correlation+FrameSnap]   Source window frames: {source_window_frames}")

                # Skip if window would include negative frames
                if source_window_frames[0] < 0:
                    runner._log_message(f"[Correlation+FrameSnap]   Skipping - window starts before frame 0")
                    continue

                # Compute hashes for source window
                source_hashes = []
                source_window_valid = True
                for sf in source_window_frames:
                    img = source_reader.get_frame_at_index(sf)
                    if img is None:
                        runner._log_message(f"[Correlation+FrameSnap]   ERROR: Could not read source frame {sf}")
                        source_window_valid = False
                        break
                    h = compute_frame_hash(img, hash_size=hash_size, method=hash_algorithm)
                    if h is None:
                        runner._log_message(f"[Correlation+FrameSnap]   ERROR: Could not hash source frame {sf}")
                        source_window_valid = False
                        break
                    source_hashes.append(h)

                if not source_window_valid:
                    continue

                # Predict where center should be in target using correlation
                predicted_target_center_time_ms = center_time_ms + pure_correlation_delay_ms
                predicted_target_center_frame = int(predicted_target_center_time_ms * fps / 1000.0)
                runner._log_message(f"[Correlation+FrameSnap]   Predicted target center: frame {predicted_target_center_frame} ({predicted_target_center_time_ms:.3f}ms)")

                # Search range in target: predicted ± search_range_frames
                search_start = predicted_target_center_frame - search_range_frames
                search_end = predicted_target_center_frame + search_range_frames

                if search_start < window_radius:
                    search_start = window_radius  # Ensure we can build full window

                runner._log_message(f"[Correlation+FrameSnap]   Searching target frames {search_start} to {search_end}")

                # Slide window through target and find best alignment
                best_offset_frames = 0  # Offset from predicted position
                best_total_distance = float('inf')
                best_matched_center = predicted_target_center_frame
                offset_scores = {}

                for target_center in range(search_start, search_end + 1):
                    target_window_frames = list(range(target_center - window_radius, target_center + window_radius + 1))

                    # Compute hashes for this target window position
                    target_hashes = []
                    target_window_valid = True
                    for tf in target_window_frames:
                        if tf < 0:
                            target_window_valid = False
                            break
                        img = target_reader.get_frame_at_index(tf)
                        if img is None:
                            target_window_valid = False
                            break
                        h = compute_frame_hash(img, hash_size=hash_size, method=hash_algorithm)
                        if h is None:
                            target_window_valid = False
                            break
                        target_hashes.append(h)

                    if not target_window_valid:
                        continue

                    # Calculate total hash distance for this alignment
                    total_distance = 0
                    frame_distances = []
                    for sh, th in zip(source_hashes, target_hashes):
                        dist = sh - th
                        total_distance += dist
                        frame_distances.append(dist)

                    offset = target_center - predicted_target_center_frame
                    offset_scores[offset] = {
                        'total_distance': total_distance,
                        'frame_distances': frame_distances,
                        'target_center': target_center
                    }

                    if total_distance < best_total_distance:
                        best_total_distance = total_distance
                        best_offset_frames = offset
                        best_matched_center = target_center

                # Log search results with times
                runner._log_message(f"[Correlation+FrameSnap]   Search results:")
                for offset in sorted(offset_scores.keys()):
                    info = offset_scores[offset]
                    target_center = info['target_center']
                    target_time_ms = target_center * 1000.0 / fps
                    marker = " ← BEST" if offset == best_offset_frames else ""
                    runner._log_message(
                        f"[Correlation+FrameSnap]     Offset {offset:+d}: frame {target_center} ({target_time_ms:.1f}ms), "
                        f"total_dist={info['total_distance']}, per_frame={info['frame_distances']}{marker}"
                    )

                # Calculate refinement from best alignment
                # Refinement = how many ms the actual match differs from correlation prediction
                matched_center_time_ms = best_matched_center * 1000.0 / fps
                actual_offset_ms = matched_center_time_ms - center_time_ms
                refinement_ms = actual_offset_ms - pure_correlation_delay_ms

                runner._log_message(f"[Correlation+FrameSnap]   ─────────────────────────────────────")
                runner._log_message(f"[Correlation+FrameSnap]   Best match: target frame {best_matched_center}")
                runner._log_message(f"[Correlation+FrameSnap]   Offset from prediction: {best_offset_frames:+d} frames")
                runner._log_message(f"[Correlation+FrameSnap]   Source center time: {center_time_ms:.3f}ms")
                runner._log_message(f"[Correlation+FrameSnap]   Matched target time: {matched_center_time_ms:.3f}ms")
                runner._log_message(f"[Correlation+FrameSnap]   Actual offset: {actual_offset_ms:.3f}ms")
                runner._log_message(f"[Correlation+FrameSnap]   Correlation predicted: {pure_correlation_delay_ms:.3f}ms")
                runner._log_message(f"[Correlation+FrameSnap]   REFINEMENT: {refinement_ms:+.3f}ms ({best_offset_frames:+d} frames)")

                # Check if this is a good match (total distance should be low)
                avg_frame_distance = best_total_distance / (window_radius * 2 + 1)
                if avg_frame_distance <= hash_threshold * 2:  # Allow some tolerance
                    refinements_ms.append(refinement_ms)
                    runner._log_message(f"[Correlation+FrameSnap]   Match quality: GOOD (avg dist={avg_frame_distance:.1f})")
                else:
                    runner._log_message(f"[Correlation+FrameSnap]   Match quality: POOR (avg dist={avg_frame_distance:.1f}) - not using")

            # Clean up video readers properly to avoid resource leaks in batch processing
            source_reader.close()
            target_reader.close()
            del source_reader
            del target_reader
            gc.collect()
        else:
            runner._log_message(f"[Correlation+FrameSnap] No scene changes detected in source video")

    # Calculate frame correction from sliding window refinements
    runner._log_message(f"[Correlation+FrameSnap] ─────────────────────────────────────────")

    if refinements_ms and len(refinements_ms) >= 2:
        runner._log_message(f"[Correlation+FrameSnap] Scene refinements: {[f'{r:+.3f}ms' for r in refinements_ms]}")

        # Check if refinements agree (within 1 frame tolerance)
        min_ref = min(refinements_ms)
        max_ref = max(refinements_ms)
        spread = max_ref - min_ref

        if spread <= frame_duration_ms:
            # Good agreement - use average refinement WITH FULL PRECISION
            # Like duration mode: keep sub-frame precision, only round at final sync step
            avg_refinement = sum(refinements_ms) / len(refinements_ms)

            # Keep full precision for correlation refinement (like duration mode)
            # Don't round to frame boundaries here - that happens at final sync
            frame_correction_ms = avg_refinement

            runner._log_message(f"[Correlation+FrameSnap] Scene checkpoints AGREE (spread={spread:.3f}ms)")
            runner._log_message(f"[Correlation+FrameSnap] Average refinement: {avg_refinement:+.3f}ms")
            runner._log_message(f"[Correlation+FrameSnap] (~{avg_refinement / frame_duration_ms:+.2f} frames)")
            runner._log_message(f"[Correlation+FrameSnap] Using PRECISE refinement (no frame rounding)")

            valid = True
        else:
            # Disagreement - scenes might not be matching correctly
            runner._log_message(f"[Correlation+FrameSnap] Scene checkpoints DISAGREE (spread={spread:.3f}ms)")
            runner._log_message(f"[Correlation+FrameSnap] This may indicate different cuts or drift")

            # Try using median as it's more robust to outliers
            sorted_refs = sorted(refinements_ms)
            median_refinement = sorted_refs[len(sorted_refs) // 2]

            # Still keep precision
            frame_correction_ms = median_refinement

            runner._log_message(f"[Correlation+FrameSnap] Using median refinement: {median_refinement:+.3f}ms")

            valid = False  # Mark as uncertain
    elif refinements_ms and len(refinements_ms) == 1:
        # Only one scene matched - use it but mark uncertain
        frame_correction_ms = refinements_ms[0]  # Keep precision
        runner._log_message(f"[Correlation+FrameSnap] Only 1 scene matched, using refinement: {refinements_ms[0]:+.3f}ms")
        valid = False
    else:
        # No scene matches - trust correlation
        frame_correction_ms = 0.0
        runner._log_message(f"[Correlation+FrameSnap] No scene matches found, trusting correlation")
        valid = False

    runner._log_message(f"[Correlation+FrameSnap] Final frame correction: {frame_correction_ms:+.3f}ms")
    runner._log_message(f"[Correlation+FrameSnap] ═══════════════════════════════════════")

    # Calculate frame delta for legacy compatibility
    frame_delta = round(frame_correction_ms / frame_duration_ms) if frame_duration_ms > 0 else 0

    return {
        'valid': valid,
        'frame_delta': frame_delta,  # Legacy, for logging
        'frame_correction_ms': frame_correction_ms,  # PRECISE correction from scene alignment
        'scene_refinements_ms': refinements_ms,  # New: refinements from each scene match
        'num_scene_matches': len(refinements_ms),
    }


def apply_correlation_frame_snap_sync(
    subtitle_path: str,
    source_video: str,
    target_video: str,
    total_delay_with_global_ms: float,
    raw_global_shift_ms: float,
    runner,
    config: dict = None,
    cached_frame_correction: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Correlation + Frame Snap Mode: Apply subtitle sync using anchor-based offset calculation.

    This mode uses audio correlation as a guide to find matching frames, then calculates
    PRECISE offset from verified frame times (like duration-align mode). No frame snapping!

    Algorithm (Anchor-Based):
    1. Use correlation to guide where to search for matching frames
    2. At checkpoints, find actual matching frames via perceptual hashing
    3. Calculate precise offset from verified frame times:
       anchor_offset = target_frame_time - source_frame_time
    4. If checkpoints agree, use average anchor offset
    5. Apply offset simply (like duration mode): start += offset, end += offset

    CRITICAL MATH:
    - total_delay_with_global_ms = raw_source_delays_ms[source] (ALREADY includes global_shift!)
    - raw_global_shift_ms = the global shift that was added during analysis
    - pure_correlation = total_delay_with_global_ms - raw_global_shift_ms
    - Frame verification uses pure_correlation (videos are in original state)
    - Anchor offset calculated from verified frame times (PRECISE, not quantized!)
    - frame_correction = anchor_offset - correlation (how much correlation was off)
    - Final offset = total_delay_with_global_ms + frame_correction
      (global_shift is already baked in, so we just add frame correction)

    Args:
        subtitle_path: Path to subtitle file
        source_video: Path to source video (where subs were authored)
        target_video: Path to target video (Source 1)
        total_delay_with_global_ms: Raw delay from ctx.delays.raw_source_delays_ms[source_key]
                                    This ALREADY includes global_shift!
        raw_global_shift_ms: Global shift from ctx.delays.raw_global_shift_ms
        runner: CommandRunner for logging
        config: Configuration dict
        cached_frame_correction: Optional cached result from previous scene detection for same source.
                                 If provided and valid, skips scene detection and reuses the correction.
                                 Dict with: frame_correction_ms, num_scene_matches, valid

    Returns:
        Dict with sync report
    """
    config = config or {}

    runner._log_message(f"[Correlation+FrameSnap] ═══════════════════════════════════════")
    runner._log_message(f"[Correlation+FrameSnap] Correlation + Frame Snap Sync Mode")
    runner._log_message(f"[Correlation+FrameSnap] ═══════════════════════════════════════")

    # CRITICAL: Calculate pure correlation by subtracting global shift
    # total_delay_with_global_ms already has global_shift baked in from analysis step
    pure_correlation_ms = total_delay_with_global_ms - raw_global_shift_ms

    runner._log_message(f"[Correlation+FrameSnap] Input values:")
    runner._log_message(f"[Correlation+FrameSnap]   Total delay (with global): {total_delay_with_global_ms:+.3f}ms")
    runner._log_message(f"[Correlation+FrameSnap]   Global shift:              {raw_global_shift_ms:+.3f}ms")
    runner._log_message(f"[Correlation+FrameSnap]   Pure correlation:          {pure_correlation_ms:+.3f}ms")
    runner._log_message(f"[Correlation+FrameSnap]   (pure = total - global, for frame verification)")

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Correlation+FrameSnap] ERROR: Failed to load subtitle file: {e}")
        return {
            'success': False,
            'error': f'Failed to load subtitle file: {e}'
        }

    if not subs.events:
        runner._log_message(f"[Correlation+FrameSnap] WARNING: No subtitle events found")
        return {
            'success': True,
            'total_events': 0,
            'pure_correlation_ms': pure_correlation_ms,
            'global_shift_ms': raw_global_shift_ms,
            'frame_correction_ms': 0.0,
            'final_offset_ms': total_delay_with_global_ms
        }

    runner._log_message(f"[Correlation+FrameSnap] Loaded {len(subs.events)} subtitle events")

    # Detect FPS (simple detection for frame duration calculation)
    fps = detect_video_fps(source_video, runner)
    frame_duration_ms = 1000.0 / fps

    # Check if we have a valid cached frame correction from a previous subtitle track
    # This saves ~1 minute of scene detection per additional track from the same source
    if cached_frame_correction is not None:
        cached_correction_ms = cached_frame_correction.get('frame_correction_ms', 0.0)
        cached_num_scenes = cached_frame_correction.get('num_scene_matches', 0)
        cached_valid = cached_frame_correction.get('valid', False)

        runner._log_message(f"[Correlation+FrameSnap] ─────────────────────────────────────────")
        runner._log_message(f"[Correlation+FrameSnap] REUSING cached scene detection result")
        runner._log_message(f"[Correlation+FrameSnap] (All subs from same source get same correction)")
        runner._log_message(f"[Correlation+FrameSnap]   Cached frame correction: {cached_correction_ms:+.3f}ms")
        runner._log_message(f"[Correlation+FrameSnap]   From {cached_num_scenes} scene matches (valid={cached_valid})")
        runner._log_message(f"[Correlation+FrameSnap] ─────────────────────────────────────────")

        # Use cached values - skip scene detection entirely
        frame_correction_ms = cached_correction_ms
        frame_delta = round(frame_correction_ms / frame_duration_ms) if frame_duration_ms > 0 else 0
        num_scene_matches = cached_num_scenes

        # Build a verification result from cached data
        verification_result = {
            'valid': cached_valid,
            'frame_delta': frame_delta,
            'frame_correction_ms': frame_correction_ms,
            'num_scene_matches': num_scene_matches,
            'reused_from_cache': True
        }
    else:
        # Detect comprehensive video properties for both videos (first track only)
        # This helps identify potential issues (interlaced, different FPS, PAL speedup)
        # Currently for logging/diagnosis only - doesn't change sync behavior yet
        source_props = detect_video_properties(source_video, runner)
        target_props = detect_video_properties(target_video, runner)
        video_comparison = compare_video_properties(source_props, target_props, runner)

        # Log if there are warnings but continue with current behavior
        if video_comparison.get('warnings'):
            runner._log_message(f"[Correlation+FrameSnap] NOTE: Video property analysis found potential issues")
            runner._log_message(f"[Correlation+FrameSnap] Recommended strategy: {video_comparison['strategy']}")
            runner._log_message(f"[Correlation+FrameSnap] Current mode will proceed with frame-based matching")
            runner._log_message(f"[Correlation+FrameSnap] (Future versions may adapt based on these properties)")

        # Run frame verification using PURE correlation (without global shift)
        # because we're comparing against original videos
        verification_result = verify_correlation_with_frame_snap(
            source_video,
            target_video,
            subs.events,
            pure_correlation_ms,  # Use pure correlation for verification!
            fps,
            runner,
            config
        )

        frame_correction_ms = 0.0
        frame_delta = 0
        num_scene_matches = verification_result.get('num_scene_matches', 0)

        if verification_result.get('valid'):
            # Verification passed (2+ scenes, they agree) - use the frame correction
            frame_delta = verification_result['frame_delta']
            frame_correction_ms = verification_result['frame_correction_ms']
            runner._log_message(f"[Correlation+FrameSnap] Frame verification passed ({num_scene_matches} scenes agree)")
            runner._log_message(f"[Correlation+FrameSnap] Frame correction: {frame_delta:+d} frames = {frame_correction_ms:+.3f}ms")
        elif num_scene_matches == 1:
            # Only 1 scene found - can't verify agreement, but use its correction
            # This is not an error, just insufficient data to cross-verify
            frame_delta = verification_result['frame_delta']
            frame_correction_ms = verification_result['frame_correction_ms']
            runner._log_message(f"[Correlation+FrameSnap] Only 1 scene matched (can't verify agreement)")
            runner._log_message(f"[Correlation+FrameSnap] Using frame correction from single scene: {frame_correction_ms:+.3f}ms")
        elif num_scene_matches >= 2:
            # 2+ scenes found but they DISAGREE - this indicates a real problem
            # (different cuts, drift, or matching errors) - respect fallback mode
            fallback_mode = config.get('correlation_snap_fallback_mode', 'snap-to-frame')

            runner._log_message(f"[Correlation+FrameSnap] Checkpoints DISAGREE ({num_scene_matches} scenes, different refinements)")
            runner._log_message(f"[Correlation+FrameSnap] This may indicate different cuts or timing drift")

            if fallback_mode == 'abort':
                runner._log_message(f"[Correlation+FrameSnap] ABORTING: Fallback mode is 'abort'")
                return {
                    'success': False,
                    'error': f"Frame verification failed: Checkpoints disagree",
                    'verification': verification_result
                }
            else:
                # Use median refinement (already calculated in verification) but warn
                frame_delta = verification_result['frame_delta']
                frame_correction_ms = verification_result['frame_correction_ms']
                runner._log_message(f"[Correlation+FrameSnap] Using median frame correction: {frame_correction_ms:+.3f}ms")
        else:
            # No scenes found at all (0 matches) - use raw delay, just warn
            # Don't abort even if fallback is 'abort' - this isn't an error, just sparse content
            runner._log_message(f"[Correlation+FrameSnap] No scene matches found in subtitle range")
            runner._log_message(f"[Correlation+FrameSnap] Using raw delay (no frame correction) - no scenes to verify against")
            frame_correction_ms = 0.0
            frame_delta = 0

    # Calculate final offset
    # IMPORTANT: total_delay_with_global_ms already has global_shift baked in
    # So final = total + frame_correction (NOT total + frame_correction + global_shift!)
    final_offset_ms = total_delay_with_global_ms + frame_correction_ms

    runner._log_message(f"[Correlation+FrameSnap] ───────────────────────────────────────")
    runner._log_message(f"[Correlation+FrameSnap] Final offset calculation:")
    runner._log_message(f"[Correlation+FrameSnap]   Pure correlation:     {pure_correlation_ms:+.3f}ms")
    runner._log_message(f"[Correlation+FrameSnap]   + Frame correction:   {frame_correction_ms:+.3f}ms")
    runner._log_message(f"[Correlation+FrameSnap]   + Global shift:       {raw_global_shift_ms:+.3f}ms")
    runner._log_message(f"[Correlation+FrameSnap]   ─────────────────────────────────────")
    runner._log_message(f"[Correlation+FrameSnap]   = FINAL offset:       {final_offset_ms:+.3f}ms")

    # Capture original metadata
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

    # Apply offset to all subtitle events using FLOOR for final rounding
    runner._log_message(f"[Correlation+FrameSnap] Applying offset to {len(subs.events)} events (using floor rounding)...")

    # Use floor for final millisecond value (user preference)
    final_offset_int = int(math.floor(final_offset_ms))

    for event in subs.events:
        event.start += final_offset_int
        event.end += final_offset_int

    # Save modified subtitle
    runner._log_message(f"[Correlation+FrameSnap] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Correlation+FrameSnap] ERROR: Failed to save subtitle file: {e}")
        return {
            'success': False,
            'error': f'Failed to save subtitle file: {e}',
            'verification': verification_result
        }

    # Validate and restore metadata
    metadata.validate_and_restore(runner, expected_delay_ms=final_offset_int)

    runner._log_message(f"[Correlation+FrameSnap] Successfully synchronized {len(subs.events)} events")
    runner._log_message(f"[Correlation+FrameSnap] ═══════════════════════════════════════")

    return {
        'success': True,
        'total_events': len(subs.events),
        'pure_correlation_ms': pure_correlation_ms,
        'frame_delta': frame_delta,
        'frame_correction_ms': frame_correction_ms,
        'global_shift_ms': raw_global_shift_ms,
        'final_offset_ms': final_offset_ms,
        'final_offset_applied': final_offset_int,
        'fps': fps,
        'frame_duration_ms': frame_duration_ms,
        'verification': verification_result
    }


# ============================================================================
# SUBTITLE-ANCHORED FRAME SNAP MODE
# ============================================================================

def apply_subtitle_anchored_frame_snap_sync(
    subtitle_path: str,
    source_video: str,
    target_video: str,
    global_shift_ms: float,
    runner,
    config: dict = None,
    temp_dir: Path = None
) -> Dict[str, Any]:
    """
    Subtitle-Anchored Frame Snap: Visual-only sync using subtitle positions as anchors.

    This mode combines the reliability of Duration-Align's frame selection (subtitle positions)
    with FrameSnap's sliding window matching, WITHOUT depending on audio correlation.

    Algorithm:
    1. Select 3 dialogue events as checkpoints (first, middle, last - avoiding OP/ED)
    2. For each checkpoint:
       a. Get source frame at subtitle.start_time
       b. Extract window of frames: center ± N frames
       c. Compute dHash for all frames in window
    3. In target video, search around expected position:
       - Base offset: 0 (or user-provided hint)
       - Search range: ±configurable ms (default 2000ms = ~48 frames at 24fps)
       - Slide the frame window through target, find best match
    4. Calculate sub-frame timing:
       - Source subtitle starts at exact time (e.g., 149630.5ms)
       - Source frame containing that time starts at frame boundary (e.g., 149604.6ms)
       - Sub-frame offset = subtitle_start - frame_start (e.g., 25.9ms)
       - Apply same sub-frame offset to matched target frame
    5. Verify all 3 checkpoints agree within tolerance
    6. Apply final offset (preserving sub-frame precision until final floor)

    This mode is ideal when:
    - Audio correlation fails or is unavailable
    - Videos are frame-aligned but with unknown offset
    - Scene detection picks bad frames (black, transitions)
    - You want purely visual-based sync

    Args:
        subtitle_path: Path to subtitle file
        source_video: Path to source video (where subs were authored)
        target_video: Path to target video (Source 1)
        global_shift_ms: Global shift from ctx.delays.raw_global_shift_ms
        runner: CommandRunner for logging
        config: Configuration dict with:
            - sub_anchor_search_range_ms: ±search range in ms (default: 2000)
            - sub_anchor_hash_algorithm: 'dhash', 'phash', 'average_hash' (default: 'dhash')
            - sub_anchor_hash_size: 8, 16 (default: 8)
            - sub_anchor_hash_threshold: max hamming distance (default: 5)
            - sub_anchor_window_radius: frames before/after center (default: 5)
            - sub_anchor_agreement_tolerance_ms: checkpoint agreement (default: 100)
            - sub_anchor_fallback_mode: 'abort', 'use-median' (default: 'abort')
            - sub_anchor_use_vapoursynth: use VS for frame extraction (default: True)
        temp_dir: Job's temporary directory for FFMS2 index storage (auto-cleaned)

    Returns:
        Dict with sync report including:
            - success: bool
            - total_events: int
            - final_offset_ms: float (precise)
            - final_offset_applied: int (floored)
            - checkpoints: List[Dict] with per-checkpoint details
            - verification: Dict with agreement info
    """
    config = config or {}

    runner._log_message(f"[SubAnchor FrameSnap] ═══════════════════════════════════════")
    runner._log_message(f"[SubAnchor FrameSnap] Subtitle-Anchored Frame Snap Sync Mode")
    runner._log_message(f"[SubAnchor FrameSnap] ═══════════════════════════════════════")
    runner._log_message(f"[SubAnchor FrameSnap] Visual-only sync using subtitle positions as anchors")
    runner._log_message(f"[SubAnchor FrameSnap] No audio correlation dependency")

    # Get config parameters
    search_range_ms = config.get('sub_anchor_search_range_ms', 2000)
    hash_algorithm = config.get('sub_anchor_hash_algorithm', 'dhash')
    hash_size = int(config.get('sub_anchor_hash_size', 8))
    hash_threshold = int(config.get('sub_anchor_hash_threshold', 5))
    window_radius = int(config.get('sub_anchor_window_radius', 5))
    tolerance_ms = config.get('sub_anchor_agreement_tolerance_ms', 100)
    fallback_mode = config.get('sub_anchor_fallback_mode', 'abort')
    use_vapoursynth = config.get('sub_anchor_use_vapoursynth', True)

    runner._log_message(f"[SubAnchor FrameSnap] Configuration:")
    runner._log_message(f"[SubAnchor FrameSnap]   Search range: ±{search_range_ms}ms")
    runner._log_message(f"[SubAnchor FrameSnap]   Hash: {hash_algorithm}, size={hash_size}, threshold={hash_threshold}")
    runner._log_message(f"[SubAnchor FrameSnap]   Window radius: {window_radius} frames (={2*window_radius+1} total)")
    runner._log_message(f"[SubAnchor FrameSnap]   Agreement tolerance: ±{tolerance_ms}ms")
    runner._log_message(f"[SubAnchor FrameSnap]   Fallback mode: {fallback_mode}")
    runner._log_message(f"[SubAnchor FrameSnap]   Global shift: {global_shift_ms:+.3f}ms")

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[SubAnchor FrameSnap] ERROR: Failed to load subtitle file: {e}")
        return {
            'success': False,
            'error': f'Failed to load subtitle file: {e}'
        }

    if not subs.events:
        runner._log_message(f"[SubAnchor FrameSnap] WARNING: No subtitle events found")
        return {
            'success': True,
            'total_events': 0,
            'final_offset_ms': global_shift_ms,
            'final_offset_applied': int(math.floor(global_shift_ms)),
            'warning': 'No subtitle events - applied global shift only'
        }

    runner._log_message(f"[SubAnchor FrameSnap] Loaded {len(subs.events)} subtitle events")

    # Filter to dialogue events (must have text content)
    dialogue_events = [e for e in subs.events if e.text and e.text.strip()]
    runner._log_message(f"[SubAnchor FrameSnap] Found {len(dialogue_events)} events with text content")

    if len(dialogue_events) < 1:
        runner._log_message(f"[SubAnchor FrameSnap] ERROR: No dialogue events found")
        return {
            'success': False,
            'error': 'No dialogue events with text content found'
        }

    # Select smart checkpoints (avoid OP/ED, prefer longer dialogue)
    checkpoints = _select_smart_checkpoints(dialogue_events, runner)

    if len(checkpoints) == 0:
        runner._log_message(f"[SubAnchor FrameSnap] ERROR: No valid checkpoints found")
        return {
            'success': False,
            'error': 'No valid checkpoints for frame matching'
        }

    runner._log_message(f"[SubAnchor FrameSnap] Selected {len(checkpoints)} checkpoints for matching")

    # Import frame matching utilities
    try:
        from .frame_matching import VideoReader, compute_frame_hash
    except ImportError:
        runner._log_message(f"[SubAnchor FrameSnap] ERROR: frame_matching module not available")
        return {
            'success': False,
            'error': 'frame_matching module not available'
        }

    # Log actual video paths for debugging
    from pathlib import Path
    runner._log_message(f"[SubAnchor FrameSnap] Source video: {Path(source_video).name}")
    runner._log_message(f"[SubAnchor FrameSnap] Target video: {Path(target_video).name}")
    runner._log_message(f"[SubAnchor FrameSnap] Same file? {Path(source_video).resolve() == Path(target_video).resolve()}")

    # Get video FPS for frame timing calculations
    source_fps = detect_video_fps(source_video, runner)
    target_fps = detect_video_fps(target_video, runner)
    frame_duration_ms = 1000.0 / source_fps

    runner._log_message(f"[SubAnchor FrameSnap] Source FPS: {source_fps:.3f} (frame duration: {frame_duration_ms:.3f}ms)")
    runner._log_message(f"[SubAnchor FrameSnap] Target FPS: {target_fps:.3f}")

    # Open video readers (pass temp_dir for job-local index storage)
    try:
        source_reader = VideoReader(source_video, runner, temp_dir=temp_dir)
        target_reader = VideoReader(target_video, runner, temp_dir=temp_dir)
    except Exception as e:
        runner._log_message(f"[SubAnchor FrameSnap] ERROR: Failed to open videos: {e}")
        return {
            'success': False,
            'error': f'Failed to open videos: {e}'
        }

    # Process each checkpoint
    measurements = []  # List of precise offset measurements
    checkpoint_details = []
    num_frames_in_window = 2 * window_radius + 1
    median_offset = 0.0
    max_deviation = 0.0

    for i, event in enumerate(checkpoints):
        subtitle_start_ms = event.start  # Exact subtitle start time
        runner._log_message(f"[SubAnchor FrameSnap] ───────────────────────────────────────")
        runner._log_message(f"[SubAnchor FrameSnap] Checkpoint {i+1}/{len(checkpoints)}: {subtitle_start_ms}ms")
        runner._log_message(f"[SubAnchor FrameSnap]   Text preview: \"{event.text[:50]}...\"" if len(event.text) > 50 else f"[SubAnchor FrameSnap]   Text: \"{event.text}\"")

        # Calculate source frame containing this subtitle
        source_center_frame = time_to_frame_floor(subtitle_start_ms, source_fps)
        source_frame_start_ms = frame_to_time_floor(source_center_frame, source_fps)
        sub_frame_offset_ms = subtitle_start_ms - source_frame_start_ms

        runner._log_message(f"[SubAnchor FrameSnap]   Source frame: {source_center_frame} (starts at {source_frame_start_ms:.3f}ms)")
        runner._log_message(f"[SubAnchor FrameSnap]   Sub-frame offset: {sub_frame_offset_ms:.3f}ms into frame")

        # Step 1: Extract and hash source frames (center ± window_radius)
        source_frame_hashes = []  # List of (frame_offset, hash)
        for offset in range(-window_radius, window_radius + 1):
            frame_num = source_center_frame + offset
            if frame_num < 0:
                continue

            frame = source_reader.get_frame_at_index(frame_num)
            if frame is not None:
                frame_hash = compute_frame_hash(frame, hash_size=hash_size, method=hash_algorithm)
                if frame_hash is not None:
                    source_frame_hashes.append((offset, frame_hash))

        if len(source_frame_hashes) < num_frames_in_window * 0.7:  # Need at least 70%
            runner._log_message(f"[SubAnchor FrameSnap]   WARNING: Not enough source frames ({len(source_frame_hashes)}/{num_frames_in_window})")
            checkpoint_details.append({
                'checkpoint_ms': subtitle_start_ms,
                'matched': False,
                'error': f'Not enough source frames ({len(source_frame_hashes)}/{num_frames_in_window})'
            })
            continue

        runner._log_message(f"[SubAnchor FrameSnap]   Extracted {len(source_frame_hashes)} source frames")

        # Step 2: Search in target video
        # Search window: start from source time (assuming similar timing), expand ±search_range_ms
        search_center_ms = subtitle_start_ms  # Start at same position (offset unknown)
        search_start_ms = max(0, search_center_ms - search_range_ms)
        search_end_ms = search_center_ms + search_range_ms

        # Convert to frame numbers for efficient searching
        search_start_frame = time_to_frame_floor(search_start_ms, target_fps)
        search_end_frame = time_to_frame_floor(search_end_ms, target_fps)

        runner._log_message(f"[SubAnchor FrameSnap]   Searching frames {search_start_frame}-{search_end_frame} ({search_end_frame - search_start_frame + 1} positions)")

        # Track best match
        best_match_frame = None
        best_aggregate_score = -1
        best_matched_count = 0
        best_avg_distance = float('inf')

        # Debug: track all distances to diagnose matching issues
        all_candidates = []

        # Search every frame in range (we want precision, not speed here)
        for target_center_frame in range(search_start_frame, search_end_frame + 1):
            # For this candidate, compare all frames in window
            matched_frames = 0
            total_distance = 0
            frames_compared = 0
            frame_distances = []

            for offset, source_hash in source_frame_hashes:
                target_frame_num = target_center_frame + offset
                if target_frame_num < 0:
                    continue

                target_frame = target_reader.get_frame_at_index(target_frame_num)
                if target_frame is not None:
                    target_hash = compute_frame_hash(target_frame, hash_size=hash_size, method=hash_algorithm)
                    if target_hash is not None:
                        distance = source_hash - target_hash
                        frames_compared += 1
                        frame_distances.append(distance)

                        if distance <= hash_threshold:
                            matched_frames += 1

                        total_distance += distance

            # Calculate aggregate score: prioritize match count, then lower distance, then proximity
            if frames_compared > 0:
                avg_distance = total_distance / frames_compared
                min_distance = min(frame_distances) if frame_distances else 999
                all_candidates.append((target_center_frame, min_distance, avg_distance, matched_frames))

                # Distance from expected position (prefer frames closer to source position)
                position_distance = abs(target_center_frame - source_center_frame)

                # Multi-tier scoring (higher is better):
                # 1. Matched frames (most important): * 100000
                # 2. Average hash distance: * 10 (reduced from 100)
                # 3. Position proximity: * 10 (increased from 1)
                # This ensures: more matches > balanced distance/position preference
                # For same-file matching, position is as important as hash quality
                aggregate_score = (matched_frames * 100000) - (avg_distance * 10) - (position_distance * 10)

                if aggregate_score > best_aggregate_score:
                    best_aggregate_score = aggregate_score
                    best_match_frame = target_center_frame
                    best_matched_count = matched_frames
                    best_avg_distance = avg_distance

        # Debug: show best candidates by scoring to diagnose issues
        if all_candidates:
            # Show top 5 by the actual scoring algorithm (with position preference)
            scored_candidates = []
            for frame, min_d, avg_d, matched in all_candidates:
                position_distance = abs(frame - source_center_frame)
                score = (matched * 100000) - (avg_d * 10) - (position_distance * 10)
                scored_candidates.append((frame, min_d, avg_d, matched, position_distance, score))

            sorted_by_score = sorted(scored_candidates, key=lambda x: x[5], reverse=True)[:10]
            runner._log_message(f"[SubAnchor FrameSnap]   DEBUG: Top 10 by aggregate score:")
            for frame, min_d, avg_d, matched, pos_dist, score in sorted_by_score:
                marker = " ← SELECTED" if frame == best_match_frame else ""
                runner._log_message(f"[SubAnchor FrameSnap]     Frame {frame}: matched={matched}/{len(source_frame_hashes)}, avg={avg_d:.1f}, pos_offset={pos_dist:+d}{marker}")

            # Also show frames near the expected position for debugging same-file issues
            runner._log_message(f"[SubAnchor FrameSnap]   DEBUG: Frames near expected position ({source_center_frame}):")
            near_source = [c for c in scored_candidates if abs(c[4]) <= 5]  # Within ±5 frames
            near_source_sorted = sorted(near_source, key=lambda x: x[4])  # Sort by position offset
            for frame, min_d, avg_d, matched, pos_dist, score in near_source_sorted:
                marker = " ← SELECTED" if frame == best_match_frame else ""
                runner._log_message(f"[SubAnchor FrameSnap]     Frame {frame}: matched={matched}/{len(source_frame_hashes)}, avg={avg_d:.1f}, pos_offset={pos_dist:+d}{marker}")

        # Step 3: Validate match quality
        min_required_matches = int(len(source_frame_hashes) * 0.70)  # 70% threshold

        if best_match_frame is not None and best_matched_count >= min_required_matches:
            # Calculate precise offset with sub-frame timing
            target_frame_start_ms = frame_to_time_floor(best_match_frame, target_fps)
            # Target subtitle should start at: target_frame_start + sub_frame_offset
            target_subtitle_time_ms = target_frame_start_ms + sub_frame_offset_ms

            # Precise offset = where subtitle should be in target - where it is in source
            precise_offset_ms = target_subtitle_time_ms - subtitle_start_ms

            match_percent = (best_matched_count / len(source_frame_hashes)) * 100
            measurements.append(precise_offset_ms)

            runner._log_message(f"[SubAnchor FrameSnap]   ✓ Match found!")
            runner._log_message(f"[SubAnchor FrameSnap]     Target frame: {best_match_frame} (starts at {target_frame_start_ms:.3f}ms)")
            runner._log_message(f"[SubAnchor FrameSnap]     Frames matched: {best_matched_count}/{len(source_frame_hashes)} ({match_percent:.0f}%)")
            runner._log_message(f"[SubAnchor FrameSnap]     Average distance: {best_avg_distance:.1f}")
            runner._log_message(f"[SubAnchor FrameSnap]     Precise offset: {precise_offset_ms:+.3f}ms")

            checkpoint_details.append({
                'checkpoint_ms': subtitle_start_ms,
                'source_frame': source_center_frame,
                'target_frame': best_match_frame,
                'sub_frame_offset_ms': sub_frame_offset_ms,
                'precise_offset_ms': precise_offset_ms,
                'matched_frames': best_matched_count,
                'total_frames': len(source_frame_hashes),
                'match_percent': match_percent,
                'avg_distance': best_avg_distance,
                'matched': True
            })
        else:
            match_percent = (best_matched_count / len(source_frame_hashes) * 100) if best_matched_count > 0 else 0
            runner._log_message(f"[SubAnchor FrameSnap]   ✗ No good match found")
            runner._log_message(f"[SubAnchor FrameSnap]     Best: {best_matched_count}/{len(source_frame_hashes)} ({match_percent:.0f}%)")
            runner._log_message(f"[SubAnchor FrameSnap]     Required: {min_required_matches} (70%)")

            checkpoint_details.append({
                'checkpoint_ms': subtitle_start_ms,
                'matched': False,
                'best_matched': best_matched_count,
                'required': min_required_matches,
                'match_percent': match_percent
            })

    # Clean up video readers
    del source_reader
    del target_reader
    gc.collect()

    runner._log_message(f"[SubAnchor FrameSnap] ───────────────────────────────────────")
    runner._log_message(f"[SubAnchor FrameSnap] Results Summary")
    runner._log_message(f"[SubAnchor FrameSnap] ───────────────────────────────────────")

    # Check results
    if len(measurements) == 0:
        runner._log_message(f"[SubAnchor FrameSnap] ERROR: No checkpoints matched successfully")
        if fallback_mode == 'abort':
            return {
                'success': False,
                'error': 'No checkpoints matched - cannot determine sync offset',
                'checkpoints': checkpoint_details
            }
        else:
            # Use global shift only
            runner._log_message(f"[SubAnchor FrameSnap] Fallback: Using global shift only ({global_shift_ms:+.3f}ms)")
            final_offset_ms = global_shift_ms

    elif len(measurements) == 1:
        # Only one checkpoint - use it but warn
        runner._log_message(f"[SubAnchor FrameSnap] WARNING: Only 1 checkpoint matched (cannot verify agreement)")
        runner._log_message(f"[SubAnchor FrameSnap] Using single measurement: {measurements[0]:+.3f}ms")
        final_offset_ms = measurements[0] + global_shift_ms

    else:
        # Multiple measurements - check agreement
        median_offset = sorted(measurements)[len(measurements) // 2]
        max_deviation = max(abs(m - median_offset) for m in measurements)

        runner._log_message(f"[SubAnchor FrameSnap] Measurements: {[f'{m:+.1f}ms' for m in measurements]}")
        runner._log_message(f"[SubAnchor FrameSnap] Median: {median_offset:+.3f}ms")
        runner._log_message(f"[SubAnchor FrameSnap] Max deviation: {max_deviation:.1f}ms")

        if max_deviation <= tolerance_ms:
            runner._log_message(f"[SubAnchor FrameSnap] ✓ Checkpoints AGREE within ±{tolerance_ms}ms")
            final_offset_ms = median_offset + global_shift_ms
        else:
            runner._log_message(f"[SubAnchor FrameSnap] ⚠ Checkpoints DISAGREE (max deviation: {max_deviation:.1f}ms > {tolerance_ms}ms)")

            if fallback_mode == 'abort':
                return {
                    'success': False,
                    'error': f'Checkpoints disagree: max deviation {max_deviation:.1f}ms > {tolerance_ms}ms tolerance',
                    'measurements': measurements,
                    'checkpoints': checkpoint_details
                }
            else:
                # Use median anyway
                runner._log_message(f"[SubAnchor FrameSnap] Fallback: Using median offset anyway")
                final_offset_ms = median_offset + global_shift_ms

    runner._log_message(f"[SubAnchor FrameSnap] ───────────────────────────────────────")
    runner._log_message(f"[SubAnchor FrameSnap] Final offset calculation:")
    if len(measurements) > 0:
        runner._log_message(f"[SubAnchor FrameSnap]   Frame match offset: {measurements[0] if len(measurements) == 1 else median_offset:+.3f}ms")
    runner._log_message(f"[SubAnchor FrameSnap]   + Global shift:      {global_shift_ms:+.3f}ms")
    runner._log_message(f"[SubAnchor FrameSnap]   ─────────────────────────────────────")
    runner._log_message(f"[SubAnchor FrameSnap]   = FINAL offset:      {final_offset_ms:+.3f}ms")

    # Capture original metadata
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

    # Apply offset to all subtitle events using FLOOR for final rounding
    final_offset_int = int(math.floor(final_offset_ms))
    runner._log_message(f"[SubAnchor FrameSnap] Applying offset to {len(subs.events)} events (floor: {final_offset_int}ms)")

    for event in subs.events:
        event.start += final_offset_int
        event.end += final_offset_int

    # Save modified subtitle
    runner._log_message(f"[SubAnchor FrameSnap] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[SubAnchor FrameSnap] ERROR: Failed to save subtitle file: {e}")
        return {
            'success': False,
            'error': f'Failed to save subtitle file: {e}',
            'checkpoints': checkpoint_details
        }

    # Validate and restore metadata
    metadata.validate_and_restore(runner, expected_delay_ms=final_offset_int)

    runner._log_message(f"[SubAnchor FrameSnap] Successfully synchronized {len(subs.events)} events")
    runner._log_message(f"[SubAnchor FrameSnap] ═══════════════════════════════════════")

    verification_result = {
        'valid': len(measurements) >= 2 and max_deviation <= tolerance_ms if len(measurements) >= 2 else len(measurements) == 1,
        'num_checkpoints_matched': len(measurements),
        'num_checkpoints_total': len(checkpoints),
        'max_deviation_ms': max_deviation if len(measurements) >= 2 else 0,
        'measurements': measurements
    }

    return {
        'success': True,
        'total_events': len(subs.events),
        'final_offset_ms': final_offset_ms,
        'final_offset_applied': final_offset_int,
        'global_shift_ms': global_shift_ms,
        'frame_match_offset_ms': median_offset if len(measurements) >= 2 else (measurements[0] if measurements else 0),
        'source_fps': source_fps,
        'target_fps': target_fps,
        'frame_duration_ms': frame_duration_ms,
        'checkpoints': checkpoint_details,
        'verification': verification_result
    }
