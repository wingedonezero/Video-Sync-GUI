# vsg_core/subtitles/sync_mode_plugins/timebase_frame_delay.py
# -*- coding: utf-8 -*-
"""
TimeBase Frame-Delay sync plugin for SubtitleData.

This mode applies a frame-rounded delay WITHOUT snapping individual events:
1. Round the delay to nearest whole frame count using VideoTimestamps
2. Convert back to precise milliseconds
3. Apply that delay to all events (no per-event snapping)
4. Preserve original duration exactly

This preserves the original sub-frame timing relationships while ensuring
the overall shift is a clean frame-based amount.
"""
from __future__ import annotations

from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Dict, Any, Optional, TYPE_CHECKING

from ..sync_modes import SyncPlugin, register_sync_plugin

if TYPE_CHECKING:
    from ..data import SubtitleData, OperationResult, OperationRecord, SyncEventData


@register_sync_plugin
class TimebaseFrameDelaySync(SyncPlugin):
    """
    Time-based sync with frame-rounded delay, no per-event snapping.

    Uses VideoTimestamps to calculate a precise frame-based delay,
    but preserves original sub-frame timing of each event.
    """

    name = 'timebase-frame-delay'
    description = 'Frame-rounded delay without per-event snapping (preserves original timing)'

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
        **kwargs
    ) -> 'OperationResult':
        """
        Apply frame-rounded delay to subtitle data without snapping.

        Args:
            subtitle_data: SubtitleData to modify
            total_delay_ms: Total delay from analysis (raw float)
            global_shift_ms: User global shift (raw float, for logging)
            target_fps: Target video FPS
            target_video: Path to target video (for VideoTimestamps)
            runner: CommandRunner for logging
            config: Settings dict

        Returns:
            OperationResult with statistics
        """
        from ..data import OperationResult, OperationRecord, SyncEventData

        config = config or {}

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log(f"[FrameDelay] === TimeBase Frame-Delay Sync ===")
        log(f"[FrameDelay] Events: {len(subtitle_data.events)}")

        if not target_fps or target_fps <= 0:
            return OperationResult(
                success=False,
                operation='sync',
                error='Valid target FPS required for frame-delay mode'
            )

        log(f"[FrameDelay] Target FPS: {target_fps:.3f}")
        log(f"[FrameDelay] Raw delay: {total_delay_ms:+.3f}ms (global shift: {global_shift_ms:+.3f}ms)")

        # Calculate frame duration for this FPS
        # Use exact fraction for NTSC rates to avoid floating point drift
        if abs(target_fps - 23.976) < 0.001:
            # 23.976fps = 24000/1001, frame duration = 1001/24 ms
            frame_duration_ms = 1001.0 / 24.0  # 41.7083... ms
        elif abs(target_fps - 29.97) < 0.01:
            # 29.97fps = 30000/1001, frame duration = 1001/30 ms
            frame_duration_ms = 1001.0 / 30.0  # 33.3666... ms
        elif abs(target_fps - 59.94) < 0.01:
            # 59.94fps = 60000/1001, frame duration = 1001/60 ms
            frame_duration_ms = 1001.0 / 60.0  # 16.6833... ms
        else:
            frame_duration_ms = 1000.0 / target_fps

        # Calculate delay in frames and round to nearest whole frame
        delay_frames_exact = total_delay_ms / frame_duration_ms

        # Get rounding mode from config (default: nearest)
        rounding_mode = config.get('frame_delay_rounding', 'nearest')

        if rounding_mode == 'floor':
            delay_frames = int(delay_frames_exact)
        elif rounding_mode == 'ceil':
            import math
            delay_frames = math.ceil(delay_frames_exact)
        else:  # 'nearest' (default)
            delay_frames = round(delay_frames_exact)

        # Convert back to milliseconds
        # Simple multiplication is accurate for CFR videos
        frame_delay_ms = delay_frames * frame_duration_ms

        # Calculate the rounding delta
        rounding_delta_ms = frame_delay_ms - total_delay_ms
        rounding_delta_frames = rounding_delta_ms / frame_duration_ms

        log(f"[FrameDelay] Delay calculation:")
        log(f"[FrameDelay]   Raw: {total_delay_ms:+.3f}ms = {delay_frames_exact:+.3f} frames")
        log(f"[FrameDelay]   Rounded ({rounding_mode}): {delay_frames} frames = {frame_delay_ms:+.3f}ms")
        log(f"[FrameDelay]   Rounding delta: {rounding_delta_ms:+.3f}ms ({rounding_delta_frames:+.3f} frames)")

        # Statistics tracking
        stats = {
            'total_events': len(subtitle_data.events),
            'events_synced': 0,
            'raw_delay_ms': total_delay_ms,
            'raw_delay_frames': delay_frames_exact,
            'rounded_delay_frames': delay_frames,
            'frame_delay_ms': frame_delay_ms,
            'rounding_delta_ms': rounding_delta_ms,
            'rounding_mode': rounding_mode,
        }

        log(f"[FrameDelay] Applying {delay_frames}-frame delay ({frame_delay_ms:+.3f}ms) to all events...")

        # Apply delay to all events (NO SNAPPING)
        for event in subtitle_data.events:
            if event.is_comment:
                continue

            original_start = event.start_ms
            original_end = event.end_ms

            # Simply add the frame-rounded delay
            event.start_ms = original_start + frame_delay_ms
            event.end_ms = original_end + frame_delay_ms

            # Populate per-event sync metadata
            event.sync = SyncEventData(
                original_start_ms=original_start,
                original_end_ms=original_end,
                start_adjustment_ms=frame_delay_ms,
                end_adjustment_ms=frame_delay_ms,
                snapped_to_frame=False,  # We don't snap!
                target_frame_start=None,
                target_frame_end=None,
            )

            stats['events_synced'] += 1

        # Build summary
        summary = (f"Frame-delay sync: {stats['events_synced']} events, "
                   f"{delay_frames:+d} frames ({frame_delay_ms:+.1f}ms)")

        # Record operation
        record = OperationRecord(
            operation='sync',
            timestamp=datetime.now(),
            parameters={
                'mode': self.name,
                'raw_delay_ms': total_delay_ms,
                'frame_delay_ms': frame_delay_ms,
                'delay_frames': delay_frames,
                'target_fps': target_fps,
                'rounding_mode': rounding_mode,
                'global_shift_ms': global_shift_ms,
            },
            events_affected=stats['events_synced'],
            summary=summary
        )
        subtitle_data.operations.append(record)

        # Log summary
        log(f"[FrameDelay] ───────────────────────────────────────")
        log(f"[FrameDelay] Sync complete:")
        log(f"[FrameDelay]   Events synced: {stats['events_synced']}/{stats['total_events']}")
        log(f"[FrameDelay]   Delay applied: {delay_frames:+d} frames ({frame_delay_ms:+.3f}ms)")
        log(f"[FrameDelay]   Rounding delta: {rounding_delta_ms:+.3f}ms")
        log(f"[FrameDelay]   No per-event snapping (original timing preserved)")
        log(f"[FrameDelay] ===================================")

        return OperationResult(
            success=True,
            operation='sync',
            events_affected=stats['events_synced'],
            summary=record.summary,
            details=stats
        )

    def _get_video_timestamps(self, video_path: str, fps: float, runner, config: dict):
        """Get VideoTimestamps handler for the video."""
        try:
            from ..frame_utils import get_vfr_timestamps
            return get_vfr_timestamps(video_path, fps, runner, config)
        except Exception as e:
            if runner:
                runner._log_message(f"[FrameDelay] WARNING: Could not get VideoTimestamps: {e}")
            return None
