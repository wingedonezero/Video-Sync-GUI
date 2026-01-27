# vsg_core/subtitles/sync_mode_plugins/video_verified.py
# -*- coding: utf-8 -*-
"""
Video-Verified sync plugin for SubtitleData.

This mode addresses the case where audio correlation detects a small offset
(typically 1 frame ~42ms) but subtitles are actually timed to VIDEO.

Problem scenario:
- Audio may be slightly offset from video in the source file
- Subtitles are authored to VIDEO timing, not audio
- Audio correlation finds -46ms (audio-to-audio offset)
- But video-to-video is actually 0ms
- For subtitles, we need the VIDEO offset (0ms), not audio offset (-46ms)

Solution:
1. Take the audio correlation result as a starting point
2. Use frame matching to find the TRUE video-to-video offset
3. If the video offset differs from audio correlation, trust video
4. Specifically checks if "zero offset" is actually correct when correlation
   detects a small sub-frame or single-frame offset

All timing is float ms internally - rounding happens only at final save.

This module also exports `calculate_video_verified_offset()` which can be used
independently to get the frame-corrected delay for any subtitle format,
including bitmap subtitles (VobSub, PGS) that can't be loaded into SubtitleData.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, TYPE_CHECKING

from ..sync_modes import SyncPlugin, register_sync_plugin

if TYPE_CHECKING:
    from ..data import SubtitleData, OperationResult, OperationRecord, SyncEventData


def calculate_video_verified_offset(
    source_video: str,
    target_video: str,
    total_delay_ms: float,
    global_shift_ms: float,
    config: Optional[Dict] = None,
    runner=None,
    temp_dir: Optional[Path] = None,
    video_duration_ms: Optional[float] = None,
) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    Calculate the video-verified offset using frame matching with sub-frame precision.

    This function performs the core frame matching logic to find the TRUE
    video-to-video offset, independent of any subtitle format. It can be
    used for both text-based and bitmap subtitles (VobSub, PGS).

    The algorithm:
    1. Uses audio correlation as starting point (any offset size)
    2. Generates candidate frame offsets around the correlation value
    3. Tests each candidate at multiple checkpoints across the video
    4. Selects the best matching frame offset
    5. Uses actual PTS timestamps for sub-frame precision

    Args:
        source_video: Path to source video file
        target_video: Path to target video file (Source 1)
        total_delay_ms: Total delay from audio correlation (with global shift)
        global_shift_ms: Global shift component of the delay
        config: Settings dict with video-verified parameters
        runner: CommandRunner for logging
        temp_dir: Temp directory for frame cache
        video_duration_ms: Optional video duration (auto-detected if not provided)

    Returns:
        Tuple of (final_offset_ms, details_dict)
        - final_offset_ms: The frame-corrected offset including global shift,
          or None if frame matching failed/wasn't needed
        - details_dict: Contains 'reason', 'audio_correlation_ms', 'video_offset_ms',
          'candidates', etc.
    """
    from ..frame_utils import detect_video_fps, detect_video_properties

    config = config or {}

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    log(f"[VideoVerified] === Frame Matching for Delay Correction ===")

    if not source_video or not target_video:
        return None, {'reason': 'missing-videos', 'error': 'Both source and target videos required'}

    # Calculate pure correlation (correlation only, without global shift)
    pure_correlation_ms = total_delay_ms - global_shift_ms

    log(f"[VideoVerified] Source: {Path(source_video).name}")
    log(f"[VideoVerified] Target: {Path(target_video).name}")
    log(f"[VideoVerified] Total delay (with global): {total_delay_ms:+.3f}ms")
    log(f"[VideoVerified] Global shift: {global_shift_ms:+.3f}ms")
    log(f"[VideoVerified] Pure correlation (audio): {pure_correlation_ms:+.3f}ms")

    # Detect video properties for both videos
    source_props = detect_video_properties(source_video, runner)
    target_props = detect_video_properties(target_video, runner)

    # Determine if we should use interlaced handling
    interlaced_handling_enabled = config.get('interlaced_handling_enabled', False)
    force_mode = config.get('interlaced_force_mode', 'auto')

    # Check if either video is interlaced/telecine
    source_needs_interlaced = source_props.get('content_type') in ('interlaced', 'telecine')
    target_needs_interlaced = target_props.get('content_type') in ('interlaced', 'telecine')
    either_interlaced = source_needs_interlaced or target_needs_interlaced

    # Determine if we should use interlaced settings
    use_interlaced_settings = False
    if force_mode == 'progressive':
        use_interlaced_settings = False
    elif force_mode in ('interlaced', 'telecine'):
        use_interlaced_settings = True
    elif force_mode == 'auto' and interlaced_handling_enabled and either_interlaced:
        use_interlaced_settings = True

    if use_interlaced_settings:
        log(f"[VideoVerified] Using INTERLACED settings")
        if source_needs_interlaced:
            log(f"[VideoVerified]   Source: {source_props.get('content_type')} ({source_props.get('width')}x{source_props.get('height')})")
        if target_needs_interlaced:
            log(f"[VideoVerified]   Target: {target_props.get('content_type')} ({target_props.get('width')}x{target_props.get('height')})")

    # Detect FPS
    fps = source_props.get('fps', 23.976)
    if not fps:
        fps = 23.976
        log(f"[VideoVerified] FPS detection failed, using default: {fps}")

    frame_duration_ms = 1000.0 / fps
    log(f"[VideoVerified] FPS: {fps:.3f} (frame: {frame_duration_ms:.3f}ms)")

    # Get config parameters - use interlaced settings if appropriate
    if use_interlaced_settings:
        num_checkpoints = config.get('interlaced_num_checkpoints', 5)
        search_range_frames = config.get('interlaced_search_range_frames', 5)
        hash_algorithm = config.get('interlaced_hash_algorithm', 'ahash')
        hash_size = int(config.get('interlaced_hash_size', 8))
        hash_threshold = int(config.get('interlaced_hash_threshold', 25))
        window_radius = int(config.get('frame_window_radius', 5))
        comparison_method = config.get('frame_comparison_method', 'hash')
        interlaced_fallback_to_audio = config.get('interlaced_fallback_to_audio', True)
    else:
        num_checkpoints = config.get('video_verified_num_checkpoints', 5)
        search_range_frames = config.get('video_verified_search_range_frames', 3)
        hash_algorithm = config.get('frame_hash_algorithm', 'dhash')
        hash_size = int(config.get('frame_hash_size', 8))
        hash_threshold = int(config.get('frame_hash_threshold', 5))
        window_radius = int(config.get('frame_window_radius', 5))
        comparison_method = config.get('frame_comparison_method', 'hash')
        interlaced_fallback_to_audio = True  # Default behavior

    log(f"[VideoVerified] Checkpoints: {num_checkpoints}, Search: ±{search_range_frames} frames")
    log(f"[VideoVerified] Hash: {hash_algorithm} size={hash_size} threshold={hash_threshold}")
    log(f"[VideoVerified] Comparison method: {comparison_method}")

    # Try to import frame utilities
    try:
        from ..frame_utils import VideoReader, compute_frame_hash, compute_hamming_distance
    except ImportError as e:
        log(f"[VideoVerified] Frame utilities unavailable: {e}")
        log(f"[VideoVerified] Falling back to correlation")
        return total_delay_ms, {
            'reason': 'fallback-no-frame-utils',
            'audio_correlation_ms': pure_correlation_ms,
            'video_offset_ms': pure_correlation_ms,
            'final_offset_ms': total_delay_ms,
            'error': str(e),
        }

    # Get video duration for checkpoint selection
    source_duration = video_duration_ms
    if not source_duration or source_duration <= 0:
        try:
            props = detect_video_properties(source_video, runner)
            source_duration = props.get('duration_ms', 0)
            if source_duration <= 0:
                raise ValueError("Could not detect video duration")
        except Exception:
            source_duration = 1200000  # Default 20 minutes
            log(f"[VideoVerified] Could not detect duration, using default: {source_duration/1000:.1f}s")

    log(f"[VideoVerified] Source duration: ~{source_duration/1000:.1f}s")

    # Generate candidate frame offsets to test (centered on correlation)
    correlation_frames = pure_correlation_ms / frame_duration_ms
    candidates_frames = _generate_frame_candidates_static(
        correlation_frames, search_range_frames
    )
    log(f"[VideoVerified] Testing frame offsets: {candidates_frames} (around {correlation_frames:+.1f} frames)")

    # Open video readers with deinterlace support
    try:
        # Use interlaced deinterlace method if enabled
        if use_interlaced_settings:
            deinterlace_mode = config.get('interlaced_deinterlace_method', 'bwdif')
            log(f"[VideoVerified] Using deinterlace method: {deinterlace_mode}")
        else:
            deinterlace_mode = config.get('frame_deinterlace_mode', 'auto')

        source_reader = VideoReader(
            source_video, runner, temp_dir=temp_dir,
            deinterlace=deinterlace_mode, config=config
        )
        target_reader = VideoReader(
            target_video, runner, temp_dir=temp_dir,
            deinterlace=deinterlace_mode, config=config
        )
    except Exception as e:
        log(f"[VideoVerified] Failed to open videos: {e}")
        log(f"[VideoVerified] Falling back to correlation")
        return total_delay_ms, {
            'reason': 'fallback-video-open-failed',
            'audio_correlation_ms': pure_correlation_ms,
            'video_offset_ms': pure_correlation_ms,
            'final_offset_ms': total_delay_ms,
            'error': str(e),
        }

    # Select checkpoint times (distributed across video)
    checkpoint_times = _select_checkpoint_times_static(source_duration, num_checkpoints)
    log(f"[VideoVerified] Checkpoint times: {[f'{t/1000:.1f}s' for t in checkpoint_times]}")

    # Test each candidate frame offset
    candidate_results = []

    # Get sequence length based on content type
    if use_interlaced_settings:
        sequence_length = config.get('interlaced_sequence_length', 5)
    else:
        sequence_length = config.get('video_verified_sequence_length', 10)

    log(f"[VideoVerified] Sequence verification: {sequence_length} consecutive frames must match")

    for frame_offset in candidates_frames:
        quality = _measure_frame_offset_quality_static(
            frame_offset, checkpoint_times, source_reader, target_reader,
            fps, frame_duration_ms, window_radius, hash_algorithm, hash_size,
            hash_threshold, comparison_method, log,
            sequence_verify_length=sequence_length
        )
        # Convert frame offset to approximate ms for logging
        approx_ms = frame_offset * frame_duration_ms
        seq_verified = quality.get('sequence_verified', 0)
        candidate_results.append({
            'frame_offset': frame_offset,
            'approx_ms': approx_ms,
            'quality': quality['score'],
            'matched_checkpoints': quality['matched'],
            'sequence_verified': seq_verified,
            'avg_distance': quality['avg_distance'],
            'match_details': quality.get('match_details', []),
        })
        log(f"[VideoVerified]   Frame {frame_offset:+d} (~{approx_ms:+.1f}ms): "
            f"score={quality['score']:.2f}, seq_verified={seq_verified}/{len(checkpoint_times)}, "
            f"avg_dist={quality['avg_distance']:.1f}")

    # Select best candidate - prefer sequence_verified count, then score, then lowest avg_distance
    best_result = max(candidate_results, key=lambda r: (r['sequence_verified'], r['quality'], -r['avg_distance']))
    best_frame_offset = best_result['frame_offset']

    log(f"[VideoVerified] ───────────────────────────────────────")
    log(f"[VideoVerified] Best frame offset: {best_frame_offset:+d} frames "
        f"(seq_verified={best_result['sequence_verified']}/{len(checkpoint_times)}, score={best_result['quality']:.2f})")

    # Check if frame matching actually worked
    # Require at least one sequence-verified checkpoint for reliable results
    if best_result['sequence_verified'] == 0:
        log(f"[VideoVerified] ⚠ Sequence verification failed - no consecutive frame sequences matched")
        log(f"[VideoVerified] Required: {sequence_length} consecutive frames to match at 70%+ threshold")
        log(f"[VideoVerified] Avg distance was {best_result['avg_distance']:.1f}, threshold is {hash_threshold}")

        # Check if this might be fixable with higher threshold
        if best_result['avg_distance'] < 40:
            log(f"[VideoVerified] TIP: Try increasing 'frame_hash_threshold' to {int(best_result['avg_distance']) + 5}")
            log(f"[VideoVerified]      (Settings → Video-Verified → Hash Threshold)")

        log(f"[VideoVerified] This could mean:")
        log(f"[VideoVerified]   - Videos have different encodes/color grading")
        log(f"[VideoVerified]   - Different telecine/pulldown patterns (common for DVD)")
        log(f"[VideoVerified]   - One video has hardcoded subs/watermarks")
        log(f"[VideoVerified]   - Deinterlacing producing different results")
        log(f"[VideoVerified] Falling back to audio correlation: {pure_correlation_ms:+.3f}ms")

        # Close readers before returning
        try:
            source_reader.close()
            target_reader.close()
        except Exception:
            pass

        # Return audio correlation as the offset
        return total_delay_ms, {
            'reason': 'fallback-no-frame-matches',
            'audio_correlation_ms': pure_correlation_ms,
            'video_offset_ms': pure_correlation_ms,
            'final_offset_ms': total_delay_ms,
            'candidates': candidate_results,
            'checkpoints': len(checkpoint_times),
            'sub_frame_precision': False,
        }

    # Calculate offset in milliseconds
    # By default uses frame-based (frame_offset * frame_duration)
    # Optionally can use PTS for VFR content (enable via config)
    use_pts = config.get('video_verified_use_pts_precision', False)
    sub_frame_offset_ms = _calculate_subframe_offset_static(
        best_frame_offset, best_result.get('match_details', []),
        checkpoint_times, source_reader, target_reader, fps, frame_duration_ms, log,
        use_pts_precision=use_pts
    )

    # Close readers
    try:
        source_reader.close()
        target_reader.close()
    except Exception:
        pass

    # Calculate final offset with global shift
    final_offset_ms = sub_frame_offset_ms + global_shift_ms

    log(f"[VideoVerified] ───────────────────────────────────────")
    log(f"[VideoVerified] Audio correlation: {pure_correlation_ms:+.3f}ms")
    precision_mode = "PTS-based" if use_pts else "frame-based"
    log(f"[VideoVerified] Video-verified offset: {sub_frame_offset_ms:+.3f}ms ({precision_mode})")
    log(f"[VideoVerified] + Global shift: {global_shift_ms:+.3f}ms")
    log(f"[VideoVerified] = Final offset: {final_offset_ms:+.3f}ms")

    if abs(sub_frame_offset_ms - pure_correlation_ms) > frame_duration_ms / 2:
        log(f"[VideoVerified] ⚠ VIDEO OFFSET DIFFERS FROM AUDIO CORRELATION")
        log(f"[VideoVerified] Audio said {pure_correlation_ms:+.1f}ms, "
            f"video shows {sub_frame_offset_ms:+.1f}ms")

    log(f"[VideoVerified] ───────────────────────────────────────")

    return final_offset_ms, {
        'reason': 'frame-matched',
        'audio_correlation_ms': pure_correlation_ms,
        'video_offset_ms': sub_frame_offset_ms,
        'frame_offset': best_frame_offset,
        'final_offset_ms': final_offset_ms,
        'candidates': candidate_results,
        'checkpoints': len(checkpoint_times),
        'use_pts_precision': use_pts,
        'use_interlaced_settings': use_interlaced_settings,
        'source_content_type': source_props.get('content_type', 'unknown'),
        'target_content_type': target_props.get('content_type', 'unknown'),
    }


def _generate_frame_candidates_static(
    correlation_frames: float,
    search_range_frames: int
) -> List[int]:
    """
    Generate candidate frame offsets to test, centered on the correlation value.

    This works for any offset size - small (< 3 frames) or large (24+ frames).
    We search in a window around the correlation-derived frame offset.

    Args:
        correlation_frames: Audio correlation converted to frames (can be fractional)
        search_range_frames: How many frames on each side to search

    Returns:
        Sorted list of integer frame offsets to test
    """
    candidates = set()

    # Round correlation to nearest frame
    base_frame = int(round(correlation_frames))

    # Always include zero (in case correlation is just wrong)
    candidates.add(0)

    # Search window around correlation
    for delta in range(-search_range_frames, search_range_frames + 1):
        candidates.add(base_frame + delta)

    return sorted(candidates)


def _generate_candidates_static(
    correlation_ms: float,
    frame_duration_ms: float,
    search_range_frames: int
) -> List[float]:
    """Generate candidate offsets to test (static version) - DEPRECATED, use _generate_frame_candidates_static."""
    candidates = set()

    # Always test zero
    candidates.add(0.0)

    # Always test correlation value
    candidates.add(round(correlation_ms, 1))

    # Test frame-quantized versions of correlation
    for frame_offset in range(-search_range_frames, search_range_frames + 1):
        candidate = round(frame_offset * frame_duration_ms, 1)
        candidates.add(candidate)

    # Also test the exact frame boundaries around correlation
    base_frame = int(round(correlation_ms / frame_duration_ms))
    for frame_delta in [-1, 0, 1]:
        candidate = round((base_frame + frame_delta) * frame_duration_ms, 1)
        candidates.add(candidate)

    return sorted(candidates)


def _select_checkpoint_times_static(
    duration_ms: float,
    num_checkpoints: int
) -> List[float]:
    """Select checkpoint times distributed across the video (static version)."""
    checkpoints = []

    # Use percentage-based positions (avoiding very start/end)
    positions = [15, 30, 50, 70, 85][:num_checkpoints]

    for pos in positions:
        time_ms = duration_ms * pos / 100
        checkpoints.append(time_ms)

    return checkpoints


def _measure_candidate_quality_static(
    offset_ms: float,
    checkpoint_times: List[float],
    source_reader,
    target_reader,
    fps: float,
    frame_duration_ms: float,
    window_radius: int,
    hash_algorithm: str,
    hash_size: int,
    hash_threshold: int,
    comparison_method: str,
    log
) -> Dict[str, Any]:
    """Measure quality of a candidate offset (static version)."""
    from ..frame_utils import compute_frame_hash, compute_hamming_distance

    total_score = 0.0
    matched_count = 0
    distances = []

    for checkpoint_ms in checkpoint_times:
        # Source frame at checkpoint time
        source_frame_idx = int(checkpoint_ms / frame_duration_ms)

        # Target frame at checkpoint + offset
        target_time_ms = checkpoint_ms + offset_ms
        target_frame_idx = int(target_time_ms / frame_duration_ms)

        try:
            source_frame = source_reader.get_frame_at_index(source_frame_idx)
            if source_frame is None:
                continue

            source_hash = compute_frame_hash(source_frame, hash_size, hash_algorithm)
            if source_hash is None:
                continue

            # Search window around expected target frame
            best_distance = float('inf')
            for delta in range(-window_radius, window_radius + 1):
                search_idx = target_frame_idx + delta
                if search_idx < 0:
                    continue

                target_frame = target_reader.get_frame_at_index(search_idx)
                if target_frame is None:
                    continue

                target_hash = compute_frame_hash(target_frame, hash_size, hash_algorithm)
                if target_hash is None:
                    continue

                distance = compute_hamming_distance(source_hash, target_hash)

                if distance < best_distance:
                    best_distance = distance

            if best_distance < float('inf'):
                distances.append(best_distance)

                if best_distance <= hash_threshold:
                    matched_count += 1
                    # Score inversely proportional to distance
                    total_score += 1.0 - (best_distance / (hash_threshold * 2))
                else:
                    # Partial score for near-matches
                    total_score += max(0, 0.5 - (best_distance / (hash_threshold * 4)))

        except Exception as e:
            log(f"[VideoVerified] Checkpoint error: {e}")
            continue

    avg_distance = sum(distances) / len(distances) if distances else float('inf')

    return {
        'score': total_score,
        'matched': matched_count,
        'avg_distance': avg_distance,
    }


def _verify_frame_sequence_static(
    source_start_idx: int,
    target_start_idx: int,
    sequence_length: int,
    source_reader,
    target_reader,
    hash_algorithm: str,
    hash_size: int,
    hash_threshold: int,
    comparison_method: str = 'hash',
) -> Tuple[int, float, List[int]]:
    """
    Verify that a sequence of consecutive frames match between source and target.

    This is the key to accurate offset detection - if the offset is correct,
    then source[N], source[N+1], source[N+2], ... should match
    target[N+offset], target[N+offset+1], target[N+offset+2], ...

    NO window search is used here - frames must match at exact positions.
    This prevents false positives from window compensation.

    Args:
        source_start_idx: Starting frame index in source
        target_start_idx: Starting frame index in target (= source_start + offset)
        sequence_length: Number of consecutive frames to verify
        source_reader: VideoReader for source
        target_reader: VideoReader for target
        hash_algorithm: Hash algorithm to use
        hash_size: Hash size
        hash_threshold: Maximum distance for a match
        comparison_method: 'hash', 'ssim', or 'mse'

    Returns:
        Tuple of (matched_count, avg_distance, distances_list)
    """
    from ..frame_utils import compute_frame_hash, compute_hamming_distance, compare_frames

    matched = 0
    distances = []

    for i in range(sequence_length):
        source_idx = source_start_idx + i
        target_idx = target_start_idx + i

        if target_idx < 0:
            continue

        try:
            source_frame = source_reader.get_frame_at_index(source_idx)
            target_frame = target_reader.get_frame_at_index(target_idx)

            if source_frame is None or target_frame is None:
                continue

            if comparison_method in ('ssim', 'mse'):
                # Use compare_frames for SSIM/MSE comparison
                distance, is_match = compare_frames(
                    source_frame, target_frame,
                    method=comparison_method,
                    hash_algorithm=hash_algorithm,
                    hash_size=hash_size
                )
                distances.append(distance)
                if is_match:
                    matched += 1
            else:
                # Default: use perceptual hash comparison
                source_hash = compute_frame_hash(source_frame, hash_size, hash_algorithm)
                target_hash = compute_frame_hash(target_frame, hash_size, hash_algorithm)

                if source_hash is None or target_hash is None:
                    continue

                distance = compute_hamming_distance(source_hash, target_hash)
                distances.append(distance)

                if distance <= hash_threshold:
                    matched += 1

        except Exception:
            continue

    avg_dist = sum(distances) / len(distances) if distances else float('inf')
    return matched, avg_dist, distances


def _measure_frame_offset_quality_static(
    frame_offset: int,
    checkpoint_times: List[float],
    source_reader,
    target_reader,
    fps: float,
    frame_duration_ms: float,
    window_radius: int,
    hash_algorithm: str,
    hash_size: int,
    hash_threshold: int,
    comparison_method: str,
    log,
    sequence_verify_length: int = 10,
) -> Dict[str, Any]:
    """
    Measure quality of a candidate frame offset using sequence verification.

    Algorithm:
    1. At each checkpoint, test if source frame N matches target frame N+offset
    2. If initial frame matches, verify with SEQUENCE of consecutive frames
    3. Sequence verification uses NO window - frames must match at exact positions
    4. This prevents false positives where window search compensates for wrong offset

    The sequence verification is key: if offset is correct, then frames
    N, N+1, N+2, ... in source should match N+offset, N+offset+1, N+offset+2, ...
    in target. If offset is wrong, the sequence will fail even if single frames
    happen to match due to similar content.

    Args:
        frame_offset: Integer frame offset to test (target_frame = source_frame + offset)
        checkpoint_times: List of times in the source video to check
        sequence_verify_length: Number of consecutive frames to verify (default 10)
        ... (other args same as before)

    Returns:
        Dict with score, matched count, avg_distance, sequence_verified count, and match_details
    """
    from ..frame_utils import compute_frame_hash, compute_hamming_distance, compare_frames

    total_score = 0.0
    matched_count = 0
    sequence_verified_count = 0
    distances = []
    match_details = []

    for checkpoint_ms in checkpoint_times:
        # Source frame at checkpoint time
        source_frame_idx = int(checkpoint_ms / frame_duration_ms)

        # Target frame with this offset (STRICT - no window for initial test)
        target_frame_idx = source_frame_idx + frame_offset

        if target_frame_idx < 0:
            continue

        try:
            # First, check if the single frame matches (strict, no window)
            source_frame = source_reader.get_frame_at_index(source_frame_idx)
            if source_frame is None:
                continue

            target_frame = target_reader.get_frame_at_index(target_frame_idx)
            if target_frame is None:
                continue

            if comparison_method in ('ssim', 'mse'):
                # Use compare_frames for SSIM/MSE comparison
                initial_distance, initial_match = compare_frames(
                    source_frame, target_frame,
                    method=comparison_method,
                    hash_algorithm=hash_algorithm,
                    hash_size=hash_size
                )
            else:
                # Default: use perceptual hash comparison
                source_hash = compute_frame_hash(source_frame, hash_size, hash_algorithm)
                if source_hash is None:
                    continue

                target_hash = compute_frame_hash(target_frame, hash_size, hash_algorithm)
                if target_hash is None:
                    continue

                initial_distance = compute_hamming_distance(source_hash, target_hash)
                initial_match = initial_distance <= hash_threshold

            distances.append(initial_distance)

            # Now verify with sequence of consecutive frames
            seq_matched, seq_avg_dist, seq_distances = _verify_frame_sequence_static(
                source_frame_idx, target_frame_idx, sequence_verify_length,
                source_reader, target_reader,
                hash_algorithm, hash_size, hash_threshold,
                comparison_method=comparison_method
            )

            # Sequence is verified if majority of frames match
            # Require at least 70% of sequence to match
            min_sequence_matches = int(sequence_verify_length * 0.7)
            sequence_verified = seq_matched >= min_sequence_matches

            # Record match details
            match_details.append({
                'source_frame': source_frame_idx,
                'target_frame': target_frame_idx,
                'distance': initial_distance,
                'is_match': initial_match,
                'sequence_matched': seq_matched,
                'sequence_length': sequence_verify_length,
                'sequence_verified': sequence_verified,
                'sequence_avg_dist': seq_avg_dist,
            })

            if sequence_verified:
                sequence_verified_count += 1
                matched_count += 1
                # High score for sequence-verified matches
                # Score based on how many frames in sequence matched
                seq_ratio = seq_matched / sequence_verify_length
                total_score += 2.0 * seq_ratio  # Up to 2.0 for perfect sequence
            elif initial_match:
                # Initial frame matched but sequence didn't verify
                # Give partial score but much lower than verified
                matched_count += 1
                total_score += 0.3
            else:
                # No match at all
                total_score += max(0, 0.1 - (initial_distance / (hash_threshold * 4)))

        except Exception as e:
            log(f"[VideoVerified] Checkpoint error: {e}")
            continue

    avg_distance = sum(distances) / len(distances) if distances else float('inf')

    return {
        'score': total_score,
        'matched': matched_count,
        'sequence_verified': sequence_verified_count,
        'avg_distance': avg_distance,
        'match_details': match_details,
    }


def _calculate_subframe_offset_static(
    frame_offset: int,
    match_details: List[Dict],
    checkpoint_times: List[float],
    source_reader,
    target_reader,
    fps: float,
    frame_duration_ms: float,
    log,
    use_pts_precision: bool = False,
) -> float:
    """
    Calculate the final offset in milliseconds.

    By default, uses simple frame-based calculation:
        offset_ms = frame_offset * frame_duration_ms

    This is reliable when sequence verification confirms the frame offset is correct
    (10/10 frames matching means we KNOW the offset). Container PTS differences
    can introduce noise from muxing quirks, so frame-based is preferred.

    Optionally, can use PTS-based calculation for VFR content or when sub-frame
    precision is needed. Enable with use_pts_precision=True.

    Args:
        frame_offset: Best frame offset found (in frames)
        match_details: List of matched frame pairs from quality measurement
        checkpoint_times: Original checkpoint times
        source_reader: VideoReader for source
        target_reader: VideoReader for target
        fps: Video FPS
        frame_duration_ms: Frame duration in ms
        log: Logging function
        use_pts_precision: If True, use PTS for sub-frame precision (default False)

    Returns:
        Offset in milliseconds
    """
    # Default: simple frame-based calculation
    frame_based_offset = frame_offset * frame_duration_ms

    if not use_pts_precision:
        # Just use frame-based - simple and reliable
        log(f"[VideoVerified] Frame-based offset: {frame_offset:+d} frames = {frame_based_offset:+.3f}ms")
        return frame_based_offset

    # PTS precision mode - use actual container timestamps
    log(f"[VideoVerified] Using PTS precision mode")

    # Prioritize sequence-verified matches (most reliable)
    sequence_verified_matches = [m for m in match_details if m.get('sequence_verified', False)]

    # Fall back to single-frame matches if no sequence-verified
    if sequence_verified_matches:
        good_matches = sequence_verified_matches
        log(f"[VideoVerified] Using {len(good_matches)} sequence-verified checkpoints for PTS calculation")
    else:
        good_matches = [m for m in match_details if m.get('is_match', False)]
        if good_matches:
            log(f"[VideoVerified] No sequence-verified matches, using {len(good_matches)} single-frame matches")

    if not good_matches:
        # No good matches - fall back to frame-based calculation
        log(f"[VideoVerified] No good matches for PTS, using frame-based: {frame_based_offset:+.3f}ms")
        return frame_based_offset

    # Calculate offset from each matched pair using PTS
    pts_offsets = []

    for match in good_matches:
        source_idx = match['source_frame']
        target_idx = match['target_frame']
        seq_info = ""
        if match.get('sequence_verified'):
            seq_info = f" [seq:{match.get('sequence_matched', '?')}/{match.get('sequence_length', '?')}]"

        try:
            source_pts = source_reader.get_frame_pts(source_idx)
            target_pts = target_reader.get_frame_pts(target_idx)

            if source_pts is not None and target_pts is not None:
                offset = target_pts - source_pts
                pts_offsets.append(offset)
                log(f"[VideoVerified]   Frame {source_idx}→{target_idx}: "
                    f"PTS {source_pts:.3f}ms→{target_pts:.3f}ms = {offset:+.3f}ms{seq_info}")

        except Exception as e:
            log(f"[VideoVerified] PTS lookup error: {e}")
            continue

    if not pts_offsets:
        # PTS lookup failed - fall back to frame-based
        log(f"[VideoVerified] PTS lookup failed, using frame-based: {frame_based_offset:+.3f}ms")
        return frame_based_offset

    # Use median offset (robust to outliers)
    pts_offsets.sort()
    median_idx = len(pts_offsets) // 2
    if len(pts_offsets) % 2 == 0:
        sub_frame_offset = (pts_offsets[median_idx - 1] + pts_offsets[median_idx]) / 2
    else:
        sub_frame_offset = pts_offsets[median_idx]

    log(f"[VideoVerified] PTS-based offset from {len(pts_offsets)} pairs: {sub_frame_offset:+.3f}ms")

    return sub_frame_offset


@register_sync_plugin
class VideoVerifiedSync(SyncPlugin):
    """
    Video-Verified sync mode.

    Uses audio correlation as starting point, then verifies with frame
    matching to determine the TRUE video-to-video offset for subtitle timing.

    Now handles ANY offset size (not just small offsets) and provides
    sub-frame precision using actual PTS timestamps from the video container.

    Features:
    - Works with large offsets like -1001ms (24+ frames)
    - Sub-frame accurate timing via PTS comparison
    - Robust median calculation from multiple checkpoints
    """

    name = 'video-verified'
    description = 'Audio correlation verified against video frame matching with sub-frame precision'

    def apply(
        self,
        subtitle_data: 'SubtitleData',
        total_delay_ms: float,
        global_shift_ms: float,
        target_fps: Optional[float] = None,
        source_video: Optional[str] = None,
        target_video: Optional[str] = None,
        runner=None,
        config: Optional[dict] = None,
        temp_dir: Optional[Path] = None,
        **kwargs
    ) -> 'OperationResult':
        """
        Apply video-verified sync to subtitle data.

        Algorithm:
        1. Use audio correlation as starting point (any size)
        2. Generate candidate frame offsets around the correlation value
        3. Test each candidate at multiple checkpoints
        4. Select best matching frame offset
        5. Calculate sub-frame precise offset using PTS timestamps
        6. Apply final offset + global shift to all events

        Args:
            subtitle_data: SubtitleData to modify
            total_delay_ms: Total delay WITH global shift baked in
            global_shift_ms: Global shift that was added
            target_fps: Target video FPS
            source_video: Path to source video
            target_video: Path to target video
            runner: CommandRunner for logging
            config: Settings dict
            temp_dir: Temp directory for index files

        Returns:
            OperationResult with statistics
        """
        from ..data import OperationResult

        config = config or {}

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log(f"[VideoVerified] === Video-Verified Sync Mode ===")
        log(f"[VideoVerified] Events: {len(subtitle_data.events)}")

        if not source_video or not target_video:
            return OperationResult(
                success=False,
                operation='sync',
                error='Both source and target videos required for video-verified mode'
            )

        # Calculate pure correlation for reference
        pure_correlation_ms = total_delay_ms - global_shift_ms

        # Estimate duration from subtitle events if available
        video_duration = None
        if subtitle_data.events:
            video_duration = max(e.end_ms for e in subtitle_data.events) + 60000

        # Use the unified calculate function (handles everything)
        final_offset_ms, details = calculate_video_verified_offset(
            source_video=source_video,
            target_video=target_video,
            total_delay_ms=total_delay_ms,
            global_shift_ms=global_shift_ms,
            config=config,
            runner=runner,
            temp_dir=temp_dir,
            video_duration_ms=video_duration,
        )

        if final_offset_ms is None:
            # Fallback to correlation on error
            final_offset_ms = total_delay_ms
            details['reason'] = details.get('reason', 'fallback-error')

        # Apply the calculated offset
        video_offset_ms = details.get('video_offset_ms', pure_correlation_ms)
        selection_reason = details.get('reason', 'unknown')

        return self._apply_offset(
            subtitle_data, final_offset_ms, global_shift_ms, pure_correlation_ms,
            video_offset_ms, selection_reason, details, runner
        )

    def _apply_offset(
        self,
        subtitle_data: 'SubtitleData',
        final_offset_ms: float,
        global_shift_ms: float,
        audio_correlation_ms: float,
        video_offset_ms: float,
        selection_reason: str,
        details: Dict,
        runner
    ) -> 'OperationResult':
        """Apply the calculated offset to all events."""
        from ..data import OperationResult, OperationRecord, SyncEventData

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log(f"[VideoVerified] Applying {final_offset_ms:+.3f}ms to {len(subtitle_data.events)} events")

        events_synced = 0

        for event in subtitle_data.events:
            if event.is_comment:
                continue

            original_start = event.start_ms
            original_end = event.end_ms

            event.start_ms += final_offset_ms
            event.end_ms += final_offset_ms

            event.sync = SyncEventData(
                original_start_ms=original_start,
                original_end_ms=original_end,
                start_adjustment_ms=final_offset_ms,
                end_adjustment_ms=final_offset_ms,
                snapped_to_frame=False,
            )

            events_synced += 1

        # Build summary
        if abs(video_offset_ms - audio_correlation_ms) > 1.0:
            summary = (f"VideoVerified: {events_synced} events, {final_offset_ms:+.1f}ms "
                      f"(audio={audio_correlation_ms:+.0f}→video={video_offset_ms:+.0f})")
        else:
            summary = f"VideoVerified: {events_synced} events, {final_offset_ms:+.1f}ms"

        # Record operation
        record = OperationRecord(
            operation='sync',
            timestamp=datetime.now(),
            parameters={
                'mode': self.name,
                'final_offset_ms': final_offset_ms,
                'global_shift_ms': global_shift_ms,
                'audio_correlation_ms': audio_correlation_ms,
                'video_offset_ms': video_offset_ms,
                'selection_reason': selection_reason,
            },
            events_affected=events_synced,
            summary=summary
        )
        subtitle_data.operations.append(record)

        log(f"[VideoVerified] Sync complete: {events_synced} events")
        log(f"[VideoVerified] ===================================")

        return OperationResult(
            success=True,
            operation='sync',
            events_affected=events_synced,
            summary=summary,
            details={
                'audio_correlation_ms': audio_correlation_ms,
                'video_offset_ms': video_offset_ms,
                'final_offset_ms': final_offset_ms,
                'selection_reason': selection_reason,
                **details,
            }
        )
