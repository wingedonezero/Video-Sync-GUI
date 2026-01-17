# vsg_core/subtitles/sync_modes/duration_align.py
# -*- coding: utf-8 -*-
"""
Duration-align subtitle synchronization mode.

Aligns subtitles by total video duration difference (frame alignment).
Optionally verifies alignment using hybrid frame matching.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Optional
import pysubs2
import gc
from ..metadata_preserver import SubtitleMetadata
from ..checkpoint_selection import select_smart_checkpoints as _select_smart_checkpoints
from ..frame_utils import (
    get_vapoursynth_frame_info,
    detect_video_fps,
    frame_to_time_vfr,
    validate_frame_alignment
)

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
    config: dict = None,
    temp_dir: Optional[Path] = None
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
        temp_dir: Optional job temp directory for FFMS2 index storage

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
        source_info = get_vapoursynth_frame_info(source_video, runner, temp_dir)
        if source_info:
            source_frame_count, source_duration_ms = source_info
        else:
            runner._log_message(f"[Duration Align] VapourSynth failed for source, falling back to ffprobe")

        # Get target video info
        target_info = get_vapoursynth_frame_info(target_video, runner, temp_dir)
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
            # Import GPU environment support
            try:
                from vsg_core.system.gpu_env import get_subprocess_environment
                env = get_subprocess_environment()
            except ImportError:
                import os
                env = os.environ.copy()

            # Get source video frame count
            cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                   '-show_entries', 'stream=nb_read_frames', '-print_format', 'json', source_video]
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            source_info = json.loads(result.stdout)
            source_frame_count = int(source_info['streams'][0]['nb_read_frames'])

            # Get target video frame count
            cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                   '-show_entries', 'stream=nb_read_frames', '-print_format', 'json', target_video]
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
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
            config,
            temp_dir
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
