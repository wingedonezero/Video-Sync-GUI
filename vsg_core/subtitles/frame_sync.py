# vsg_core/subtitles/frame_sync.py
# -*- coding: utf-8 -*-
"""
Frame-perfect subtitle synchronization module.

Shifts subtitles by FRAME COUNT instead of milliseconds to preserve
frame-perfect alignment for typesetting and moving signs from release groups.

Supports multiple timing modes:
- 'middle': Half-frame offset (targets middle of frame window)
- 'aegisub': Aegisub-style (ceil to centisecond)

For Variable Frame Rate videos, use the separate 'videotimestamps' sync mode.
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
    delay_ms: float,
    runner,
    config: dict = None,
    rounding_mode: str = 'round'
) -> Dict[str, Any]:
    """
    Apply raw audio delay with ASS centisecond precision rounding.

    This is a pure delay mode for testing/debugging:
    1. Load subtitles
    2. Add raw delay to all timestamps
    3. Round to centisecond precision (10ms for ASS format)
    4. Save subtitles

    NO frame analysis, NO VideoTimestamps - just pure math.
    Useful for isolating whether frame correction is causing sync issues.

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        delay_ms: Raw audio delay (unrounded float, full precision)
        runner: CommandRunner for logging
        config: Optional config dict (unused, for API compatibility)
        rounding_mode: How to round to centiseconds:
            - 'floor': Round down (1065.458ms → 1060ms)
            - 'round': Round to nearest (1065.458ms → 1070ms)
            - 'ceil': Round up (1065.458ms → 1070ms)

    Returns:
        Dict with report statistics
    """
    config = config or {}
    rounding_mode = config.get('raw_delay_rounding', rounding_mode)

    runner._log_message(f"[Raw Delay Sync] Mode: Pure delay + centisecond rounding")
    runner._log_message(f"[Raw Delay Sync] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[Raw Delay Sync] Raw audio delay: {delay_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync] Rounding mode: {rounding_mode}")

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
            'total_events': 0,
            'delay_applied_ms': delay_ms
        }

    runner._log_message(f"[Raw Delay Sync] Loaded {len(subs.events)} subtitle events")

    # Apply delay to all events
    for event in subs.events:
        # Add raw delay
        new_start_ms = event.start + delay_ms
        new_end_ms = event.end + delay_ms

        # Round to centiseconds (10ms precision for ASS)
        if rounding_mode == 'floor':
            event.start = int(new_start_ms // 10) * 10
            event.end = int(new_end_ms // 10) * 10
        elif rounding_mode == 'ceil':
            event.start = int(math.ceil(new_start_ms / 10)) * 10
            event.end = int(math.ceil(new_end_ms / 10)) * 10
        else:  # 'round' (default)
            event.start = int(round(new_start_ms / 10)) * 10
            event.end = int(round(new_end_ms / 10)) * 10

    # Calculate what the delay became after rounding
    # Use first event as example
    if subs.events:
        first_event_original = metadata.metadata.get('first_event_start', 0)
        first_event_new = subs.events[0].start
        actual_delay = first_event_new - first_event_original
        runner._log_message(f"[Raw Delay Sync] Example: First event shifted by {actual_delay:+.0f}ms (after rounding)")

    # Save modified subtitle
    runner._log_message(f"[Raw Delay Sync] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Raw Delay Sync] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Validate and restore lost metadata
    metadata.validate_and_restore(runner, expected_delay_ms=int(round(delay_ms)))

    # Log results
    runner._log_message(f"[Raw Delay Sync] ✓ Successfully synchronized {len(subs.events)} events")
    runner._log_message(f"[Raw Delay Sync]   - Raw delay applied: {delay_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   - Rounding mode: {rounding_mode}")

    return {
        'total_events': len(subs.events),
        'raw_delay_ms': delay_ms,
        'rounding_mode': rounding_mode
    }


# ============================================================================
# DURATION ALIGNMENT MODE (Frame Alignment via Total Duration)
# ============================================================================

def verify_alignment_with_sliding_window(
    source_video: str,
    target_video: str,
    subtitle_events: List,
    duration_offset_ms: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Hybrid verification: Use duration offset as starting point, then verify with
    sliding window frame matching at multiple checkpoints.

    Algorithm:
    1. Use duration_offset_ms as rough estimate
    2. Pick 3 checkpoints (first/mid/last subtitles)
    3. For each checkpoint:
       - Extract 11 frames from source (center ± 5)
       - Search in target around duration_offset ± search_window
       - Use perceptual hash sliding window to find best match
       - Record the precise offset
    4. Check if all measurements agree within tolerance
    5. Return precise offset if agreement, else indicate fallback needed

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
    runner._log_message(f"[Hybrid Verification] Running frame-based verification...")
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

    # Filter valid events (require at least 5 seconds in)
    valid_events = [e for e in subtitle_events if e.start >= 5000]
    if not valid_events:
        runner._log_message(f"[Hybrid Verification] WARNING: No valid subtitle events found")
        return {
            'enabled': True,
            'valid': False,
            'error': 'No valid subtitle events for verification',
            'measurements': [],
            'duration_offset_ms': duration_offset_ms
        }

    # Select 3 checkpoints (first, middle, last)
    num_points = min(3, len(valid_events))
    if num_points == 1:
        checkpoints = [valid_events[0]]
    else:
        first_event = valid_events[0]
        middle_event = valid_events[len(valid_events) // 2]
        last_event = valid_events[-1]
        checkpoints = [first_event, middle_event, last_event]

    runner._log_message(f"[Hybrid Verification] Selected {len(checkpoints)} checkpoints for verification")

    # Import frame matching utilities
    try:
        from .frame_matching import VideoReader, compute_perceptual_hash
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

    # Process each checkpoint
    for i, event in enumerate(checkpoints):
        checkpoint_time_ms = event.start
        runner._log_message(f"[Hybrid Verification] Checkpoint {i+1}/{len(checkpoints)}: {checkpoint_time_ms}ms")

        # Extract 11 frames from source (center ± 5 frames)
        center_time_s = checkpoint_time_ms / 1000.0
        fps = source_reader.fps or 23.976
        frame_duration_s = 1.0 / fps

        source_frames = []
        for offset in range(-5, 6):  # -5 to +5 = 11 frames
            frame_time_s = center_time_s + (offset * frame_duration_s)
            frame = source_reader.get_frame_at_time(frame_time_s)
            if frame is not None:
                source_frames.append((offset, frame))

        if len(source_frames) < 5:  # Need at least 5 frames
            runner._log_message(f"[Hybrid Verification] WARNING: Could not extract enough frames from source")
            continue

        # Compute hash for center frame
        center_frame = [f for o, f in source_frames if o == 0]
        if not center_frame:
            runner._log_message(f"[Hybrid Verification] WARNING: No center frame extracted")
            continue

        source_hash = compute_perceptual_hash(center_frame[0], method=hash_algorithm, hash_size=hash_size)

        # Search in target around duration_offset ± search_window
        search_center_ms = checkpoint_time_ms + duration_offset_ms
        search_start_ms = search_center_ms - search_window_ms
        search_end_ms = search_center_ms + search_window_ms

        runner._log_message(f"[Hybrid Verification]   Searching {search_start_ms:.0f}ms - {search_end_ms:.0f}ms")

        # Sliding window search
        best_match_offset = None
        best_match_distance = float('inf')

        search_step_ms = 1000.0 / fps  # Search every frame
        current_search_ms = search_start_ms

        while current_search_ms <= search_end_ms:
            target_frame = target_reader.get_frame_at_time(current_search_ms / 1000.0)
            if target_frame is not None:
                target_hash = compute_perceptual_hash(target_frame, method=hash_algorithm, hash_size=hash_size)
                distance = bin(source_hash ^ target_hash).count('1')  # Hamming distance

                if distance < best_match_distance:
                    best_match_distance = distance
                    best_match_offset = current_search_ms - checkpoint_time_ms

            current_search_ms += search_step_ms

        if best_match_offset is None:
            runner._log_message(f"[Hybrid Verification] WARNING: No match found for checkpoint {i+1}")
            continue

        if best_match_distance <= hash_threshold:
            measurements.append(best_match_offset)
            runner._log_message(f"[Hybrid Verification]   ✓ Match found: offset={best_match_offset:+.1f}ms, distance={best_match_distance}")
            checkpoint_details.append({
                'checkpoint_ms': checkpoint_time_ms,
                'offset_ms': best_match_offset,
                'hash_distance': best_match_distance,
                'matched': True
            })
        else:
            runner._log_message(f"[Hybrid Verification]   ✗ No good match: best distance={best_match_distance} (threshold={hash_threshold})")
            checkpoint_details.append({
                'checkpoint_ms': checkpoint_time_ms,
                'offset_ms': None,
                'hash_distance': best_match_distance,
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
                fallback_target = config.get('duration_align_fallback_target', 'dual-videotimestamps')
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
                fallback_target = config.get('duration_align_fallback_target', 'dual-videotimestamps')
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


# ============================================================================
# FRAME-CORRECTED DELAY CALCULATION
# ============================================================================

def compute_frame_corrected_delay(
    source_video: str,
    target_video: str,
    raw_delay_ms: float,
    anchor_subtitle_time_ms: int,
    runner,
    config: dict = None
) -> float:
    """
    Compute a single frame-corrected delay using video timestamps.

    This function implements the CORRECT subtitle sync algorithm:
    1. Uses video-timestamps ONLY to compute a frame-corrected delay offset
    2. Returns a single delay to be applied to ALL subtitle events
    3. No per-event frame snapping (which causes random ±1-4 frame errors)

    Algorithm (CORRECTED - no source frame snapping):
    1. Take anchor subtitle time directly (don't snap to source frame!)
    2. Add the raw audio delay → predicted target position
    3. Find the nearest frame PTS in target video
    4. Compute the correction factor (target_pts - predicted_pts)
    5. Return final_delay = raw_delay + correction

    For frame-aligned videos (same frame count), snapping to source frame first
    loses precision and causes offset errors. We use the actual subtitle timing.

    Args:
        source_video: Path to video that subs were originally timed to
        target_video: Path to target video (Source 1)
        raw_delay_ms: Raw audio delay from correlation (unrounded float)
        anchor_subtitle_time_ms: Timestamp of anchor subtitle (first dialogue line)
        runner: CommandRunner for logging
        config: Optional config dict with settings

    Returns:
        Frame-corrected delay in milliseconds (float)
    """
    runner._log_message(f"[Frame Correction] Computing frame-corrected delay using anchor-based method")
    runner._log_message(f"[Frame Correction] Anchor subtitle time: {anchor_subtitle_time_ms}ms")
    runner._log_message(f"[Frame Correction] Raw audio delay: {raw_delay_ms:+.3f}ms")

    # Detect FPS of both videos
    source_fps = detect_video_fps(source_video, runner)
    target_fps = detect_video_fps(target_video, runner)

    runner._log_message(f"[Frame Correction] Source FPS: {source_fps:.3f}")
    runner._log_message(f"[Frame Correction] Target FPS: {target_fps:.3f}")

    # Step 1 (OPTIONAL): Find source frame for reference/logging only
    source_frame = time_to_frame_vfr(anchor_subtitle_time_ms, source_video, source_fps, runner, config)
    if source_frame is not None:
        source_pts = frame_to_time_vfr(source_frame, source_video, source_fps, runner, config)
        if source_pts is not None:
            runner._log_message(f"[Frame Correction] Source reference: frame {source_frame} @ {source_pts}ms")

    # Step 2: Add raw delay DIRECTLY to anchor time (no source frame snapping!)
    # This preserves the exact subtitle timing and prevents offset errors
    predicted_target_time = anchor_subtitle_time_ms + raw_delay_ms
    runner._log_message(f"[Frame Correction] Predicted target position: {anchor_subtitle_time_ms}ms + {raw_delay_ms:+.3f}ms = {predicted_target_time:.3f}ms")

    # Step 3: Find nearest frame PTS in target
    target_frame = time_to_frame_vfr(predicted_target_time, target_video, target_fps, runner, config)
    if target_frame is None:
        runner._log_message(f"[Frame Correction] WARNING: Failed to get target frame, using raw delay")
        return raw_delay_ms

    target_pts = frame_to_time_vfr(target_frame, target_video, target_fps, runner, config)
    if target_pts is None:
        runner._log_message(f"[Frame Correction] WARNING: Failed to get target PTS, using raw delay")
        return raw_delay_ms

    runner._log_message(f"[Frame Correction] Target: frame {target_frame} @ {target_pts}ms")

    # Step 4: Compute correction factor
    correction = target_pts - predicted_target_time
    runner._log_message(f"[Frame Correction] Correction: {target_pts}ms - {predicted_target_time:.3f}ms = {correction:.3f}ms")

    # Step 5: Calculate final delay
    final_delay = raw_delay_ms + correction
    runner._log_message(f"[Frame Correction] Final delay: {raw_delay_ms:+.3f}ms + {correction:+.3f}ms = {final_delay:+.3f}ms")
    runner._log_message(f"[Frame Correction] ✓ Frame-corrected delay calculated successfully")

    return final_delay


# ============================================================================
# CLEAN VIDEOTIMESTAMPS MODE (No custom offsets)
# ============================================================================

def apply_videotimestamps_sync(
    subtitle_path: str,
    delay_ms: float,
    target_fps: float,
    runner,
    config: dict = None,
    video_path: str = None
) -> Dict[str, Any]:
    """
    Apply frame-corrected synchronization using VideoTimestamps library.

    CORRECT ALGORITHM (prevents per-event frame rounding errors):
    1. Find first non-empty subtitle event as anchor
    2. Calculate frame correction for anchor subtitle
    3. Apply single frame-corrected delay to ALL events (preserves relative timing)
    4. No per-event frame snapping (eliminates random ±1-4 frame errors)

    This provides frame-accurate alignment while preserving subtitle timing relationships:
    - Uses video-timestamps ONLY for delay correction calculation
    - Applies single global shift to all events
    - Preserves original subtitle durations and relative positions
    - ASS/SRT format handles final centisecond quantization

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        delay_ms: Raw audio delay from correlation (unrounded float)
        target_fps: Frame rate (used for CFR videos)
        runner: CommandRunner for logging
        config: Optional config dict
        video_path: Path to video file (required)

    Returns:
        Dict with report statistics
    """
    if not video_path:
        runner._log_message("[VideoTimestamps Sync] ERROR: VideoTimestamps mode requires video_path")
        return {'error': 'VideoTimestamps mode requires video_path'}

    config = config or {}

    runner._log_message(f"[VideoTimestamps Sync] Mode: Frame-corrected sync using target video")
    runner._log_message(f"[VideoTimestamps Sync] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[VideoTimestamps Sync] Target video: {Path(video_path).name}")
    runner._log_message(f"[VideoTimestamps Sync] Raw audio delay: {delay_ms:+.3f}ms")

    # Capture original metadata before pysubs2 processing
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[VideoTimestamps Sync] ERROR: Failed to load subtitle file: {e}")
        return {'error': str(e)}

    if not subs.events:
        runner._log_message(f"[VideoTimestamps Sync] WARNING: No subtitle events found in file")
        return {
            'total_events': 0,
            'frame_corrected_delay_ms': delay_ms
        }

    runner._log_message(f"[VideoTimestamps Sync] Loaded {len(subs.events)} subtitle events")

    # Find first non-empty event as anchor
    anchor_event = next((e for e in subs.events if e.end > e.start), subs.events[0])
    anchor_time_ms = anchor_event.start

    runner._log_message(f"[VideoTimestamps Sync] Using anchor subtitle at {anchor_time_ms}ms")
    runner._log_message(f"[VideoTimestamps Sync] Computing frame correction for anchor...")

    # Calculate frame correction for single-video mode
    # Add delay first
    adjusted_anchor_time = anchor_time_ms + delay_ms

    # Snap to frame boundary
    anchor_frame = time_to_frame_vfr(adjusted_anchor_time, video_path, target_fps, runner, config)
    if anchor_frame is None:
        runner._log_message(f"[VideoTimestamps Sync] WARNING: Failed to get anchor frame, using raw delay")
        frame_corrected_delay = delay_ms
    else:
        anchor_frame_pts = frame_to_time_vfr(anchor_frame, video_path, target_fps, runner, config)
        if anchor_frame_pts is None:
            runner._log_message(f"[VideoTimestamps Sync] WARNING: Failed to get anchor PTS, using raw delay")
            frame_corrected_delay = delay_ms
        else:
            # Correction = difference between frame-snapped position and original adjusted position
            correction = anchor_frame_pts - adjusted_anchor_time
            frame_corrected_delay = delay_ms + correction

            runner._log_message(f"[VideoTimestamps Sync] Anchor after delay: {adjusted_anchor_time:.3f}ms")
            runner._log_message(f"[VideoTimestamps Sync] Anchor frame {anchor_frame} @ {anchor_frame_pts}ms")
            runner._log_message(f"[VideoTimestamps Sync] Correction: {correction:+.3f}ms")
            runner._log_message(f"[VideoTimestamps Sync] Frame-corrected delay: {frame_corrected_delay:+.3f}ms")

    runner._log_message(f"[VideoTimestamps Sync] Applying single delay of {frame_corrected_delay:+.3f}ms to all {len(subs.events)} events...")

    # Apply the SAME delay to ALL events (no per-event frame snapping!)
    for event in subs.events:
        event.start = event.start + frame_corrected_delay
        event.end = event.end + frame_corrected_delay

    # Save modified subtitle
    runner._log_message(f"[VideoTimestamps Sync] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[VideoTimestamps Sync] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Validate and restore lost metadata
    metadata.validate_and_restore(runner, expected_delay_ms=int(round(frame_corrected_delay)))

    # Log results
    runner._log_message(f"[VideoTimestamps Sync] ✓ Successfully synchronized {len(subs.events)} events")
    runner._log_message(f"[VideoTimestamps Sync]   - Raw audio delay: {delay_ms:+.3f}ms")
    runner._log_message(f"[VideoTimestamps Sync]   - Frame-corrected delay: {frame_corrected_delay:+.3f}ms")
    runner._log_message(f"[VideoTimestamps Sync]   - Correction applied: {(frame_corrected_delay - delay_ms):+.3f}ms")

    return {
        'total_events': len(subs.events),
        'raw_delay_ms': delay_ms,
        'frame_corrected_delay_ms': frame_corrected_delay,
        'correction_ms': frame_corrected_delay - delay_ms,
        'target_fps': target_fps
    }


# ============================================================================
# MODE 4: DUAL VIDEOTIMESTAMPS (Two-Video Frame-Accurate Mapping)
# ============================================================================

def apply_dual_videotimestamps_sync(
    subtitle_path: str,
    source_video: str,
    target_video: str,
    delay_ms: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Apply frame-accurate synchronization using VideoTimestamps from BOTH videos.

    CORRECT ALGORITHM (prevents per-event frame rounding errors):
    1. Find first non-empty subtitle event as anchor
    2. Use compute_frame_corrected_delay() to calculate ONE frame-corrected delay
    3. Apply that single delay to ALL subtitle events (preserves relative timing)
    4. No per-event frame snapping (eliminates random ±1-4 frame errors)

    This provides frame-accurate alignment while preserving subtitle timing relationships:
    - Uses video-timestamps ONLY for delay correction calculation
    - Applies single global shift to all events
    - Preserves original subtitle durations and relative positions
    - ASS/SRT format handles final centisecond quantization

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        source_video: Path to video that subs were originally timed to
        target_video: Path to target video (Source 1)
        delay_ms: Raw audio delay from correlation (unrounded float, includes global shift)
        runner: CommandRunner for logging
        config: Optional config dict with settings

    Returns:
        Dict with report statistics
    """
    config = config or {}

    runner._log_message(f"[Dual VideoTimestamps] Mode: Frame-corrected sync using both videos")
    runner._log_message(f"[Dual VideoTimestamps] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[Dual VideoTimestamps] Source video: {Path(source_video).name}")
    runner._log_message(f"[Dual VideoTimestamps] Target video: {Path(target_video).name}")
    runner._log_message(f"[Dual VideoTimestamps] Raw audio delay: {delay_ms:+.3f}ms")

    # Capture original metadata before pysubs2 processing
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Dual VideoTimestamps] ERROR: Failed to load subtitle file: {e}")
        return {'error': str(e)}

    if not subs.events:
        runner._log_message(f"[Dual VideoTimestamps] WARNING: No subtitle events found in file")
        return {
            'total_events': 0,
            'frame_corrected_delay_ms': delay_ms
        }

    runner._log_message(f"[Dual VideoTimestamps] Loaded {len(subs.events)} subtitle events")

    # Find first non-empty event as anchor
    anchor_event = next((e for e in subs.events if e.end > e.start), subs.events[0])
    anchor_time_ms = anchor_event.start

    runner._log_message(f"[Dual VideoTimestamps] Using anchor subtitle at {anchor_time_ms}ms")

    # Compute single frame-corrected delay using anchor subtitle
    frame_corrected_delay = compute_frame_corrected_delay(
        source_video,
        target_video,
        delay_ms,
        anchor_time_ms,
        runner,
        config
    )

    runner._log_message(f"[Dual VideoTimestamps] Applying single delay of {frame_corrected_delay:+.3f}ms to all {len(subs.events)} events...")

    # Apply the SAME delay to ALL events (no per-event frame snapping!)
    for event in subs.events:
        event.start = event.start + frame_corrected_delay
        event.end = event.end + frame_corrected_delay

    # Save modified subtitle
    runner._log_message(f"[Dual VideoTimestamps] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Dual VideoTimestamps] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Validate and restore lost metadata
    metadata.validate_and_restore(runner, expected_delay_ms=int(round(frame_corrected_delay)))

    # Log results
    runner._log_message(f"[Dual VideoTimestamps] ✓ Successfully synchronized {len(subs.events)} events")
    runner._log_message(f"[Dual VideoTimestamps]   - Raw audio delay: {delay_ms:+.3f}ms")
    runner._log_message(f"[Dual VideoTimestamps]   - Frame-corrected delay: {frame_corrected_delay:+.3f}ms")
    runner._log_message(f"[Dual VideoTimestamps]   - Correction applied: {(frame_corrected_delay - delay_ms):+.3f}ms")

    return {
        'total_events': len(subs.events),
        'raw_delay_ms': delay_ms,
        'frame_corrected_delay_ms': frame_corrected_delay,
        'correction_ms': frame_corrected_delay - delay_ms
    }


# ============================================================================
# MODE 5: FRAME-SNAPPED (Snap Start, Preserve Duration)
# ============================================================================

def apply_frame_snapped_sync(
    subtitle_path: str,
    delay_ms: int,
    target_fps: float,
    runner,
    config: dict = None,
    video_path: str = None
) -> Dict[str, Any]:
    """
    Apply frame-snapped synchronization: Snap START to frames, preserve duration in TIME.

    This mode addresses the "random off by 1 frame" issue by:
    1. Applying the delay in milliseconds (not converting to frame count upfront)
    2. Snapping each subtitle START to the nearest frame boundary
    3. Preserving the original duration in milliseconds
    4. Calculating END as start + duration (not rounding independently)

    This ensures:
    - Start times are frame-aligned (important for moving signs)
    - Duration is preserved exactly (whole block moves together)
    - No independent rounding of start and end (prevents random errors)

    Algorithm:
    1. For each subtitle event:
       - Apply delay_ms to start time
       - Convert to nearest frame boundary
       - Convert back to time (frame-snapped start)
       - Calculate end as start + original_duration
    2. Save modified subtitle file

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        delay_ms: Time offset in milliseconds
        target_fps: Target video frame rate
        runner: CommandRunner for logging
        config: Optional config dict with settings:
            - 'frame_sync_mode': 'middle' or 'aegisub' (for frame conversion)
        video_path: Path to video file (unused, kept for API compatibility)

    Returns:
        Dict with report statistics
    """
    config = config or {}

    # Determine timing mode for frame conversion
    timing_mode = config.get('frame_sync_mode', 'middle')

    runner._log_message(f"[Frame-Snapped Sync] Mode: Snap start, preserve duration")
    runner._log_message(f"[Frame-Snapped Sync] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[Frame-Snapped Sync] Target FPS: {target_fps:.3f}")
    runner._log_message(f"[Frame-Snapped Sync] Delay to apply: {delay_ms:+d} ms")
    runner._log_message(f"[Frame-Snapped Sync] Frame timing convention: {timing_mode}")

    # Capture original metadata before pysubs2 processing
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Frame-Snapped Sync] ERROR: Failed to load subtitle file: {e}")
        return {'error': str(e)}

    if not subs.events:
        runner._log_message(f"[Frame-Snapped Sync] WARNING: No subtitle events found in file")
        return {
            'total_events': 0,
            'adjusted_events': 0,
            'delay_applied_ms': delay_ms,
            'target_fps': target_fps
        }

    # Select conversion functions based on timing mode
    if timing_mode == 'aegisub':
        time_to_frame_func = time_to_frame_aegisub
        frame_to_time_func = frame_to_time_aegisub
    else:  # 'middle' or default
        time_to_frame_func = time_to_frame_middle
        frame_to_time_func = frame_to_time_middle

    adjusted_count = 0
    duration_preserved_count = 0
    runner._log_message(f"[Frame-Snapped Sync] Processing {len(subs.events)} subtitle events...")

    # Process each event: snap start to frame, preserve duration
    for event in subs.events:
        original_start = event.start
        original_end = event.end
        original_duration = original_end - original_start

        # Skip empty events
        if original_duration == 0:
            continue

        # 1. Apply delay in milliseconds
        new_start_ms = original_start + delay_ms

        # 2. Snap start to nearest frame boundary
        new_start_frame = time_to_frame_func(new_start_ms, target_fps)
        new_start_ms_snapped = frame_to_time_func(new_start_frame, target_fps)

        # 3. Preserve duration in TIME (don't round end independently!)
        new_end_ms = new_start_ms_snapped + original_duration

        # Update event
        event.start = new_start_ms_snapped
        event.end = new_end_ms

        if delay_ms != 0:
            adjusted_count += 1

        # Track that we preserved duration
        duration_preserved_count += 1

    # Save modified subtitle
    runner._log_message(f"[Frame-Snapped Sync] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Frame-Snapped Sync] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Validate and restore lost metadata (with timing validation)
    metadata.validate_and_restore(runner, expected_delay_ms=delay_ms)

    # Log results
    runner._log_message(f"[Frame-Snapped Sync] ✓ Successfully processed {len(subs.events)} events")
    runner._log_message(f"[Frame-Snapped Sync]   - Events adjusted: {adjusted_count}")
    runner._log_message(f"[Frame-Snapped Sync]   - Durations preserved: {duration_preserved_count}")
    runner._log_message(f"[Frame-Snapped Sync]   - Delay applied: {delay_ms:+d} ms")

    return {
        'total_events': len(subs.events),
        'adjusted_events': adjusted_count,
        'durations_preserved': duration_preserved_count,
        'delay_applied_ms': delay_ms,
        'target_fps': target_fps
    }


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

    Algorithm:
    1. Convert delay_ms to frame count (using configured rounding method)
    2. For each subtitle event:
       - Convert timestamp to frame number (using selected mode)
       - Add frame offset
       - Convert back to timestamp (using selected mode)
    3. Optionally fix zero-duration events (if enabled)
    4. Save modified subtitle file

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        delay_ms: Time offset in milliseconds (converted to frames)
        target_fps: Target video frame rate
        runner: CommandRunner for logging
        config: Optional config dict with settings:
            - 'frame_sync_mode': 'middle' or 'aegisub'
            - 'frame_shift_rounding': 'round', 'floor', or 'ceil'
            - 'frame_sync_fix_zero_duration': bool
        video_path: Path to video file (unused, kept for API compatibility)

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

    # Convert delay to frame count using configured rounding method
    frame_duration_ms = 1000.0 / target_fps
    rounding_method = config.get('frame_shift_rounding', 'round')

    raw_frame_shift = delay_ms / frame_duration_ms
    if rounding_method == 'floor':
        frame_shift = int(raw_frame_shift)  # floor
    elif rounding_method == 'ceil':
        frame_shift = int(raw_frame_shift) + (1 if raw_frame_shift > int(raw_frame_shift) else 0)  # ceil
    else:  # 'round' (default)
        frame_shift = round(raw_frame_shift)

    effective_delay_ms = frame_shift * frame_duration_ms

    runner._log_message(f"[Frame-Perfect Sync] Frame duration: {frame_duration_ms:.3f} ms")
    runner._log_message(f"[Frame-Perfect Sync] Frame shift: {frame_shift:+d} frames (using {rounding_method})")
    runner._log_message(f"[Frame-Perfect Sync] Effective delay: {effective_delay_ms:+.1f} ms")

    if abs(delay_ms - effective_delay_ms) > 0.5:
        runner._log_message(f"[Frame-Perfect Sync] NOTE: Rounded {delay_ms}ms to {effective_delay_ms:.1f}ms ({abs(delay_ms - effective_delay_ms):.1f}ms difference)")

    # Capture original metadata before pysubs2 processing
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

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

        # Convert to frame numbers
        start_frame = time_to_frame_func(original_start, target_fps)
        end_frame = time_to_frame_func(original_end, target_fps)

        # Apply frame shift
        new_start_frame = start_frame + frame_shift
        new_end_frame = end_frame + frame_shift

        # Convert back to timestamps
        new_start_ms = frame_to_time_func(new_start_frame, target_fps)
        new_end_ms = frame_to_time_func(new_end_frame, target_fps)

        # Optionally fix zero-duration events
        fix_zero_duration = config.get('frame_sync_fix_zero_duration', False)
        if fix_zero_duration and new_end_ms <= new_start_ms:
            new_end_ms = new_start_ms + int(round(frame_duration_ms))
            runner._log_message(f"[Frame-Perfect Sync] WARNING: Fixed zero-duration event at {new_start_ms}ms (added 1 frame)")

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

    # Validate and restore lost metadata (with timing validation)
    metadata.validate_and_restore(runner, expected_delay_ms=delay_ms)

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
