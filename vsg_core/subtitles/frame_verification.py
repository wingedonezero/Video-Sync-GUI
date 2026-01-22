# vsg_core/subtitles/frame_verification.py
# -*- coding: utf-8 -*-
"""
Frame verification utilities for subtitle synchronization.

Contains verification functions used by sync mode plugins for
validating frame alignment between source and target videos.
"""
from __future__ import annotations
from typing import List, Dict, Any
import gc


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

    Uses sliding window scene alignment to verify correlation-based offsets.

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
            - frame_delta: int (best frame adjustment: -1, 0, or +1)
            - frame_correction_ms: float (PRECISE ms refinement from anchor frames)
            - num_scene_matches: int (number of scene checkpoints that matched)
    """
    from .frame_utils import detect_scene_changes

    config = config or {}

    runner._log_message(f"[Correlation+FrameSnap] ═══════════════════════════════════════")
    runner._log_message(f"[Correlation+FrameSnap] Verifying frame alignment...")
    runner._log_message(f"[Correlation+FrameSnap] Pure correlation delay: {pure_correlation_delay_ms:+.3f}ms")

    frame_duration_ms = 1000.0 / fps
    runner._log_message(f"[Correlation+FrameSnap] FPS: {fps:.3f} → frame duration: {frame_duration_ms:.3f}ms")

    # Get config parameters (unified settings with fallback)
    hash_algorithm = config.get('frame_hash_algorithm', config.get('correlation_snap_hash_algorithm', 'dhash'))
    hash_size = int(config.get('frame_hash_size', config.get('correlation_snap_hash_size', 8)))
    hash_threshold = int(config.get('frame_hash_threshold', config.get('correlation_snap_hash_threshold', 5)))
    window_radius = int(config.get('frame_window_radius', config.get('correlation_snap_window_radius', 3)))
    search_range_frames = int(config.get('correlation_snap_search_range', 5))

    runner._log_message(f"[Correlation+FrameSnap] Hash: {hash_algorithm}, size={hash_size}, threshold={hash_threshold}")

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

    use_scene_checkpoints = config.get('correlation_snap_use_scene_changes', True)
    refinements_ms = []

    if use_scene_checkpoints:
        runner._log_message(f"[Correlation+FrameSnap] Sliding Window Scene Alignment")
        runner._log_message(f"[Correlation+FrameSnap] Window: {window_radius*2+1} frames, Search: ±{search_range_frames} frames")

        start_frame = int(min_sub_time * fps / 1000.0)
        end_frame = int(max_sub_time * fps / 1000.0)

        runner._log_message(f"[Correlation+FrameSnap] Detecting scene changes in SOURCE video...")
        source_scene_frames = detect_scene_changes(source_video, start_frame, end_frame, runner, max_scenes=5)

        if source_scene_frames:
            runner._log_message(f"[Correlation+FrameSnap] Found {len(source_scene_frames)} scene anchors")

            source_reader = None
            target_reader = None
            try:
                use_vs = config.get('frame_use_vapoursynth', True)
                source_reader = VideoReader(source_video, runner, use_vapoursynth=use_vs)
                target_reader = VideoReader(target_video, runner, use_vapoursynth=use_vs)
            except Exception as e:
                runner._log_message(f"[Correlation+FrameSnap] ERROR: Failed to open videos: {e}")
                if source_reader:
                    source_reader.close()
                return {
                    'valid': False,
                    'error': f'Failed to open videos: {e}',
                    'frame_delta': 0,
                    'frame_correction_ms': 0.0
                }

            for scene_idx, center_frame in enumerate(source_scene_frames[:3]):
                runner._log_message(f"[Correlation+FrameSnap] Scene {scene_idx+1}: frame {center_frame}")

                center_time_ms = center_frame * 1000.0 / fps
                source_window_frames = list(range(center_frame - window_radius, center_frame + window_radius + 1))

                if source_window_frames[0] < 0:
                    continue

                # Compute source window hashes
                source_hashes = []
                source_valid = True
                for sf in source_window_frames:
                    img = source_reader.get_frame_at_index(sf)
                    if img is None:
                        source_valid = False
                        break
                    h = compute_frame_hash(img, hash_size=hash_size, method=hash_algorithm)
                    if h is None:
                        source_valid = False
                        break
                    source_hashes.append(h)

                if not source_valid:
                    continue

                # Search for best match in target
                predicted_target_center_time_ms = center_time_ms + pure_correlation_delay_ms
                predicted_target_center_frame = int(predicted_target_center_time_ms * fps / 1000.0)

                search_start = max(window_radius, predicted_target_center_frame - search_range_frames)
                search_end = predicted_target_center_frame + search_range_frames

                best_offset_frames = 0
                best_total_distance = float('inf')
                best_matched_center = predicted_target_center_frame

                for target_center in range(search_start, search_end + 1):
                    target_window_frames = list(range(target_center - window_radius, target_center + window_radius + 1))

                    target_hashes = []
                    target_valid = True
                    for tf in target_window_frames:
                        if tf < 0:
                            target_valid = False
                            break
                        img = target_reader.get_frame_at_index(tf)
                        if img is None:
                            target_valid = False
                            break
                        h = compute_frame_hash(img, hash_size=hash_size, method=hash_algorithm)
                        if h is None:
                            target_valid = False
                            break
                        target_hashes.append(h)

                    if not target_valid:
                        continue

                    total_distance = sum(sh - th for sh, th in zip(source_hashes, target_hashes))

                    if total_distance < best_total_distance:
                        best_total_distance = total_distance
                        best_offset_frames = target_center - predicted_target_center_frame
                        best_matched_center = target_center

                # Calculate refinement
                matched_center_time_ms = best_matched_center * 1000.0 / fps
                actual_offset_ms = matched_center_time_ms - center_time_ms
                refinement_ms = actual_offset_ms - pure_correlation_delay_ms

                avg_frame_distance = best_total_distance / (window_radius * 2 + 1)
                if avg_frame_distance <= hash_threshold * 2:
                    refinements_ms.append(refinement_ms)
                    runner._log_message(f"[Correlation+FrameSnap]   Refinement: {refinement_ms:+.3f}ms (GOOD)")
                else:
                    runner._log_message(f"[Correlation+FrameSnap]   Match quality POOR - skipping")

            source_reader.close()
            target_reader.close()
            del source_reader
            del target_reader
            gc.collect()
        else:
            runner._log_message(f"[Correlation+FrameSnap] No scene changes detected")

    # Calculate final correction
    if refinements_ms and len(refinements_ms) >= 2:
        min_ref = min(refinements_ms)
        max_ref = max(refinements_ms)
        spread = max_ref - min_ref

        if spread <= frame_duration_ms:
            frame_correction_ms = sum(refinements_ms) / len(refinements_ms)
            runner._log_message(f"[Correlation+FrameSnap] Checkpoints AGREE: {frame_correction_ms:+.3f}ms")
            valid = True
        else:
            sorted_refs = sorted(refinements_ms)
            frame_correction_ms = sorted_refs[len(sorted_refs) // 2]
            runner._log_message(f"[Correlation+FrameSnap] Checkpoints DISAGREE, using median: {frame_correction_ms:+.3f}ms")
            valid = False
    elif refinements_ms and len(refinements_ms) == 1:
        frame_correction_ms = refinements_ms[0]
        runner._log_message(f"[Correlation+FrameSnap] Only 1 match: {frame_correction_ms:+.3f}ms")
        valid = False
    else:
        frame_correction_ms = 0.0
        runner._log_message(f"[Correlation+FrameSnap] No matches, trusting correlation")
        valid = False

    frame_delta = round(frame_correction_ms / frame_duration_ms) if frame_duration_ms > 0 else 0

    return {
        'valid': valid,
        'frame_delta': frame_delta,
        'frame_correction_ms': frame_correction_ms,
        'scene_refinements_ms': refinements_ms,
        'num_scene_matches': len(refinements_ms),
    }


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

    Args:
        source_video: Path to source video
        target_video: Path to target video
        subtitle_events: List of subtitle events
        duration_offset_ms: Rough offset from duration calculation
        runner: CommandRunner for logging
        config: Config dict

    Returns:
        Dict with:
            - enabled: bool (whether verification ran)
            - valid: bool (whether measurements agree)
            - precise_offset_ms: float (median of measurements if valid)
            - measurements: List[float] (individual measurements)
            - duration_offset_ms: float (original duration offset)
    """
    from .checkpoint_selection import select_smart_checkpoints

    config = config or {}

    runner._log_message(f"[Hybrid Verification] ═══════════════════════════════════════")
    runner._log_message(f"[Hybrid Verification] Running TEMPORAL CONSISTENCY verification...")
    runner._log_message(f"[Hybrid Verification] Duration offset (rough): {duration_offset_ms:+.3f}ms")

    # Get config parameters (unified settings with fallback)
    search_window_ms = config.get('frame_search_range_ms', config.get('duration_align_verify_search_window_ms', 2000))
    tolerance_ms = config.get('frame_agreement_tolerance_ms', config.get('duration_align_verify_agreement_tolerance_ms', 100))
    hash_algorithm = config.get('frame_hash_algorithm', config.get('duration_align_hash_algorithm', 'dhash'))
    hash_size = int(config.get('frame_hash_size', config.get('duration_align_hash_size', 8)))
    hash_threshold = int(config.get('frame_hash_threshold', config.get('duration_align_hash_threshold', 5)))

    runner._log_message(f"[Hybrid Verification] Search window: ±{search_window_ms}ms")
    runner._log_message(f"[Hybrid Verification] Agreement tolerance: ±{tolerance_ms}ms")
    runner._log_message(f"[Hybrid Verification] Hash: {hash_algorithm}, size={hash_size}, threshold={hash_threshold}")

    checkpoints = select_smart_checkpoints(subtitle_events, runner)

    if len(checkpoints) == 0:
        runner._log_message(f"[Hybrid Verification] ERROR: No valid checkpoints found")
        return {
            'enabled': True,
            'valid': False,
            'error': 'No valid checkpoints for verification',
            'measurements': [],
            'duration_offset_ms': duration_offset_ms
        }

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

    try:
        use_vs = config.get('frame_use_vapoursynth', True)
        source_reader = VideoReader(source_video, runner, use_vapoursynth=use_vs)
        target_reader = VideoReader(target_video, runner, use_vapoursynth=use_vs)
    except Exception as e:
        runner._log_message(f"[Hybrid Verification] ERROR: Failed to open videos: {e}")
        return {
            'enabled': True,
            'valid': False,
            'error': f'Failed to open videos: {e}',
            'measurements': [],
            'duration_offset_ms': duration_offset_ms
        }

    fps = source_reader.fps or 23.976
    frame_duration_ms = 1000.0 / fps
    num_frames = 11  # center ± 5

    for i, event in enumerate(checkpoints):
        checkpoint_time_ms = event.start
        runner._log_message(f"[Hybrid Verification] Checkpoint {i+1}/{len(checkpoints)}: {checkpoint_time_ms}ms")

        # Extract source frame hashes
        source_frame_hashes = []
        for offset in range(-5, 6):
            frame_time_ms = checkpoint_time_ms + (offset * frame_duration_ms)
            frame = source_reader.get_frame_at_time(int(frame_time_ms))
            if frame is not None:
                frame_hash = compute_frame_hash(frame, hash_size=hash_size, method=hash_algorithm)
                if frame_hash is not None:
                    source_frame_hashes.append((offset, frame_hash))

        if len(source_frame_hashes) < 8:
            runner._log_message(f"[Hybrid Verification] WARNING: Not enough source frames ({len(source_frame_hashes)}/11)")
            continue

        # Sliding window search
        search_center_ms = checkpoint_time_ms + duration_offset_ms
        search_start_ms = search_center_ms - search_window_ms
        search_end_ms = search_center_ms + search_window_ms

        best_match_offset = None
        best_aggregate_score = -1
        best_matched_frames = 0

        search_step_ms = 5 * frame_duration_ms
        current_search_ms = search_start_ms

        while current_search_ms <= search_end_ms:
            matched_frames = 0
            total_distance = 0

            for offset, source_hash in source_frame_hashes:
                target_time_ms = current_search_ms + (offset * frame_duration_ms)
                target_frame = target_reader.get_frame_at_time(int(target_time_ms))

                if target_frame is not None:
                    target_hash = compute_frame_hash(target_frame, hash_size=hash_size, method=hash_algorithm)
                    if target_hash is not None:
                        distance = source_hash - target_hash
                        if distance <= hash_threshold:
                            matched_frames += 1
                        total_distance += distance

            if len(source_frame_hashes) > 0:
                avg_distance = total_distance / len(source_frame_hashes)
                aggregate_score = (matched_frames * 1000) - avg_distance

                if aggregate_score > best_aggregate_score:
                    best_aggregate_score = aggregate_score
                    best_match_offset = current_search_ms - checkpoint_time_ms
                    best_matched_frames = matched_frames

            current_search_ms += search_step_ms

        min_required_matches = int(len(source_frame_hashes) * 0.70)

        if best_match_offset is not None and best_matched_frames >= min_required_matches:
            match_percent = (best_matched_frames / len(source_frame_hashes)) * 100
            measurements.append(best_match_offset)
            runner._log_message(f"[Hybrid Verification]   ✓ Match: offset={best_match_offset:+.1f}ms ({match_percent:.0f}%)")
            checkpoint_details.append({
                'checkpoint_ms': checkpoint_time_ms,
                'offset_ms': best_match_offset,
                'match_percent': match_percent,
                'matched': True
            })
        else:
            match_percent = (best_matched_frames / len(source_frame_hashes) * 100) if best_matched_frames else 0
            runner._log_message(f"[Hybrid Verification]   ✗ No temporal consistency ({match_percent:.0f}%)")
            checkpoint_details.append({
                'checkpoint_ms': checkpoint_time_ms,
                'offset_ms': best_match_offset,
                'match_percent': match_percent,
                'matched': False
            })

    del source_reader
    del target_reader
    gc.collect()

    if len(measurements) < 2:
        runner._log_message(f"[Hybrid Verification] FAILED: Not enough measurements ({len(measurements)}/2)")
        return {
            'enabled': True,
            'valid': False,
            'measurements': measurements,
            'duration_offset_ms': duration_offset_ms,
            'checkpoints': checkpoint_details,
            'error': 'Not enough successful measurements'
        }

    median_offset = sorted(measurements)[len(measurements) // 2]
    max_deviation = max(abs(m - median_offset) for m in measurements)

    runner._log_message(f"[Hybrid Verification] Measurements: {[f'{m:+.1f}ms' for m in measurements]}")
    runner._log_message(f"[Hybrid Verification] Median offset: {median_offset:+.1f}ms")
    runner._log_message(f"[Hybrid Verification] Max deviation: {max_deviation:.1f}ms")

    if max_deviation <= tolerance_ms:
        runner._log_message(f"[Hybrid Verification] ✓ PASS: Measurements agree within ±{tolerance_ms}ms")
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
        runner._log_message(f"[Hybrid Verification] ✗ FAIL: Measurements disagree (deviation: {max_deviation:.1f}ms)")
        return {
            'enabled': True,
            'valid': False,
            'precise_offset_ms': median_offset,
            'measurements': measurements,
            'duration_offset_ms': duration_offset_ms,
            'max_deviation_ms': max_deviation,
            'checkpoints': checkpoint_details,
            'error': 'Measurements disagree'
        }
