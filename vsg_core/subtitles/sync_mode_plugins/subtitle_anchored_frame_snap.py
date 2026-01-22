# vsg_core/subtitles/sync_mode_plugins/subtitle_anchored_frame_snap.py
# -*- coding: utf-8 -*-
"""
Subtitle-Anchored Frame Snap sync plugin for SubtitleData.

Visual-only sync using subtitle positions as anchors. Uses subtitle start times
to find matching frames via perceptual hashing, without audio correlation.

All timing is float ms internally - rounding happens only at final save.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from ..sync_modes import SyncPlugin, register_sync_plugin

if TYPE_CHECKING:
    from ..data import SubtitleData, OperationResult, OperationRecord, SyncEventData


@register_sync_plugin
class SubtitleAnchoredFrameSnapSync(SyncPlugin):
    """
    Subtitle-Anchored Frame Snap sync mode.

    Visual-only sync using subtitle positions as anchors.
    """

    name = 'subtitle-anchored-frame-snap'
    description = 'Visual-only sync using subtitle positions as anchors'

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
        Apply subtitle-anchored frame snap sync to subtitle data.

        Algorithm:
        1. Select 3 dialogue events as checkpoints (avoiding OP/ED)
        2. For each checkpoint, match source frame to target frame via hashing
        3. Calculate precise offset from verified frame times
        4. Apply offset to all events

        Args:
            subtitle_data: SubtitleData to modify
            total_delay_ms: Total delay (not used - calculated from frame matching)
            global_shift_ms: Global shift from delays
            target_fps: Target video FPS
            source_video: Path to source video
            target_video: Path to target video
            runner: CommandRunner for logging
            config: Settings dict
            temp_dir: Temp directory for index files

        Returns:
            OperationResult with statistics
        """
        from ..data import OperationResult, OperationRecord, SyncEventData
        from ..frame_utils import detect_video_fps
        from ..checkpoint_selection import select_smart_checkpoints

        config = config or {}

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log(f"[SubAnchor] === Subtitle-Anchored Frame Snap Sync ===")
        log(f"[SubAnchor] Events: {len(subtitle_data.events)}")

        if not source_video or not target_video:
            return OperationResult(
                success=False,
                operation='sync',
                error='Both source and target videos required for subtitle-anchored-frame-snap'
            )

        log(f"[SubAnchor] Source: {Path(source_video).name}")
        log(f"[SubAnchor] Target: {Path(target_video).name}")
        log(f"[SubAnchor] Global shift: {global_shift_ms:+.3f}ms")

        # Detect FPS
        fps = target_fps or detect_video_fps(source_video, runner)
        if not fps:
            fps = 23.976
            log(f"[SubAnchor] FPS detection failed, using default: {fps}")

        frame_duration_ms = 1000.0 / fps
        log(f"[SubAnchor] FPS: {fps:.3f} (frame: {frame_duration_ms:.3f}ms)")

        # Get config parameters (unified settings with fallback to mode-specific)
        search_range_ms = config.get('frame_search_range_ms', config.get('sub_anchor_search_range_ms', 2000))
        hash_algorithm = config.get('frame_hash_algorithm', config.get('sub_anchor_hash_algorithm', 'dhash'))
        hash_size = int(config.get('frame_hash_size', config.get('sub_anchor_hash_size', 8)))
        hash_threshold = int(config.get('frame_hash_threshold', config.get('sub_anchor_hash_threshold', 5)))
        window_radius = int(config.get('frame_window_radius', config.get('sub_anchor_window_radius', 5)))
        tolerance_ms = config.get('frame_agreement_tolerance_ms', config.get('sub_anchor_agreement_tolerance_ms', 100))
        fallback_mode = config.get('sub_anchor_fallback_mode', 'abort')  # Mode-specific
        use_vapoursynth = config.get('frame_use_vapoursynth', config.get('sub_anchor_use_vapoursynth', True))

        log(f"[SubAnchor] Search range: ±{search_range_ms}ms")
        log(f"[SubAnchor] Hash: {hash_algorithm}, size={hash_size}, threshold={hash_threshold}")
        log(f"[SubAnchor] Window radius: {window_radius} frames, tolerance: {tolerance_ms}ms")

        # Create event wrapper for checkpoint selection
        class EventWrapper:
            def __init__(self, event, idx):
                self.start = int(event.start_ms)
                self.end = int(event.end_ms)
                self.style = event.style
                self.text = event.text
                self.idx = idx

        wrapped_events = [EventWrapper(e, i) for i, e in enumerate(subtitle_data.events) if not e.is_comment]

        if not wrapped_events:
            return OperationResult(
                success=False,
                operation='sync',
                error='No dialogue events for checkpoint selection'
            )

        # Select checkpoints
        checkpoints = select_smart_checkpoints(wrapped_events, runner)
        if len(checkpoints) < 2:
            return OperationResult(
                success=False,
                operation='sync',
                error=f'Need at least 2 checkpoints, got {len(checkpoints)}'
            )

        log(f"[SubAnchor] Selected {len(checkpoints)} checkpoints")

        # Try to import frame matching
        try:
            from ..sync_modes.frame_matching import VideoReader, compute_frame_hash, compute_hamming_distance
        except ImportError as e:
            return OperationResult(
                success=False,
                operation='sync',
                error=f'Frame matching module not available: {e}'
            )

        # Open video readers
        try:
            source_reader = VideoReader(source_video, runner, use_vapoursynth=use_vapoursynth, temp_dir=temp_dir)
            target_reader = VideoReader(target_video, runner, use_vapoursynth=use_vapoursynth, temp_dir=temp_dir)
        except Exception as e:
            return OperationResult(
                success=False,
                operation='sync',
                error=f'Failed to open videos: {e}'
            )

        # Process each checkpoint
        checkpoint_offsets = []
        checkpoint_details = []

        for i, event in enumerate(checkpoints):
            subtitle_time_ms = event.start
            log(f"[SubAnchor] Checkpoint {i+1}/{len(checkpoints)}: {subtitle_time_ms}ms")

            # Get source frame and compute hash
            source_frame = source_reader.get_frame_at_time(subtitle_time_ms)
            if source_frame is None:
                log(f"[SubAnchor] WARNING: Failed to get source frame at {subtitle_time_ms}ms")
                continue

            source_hash = compute_frame_hash(source_frame, hash_size=hash_size, method=hash_algorithm)
            if source_hash is None:
                log(f"[SubAnchor] WARNING: Failed to compute source hash")
                continue

            # Search in target
            best_match_time = None
            best_match_distance = float('inf')
            search_start = subtitle_time_ms - search_range_ms
            search_end = subtitle_time_ms + search_range_ms

            # Sample every frame in search range
            search_time = search_start
            while search_time <= search_end:
                target_frame = target_reader.get_frame_at_time(int(search_time))
                if target_frame is not None:
                    target_hash = compute_frame_hash(target_frame, hash_size=hash_size, method=hash_algorithm)
                    if target_hash is not None:
                        distance = compute_hamming_distance(source_hash, target_hash)
                        if distance < best_match_distance:
                            best_match_distance = distance
                            best_match_time = search_time
                search_time += frame_duration_ms

            if best_match_time is not None and best_match_distance <= hash_threshold:
                offset = best_match_time - subtitle_time_ms
                checkpoint_offsets.append(offset)
                checkpoint_details.append({
                    'checkpoint': i + 1,
                    'source_time_ms': subtitle_time_ms,
                    'target_time_ms': best_match_time,
                    'offset_ms': offset,
                    'hash_distance': best_match_distance,
                    'match_quality': 'good' if best_match_distance <= 3 else 'marginal'
                })
                log(f"[SubAnchor]   Match: {subtitle_time_ms}ms → {best_match_time}ms (Δ{offset:+.1f}ms, dist={best_match_distance})")
            else:
                log(f"[SubAnchor]   No match found (best distance: {best_match_distance})")
                checkpoint_details.append({
                    'checkpoint': i + 1,
                    'source_time_ms': subtitle_time_ms,
                    'match_quality': 'none',
                    'best_distance': best_match_distance,
                })

        # Close readers
        try:
            source_reader.close()
            target_reader.close()
        except:
            pass

        # Check if we have enough matches
        if len(checkpoint_offsets) < 2:
            if fallback_mode == 'abort':
                return OperationResult(
                    success=False,
                    operation='sync',
                    error=f'Not enough matching checkpoints ({len(checkpoint_offsets)}/2 minimum)'
                )
            else:
                log(f"[SubAnchor] WARNING: Only {len(checkpoint_offsets)} matches, using available data")

        if not checkpoint_offsets:
            return OperationResult(
                success=False,
                operation='sync',
                error='No checkpoints matched'
            )

        # Check agreement
        offset_range = max(checkpoint_offsets) - min(checkpoint_offsets)
        offsets_agree = offset_range <= tolerance_ms

        if not offsets_agree:
            log(f"[SubAnchor] WARNING: Offsets disagree (range: {offset_range:.1f}ms > tolerance: {tolerance_ms}ms)")
            if fallback_mode == 'abort':
                return OperationResult(
                    success=False,
                    operation='sync',
                    error=f'Checkpoint offsets disagree: range {offset_range:.1f}ms exceeds {tolerance_ms}ms tolerance'
                )
            log(f"[SubAnchor] Using median offset anyway")

        # Calculate final offset (median + global shift)
        sorted_offsets = sorted(checkpoint_offsets)
        median_offset = sorted_offsets[len(sorted_offsets) // 2]
        final_offset_ms = median_offset + global_shift_ms

        log(f"[SubAnchor] ───────────────────────────────────────")
        log(f"[SubAnchor] Checkpoint offsets: {[f'{o:+.1f}' for o in checkpoint_offsets]}")
        log(f"[SubAnchor] Median offset: {median_offset:+.3f}ms")
        log(f"[SubAnchor] + Global shift: {global_shift_ms:+.3f}ms")
        log(f"[SubAnchor] = Final offset: {final_offset_ms:+.3f}ms")
        log(f"[SubAnchor] ───────────────────────────────────────")

        # Apply offset to all events
        log(f"[SubAnchor] Applying {final_offset_ms:+.3f}ms to {len(subtitle_data.events)} events")

        events_synced = 0
        for event in subtitle_data.events:
            if event.is_comment:
                continue

            original_start = event.start_ms
            original_end = event.end_ms

            event.start_ms += final_offset_ms
            event.end_ms += final_offset_ms

            # Populate per-event sync metadata
            event.sync = SyncEventData(
                original_start_ms=original_start,
                original_end_ms=original_end,
                start_adjustment_ms=final_offset_ms,
                end_adjustment_ms=final_offset_ms,
                snapped_to_frame=False,
            )

            events_synced += 1

        # Build summary
        summary = f"SubtitleAnchored: {events_synced} events, {final_offset_ms:+.1f}ms"
        if offsets_agree:
            summary += f" ({len(checkpoint_offsets)} checkpoints agree)"
        else:
            summary += f" (offsets varied {offset_range:.0f}ms)"

        # Record operation
        record = OperationRecord(
            operation='sync',
            timestamp=datetime.now(),
            parameters={
                'mode': self.name,
                'median_offset_ms': median_offset,
                'global_shift_ms': global_shift_ms,
                'final_offset_ms': final_offset_ms,
                'num_checkpoints': len(checkpoint_offsets),
                'offsets_agree': offsets_agree,
                'offset_range_ms': offset_range,
            },
            events_affected=events_synced,
            summary=summary
        )
        subtitle_data.operations.append(record)

        log(f"[SubAnchor] Sync complete: {events_synced} events")
        log(f"[SubAnchor] ===================================")

        return OperationResult(
            success=True,
            operation='sync',
            events_affected=events_synced,
            summary=summary,
            details={
                'median_offset_ms': median_offset,
                'final_offset_ms': final_offset_ms,
                'checkpoints': checkpoint_details,
                'offsets_agree': offsets_agree,
            }
        )
