# vsg_core/subtitles/sync_modes/correlation_guided_frame_anchor.py
# -*- coding: utf-8 -*-
"""
Correlation-Guided Frame Anchor synchronization mode.

Uses audio correlation to guide frame-based verification with time-based anchors.
Combines the strengths of correlation (guidance) and subtitle-anchor (robust matching).
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Optional
import pysubs2
import math
import gc
from ..metadata_preserver import SubtitleMetadata
from ..frame_utils import (
    time_to_frame_floor,
    frame_to_time_floor,
    detect_video_fps,
    get_vapoursynth_frame_info
)


def _find_matching_frame_for_subtitle(
    source_reader,
    target_reader,
    source_frame: int,
    predicted_target_ms: float,
    target_fps: float,
    window_radius: int,
    hash_size: int,
    hash_algorithm: str,
    hash_threshold: int,
    runner
) -> Optional[int]:
    """
    Find the best matching target frame for a single source frame.

    This is used for per-line refinement to find frame-perfect alignment.

    Args:
        source_reader: VideoReader for source video
        target_reader: VideoReader for target video
        source_frame: Source frame number to match
        predicted_target_ms: Predicted target time in ms (from global offset)
        target_fps: Target video FPS
        window_radius: Frames to search ±center (e.g., 5 = search 11 frames total)
        hash_size: Hash size for perceptual hashing
        hash_algorithm: Hash algorithm ('dhash', 'phash', etc.)
        hash_threshold: Max hamming distance for match
        runner: CommandRunner for logging

    Returns:
        Frame number of best match, or None if no good match found
    """
    from ..frame_matching import compute_frame_hash

    # Get source frame hash
    source_frame_img = source_reader.get_frame_at_index(source_frame)
    if source_frame_img is None:
        return None

    source_hash = compute_frame_hash(source_frame_img, hash_size=hash_size, method=hash_algorithm)
    if source_hash is None:
        return None

    # Calculate search range
    predicted_center_frame = time_to_frame_floor(predicted_target_ms, target_fps)
    search_start_frame = max(0, predicted_center_frame - window_radius)
    search_end_frame = predicted_center_frame + window_radius

    # Find best matching frame
    best_frame = None
    best_distance = float('inf')

    for target_frame in range(search_start_frame, search_end_frame + 1):
        target_frame_img = target_reader.get_frame_at_index(target_frame)
        if target_frame_img is None:
            continue

        target_hash = compute_frame_hash(target_frame_img, hash_size=hash_size, method=hash_algorithm)
        if target_hash is None:
            continue

        distance = source_hash - target_hash

        # If perfect or very close match, use it immediately
        if distance <= hash_threshold and distance < best_distance:
            best_distance = distance
            best_frame = target_frame

            # Perfect match - no need to search further
            if distance == 0:
                break

    # Only return if we found a match within threshold
    if best_frame is not None and best_distance <= hash_threshold:
        return best_frame

    return None


def _process_subtitle_batch(batch_data):
    """
    Process a batch of subtitle events in a separate process.

    This function is at module level (not nested) so it can be pickled
    for multiprocessing.

    Args:
        batch_data: Tuple of (batch_events, batch_start_idx, source_video, target_video,
                             source_fps, target_fps, final_offset_ms, hash_size,
                             hash_algorithm, hash_threshold, temp_dir)

    Returns:
        List of result dictionaries with refined timings
    """
    (batch_events, batch_start_idx, source_video, target_video,
     source_fps, target_fps, final_offset_ms, hash_size,
     hash_algorithm, hash_threshold, temp_dir) = batch_data

    # Each worker needs its own video readers
    # Import here to avoid pickling issues
    from ..frame_matching import VideoReader
    from ..frame_utils import time_to_frame_floor, frame_to_time_floor
    import math

    # Create a minimal runner for this worker (no logging to avoid conflicts)
    class DummyRunner:
        def _log_message(self, msg):
            pass

    dummy_runner = DummyRunner()

    worker_source_reader = VideoReader(source_video, dummy_runner, temp_dir=temp_dir)
    worker_target_reader = VideoReader(target_video, dummy_runner, temp_dir=temp_dir)

    results = []
    for idx, event in enumerate(batch_events):
        original_duration_ms = event.end - event.start
        source_start_frame = time_to_frame_floor(event.start, source_fps)
        predicted_start_ms = event.start + final_offset_ms

        refined_start_frame = _find_matching_frame_for_subtitle(
            source_reader=worker_source_reader,
            target_reader=worker_target_reader,
            source_frame=source_start_frame,
            predicted_target_ms=predicted_start_ms,
            target_fps=target_fps,
            window_radius=5,
            hash_size=hash_size,
            hash_algorithm=hash_algorithm,
            hash_threshold=hash_threshold,
            runner=dummy_runner
        )

        if refined_start_frame is not None:
            refined_start_ms = frame_to_time_floor(refined_start_frame, target_fps)
            correction_ms = refined_start_ms - predicted_start_ms
            refined_end_ms = refined_start_ms + original_duration_ms

            if refined_end_ms > refined_start_ms:
                results.append({
                    'idx': batch_start_idx + idx,
                    'start': int(refined_start_ms),
                    'end': int(refined_end_ms),
                    'refined': True,
                    'correction': abs(correction_ms),
                    'invalid': False
                })
            else:
                results.append({
                    'idx': batch_start_idx + idx,
                    'start': event.start + int(math.floor(final_offset_ms)),
                    'end': event.end + int(math.floor(final_offset_ms)),
                    'refined': False,
                    'correction': 0,
                    'invalid': True
                })
        else:
            results.append({
                'idx': batch_start_idx + idx,
                'start': event.start + int(math.floor(final_offset_ms)),
                'end': event.end + int(math.floor(final_offset_ms)),
                'refined': False,
                'correction': 0,
                'invalid': False
            })

    del worker_source_reader
    del worker_target_reader
    return results


def apply_correlation_guided_frame_anchor_sync(
    subtitle_path: str,
    source_video: str,
    target_video: str,
    total_delay_with_global_ms: float,
    raw_global_shift_ms: float,
    runner,
    config: dict = None,
    temp_dir: Path = None
) -> Dict[str, Any]:
    """
    Correlation-Guided Frame Anchor: Use correlation to guide robust frame matching.

    This mode combines:
    - Correlation baseline (narrows search window)
    - Time-based anchors (deterministic, not subtitle-dependent)
    - Subtitle-anchor's robust sliding window matching
    - 3-checkpoint agreement verification

    Algorithm:
    1. Use correlation to get rough offset baseline
    2. Select 3 time-based anchor points (10%, 50%, 90% of video duration)
    3. For each anchor:
       - Extract 11-frame window from source (center ± 5 frames)
       - Use correlation to predict target position
       - Search ±search_range_ms around prediction
       - Use sliding window matching with aggregate scoring
    4. Verify 3-checkpoint agreement
    5. Calculate final offset: correlation + frame_correction + global_shift

    This mode is ideal when:
    - You want correlation's guidance but need frame-level precision
    - Subtitle positions may be unreliable
    - Videos are similar but with small frame offsets
    - You want fewer false matches than pure subtitle-anchor

    Args:
        subtitle_path: Path to subtitle file (for saving result)
        source_video: Path to source video (where subs were authored)
        target_video: Path to target video (Source 1)
        total_delay_with_global_ms: Total delay from correlation (includes global shift)
        raw_global_shift_ms: Global shift that was applied during analysis
        runner: CommandRunner for logging
        config: Configuration dict with:
            - corr_anchor_search_range_ms: ±search range (default: 2000)
            - corr_anchor_hash_algorithm: 'dhash', 'phash' (default: 'dhash')
            - corr_anchor_hash_size: 8, 16 (default: 8)
            - corr_anchor_hash_threshold: max hamming distance (default: 5)
            - corr_anchor_window_radius: frames around center (default: 5)
            - corr_anchor_agreement_tolerance_ms: checkpoint agreement (default: 100)
            - corr_anchor_fallback_mode: 'abort', 'use-median', 'use-correlation' (default: 'abort')
            - corr_anchor_use_vapoursynth: use VS for extraction (default: True)
            - corr_anchor_anchor_positions: [early%, mid%, late%] (default: [10, 50, 90])
        temp_dir: Job's temporary directory for FFMS2 index storage

    Returns:
        Dict with sync report
    """
    config = config or {}

    # Calculate pure correlation (without global shift)
    pure_correlation_ms = total_delay_with_global_ms - raw_global_shift_ms

    runner._log_message(f"[CorrGuided Anchor] ═══════════════════════════════════════")
    runner._log_message(f"[CorrGuided Anchor] Correlation-Guided Frame Anchor Sync Mode")
    runner._log_message(f"[CorrGuided Anchor] ═══════════════════════════════════════")
    runner._log_message(f"[CorrGuided Anchor] Uses correlation baseline + robust frame matching")

    # Get config parameters
    search_range_ms = config.get('corr_anchor_search_range_ms', 2000)
    hash_algorithm = config.get('corr_anchor_hash_algorithm', 'dhash')
    hash_size = int(config.get('corr_anchor_hash_size', 8))
    hash_threshold = int(config.get('corr_anchor_hash_threshold', 5))
    window_radius = int(config.get('corr_anchor_window_radius', 5))
    tolerance_ms = config.get('corr_anchor_agreement_tolerance_ms', 100)
    fallback_mode = config.get('corr_anchor_fallback_mode', 'abort')
    use_vapoursynth = config.get('corr_anchor_use_vapoursynth', True)
    anchor_positions_pct = config.get('corr_anchor_anchor_positions', [10, 50, 90])

    runner._log_message(f"[CorrGuided Anchor] Configuration:")
    runner._log_message(f"[CorrGuided Anchor]   Correlation baseline: {pure_correlation_ms:+.3f}ms")
    runner._log_message(f"[CorrGuided Anchor]   Global shift: {raw_global_shift_ms:+.3f}ms")
    runner._log_message(f"[CorrGuided Anchor]   Search range: ±{search_range_ms}ms around prediction")
    runner._log_message(f"[CorrGuided Anchor]   Hash: {hash_algorithm}, size={hash_size}, threshold={hash_threshold}")
    runner._log_message(f"[CorrGuided Anchor]   Window radius: {window_radius} frames (={2*window_radius+1} total)")
    runner._log_message(f"[CorrGuided Anchor]   Agreement tolerance: ±{tolerance_ms}ms")
    runner._log_message(f"[CorrGuided Anchor]   Fallback mode: {fallback_mode}")
    runner._log_message(f"[CorrGuided Anchor]   Anchor positions: {anchor_positions_pct}%")

    # Load subtitle file (needed for final save)
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[CorrGuided Anchor] ERROR: Failed to load subtitle file: {e}")
        return {
            'success': False,
            'error': f'Failed to load subtitle file: {e}'
        }

    if not subs.events:
        runner._log_message(f"[CorrGuided Anchor] WARNING: No subtitle events found")
        return {
            'success': True,
            'total_events': 0,
            'final_offset_ms': total_delay_with_global_ms,
            'final_offset_applied': int(math.floor(total_delay_with_global_ms)),
            'warning': 'No subtitle events - applied correlation + global shift only'
        }

    runner._log_message(f"[CorrGuided Anchor] Loaded {len(subs.events)} subtitle events")

    # Get video duration to select anchor points
    source_fps = detect_video_fps(source_video, runner)
    target_fps = detect_video_fps(target_video, runner)
    frame_duration_ms = 1000.0 / source_fps

    runner._log_message(f"[CorrGuided Anchor] Source FPS: {source_fps:.3f}")
    runner._log_message(f"[CorrGuided Anchor] Target FPS: {target_fps:.3f}")

    # Get source video duration
    source_info = get_vapoursynth_frame_info(source_video, runner, temp_dir)
    if source_info:
        source_frame_count, source_duration_ms = source_info
        runner._log_message(f"[CorrGuided Anchor] Source duration: {source_duration_ms:.0f}ms ({source_frame_count} frames)")
    else:
        runner._log_message(f"[CorrGuided Anchor] ERROR: Failed to get source video duration")
        return {
            'success': False,
            'error': 'Failed to get source video duration'
        }

    # Select 3 time-based anchor points
    anchor_times_ms = []
    for pct in anchor_positions_pct:
        anchor_time = (pct / 100.0) * source_duration_ms
        anchor_times_ms.append(anchor_time)

    runner._log_message(f"[CorrGuided Anchor] Selected {len(anchor_times_ms)} time-based anchors:")
    for i, (pct, time_ms) in enumerate(zip(anchor_positions_pct, anchor_times_ms), 1):
        runner._log_message(f"[CorrGuided Anchor]   {i}. {pct}% → {time_ms:.0f}ms")

    # Import frame matching utilities
    try:
        from ..frame_matching import VideoReader, compute_frame_hash
    except ImportError:
        runner._log_message(f"[CorrGuided Anchor] ERROR: frame_matching module not available")
        return {
            'success': False,
            'error': 'frame_matching module not available'
        }

    # Log video paths for debugging
    runner._log_message(f"[CorrGuided Anchor] Source video: {Path(source_video).name}")
    runner._log_message(f"[CorrGuided Anchor] Target video: {Path(target_video).name}")

    # Open video readers
    try:
        source_reader = VideoReader(source_video, runner, temp_dir=temp_dir)
        target_reader = VideoReader(target_video, runner, temp_dir=temp_dir)
    except Exception as e:
        runner._log_message(f"[CorrGuided Anchor] ERROR: Failed to open videos: {e}")
        return {
            'success': False,
            'error': f'Failed to open videos: {e}'
        }

    # Process each anchor point
    measurements = []  # List of precise offset measurements
    checkpoint_details = []
    num_frames_in_window = 2 * window_radius + 1

    for i, anchor_time_ms in enumerate(anchor_times_ms):
        pct = anchor_positions_pct[i]
        runner._log_message(f"[CorrGuided Anchor] ───────────────────────────────────────")
        runner._log_message(f"[CorrGuided Anchor] Checkpoint {i+1}/{len(anchor_times_ms)}: {pct}% @ {anchor_time_ms:.0f}ms")

        # Calculate source frame at this anchor time
        source_center_frame = time_to_frame_floor(anchor_time_ms, source_fps)
        source_frame_start_ms = frame_to_time_floor(source_center_frame, source_fps)

        runner._log_message(f"[CorrGuided Anchor]   Source frame: {source_center_frame} (starts at {source_frame_start_ms:.3f}ms)")

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
            runner._log_message(f"[CorrGuided Anchor]   WARNING: Not enough source frames ({len(source_frame_hashes)}/{num_frames_in_window})")
            checkpoint_details.append({
                'checkpoint_pct': pct,
                'checkpoint_ms': anchor_time_ms,
                'matched': False,
                'error': f'Not enough source frames ({len(source_frame_hashes)}/{num_frames_in_window})'
            })
            continue

        runner._log_message(f"[CorrGuided Anchor]   Extracted {len(source_frame_hashes)} source frames")

        # Step 2: Use correlation to predict target position
        predicted_target_time_ms = anchor_time_ms + pure_correlation_ms
        search_start_ms = max(0, predicted_target_time_ms - search_range_ms)
        search_end_ms = predicted_target_time_ms + search_range_ms

        # Convert to frame numbers
        search_start_frame = time_to_frame_floor(search_start_ms, target_fps)
        search_end_frame = time_to_frame_floor(search_end_ms, target_fps)

        runner._log_message(f"[CorrGuided Anchor]   Correlation predicts: {predicted_target_time_ms:.0f}ms")
        runner._log_message(f"[CorrGuided Anchor]   Searching frames {search_start_frame}-{search_end_frame} ({search_end_frame - search_start_frame + 1} positions)")

        # Track best match
        best_match_frame = None
        best_aggregate_score = -1
        best_matched_count = 0
        best_avg_distance = float('inf')

        # Search every frame in range
        for target_center_frame in range(search_start_frame, search_end_frame + 1):
            # For this candidate, compare all frames in window
            matched_frames = 0
            total_distance = 0
            frames_compared = 0

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

                        if distance <= hash_threshold:
                            matched_frames += 1

                        total_distance += distance

            # Calculate aggregate score
            if frames_compared > 0:
                avg_distance = total_distance / frames_compared

                # Distance from correlation prediction (prefer frames closer to prediction)
                predicted_center_frame = time_to_frame_floor(predicted_target_time_ms, target_fps)
                position_distance = abs(target_center_frame - predicted_center_frame)

                # Multi-tier scoring (same as subtitle-anchor):
                # 1. Matched frames: * 100000
                # 2. Average hash distance: * 10
                # 3. Position proximity to prediction: * 10
                aggregate_score = (matched_frames * 100000) - (avg_distance * 10) - (position_distance * 10)

                if aggregate_score > best_aggregate_score:
                    best_aggregate_score = aggregate_score
                    best_match_frame = target_center_frame
                    best_matched_count = matched_frames
                    best_avg_distance = avg_distance

        # Step 3: Validate match quality
        min_required_matches = int(len(source_frame_hashes) * 0.70)  # 70% threshold

        if best_match_frame is not None and best_matched_count >= min_required_matches:
            # Calculate precise offset (raw, no sub-frame offset needed)
            target_frame_start_ms = frame_to_time_floor(best_match_frame, target_fps)
            precise_offset_ms = target_frame_start_ms - source_frame_start_ms

            match_percent = (best_matched_count / len(source_frame_hashes)) * 100
            measurements.append(precise_offset_ms)

            runner._log_message(f"[CorrGuided Anchor]   ✓ Match found!")
            runner._log_message(f"[CorrGuided Anchor]     Target frame: {best_match_frame} (starts at {target_frame_start_ms:.3f}ms)")
            runner._log_message(f"[CorrGuided Anchor]     Frames matched: {best_matched_count}/{len(source_frame_hashes)} ({match_percent:.0f}%)")
            runner._log_message(f"[CorrGuided Anchor]     Average distance: {best_avg_distance:.1f}")
            runner._log_message(f"[CorrGuided Anchor]     Precise offset: {precise_offset_ms:+.3f}ms")

            checkpoint_details.append({
                'checkpoint_pct': pct,
                'checkpoint_ms': anchor_time_ms,
                'source_frame': source_center_frame,
                'target_frame': best_match_frame,
                'precise_offset_ms': precise_offset_ms,
                'matched_frames': best_matched_count,
                'total_frames': len(source_frame_hashes),
                'match_percent': match_percent,
                'avg_distance': best_avg_distance,
                'matched': True
            })
        else:
            match_percent = (best_matched_count / len(source_frame_hashes) * 100) if best_matched_count > 0 else 0
            runner._log_message(f"[CorrGuided Anchor]   ✗ No good match found")
            runner._log_message(f"[CorrGuided Anchor]     Best: {best_matched_count}/{len(source_frame_hashes)} ({match_percent:.0f}%)")
            runner._log_message(f"[CorrGuided Anchor]     Required: {min_required_matches} (70%)")

            checkpoint_details.append({
                'checkpoint_pct': pct,
                'checkpoint_ms': anchor_time_ms,
                'matched': False,
                'best_matched': best_matched_count,
                'required': min_required_matches,
                'match_percent': match_percent
            })

    # Clean up video readers
    del source_reader
    del target_reader
    gc.collect()

    runner._log_message(f"[CorrGuided Anchor] ───────────────────────────────────────")
    runner._log_message(f"[CorrGuided Anchor] Results Summary")
    runner._log_message(f"[CorrGuided Anchor] ───────────────────────────────────────")

    # Initialize variables for result reporting
    median_offset = 0.0
    max_deviation = 0.0
    frame_correction = 0.0

    # Check results
    if len(measurements) == 0:
        runner._log_message(f"[CorrGuided Anchor] ERROR: No checkpoints matched successfully")
        if fallback_mode == 'abort':
            return {
                'success': False,
                'error': 'No checkpoints matched - cannot determine sync offset',
                'checkpoints': checkpoint_details
            }
        elif fallback_mode == 'use-correlation':
            runner._log_message(f"[CorrGuided Anchor] Fallback: Using correlation offset only")
            final_offset_ms = total_delay_with_global_ms
        else:  # 'use-median' with no measurements - use correlation
            runner._log_message(f"[CorrGuided Anchor] Fallback: Using correlation offset only")
            final_offset_ms = total_delay_with_global_ms

    elif len(measurements) == 1:
        # Only one checkpoint - use it but warn
        runner._log_message(f"[CorrGuided Anchor] WARNING: Only 1 checkpoint matched (cannot verify agreement)")
        runner._log_message(f"[CorrGuided Anchor] Using single measurement: {measurements[0]:+.3f}ms")
        frame_correction = measurements[0] - pure_correlation_ms
        final_offset_ms = measurements[0] + raw_global_shift_ms

    else:
        # Multiple measurements - check agreement
        median_offset = sorted(measurements)[len(measurements) // 2]
        max_deviation = max(abs(m - median_offset) for m in measurements)

        runner._log_message(f"[CorrGuided Anchor] Measurements: {[f'{m:+.1f}ms' for m in measurements]}")
        runner._log_message(f"[CorrGuided Anchor] Median: {median_offset:+.3f}ms")
        runner._log_message(f"[CorrGuided Anchor] Max deviation: {max_deviation:.1f}ms")

        if max_deviation <= tolerance_ms:
            runner._log_message(f"[CorrGuided Anchor] ✓ Checkpoints AGREE within ±{tolerance_ms}ms")
            frame_correction = median_offset - pure_correlation_ms
            final_offset_ms = median_offset + raw_global_shift_ms
        else:
            runner._log_message(f"[CorrGuided Anchor] ⚠ Checkpoints DISAGREE (max deviation: {max_deviation:.1f}ms > {tolerance_ms}ms)")

            if fallback_mode == 'abort':
                return {
                    'success': False,
                    'error': f'Checkpoints disagree: max deviation {max_deviation:.1f}ms > {tolerance_ms}ms tolerance',
                    'measurements': measurements,
                    'checkpoints': checkpoint_details
                }
            elif fallback_mode == 'use-correlation':
                runner._log_message(f"[CorrGuided Anchor] Fallback: Using correlation offset")
                final_offset_ms = total_delay_with_global_ms
            else:  # 'use-median'
                runner._log_message(f"[CorrGuided Anchor] Fallback: Using median offset anyway")
                frame_correction = median_offset - pure_correlation_ms
                final_offset_ms = median_offset + raw_global_shift_ms

    runner._log_message(f"[CorrGuided Anchor] ───────────────────────────────────────")
    runner._log_message(f"[CorrGuided Anchor] Final offset calculation:")
    runner._log_message(f"[CorrGuided Anchor]   Pure correlation:    {pure_correlation_ms:+.3f}ms")
    if len(measurements) > 0:
        runner._log_message(f"[CorrGuided Anchor]   Frame correction:    {frame_correction:+.3f}ms")
    runner._log_message(f"[CorrGuided Anchor]   + Global shift:      {raw_global_shift_ms:+.3f}ms")
    runner._log_message(f"[CorrGuided Anchor]   ─────────────────────────────────────")
    runner._log_message(f"[CorrGuided Anchor]   = FINAL offset:      {final_offset_ms:+.3f}ms")

    # Calculate final_offset_int for reporting (used even if refinement applies individual offsets)
    final_offset_int = int(math.floor(final_offset_ms))

    # Check if per-line refinement is enabled
    refine_per_line = config.get('corr_anchor_refine_per_line', False)

    if refine_per_line and len(measurements) > 0:
        runner._log_message(f"[CorrGuided Anchor] ───────────────────────────────────────")
        runner._log_message(f"[CorrGuided Anchor] Per-Line Frame Refinement ENABLED")
        runner._log_message(f"[CorrGuided Anchor] Refining each subtitle to exact frames...")

        # Re-open video readers for refinement
        try:
            source_reader = VideoReader(source_video, runner, temp_dir=temp_dir)
            target_reader = VideoReader(target_video, runner, temp_dir=temp_dir)
        except Exception as e:
            runner._log_message(f"[CorrGuided Anchor] WARNING: Failed to reopen videos for refinement: {e}")
            runner._log_message(f"[CorrGuided Anchor] Falling back to global offset for all lines")
            refine_per_line = False

        if refine_per_line:
            # Get worker count for parallelization
            num_workers = int(config.get('corr_anchor_refine_workers', 4))
            num_workers = max(1, min(num_workers, 16))  # Clamp to 1-16

            runner._log_message(f"[CorrGuided Anchor] Using {num_workers} worker(s) for parallel processing")

            # Statistics tracking
            refinement_stats = {
                'total_lines': 0,
                'refined': 0,
                'fallback': 0,
                'corrections': [],
                'invalid_prevented': 0
            }

            # Calculate progress milestones (percentage-based)
            total_events = len(subs.events)
            milestones = {int(total_events * pct / 100) for pct in [10, 25, 50, 75, 90, 100]}

            if num_workers == 1:
                # Sequential processing (simpler, easier to debug)
                for idx, event in enumerate(subs.events):
                    refinement_stats['total_lines'] += 1

                    # Progress reporting at percentage milestones
                    if (idx + 1) in milestones:
                        progress_pct = ((idx + 1) / total_events) * 100
                        runner._log_message(f"[CorrGuided Anchor] Progress: {progress_pct:.0f}% ({idx + 1}/{total_events} lines)")

                    # Store original duration (authoring intent - doesn't change)
                    original_duration_ms = event.end - event.start

                    # --- REFINE START TIME ONLY ---
                    source_start_frame = time_to_frame_floor(event.start, source_fps)
                    predicted_start_ms = event.start + final_offset_ms

                    refined_start_frame = _find_matching_frame_for_subtitle(
                        source_reader=source_reader,
                        target_reader=target_reader,
                        source_frame=source_start_frame,
                        predicted_target_ms=predicted_start_ms,
                        target_fps=target_fps,
                        window_radius=5,
                        hash_size=hash_size,
                        hash_algorithm=hash_algorithm,
                        hash_threshold=hash_threshold,
                        runner=runner
                    )

                    if refined_start_frame is not None:
                        # Use exact frame timing for start
                        refined_start_ms = frame_to_time_floor(refined_start_frame, target_fps)
                        correction_ms = refined_start_ms - predicted_start_ms
                        refinement_stats['corrections'].append(abs(correction_ms))

                        # Calculate end by preserving original duration
                        refined_end_ms = refined_start_ms + original_duration_ms

                        # Validate: ensure end > start (should always be true since duration is positive)
                        if refined_end_ms > refined_start_ms:
                            event.start = int(refined_start_ms)
                            event.end = int(refined_end_ms)
                            refinement_stats['refined'] += 1
                        else:
                            # Shouldn't happen, but fall back to global offset
                            event.start += int(math.floor(final_offset_ms))
                            event.end += int(math.floor(final_offset_ms))
                            refinement_stats['fallback'] += 1
                            refinement_stats['invalid_prevented'] += 1
                    else:
                        # Fall back to global offset for both start and end
                        event.start += int(math.floor(final_offset_ms))
                        event.end += int(math.floor(final_offset_ms))
                        refinement_stats['fallback'] += 1
            else:
                # Parallel processing using ProcessPoolExecutor
                from concurrent.futures import ProcessPoolExecutor

                # Prepare batches for parallel processing
                batch_size = max(10, len(subs.events) // (num_workers * 4))  # 4 batches per worker
                batches = [subs.events[i:i+batch_size] for i in range(0, len(subs.events), batch_size)]

                runner._log_message(f"[CorrGuided Anchor] Processing {len(subs.events)} lines in {len(batches)} batches")

                # Track progress across batches
                completed_lines = 0

                # Create batch data with all required parameters
                # Format: (batch_events, batch_start_idx, source_video, target_video,
                #          source_fps, target_fps, final_offset_ms, hash_size,
                #          hash_algorithm, hash_threshold, temp_dir)
                batch_data = [
                    (batch, i * batch_size, source_video, target_video,
                     source_fps, target_fps, final_offset_ms, hash_size,
                     hash_algorithm, hash_threshold, temp_dir)
                    for i, batch in enumerate(batches)
                ]

                # Process batches in parallel
                with ProcessPoolExecutor(max_workers=num_workers) as executor:
                    for batch_results in executor.map(_process_subtitle_batch, batch_data):
                        # Apply results to subtitle events
                        for result in batch_results:
                            subs.events[result['idx']].start = result['start']
                            subs.events[result['idx']].end = result['end']

                            refinement_stats['total_lines'] += 1
                            if result['refined']:
                                refinement_stats['refined'] += 1
                                refinement_stats['corrections'].append(result['correction'])
                            else:
                                refinement_stats['fallback'] += 1
                            if result['invalid']:
                                refinement_stats['invalid_prevented'] += 1

                            completed_lines += 1

                            # Progress reporting
                            if completed_lines in milestones:
                                progress_pct = (completed_lines / total_events) * 100
                                runner._log_message(f"[CorrGuided Anchor] Progress: {progress_pct:.0f}% ({completed_lines}/{total_events} lines)")

            # Clean up video readers (only if sequential)
            if num_workers == 1:
                del source_reader
                del target_reader
            gc.collect()

            # Report statistics
            success_rate = (refinement_stats['refined'] / refinement_stats['total_lines'] * 100) if refinement_stats['total_lines'] > 0 else 0

            avg_correction = sum(refinement_stats['corrections']) / len(refinement_stats['corrections']) if refinement_stats['corrections'] else 0
            max_correction = max(refinement_stats['corrections']) if refinement_stats['corrections'] else 0

            runner._log_message(f"[CorrGuided Anchor] ───────────────────────────────────────")
            runner._log_message(f"[CorrGuided Anchor] Refinement Statistics:")
            runner._log_message(f"[CorrGuided Anchor]   Total subtitle lines: {refinement_stats['total_lines']}")
            runner._log_message(f"[CorrGuided Anchor]   Start times refined: {refinement_stats['refined']}/{refinement_stats['total_lines']} ({success_rate:.1f}%)")
            runner._log_message(f"[CorrGuided Anchor]   Fallback to global: {refinement_stats['fallback']}/{refinement_stats['total_lines']} ({refinement_stats['fallback']/refinement_stats['total_lines']*100:.1f}%)")
            if refinement_stats['invalid_prevented'] > 0:
                runner._log_message(f"[CorrGuided Anchor]   Invalid timings prevented: {refinement_stats['invalid_prevented']}")
            runner._log_message(f"[CorrGuided Anchor]   Average correction: {avg_correction:.1f}ms")
            runner._log_message(f"[CorrGuided Anchor]   Max correction: {max_correction:.1f}ms")
            runner._log_message(f"[CorrGuided Anchor] ───────────────────────────────────────")
    else:
        # Capture original metadata
        metadata = SubtitleMetadata(subtitle_path)
        metadata.capture()

        # Apply offset to all subtitle events using FLOOR for final rounding
        runner._log_message(f"[CorrGuided Anchor] Applying offset to {len(subs.events)} events (floor: {final_offset_int}ms)")

        for event in subs.events:
            event.start += final_offset_int
            event.end += final_offset_int

    # Capture original metadata (if not already done during non-refinement path)
    if refine_per_line and len(measurements) > 0:
        metadata = SubtitleMetadata(subtitle_path)
        metadata.capture()
    elif 'metadata' not in locals():
        # Metadata wasn't captured yet (edge case)
        metadata = SubtitleMetadata(subtitle_path)
        metadata.capture()

    # Save modified subtitle
    runner._log_message(f"[CorrGuided Anchor] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[CorrGuided Anchor] ERROR: Failed to save subtitle file: {e}")
        return {
            'success': False,
            'error': f'Failed to save subtitle file: {e}',
            'checkpoints': checkpoint_details
        }

    # Validate and restore metadata
    # For refinement mode, we can't specify expected_delay since each line is different
    if refine_per_line and len(measurements) > 0:
        metadata.validate_and_restore(runner, expected_delay_ms=None)
    else:
        metadata.validate_and_restore(runner, expected_delay_ms=final_offset_int)

    runner._log_message(f"[CorrGuided Anchor] Successfully synchronized {len(subs.events)} events")
    runner._log_message(f"[CorrGuided Anchor] ═══════════════════════════════════════")

    # Flush logs to ensure subtitle sync phase is fully written before next phase
    import logging
    logger = logging.getLogger('vsg_job')
    for handler in logger.handlers:
        handler.flush()

    verification_result = {
        'valid': len(measurements) >= 2 and max_deviation <= tolerance_ms if len(measurements) >= 2 else len(measurements) == 1,
        'num_checkpoints_matched': len(measurements),
        'num_checkpoints_total': len(anchor_times_ms),
        'max_deviation_ms': max_deviation if len(measurements) >= 2 else 0,
        'measurements': measurements
    }

    return {
        'success': True,
        'total_events': len(subs.events),
        'final_offset_ms': final_offset_ms,
        'final_offset_applied': final_offset_int,
        'global_shift_ms': raw_global_shift_ms,
        'pure_correlation_ms': pure_correlation_ms,
        'frame_correction_ms': frame_correction if len(measurements) > 0 else 0,
        'frame_match_offset_ms': median_offset if len(measurements) >= 2 else (measurements[0] if measurements else 0),
        'source_fps': source_fps,
        'target_fps': target_fps,
        'frame_duration_ms': frame_duration_ms,
        'checkpoints': checkpoint_details,
        'verification': verification_result
    }
