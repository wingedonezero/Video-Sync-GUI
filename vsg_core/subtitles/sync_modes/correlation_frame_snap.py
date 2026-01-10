# vsg_core/subtitles/sync_modes/correlation_frame_snap.py
# -*- coding: utf-8 -*-
"""
Correlation + Frame Snap subtitle synchronization mode.

Uses audio correlation as guide, then verifies frame alignment with scene detection
and sliding window matching.
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
    detect_scene_changes,
    detect_video_properties,
    compare_video_properties
)

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

