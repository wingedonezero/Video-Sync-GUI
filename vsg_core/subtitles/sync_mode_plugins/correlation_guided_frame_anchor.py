# vsg_core/subtitles/sync_mode_plugins/correlation_guided_frame_anchor.py
"""
Correlation-Guided Frame Anchor sync plugin for SubtitleData.

Uses correlation to guide robust frame matching with time-based anchor points.
Combines correlation baseline with subtitle-anchor's sliding window matching.

All timing is float ms internally - rounding happens only at final save.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..sync_modes import SyncPlugin, register_sync_plugin

if TYPE_CHECKING:
    from ..data import OperationResult, SubtitleData


@register_sync_plugin
class CorrelationGuidedFrameAnchorSync(SyncPlugin):
    """
    Correlation-Guided Frame Anchor sync mode.

    Uses correlation to guide frame matching with time-based anchors.
    """

    name = 'correlation-guided-frame-anchor'
    description = 'Correlation-guided frame matching with time-based anchors'

    def apply(
        self,
        subtitle_data: SubtitleData,
        total_delay_ms: float,
        global_shift_ms: float,
        target_fps: float | None = None,
        source_video: str | None = None,
        target_video: str | None = None,
        runner=None,
        config: dict | None = None,
        temp_dir: Path | None = None,
        sync_exclusion_styles: list[str] | None = None,
        sync_exclusion_mode: str = 'exclude',
        **kwargs
    ) -> OperationResult:
        """
        Apply correlation-guided frame anchor sync to subtitle data.

        Algorithm:
        1. Use correlation to get rough offset baseline
        2. Select 3 time-based anchor points (10%, 50%, 90% of video)
        3. Match frames via sliding window at each anchor
        4. Verify 3-checkpoint agreement
        5. Apply final offset to all events

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
            sync_exclusion_styles: Styles to exclude/include from frame sync
            sync_exclusion_mode: 'exclude' or 'include'

        Returns:
            OperationResult with statistics
        """
        from ..data import OperationResult
        from ..frame_utils import detect_video_fps, get_video_duration_ms

        config = config or {}

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log("[CorrGuided] === Correlation-Guided Frame Anchor Sync ===")
        log(f"[CorrGuided] Events: {len(subtitle_data.events)}")

        if not source_video or not target_video:
            return OperationResult(
                success=False,
                operation='sync',
                error='Both source and target videos required for correlation-guided-frame-anchor'
            )

        # Calculate pure correlation (correlation only, without global shift)
        pure_correlation_ms = total_delay_ms - global_shift_ms

        log(f"[CorrGuided] Source: {Path(source_video).name}")
        log(f"[CorrGuided] Target: {Path(target_video).name}")
        log(f"[CorrGuided] Total delay (with global): {total_delay_ms:+.3f}ms")
        log(f"[CorrGuided] Global shift: {global_shift_ms:+.3f}ms")
        log(f"[CorrGuided] Pure correlation: {pure_correlation_ms:+.3f}ms")

        # Detect FPS
        fps = target_fps or detect_video_fps(source_video, runner)
        if not fps:
            fps = 23.976
            log(f"[CorrGuided] FPS detection failed, using default: {fps}")

        frame_duration_ms = 1000.0 / fps
        log(f"[CorrGuided] FPS: {fps:.3f} (frame: {frame_duration_ms:.3f}ms)")

        # Get unified config parameters
        search_range_ms = config.get('frame_search_range_ms', 2000)
        hash_algorithm = config.get('frame_hash_algorithm', 'dhash')
        hash_size = int(config.get('frame_hash_size', 8))
        hash_threshold = int(config.get('frame_hash_threshold', 5))
        window_radius = int(config.get('frame_window_radius', 5))
        tolerance_ms = config.get('frame_agreement_tolerance_ms', 100)
        fallback_mode = config.get('corr_anchor_fallback_mode', 'use-correlation')
        anchor_positions = config.get('corr_anchor_anchor_positions', [10, 50, 90])

        log(f"[CorrGuided] Search range: ±{search_range_ms}ms")
        log(f"[CorrGuided] Hash: {hash_algorithm}, size={hash_size}, threshold={hash_threshold}")
        log(f"[CorrGuided] Anchor positions: {anchor_positions}%")

        # Try to get video duration for anchor calculation
        try:
            source_duration = get_video_duration_ms(source_video, runner)
        except:
            # Estimate from last subtitle
            if subtitle_data.events:
                source_duration = max(e.end_ms for e in subtitle_data.events) + 60000
            else:
                source_duration = 1200000  # 20 minutes default

        log(f"[CorrGuided] Source duration: ~{source_duration/1000:.1f}s")

        # Try to import frame utilities
        try:
            from ..frame_utils import (
                VideoReader,
                compute_frame_hash,
                compute_hamming_distance,
            )
        except ImportError as e:
            # Fall back to just correlation
            log(f"[CorrGuided] Frame utilities unavailable: {e}")
            log("[CorrGuided] Falling back to correlation-only offset")
            return self._apply_correlation_only(
                subtitle_data, total_delay_ms, global_shift_ms, sync_exclusion_styles, sync_exclusion_mode, runner
            )

        # Open video readers
        try:
            use_vs = config.get('frame_use_vapoursynth', True)
            source_reader = VideoReader(source_video, runner, use_vapoursynth=use_vs, temp_dir=temp_dir)
            target_reader = VideoReader(target_video, runner, use_vapoursynth=use_vs, temp_dir=temp_dir)
        except Exception as e:
            log(f"[CorrGuided] Failed to open videos: {e}")
            log("[CorrGuided] Falling back to correlation-only offset")
            return self._apply_correlation_only(
                subtitle_data, total_delay_ms, global_shift_ms, sync_exclusion_styles, sync_exclusion_mode, runner
            )

        # Calculate anchor times from positions
        anchor_times = [int(source_duration * pos / 100) for pos in anchor_positions]
        log(f"[CorrGuided] Anchor times: {anchor_times}ms")

        # Process each anchor point
        measurements = []
        checkpoint_details = []

        for i, anchor_time in enumerate(anchor_times):
            log(f"[CorrGuided] Anchor {i+1}/{len(anchor_times)}: {anchor_time}ms")

            # Get source frames for window
            source_hashes = []
            for offset in range(-window_radius, window_radius + 1):
                frame_time = anchor_time + int(offset * frame_duration_ms)
                frame = source_reader.get_frame_at_time(frame_time)
                if frame is not None:
                    h = compute_frame_hash(frame, hash_size=hash_size, method=hash_algorithm)
                    if h is not None:
                        source_hashes.append((offset, h))

            if len(source_hashes) < 3:
                log("[CorrGuided]   WARNING: Not enough source frames")
                continue

            # Predicted target time based on correlation
            predicted_target = anchor_time + pure_correlation_ms

            # Search around prediction
            best_match_offset = None
            best_match_score = float('inf')

            search_start = predicted_target - search_range_ms
            search_end = predicted_target + search_range_ms
            search_step = frame_duration_ms

            search_time = search_start
            while search_time <= search_end:
                # Get target frames for this position
                total_distance = 0
                matched_frames = 0

                for src_offset, src_hash in source_hashes:
                    target_time = int(search_time + src_offset * frame_duration_ms)
                    target_frame = target_reader.get_frame_at_time(target_time)
                    if target_frame is not None:
                        target_hash = compute_frame_hash(target_frame, hash_size=hash_size, method=hash_algorithm)
                        if target_hash is not None:
                            dist = compute_hamming_distance(src_hash, target_hash)
                            total_distance += dist
                            matched_frames += 1

                if matched_frames > 0:
                    avg_distance = total_distance / matched_frames
                    if avg_distance < best_match_score:
                        best_match_score = avg_distance
                        best_match_offset = search_time - anchor_time

                search_time += search_step

            if best_match_offset is not None and best_match_score <= hash_threshold * 2:
                measurements.append(best_match_offset)
                checkpoint_details.append({
                    'anchor': i + 1,
                    'anchor_time_ms': anchor_time,
                    'offset_ms': best_match_offset,
                    'score': best_match_score,
                    'quality': 'good' if best_match_score <= hash_threshold else 'marginal'
                })
                log(f"[CorrGuided]   Match: offset={best_match_offset:+.1f}ms, score={best_match_score:.1f}")
            else:
                log(f"[CorrGuided]   No good match (best score: {best_match_score:.1f})")

        # Close readers
        try:
            source_reader.close()
            target_reader.close()
        except:
            pass

        # Determine final offset
        frame_correction_ms = 0.0

        if len(measurements) >= 2:
            # Check agreement
            offset_range = max(measurements) - min(measurements)
            offsets_agree = offset_range <= tolerance_ms

            if offsets_agree:
                # Use median
                sorted_m = sorted(measurements)
                median_offset = sorted_m[len(sorted_m) // 2]
                frame_correction_ms = median_offset - pure_correlation_ms
                log(f"[CorrGuided] ✓ Anchors agree: median={median_offset:+.1f}ms, correction={frame_correction_ms:+.3f}ms")
            else:
                log(f"[CorrGuided] WARNING: Anchors disagree (range: {offset_range:.1f}ms)")
                if fallback_mode == 'abort':
                    return OperationResult(
                        success=False,
                        operation='sync',
                        error=f'Anchor offsets disagree: range {offset_range:.1f}ms exceeds {tolerance_ms}ms'
                    )
                elif fallback_mode == 'use-median':
                    sorted_m = sorted(measurements)
                    median_offset = sorted_m[len(sorted_m) // 2]
                    frame_correction_ms = median_offset - pure_correlation_ms
                    log(f"[CorrGuided] Using median anyway: {median_offset:+.1f}ms")
                else:  # use-correlation
                    log("[CorrGuided] Using correlation only (no frame correction)")
        else:
            log(f"[CorrGuided] Not enough anchor matches ({len(measurements)}/2)")
            if fallback_mode == 'abort':
                return OperationResult(
                    success=False,
                    operation='sync',
                    error=f'Not enough anchor matches ({len(measurements)}/2 minimum)'
                )
            log("[CorrGuided] Using correlation only")

        # Calculate final offset
        final_offset_ms = total_delay_ms + frame_correction_ms

        log("[CorrGuided] ───────────────────────────────────────")
        log("[CorrGuided] Final calculation:")
        log(f"[CorrGuided]   Total delay:       {total_delay_ms:+.3f}ms")
        log(f"[CorrGuided]   + Frame correction: {frame_correction_ms:+.3f}ms")
        log(f"[CorrGuided]   = Final offset:    {final_offset_ms:+.3f}ms")
        log("[CorrGuided] ───────────────────────────────────────")

        # Apply offset to all events
        return self._apply_offset(
            subtitle_data, final_offset_ms, total_delay_ms, global_shift_ms,
            frame_correction_ms, checkpoint_details, sync_exclusion_styles,
            sync_exclusion_mode, runner
        )

    def _apply_correlation_only(
        self,
        subtitle_data: SubtitleData,
        total_delay_ms: float,
        global_shift_ms: float,
        sync_exclusion_styles: list[str] | None,
        sync_exclusion_mode: str,
        runner
    ) -> OperationResult:
        """Apply correlation-only offset when frame matching unavailable."""
        return self._apply_offset(
            subtitle_data, total_delay_ms, total_delay_ms, global_shift_ms,
            0.0, [], sync_exclusion_styles, sync_exclusion_mode, runner
        )

    def _apply_offset(
        self,
        subtitle_data: SubtitleData,
        final_offset_ms: float,
        total_delay_ms: float,
        global_shift_ms: float,
        frame_correction_ms: float,
        checkpoint_details: list[dict],
        sync_exclusion_styles: list[str] | None,
        sync_exclusion_mode: str,
        runner
    ) -> OperationResult:
        """Apply the calculated offset to all events."""
        from ..data import OperationRecord, OperationResult, SyncEventData

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log(f"[CorrGuided] Applying {final_offset_ms:+.3f}ms to {len(subtitle_data.events)} events")

        events_synced = 0
        events_excluded = 0

        for event in subtitle_data.events:
            if event.is_comment:
                continue

            # Check sync exclusion
            should_exclude = False
            if sync_exclusion_styles:
                if sync_exclusion_mode == 'exclude':
                    should_exclude = event.style in sync_exclusion_styles
                else:  # include mode
                    should_exclude = event.style not in sync_exclusion_styles

            original_start = event.start_ms
            original_end = event.end_ms

            if should_exclude:
                # Apply base offset only (no frame refinement)
                event.start_ms += total_delay_ms
                event.end_ms += total_delay_ms
                events_excluded += 1

                event.sync = SyncEventData(
                    original_start_ms=original_start,
                    original_end_ms=original_end,
                    start_adjustment_ms=total_delay_ms,
                    end_adjustment_ms=total_delay_ms,
                    snapped_to_frame=False,
                )
            else:
                # Apply full offset with frame correction
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
        summary = f"CorrGuided: {events_synced} events, {final_offset_ms:+.1f}ms"
        if checkpoint_details:
            summary += f" ({len(checkpoint_details)} anchors)"
        if events_excluded > 0:
            summary += f" ({events_excluded} excluded)"

        # Record operation
        record = OperationRecord(
            operation='sync',
            timestamp=datetime.now(),
            parameters={
                'mode': self.name,
                'total_delay_ms': total_delay_ms,
                'global_shift_ms': global_shift_ms,
                'frame_correction_ms': frame_correction_ms,
                'final_offset_ms': final_offset_ms,
                'num_anchors': len(checkpoint_details),
            },
            events_affected=events_synced,
            summary=summary
        )
        subtitle_data.operations.append(record)

        log(f"[CorrGuided] Sync complete: {events_synced} events")
        if events_excluded > 0:
            log(f"[CorrGuided] ({events_excluded} styles excluded from frame correction)")
        log("[CorrGuided] ===================================")

        return OperationResult(
            success=True,
            operation='sync',
            events_affected=events_synced,
            summary=summary,
            details={
                'frame_correction_ms': frame_correction_ms,
                'final_offset_ms': final_offset_ms,
                'checkpoints': checkpoint_details,
                'events_excluded': events_excluded,
            }
        )
