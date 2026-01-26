# vsg_core/subtitles/frame_utils.py
# -*- coding: utf-8 -*-
"""
Shared frame timing and video utility functions for subtitle synchronization.

Contains:
- Frame/time conversion functions (CFR and VFR support)
- VapourSynth frame indexing and extraction
- Scene detection using PySceneDetect
- Video property detection (FPS, interlacing, etc.)
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import math
import gc
import tempfile


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

import threading

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

        # Thread-safe cache write
        with _vfr_cache_lock:
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

def _get_ffms2_cache_path(video_path: str, temp_dir: Optional[Path]) -> Path:
    """
    Generate cache path for FFMS2 index in job's temp directory.

    Cache key: parent_dir + filename + size + mtime (unique per file path)
    Location: {job_temp_dir}/ffindex/{cache_key}.ffindex

    The index is created in the job's temp folder so it can be:
    1. Easily identified by filename and source
    2. Reused within the job (multiple sync operations on same video)
    3. Cleaned up automatically when job completes
    4. Avoid collisions when different sources have same episode numbers
    """
    import os
    import hashlib

    video_path_obj = Path(video_path)

    # Get file metadata for cache invalidation
    stat = os.stat(video_path)
    file_size = stat.st_size
    mtime = int(stat.st_mtime)

    # Include parent directory to distinguish between sources
    # E.g., "source1/1.mkv" vs "source2/1.mkv" get different indexes
    parent_dir = video_path_obj.parent.name

    # If parent is empty/root, use path hash instead
    if not parent_dir or parent_dir == '.':
        path_hash = hashlib.md5(str(video_path_obj.resolve()).encode()).hexdigest()[:8]
        cache_key = f"{video_path_obj.stem}_{path_hash}_{file_size}_{mtime}"
    else:
        cache_key = f"{parent_dir}_{video_path_obj.stem}_{file_size}_{mtime}"

    # ALWAYS use job's temp_dir for index storage (for cleanup)
    if temp_dir:
        cache_dir = temp_dir / "ffindex"
        cache_dir.mkdir(parents=True, exist_ok=True)
    else:
        # Fallback: use system temp (but warn - won't be cleaned up)
        cache_dir = Path(tempfile.gettempdir()) / "vsg_ffindex"
        cache_dir.mkdir(parents=True, exist_ok=True)

    return cache_dir / f"{cache_key}.ffindex"


def get_vapoursynth_frame_info(video_path: str, runner, temp_dir: Optional[Path] = None) -> Optional[Tuple[int, float]]:
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
        temp_dir: Optional job temp directory for index storage

    Returns:
        Tuple of (frame_count, last_frame_timestamp_ms) or None on error
    """
    try:
        import vapoursynth as vs

        runner._log_message(f"[VapourSynth] Indexing video: {Path(video_path).name}")

        # Create new core instance for isolation
        core = vs.core

        # Generate cache path for FFMS2 index
        index_path = _get_ffms2_cache_path(video_path, temp_dir)

        # Show where index is stored
        if temp_dir:
            # Show relative path from job temp dir
            try:
                rel_path = index_path.relative_to(temp_dir)
                location_msg = f"job_temp/{rel_path}"
            except ValueError:
                location_msg = str(index_path)
        else:
            location_msg = str(index_path)

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
                # Log whether index already exists
                if index_path.exists():
                    runner._log_message(f"[VapourSynth] ✓ Reusing existing index from: {location_msg}")
                else:
                    runner._log_message(f"[VapourSynth] Creating new index at: {location_msg}")
                    runner._log_message(f"[VapourSynth] This may take 1-2 minutes...")

                # Use FFMS2 with custom cache path
                clip = core.ffms2.Source(
                    source=str(video_path),
                    cachefile=str(index_path)
                )
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


def extract_frame_as_image(video_path: str, frame_number: int, runner, temp_dir: Optional[Path] = None) -> Optional[bytes]:
    """
    Extract a single frame from video as PNG image data using VapourSynth.

    Args:
        video_path: Path to video file
        frame_number: Frame index to extract (0-based)
        runner: CommandRunner for logging
        temp_dir: Optional job temp directory for index storage

    Returns:
        PNG image data as bytes, or None on error
    """
    try:
        import vapoursynth as vs
        from PIL import Image
        import numpy as np
        import io

        core = vs.core

        # Generate cache path for FFMS2 index
        index_path = _get_ffms2_cache_path(video_path, temp_dir)

        # Load video - try L-SMASH first, fall back to FFmpegSource2
        clip = None
        try:
            clip = core.lsmas.LWLibavSource(str(video_path))
        except (AttributeError, Exception):
            pass

        if clip is None:
            try:
                # Use FFMS2 with custom cache path
                clip = core.ffms2.Source(
                    source=str(video_path),
                    cachefile=str(index_path)
                )
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

        # Import GPU environment support
        try:
            from vsg_core.system.gpu_env import get_subprocess_environment
            env = get_subprocess_environment()
        except ImportError:
            import os
            env = os.environ.copy()

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)

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

        # Import GPU environment support
        try:
            from vsg_core.system.gpu_env import get_subprocess_environment
            env = get_subprocess_environment()
        except ImportError:
            import os
            env = os.environ.copy()

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)

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


def validate_frame_alignment(
    source_video: str,
    target_video: str,
    subtitle_events: List,
    duration_offset_ms: float,
    runner,
    config: dict = None,
    temp_dir: Optional[Path] = None
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
        temp_dir: Optional job temp directory for index storage

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
            src_img = extract_frame_as_image(source_video, src_frame_num, runner, temp_dir)
            tgt_img = extract_frame_as_image(target_video, tgt_frame_num, runner, temp_dir)

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
# VIDEO READER - Efficient frame extraction with multi-backend support
# ============================================================================

class VideoReader:
    """
    Efficient video reader that keeps video file open for fast frame access.

    Priority order:
    1. VapourSynth + FFMS2 plugin (fastest - persistent index caching, <1ms per frame, thread-safe)
    2. pyffms2 (fast - indexed seeking, but re-indexes each time)
    3. OpenCV (medium - keeps file open, but seeks from keyframes)
    4. FFmpeg (slow - spawns process per frame)

    Supports automatic deinterlacing for interlaced content with configurable methods:
    - 'auto': Auto-detect and deinterlace only if interlaced
    - 'none': Never deinterlace (raw frames)
    - 'yadif': YADIF deinterlacer (good quality, moderate speed)
    - 'yadifmod': YADIFmod (better edge handling than YADIF)
    - 'bob': Bob deinterlacer (fast, doubles framerate)
    - 'w3fdif': W3FDIF (BBC's deinterlacer, high quality)
    - 'bwdif': BWDIF (motion adaptive, good quality)
    """

    # Available deinterlace methods
    DEINTERLACE_METHODS = ['auto', 'none', 'yadif', 'yadifmod', 'bob', 'w3fdif', 'bwdif']

    def __init__(self, video_path: str, runner, temp_dir: Path = None,
                 deinterlace: str = 'auto', config: dict = None, **kwargs):
        self.video_path = video_path
        self.runner = runner
        self.vs_clip = None  # VapourSynth clip
        self.source = None   # FFMS2 source
        self.cap = None      # OpenCV capture
        self.use_vapoursynth = False
        self.use_ffms2 = False
        self.use_opencv = False
        self.fps = None
        self.temp_dir = temp_dir
        self.deinterlace_method = deinterlace
        self.config = config or {}
        self.is_interlaced = False
        self.field_order = 'progressive'
        self.deinterlace_applied = False

        # Detect video properties for interlacing info
        self._detect_interlacing()

        # Try VapourSynth first (fastest - persistent index caching)
        if self._try_vapoursynth():
            return

        # Try FFMS2 second (fast but re-indexes each time)
        try:
            import ffms2

            # Note: The pyffms2 Python bindings don't reliably support loading cached indexes
            # We create the index on-demand each time (still faster than OpenCV fallback)
            runner._log_message(f"[FrameUtils] Creating FFMS2 index...")
            runner._log_message(f"[FrameUtils] This may take 1-2 minutes on first access...")

            # Create indexer and generate index
            indexer = ffms2.Indexer(str(video_path))
            index = indexer.do_indexing2()

            # Get first video track
            track_number = index.get_first_indexed_track_of_type(ffms2.FFMS_TYPE_VIDEO)

            # Create video source from index
            self.source = ffms2.VideoSource(str(video_path), track_number, index)
            self.use_ffms2 = True

            # Get video properties
            self.fps = self.source.properties.FPSNumerator / self.source.properties.FPSDenominator

            runner._log_message(f"[FrameUtils] FFMS2 ready! Using instant frame seeking (FPS: {self.fps:.3f})")
            return

        except ImportError:
            runner._log_message(f"[FrameUtils] FFMS2 not installed, trying opencv...")
            runner._log_message(f"[FrameUtils] Install FFMS2 for 100x speedup: pip install ffms2")
        except Exception as e:
            runner._log_message(f"[FrameUtils] WARNING: FFMS2 failed ({e}), trying opencv...")


        # Fallback to opencv if FFMS2 unavailable
        try:
            import cv2
            self.cv2 = cv2
            self.cap = cv2.VideoCapture(str(video_path))
            if self.cap.isOpened():
                self.use_opencv = True
                self.fps = self.cap.get(cv2.CAP_PROP_FPS)
                runner._log_message(f"[FrameUtils] Using opencv for frame access (FPS: {self.fps:.3f})")
            else:
                runner._log_message(f"[FrameUtils] WARNING: opencv couldn't open video, falling back to ffmpeg")
                self.cap = None
        except ImportError:
            runner._log_message(f"[FrameUtils] WARNING: opencv not installed, using slower ffmpeg fallback")
            runner._log_message(f"[FrameUtils] Install opencv for better performance: pip install opencv-python")

    def _detect_interlacing(self):
        """Detect if video is interlaced using ffprobe."""
        try:
            props = detect_video_properties(self.video_path, self.runner)
            self.is_interlaced = props.get('interlaced', False)
            self.field_order = props.get('field_order', 'progressive')

            if self.is_interlaced:
                self.runner._log_message(
                    f"[FrameUtils] Interlaced content detected: {self.field_order.upper()}"
                )
        except Exception as e:
            self.runner._log_message(f"[FrameUtils] Could not detect interlacing: {e}")
            self.is_interlaced = False
            self.field_order = 'progressive'

    def _should_deinterlace(self) -> bool:
        """Determine if deinterlacing should be applied."""
        if self.deinterlace_method == 'none':
            return False
        if self.deinterlace_method == 'auto':
            return self.is_interlaced
        # Explicit method selected - always deinterlace
        return True

    def _get_deinterlace_method(self) -> str:
        """Get the actual deinterlace method to use."""
        if self.deinterlace_method == 'auto':
            # Default to yadif for auto mode
            return self.config.get('frame_deinterlace_method', 'yadif')
        return self.deinterlace_method

    def _apply_deinterlace_filter(self, clip, core):
        """
        Apply deinterlace filter to VapourSynth clip.

        Args:
            clip: VapourSynth clip
            core: VapourSynth core

        Returns:
            Deinterlaced clip
        """
        method = self._get_deinterlace_method()
        tff = self.field_order == 'tff'  # True = Top Field First

        self.runner._log_message(
            f"[FrameUtils] Applying deinterlace: {method} (field order: {'TFF' if tff else 'BFF'})"
        )

        try:
            if method == 'yadif':
                # YADIF - Yet Another DeInterlacing Filter
                # Mode 0 = output one frame per frame (not bob)
                # Order: 1 = TFF, 0 = BFF
                if hasattr(core, 'yadifmod'):
                    # Prefer yadifmod if available (better edge handling)
                    clip = core.yadifmod.Yadifmod(clip, order=1 if tff else 0, mode=0)
                elif hasattr(core, 'yadif'):
                    clip = core.yadif.Yadif(clip, order=1 if tff else 0, mode=0)
                else:
                    # Fallback to znedi3-based yadif alternative
                    self.runner._log_message("[FrameUtils] YADIF plugin not found, using std.SeparateFields + DoubleWeave")
                    clip = self._deinterlace_fallback(clip, core, tff)

            elif method == 'yadifmod':
                # YADIFmod - improved edge handling
                if hasattr(core, 'yadifmod'):
                    clip = core.yadifmod.Yadifmod(clip, order=1 if tff else 0, mode=0)
                else:
                    self.runner._log_message("[FrameUtils] YADIFmod not available, falling back to YADIF")
                    return self._apply_deinterlace_filter_method(clip, core, 'yadif', tff)

            elif method == 'bob':
                # Bob - doubles framerate by outputting each field as frame
                # Simple and fast, good for frame matching
                clip = core.std.SeparateFields(clip, tff=tff)
                clip = core.resize.Spline36(clip, height=clip.height * 2)

            elif method == 'w3fdif':
                # W3FDIF - BBC's deinterlacer
                if hasattr(core, 'w3fdif'):
                    clip = core.w3fdif.W3FDIF(clip, order=1 if tff else 0, mode=1)
                else:
                    self.runner._log_message("[FrameUtils] W3FDIF not available, falling back to YADIF")
                    return self._apply_deinterlace_filter_method(clip, core, 'yadif', tff)

            elif method == 'bwdif':
                # BWDIF - motion adaptive deinterlacer
                if hasattr(core, 'bwdif'):
                    clip = core.bwdif.Bwdif(clip, field=1 if tff else 0)
                else:
                    self.runner._log_message("[FrameUtils] BWDIF not available, falling back to YADIF")
                    return self._apply_deinterlace_filter_method(clip, core, 'yadif', tff)

            else:
                self.runner._log_message(f"[FrameUtils] Unknown deinterlace method: {method}, using YADIF")
                return self._apply_deinterlace_filter_method(clip, core, 'yadif', tff)

            self.deinterlace_applied = True
            self.runner._log_message(f"[FrameUtils] Deinterlace filter applied successfully")
            return clip

        except Exception as e:
            self.runner._log_message(f"[FrameUtils] Deinterlace failed: {e}, using raw frames")
            return clip

    def _apply_deinterlace_filter_method(self, clip, core, method: str, tff: bool):
        """Helper to apply a specific deinterlace method."""
        self.deinterlace_method = method
        return self._apply_deinterlace_filter(clip, core)

    def _deinterlace_fallback(self, clip, core, tff: bool):
        """Fallback deinterlacing using standard VapourSynth functions."""
        # Separate fields, then weave back
        clip = core.std.SeparateFields(clip, tff=tff)
        clip = core.std.DoubleWeave(clip, tff=tff)
        clip = core.std.SelectEvery(clip, 2, 0)
        return clip

    def _get_index_cache_path(self, video_path: str, temp_dir: Path) -> Path:
        """
        Generate cache path for FFMS2 index in job's temp directory.

        Cache key: parent_dir + filename + size + mtime (unique per file path)
        Location: {job_temp_dir}/ffindex/{cache_key}.ffindex

        The index is created in the job's temp folder so it can be:
        1. Easily identified by filename and source
        2. Reused within the job (multiple tracks using same source)
        3. Cleaned up automatically when job completes
        4. Avoid collisions when different sources have same episode numbers
        """
        import os
        import hashlib

        video_path_obj = Path(video_path)

        # Get file metadata for cache invalidation
        stat = os.stat(video_path)
        file_size = stat.st_size
        mtime = int(stat.st_mtime)

        # Include parent directory to distinguish between sources
        # E.g., "source1/1.mkv" vs "source2/1.mkv" get different indexes
        parent_dir = video_path_obj.parent.name

        # If parent is empty/root, use path hash instead
        if not parent_dir or parent_dir == '.':
            path_hash = hashlib.md5(str(video_path_obj.resolve()).encode()).hexdigest()[:8]
            cache_key = f"{video_path_obj.stem}_{path_hash}_{file_size}_{mtime}"
        else:
            cache_key = f"{parent_dir}_{video_path_obj.stem}_{file_size}_{mtime}"

        # ALWAYS use job's temp_dir for index storage (for cleanup)
        if temp_dir:
            cache_dir = temp_dir / "ffindex"
            cache_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Fallback: use system temp (but warn - won't be cleaned up)
            cache_dir = Path(tempfile.gettempdir()) / "vsg_ffindex"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.runner._log_message(f"[FrameUtils] WARNING: No job temp_dir provided, index won't be auto-cleaned")

        index_path = cache_dir / f"{cache_key}.ffindex"
        return index_path

    def _try_vapoursynth(self) -> bool:
        """
        Try to initialize VapourSynth with FFMS2 plugin for persistent index caching.

        Returns:
            True if successful, False if VapourSynth unavailable or failed
        """
        try:
            import vapoursynth as vs

            self.runner._log_message("[FrameUtils] Attempting VapourSynth with FFMS2 plugin...")

            # Get VapourSynth core instance
            core = vs.core

            # Check if ffms2 plugin is available
            if not hasattr(core, 'ffms2'):
                self.runner._log_message("[FrameUtils] VapourSynth installed but ffms2 plugin missing")
                self.runner._log_message("[FrameUtils] Install FFMS2 plugin for VapourSynth")
                return False

            # Generate cache path
            index_path = self._get_index_cache_path(self.video_path, self.temp_dir)

            # Show where index is stored
            if self.temp_dir:
                # Show relative path from job temp dir
                try:
                    rel_path = index_path.relative_to(self.temp_dir)
                    location_msg = f"job_temp/{rel_path}"
                except ValueError:
                    location_msg = str(index_path)
            else:
                location_msg = str(index_path)

            # Load video with index caching
            if index_path.exists():
                self.runner._log_message(f"[FrameUtils] Reusing existing index from: {location_msg}")
            else:
                self.runner._log_message(f"[FrameUtils] Creating new index at: {location_msg}")
                self.runner._log_message(f"[FrameUtils] This may take 1-2 minutes...")

            clip = core.ffms2.Source(
                source=str(self.video_path),
                cachefile=str(index_path)
            )

            # Apply deinterlacing if needed
            if self._should_deinterlace():
                clip = self._apply_deinterlace_filter(clip, core)

            # Keep clip in original format (usually YUV)
            # We'll extract only luma (Y) plane for hashing - more reliable than RGB
            self.vs_clip = clip

            # Get video properties
            self.fps = self.vs_clip.fps_num / self.vs_clip.fps_den
            self.use_vapoursynth = True

            deinterlace_status = ""
            if self.deinterlace_applied:
                deinterlace_status = f", deinterlaced with {self._get_deinterlace_method()}"
            elif self.is_interlaced and self.deinterlace_method == 'none':
                deinterlace_status = ", interlaced (deinterlace disabled)"

            self.runner._log_message(f"[FrameUtils] VapourSynth ready! Using persistent index cache (FPS: {self.fps:.3f}{deinterlace_status})")
            self.runner._log_message(f"[FrameUtils] Index will be shared across all workers (no re-indexing!)")

            return True

        except ImportError:
            self.runner._log_message("[FrameUtils] VapourSynth not installed, trying pyffms2...")
            self.runner._log_message("[FrameUtils] Install VapourSynth for persistent index caching: pip install VapourSynth")
            return False
        except AttributeError as e:
            self.runner._log_message(f"[FrameUtils] VapourSynth ffms2 plugin not found: {e}")
            self.runner._log_message("[FrameUtils] Install FFMS2 plugin for VapourSynth")
            return False
        except Exception as e:
            self.runner._log_message(f"[FrameUtils] VapourSynth initialization failed: {e}")
            return False

    def get_frame_at_time(self, time_ms: int) -> Optional['Image.Image']:
        """
        Extract frame at specified timestamp.

        Args:
            time_ms: Timestamp in milliseconds

        Returns:
            PIL Image object, or None on failure
        """
        if self.use_vapoursynth and self.vs_clip:
            return self._get_frame_vapoursynth(time_ms)
        elif self.use_ffms2 and self.source:
            return self._get_frame_ffms2(time_ms)
        elif self.use_opencv and self.cap:
            return self._get_frame_opencv(time_ms)
        else:
            return self._get_frame_ffmpeg(time_ms)

    def get_frame_at_index(self, frame_num: int) -> Optional['Image.Image']:
        """
        Extract frame by frame number directly (avoids time-to-frame conversion precision issues).

        This method bypasses the floating-point time conversion that can cause 1-frame
        offsets with NTSC framerates (23.976fps, 29.97fps) where int(time * fps) may
        truncate incorrectly (e.g., 1000.9999 -> 1000 instead of 1001).

        Args:
            frame_num: Frame index (0-based)

        Returns:
            PIL Image object, or None on failure
        """
        if self.use_vapoursynth and self.vs_clip:
            return self._get_frame_vapoursynth_by_index(frame_num)
        elif self.use_ffms2 and self.source:
            return self._get_frame_ffms2_by_index(frame_num)
        elif self.use_opencv and self.cap:
            # OpenCV doesn't have reliable frame-accurate seeking by index
            # Fall back to time-based seeking with best effort
            time_ms = int(frame_num * 1000.0 / self.fps) if self.fps else 0
            return self._get_frame_opencv(time_ms)
        else:
            # FFmpeg fallback - use time-based
            time_ms = int(frame_num * 1000.0 / self.fps) if self.fps else 0
            return self._get_frame_ffmpeg(time_ms)

    def _get_frame_vapoursynth_by_index(self, frame_num: int) -> Optional['Image.Image']:
        """Extract frame by index using VapourSynth (frame-accurate)."""
        try:
            from PIL import Image
            import numpy as np

            # Clamp to valid range
            frame_num = max(0, min(frame_num, len(self.vs_clip) - 1))

            # Get frame directly by index (no time conversion!)
            frame = self.vs_clip.get_frame(frame_num)

            # Extract Y (luma) plane as grayscale
            y_plane = np.asarray(frame[0])

            # Normalize bit depth to 8-bit for PIL
            # VapourSynth can provide 8-bit, 10-bit, 12-bit, or 16-bit data
            if y_plane.dtype == np.uint16:
                # For 10-bit (0-1023) or 16-bit (0-65535), normalize to 8-bit (0-255)
                # Most anime is 10-bit, so values are in 0-1023 range
                # Right-shift by (bit_depth - 8) to normalize
                # For 10-bit: shift right by 2 (divide by 4)
                # For 16-bit: shift right by 8 (divide by 256)
                max_val = y_plane.max()
                if max_val <= 1023:  # 10-bit
                    y_plane = (y_plane >> 2).astype(np.uint8)
                else:  # 12-bit or 16-bit
                    y_plane = (y_plane >> 8).astype(np.uint8)
            elif y_plane.dtype != np.uint8:
                # Ensure we have uint8
                y_plane = y_plane.astype(np.uint8)

            return Image.fromarray(y_plane, 'L')

        except Exception as e:
            self.runner._log_message(f"[FrameUtils] ERROR: VapourSynth frame extraction by index failed: {e}")
            return None

    def _get_frame_ffms2_by_index(self, frame_num: int) -> Optional['Image.Image']:
        """Extract frame by index using FFMS2 (frame-accurate)."""
        try:
            from PIL import Image
            import numpy as np

            # Clamp to valid range
            frame_num = max(0, min(frame_num, self.source.properties.NumFrames - 1))

            # Get frame directly by index (no time conversion!)
            frame = self.source.get_frame(frame_num)

            # Convert to PIL Image
            # FFMS2 typically returns Y plane as first plane for grayscale, or RGB
            frame_array = frame.planes[0]

            # Normalize bit depth to 8-bit for PIL if needed
            if frame_array.dtype == np.uint16:
                max_val = frame_array.max()
                if max_val <= 1023:  # 10-bit
                    frame_array = (frame_array >> 2).astype(np.uint8)
                else:  # 12-bit or 16-bit
                    frame_array = (frame_array >> 8).astype(np.uint8)
            elif frame_array.dtype != np.uint8:
                frame_array = frame_array.astype(np.uint8)

            return Image.fromarray(frame_array)

        except Exception as e:
            self.runner._log_message(f"[FrameUtils] ERROR: FFMS2 frame extraction by index failed: {e}")
            return None

    def _get_frame_vapoursynth(self, time_ms: int) -> Optional['Image.Image']:
        """
        Extract frame using VapourSynth (instant indexed seeking with persistent cache).

        Extracts only the luma (Y) plane as grayscale for better perceptual hashing.
        Luma contains most of the perceptual information and avoids color conversion artifacts.
        """
        try:
            from PIL import Image
            import numpy as np

            # Convert time to frame number
            frame_num = int((time_ms / 1000.0) * self.fps)

            # Clamp to valid range
            frame_num = max(0, min(frame_num, len(self.vs_clip) - 1))

            # Get frame (instant - uses FFMS2 index!)
            frame = self.vs_clip.get_frame(frame_num)

            # VapourSynth frames support the array protocol
            # frame[0] is the Y (luma) plane, np.asarray handles stride automatically
            y_plane = np.asarray(frame[0])

            # Normalize bit depth to 8-bit for PIL
            # VapourSynth can provide 8-bit, 10-bit, 12-bit, or 16-bit data
            if y_plane.dtype == np.uint16:
                # For 10-bit (0-1023) or 16-bit (0-65535), normalize to 8-bit (0-255)
                # Most anime is 10-bit, so values are in 0-1023 range
                # Right-shift by (bit_depth - 8) to normalize
                # For 10-bit: shift right by 2 (divide by 4)
                # For 16-bit: shift right by 8 (divide by 256)
                max_val = y_plane.max()
                if max_val <= 1023:  # 10-bit
                    y_plane = (y_plane >> 2).astype(np.uint8)
                else:  # 12-bit or 16-bit
                    y_plane = (y_plane >> 8).astype(np.uint8)
            elif y_plane.dtype != np.uint8:
                # Ensure we have uint8
                y_plane = y_plane.astype(np.uint8)

            # Convert to PIL Image (grayscale mode 'L')
            return Image.fromarray(y_plane, 'L')

        except Exception as e:
            self.runner._log_message(f"[FrameUtils] ERROR: VapourSynth frame extraction failed: {e}")
            return None

    def _get_frame_ffms2(self, time_ms: int) -> Optional['Image.Image']:
        """Extract frame using FFMS2 (instant indexed seeking)."""
        try:
            from PIL import Image
            import numpy as np

            # Convert time to frame number
            frame_num = int((time_ms / 1000.0) * self.fps)

            # Clamp to valid range
            frame_num = max(0, min(frame_num, self.source.properties.NumFrames - 1))

            # Get frame (instant - uses index!)
            frame = self.source.get_frame(frame_num)

            # Convert to PIL Image
            # FFMS2 returns frames as numpy arrays in RGB format
            frame_array = frame.planes[0]  # Get RGB data

            # Normalize bit depth to 8-bit for PIL if needed
            if frame_array.dtype == np.uint16:
                max_val = frame_array.max()
                if max_val <= 1023:  # 10-bit
                    frame_array = (frame_array >> 2).astype(np.uint8)
                else:  # 12-bit or 16-bit
                    frame_array = (frame_array >> 8).astype(np.uint8)
            elif frame_array.dtype != np.uint8:
                frame_array = frame_array.astype(np.uint8)

            # Create PIL Image from numpy array
            return Image.fromarray(frame_array)

        except Exception as e:
            self.runner._log_message(f"[FrameUtils] ERROR: FFMS2 frame extraction failed: {e}")
            return None

    def _get_frame_opencv(self, time_ms: int) -> Optional['Image.Image']:
        """Extract frame using opencv (fast)."""
        try:
            from PIL import Image

            # Seek to timestamp (opencv uses milliseconds)
            self.cap.set(self.cv2.CAP_PROP_POS_MSEC, time_ms)

            # Read frame
            ret, frame_bgr = self.cap.read()

            if not ret or frame_bgr is None:
                return None

            # Convert BGR to RGB
            frame_rgb = self.cv2.cvtColor(frame_bgr, self.cv2.COLOR_BGR2RGB)

            # Convert to PIL Image
            return Image.fromarray(frame_rgb)

        except Exception as e:
            self.runner._log_message(f"[FrameUtils] ERROR: opencv frame extraction failed: {e}")
            return None

    def _get_frame_ffmpeg(self, time_ms: int) -> Optional['Image.Image']:
        """Extract frame using ffmpeg (slow fallback)."""
        from PIL import Image
        import subprocess
        import os

        tmp_path = None
        try:
            time_sec = time_ms / 1000.0

            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp_path = tmp.name

            cmd = [
                'ffmpeg',
                '-ss', f'{time_sec:.3f}',
                '-i', str(self.video_path),
                '-vframes', '1',
                '-q:v', '2',
                '-y',
                tmp_path
            ]

            # Import GPU environment support
            try:
                from vsg_core.system.gpu_env import get_subprocess_environment
                env = get_subprocess_environment()
            except ImportError:
                env = os.environ.copy()

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=env
            )

            if result.returncode != 0:
                return None

            frame = Image.open(tmp_path)
            frame.load()

            return frame

        except Exception:
            return None
        finally:
            # Always clean up temp file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def close(self):
        """Release video resources."""

        # VapourSynth cleanup
        if self.vs_clip:
            # VapourSynth clips are reference counted, just clear reference
            self.vs_clip = None

        # FFMS2 cleanup
        if self.source:
            # FFMS2 sources don't need explicit closing, but clear reference
            self.source = None

        # OpenCV cleanup
        if self.cap:
            self.cap.release()
            self.cap = None

        # Force garbage collection to release nanobind objects
        gc.collect()


# ============================================================================
# FRAME HASHING - Perceptual hash functions for frame comparison
# ============================================================================

def compute_frame_hash(frame: 'Image.Image', hash_size: int = 8, method: str = 'phash') -> Optional[Any]:
    """
    Compute perceptual hash of a frame.

    Args:
        frame: PIL Image object
        hash_size: Hash size (8x8 = 64 bits, 16x16 = 256 bits)
        method: Hash method ('phash', 'dhash', 'average_hash', 'whash')

    Returns:
        ImageHash object, or None on failure
    """
    try:
        import imagehash

        if method == 'dhash':
            return imagehash.dhash(frame, hash_size=hash_size)
        elif method == 'average_hash':
            return imagehash.average_hash(frame, hash_size=hash_size)
        elif method == 'whash':
            return imagehash.whash(frame, hash_size=hash_size)
        else:  # 'phash' or default
            return imagehash.phash(frame, hash_size=hash_size)

    except ImportError:
        return None
    except Exception:
        return None


def compute_hamming_distance(hash1, hash2) -> int:
    """
    Compute Hamming distance between two perceptual hashes.

    Args:
        hash1: First ImageHash object
        hash2: Second ImageHash object

    Returns:
        Hamming distance (number of differing bits). Lower = more similar.
        Returns 0 for identical frames, typically <5 for matching frames,
        and >10 for different frames.
    """
    # ImageHash objects support subtraction to get Hamming distance
    return hash1 - hash2
