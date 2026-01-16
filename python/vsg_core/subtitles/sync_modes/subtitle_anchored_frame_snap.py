# vsg_core/subtitles/sync_modes/subtitle_anchored_frame_snap.py
# -*- coding: utf-8 -*-
"""
Subtitle-Anchored Frame Snap synchronization mode.

Visual-only sync using subtitle positions as anchors. Does not depend on audio correlation.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Optional
import pysubs2
import math
import gc
from ..metadata_preserver import SubtitleMetadata
from ..checkpoint_selection import select_smart_checkpoints as _select_smart_checkpoints
from ..frame_utils import (
    time_to_frame_floor,
    frame_to_time_floor,
    detect_video_fps
)

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
