# vsg_core/subtitles/sync_mode_plugins/timebase_frame_locked.py
# -*- coding: utf-8 -*-
"""
TimeBase Frame-Locked Timestamps sync plugin for SubtitleData.

This mode applies delay + frame-snapping using VideoTimestamps:
1. Frame-align the global delay to TARGET video frame boundary
2. Apply frame-aligned delay to all events
3. Frame-snap each event start to TARGET frame boundary
4. Preserve duration by adjusting end with same delta

All operations work with float ms - rounding happens only at save_ass().
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
class TimebaseFrameLockedSync(SyncPlugin):
    """
    Time-based sync with VideoTimestamps frame locking.

    Uses TARGET video to ensure frame-accurate alignment.
    """

    name = 'timebase-frame-locked-timestamps'
    description = 'Time-based delay with VideoTimestamps frame-accurate alignment'

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
        Apply frame-locked sync to subtitle data.

        Args:
            subtitle_data: SubtitleData to modify
            total_delay_ms: Total delay from analysis (raw float)
            global_shift_ms: User global shift (raw float, for logging)
            target_fps: Target video FPS
            target_video: Path to target video (required for frame locking)
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

        log(f"[FrameLocked] === TimeBase Frame-Locked Timestamps Sync ===")
        log(f"[FrameLocked] Events: {len(subtitle_data.events)}")

        if not target_video:
            return OperationResult(
                success=False,
                operation='sync',
                error='Target video required for frame-locked mode'
            )

        if not target_fps or target_fps <= 0:
            return OperationResult(
                success=False,
                operation='sync',
                error='Valid target FPS required for frame-locked mode'
            )

        log(f"[FrameLocked] Target: {Path(target_video).name} ({target_fps:.3f} fps)")
        log(f"[FrameLocked] Raw delay: {total_delay_ms:+.3f}ms (global shift: {global_shift_ms:+.3f}ms)")

        # Try to get VideoTimestamps for precise frame alignment
        vts = self._get_video_timestamps(target_video, target_fps, runner, config)

        # Statistics tracking
        stats = {
            'total_events': len(subtitle_data.events),
            'events_synced': 0,
            'start_snapped': 0,
            'start_already_aligned': 0,
            'duration_adjusted': 0,
            'raw_delay_ms': total_delay_ms,
            'frame_aligned_delay_ms': total_delay_ms,
            'alignment_delta_ms': 0.0,
        }

        # Step 1: Frame-align the global delay
        # Config option: frame_lock_submillisecond_precision (default: False)
        # When True, preserves sub-ms precision in frame calculations
        use_submillisecond = config.get('frame_lock_submillisecond_precision', False)

        if vts:
            frame_aligned_delay = self._frame_align_delay(
                total_delay_ms, vts, target_fps, log,
                use_submillisecond=use_submillisecond
            )
            stats['frame_aligned_delay_ms'] = frame_aligned_delay
            stats['alignment_delta_ms'] = frame_aligned_delay - total_delay_ms
        else:
            log(f"[FrameLocked] VideoTimestamps unavailable, using raw delay")
            frame_aligned_delay = total_delay_ms

        # Step 2: Apply delay and frame-snap each event
        log(f"[FrameLocked] Applying frame-aligned delay: {frame_aligned_delay:+.3f}ms")

        # Track per-event adjustments for stats
        start_adjustments = []
        end_adjustments = []

        for event in subtitle_data.events:
            # Skip comments if configured
            if event.is_comment:
                continue

            original_start = event.start_ms
            original_end = event.end_ms
            original_duration = original_end - original_start

            # Apply delay
            delayed_start = original_start + frame_aligned_delay
            delayed_end = original_end + frame_aligned_delay

            # Initialize sync tracking data
            start_frame = None
            end_frame = None
            snapped = False

            # Frame-snap start time
            if vts:
                snapped_start, start_frame = self._snap_to_frame_start(delayed_start, vts, target_fps)
                start_delta = snapped_start - delayed_start

                if abs(start_delta) > 0.5:
                    stats['start_snapped'] += 1
                    snapped = True
                else:
                    stats['start_already_aligned'] += 1

                # Preserve duration
                snapped_end = delayed_end + start_delta

                # Safety: ensure end is after start (at least next frame)
                if vts:
                    end_frame = self._time_to_frame(snapped_end, vts, target_fps)
                    if end_frame <= start_frame:
                        # Push end to next frame start
                        snapped_end = self._frame_to_time(start_frame + 1, vts, target_fps)
                        stats['duration_adjusted'] += 1

                event.start_ms = snapped_start
                event.end_ms = snapped_end
            else:
                # No VideoTimestamps - just apply delay
                event.start_ms = delayed_start
                event.end_ms = delayed_end
                snapped_start = delayed_start
                snapped_end = delayed_end

            # Calculate actual adjustments
            start_adj = event.start_ms - original_start
            end_adj = event.end_ms - original_end
            start_adjustments.append(start_adj)
            end_adjustments.append(end_adj)

            # Populate per-event sync metadata
            event.sync = SyncEventData(
                original_start_ms=original_start,
                original_end_ms=original_end,
                start_adjustment_ms=start_adj,
                end_adjustment_ms=end_adj,
                snapped_to_frame=snapped,
                target_frame_start=start_frame,
                target_frame_end=end_frame,
            )

            stats['events_synced'] += 1

        # Calculate adjustment statistics
        if start_adjustments:
            stats['min_adjustment_ms'] = min(start_adjustments)
            stats['max_adjustment_ms'] = max(start_adjustments)
            stats['avg_adjustment_ms'] = sum(start_adjustments) / len(start_adjustments)
        else:
            stats['min_adjustment_ms'] = 0.0
            stats['max_adjustment_ms'] = 0.0
            stats['avg_adjustment_ms'] = 0.0

        # Build summary with adjustment range if varied
        if stats['min_adjustment_ms'] != stats['max_adjustment_ms']:
            summary = (f"Frame-locked sync: {stats['events_synced']} events, "
                      f"avg {stats['avg_adjustment_ms']:+.1f}ms "
                      f"(range: {stats['min_adjustment_ms']:+.1f} to {stats['max_adjustment_ms']:+.1f})")
        else:
            summary = f"Frame-locked sync: {stats['events_synced']} events, delay {frame_aligned_delay:+.1f}ms"

        # Record operation
        record = OperationRecord(
            operation='sync',
            timestamp=datetime.now(),
            parameters={
                'mode': self.name,
                'input_delay_ms': total_delay_ms,
                'frame_aligned_delay_ms': frame_aligned_delay,
                'target_fps': target_fps,
                'global_shift_ms': global_shift_ms,
            },
            events_affected=stats['events_synced'],
            summary=summary
        )
        subtitle_data.operations.append(record)

        # Log summary
        log(f"[FrameLocked] ───────────────────────────────────────")
        log(f"[FrameLocked] Sync complete:")
        log(f"[FrameLocked]   Events synced: {stats['events_synced']}/{stats['total_events']}")
        log(f"[FrameLocked]   Start times snapped: {stats['start_snapped']}")
        log(f"[FrameLocked]   Already aligned: {stats['start_already_aligned']}")
        log(f"[FrameLocked]   Duration adjustments: {stats['duration_adjusted']}")
        log(f"[FrameLocked]   Frame alignment delta: {stats['alignment_delta_ms']:+.3f}ms")
        log(f"[FrameLocked] ===================================")

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
                runner._log_message(f"[FrameLocked] WARNING: Could not get VideoTimestamps: {e}")
            return None

    def _frame_align_delay(self, delay_ms: float, vts, fps: float, log, use_submillisecond: bool = False) -> float:
        """
        Align delay to nearest frame boundary.

        Returns delay that corresponds to an exact frame start time.

        Args:
            delay_ms: Delay in milliseconds (may have sub-ms precision)
            vts: VideoTimestamps instance
            fps: Frame rate
            log: Logging function
            use_submillisecond: If True, preserve sub-millisecond precision when
                               converting to frame. If False (default), truncate
                               to integer milliseconds before conversion.
                               Default matches historical behavior.

        Note on precision:
            VideoTimestamps.time_to_frame() accepts a Fraction for precise timing.
            - Truncated mode: Fraction(int(delay_ms), 1) e.g., 1234.567 -> 1234
            - Precise mode: Fraction(int(delay_ms * 1000), 1000) e.g., 1234.567 -> 1234567/1000
            The difference only matters near frame boundaries (<1ms from edge).
            Since ASS format saves at 10ms precision anyway, truncation is usually fine.
        """
        try:
            from video_timestamps import TimeType

            # Convert delay to Fraction for VideoTimestamps
            if use_submillisecond:
                # Preserve sub-millisecond precision (e.g., 1234.567 -> Fraction(1234567, 1000))
                delay_frac = Fraction(int(delay_ms * 1000), 1000)
                log(f"[FrameLocked] Using sub-millisecond precision: {float(delay_frac):.3f}ms")
            else:
                # Truncate to integer milliseconds (historical default behavior)
                # e.g., 1234.567 -> Fraction(1234, 1)
                delay_frac = Fraction(int(delay_ms), 1)

            frame = vts.time_to_frame(delay_frac, TimeType.EXACT)

            # Get exact frame start time
            frame_start = vts.frame_to_time(frame, TimeType.START)
            aligned_ms = float(frame_start)

            log(f"[FrameLocked] Frame alignment: {delay_ms:.3f}ms -> frame {frame} -> {aligned_ms:.3f}ms")
            log(f"[FrameLocked] Alignment delta: {aligned_ms - delay_ms:+.3f}ms")

            return aligned_ms

        except Exception as e:
            log(f"[FrameLocked] WARNING: Frame alignment failed: {e}")
            return delay_ms

    def _snap_to_frame_start(self, time_ms: float, vts, fps: float) -> tuple:
        """
        Snap time to frame start boundary.

        Returns (snapped_time_ms, frame_number)
        """
        try:
            from video_timestamps import TimeType

            time_frac = Fraction(int(time_ms), 1)
            frame = vts.time_to_frame(time_frac, TimeType.EXACT)
            frame_start = vts.frame_to_time(frame, TimeType.START)

            return (float(frame_start), frame)

        except Exception:
            # Fallback to simple frame calculation
            frame_duration = 1000.0 / fps
            frame = int(time_ms / frame_duration)
            snapped = frame * frame_duration
            return (snapped, frame)

    def _time_to_frame(self, time_ms: float, vts, fps: float) -> int:
        """Convert time to frame number."""
        try:
            from video_timestamps import TimeType
            return vts.time_to_frame(Fraction(int(time_ms), 1), TimeType.EXACT)
        except Exception:
            return int(time_ms / (1000.0 / fps))

    def _frame_to_time(self, frame: int, vts, fps: float) -> float:
        """Convert frame number to time (frame start)."""
        try:
            from video_timestamps import TimeType
            return float(vts.frame_to_time(frame, TimeType.START))
        except Exception:
            return frame * (1000.0 / fps)
