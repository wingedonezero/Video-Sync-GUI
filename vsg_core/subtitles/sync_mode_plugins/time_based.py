# vsg_core/subtitles/sync_mode_plugins/time_based.py
"""
Time-based sync plugin for SubtitleData.

Simple delay application - applies raw delay to all events.
Used when mkvmerge --sync is not handling the delay.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ..sync_modes import SyncPlugin, register_sync_plugin

if TYPE_CHECKING:
    from ..data import OperationResult, SubtitleData


@register_sync_plugin
class TimeBasedSync(SyncPlugin):
    """
    Simple time-based sync - applies raw delay to all events.

    This is the baseline sync mode. For time-based with mkvmerge --sync,
    no subtitle modification is needed (handled by mkvmerge).
    """

    name = 'time-based'
    description = 'Simple delay application (or mkvmerge --sync)'

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
        **kwargs
    ) -> OperationResult:
        """
        Apply time-based sync.

        If config['time_based_use_raw_values'] is False (default),
        returns success with no changes (mkvmerge handles sync).

        If True, applies raw delay to subtitle events.
        """
        from ..data import OperationRecord, OperationResult

        config = config or {}

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        use_raw_values = config.get('time_based_use_raw_values', False)

        if not use_raw_values:
            # Default: mkvmerge --sync handles the delay
            log("[TimeBased] Using mkvmerge --sync mode (no subtitle modification)")

            record = OperationRecord(
                operation='sync',
                timestamp=datetime.now(),
                parameters={
                    'mode': 'time-based-mkvmerge',
                    'total_delay_ms': total_delay_ms,
                },
                events_affected=0,
                summary='Sync handled by mkvmerge --sync'
            )
            subtitle_data.operations.append(record)

            return OperationResult(
                success=True,
                operation='sync',
                events_affected=0,
                summary='mkvmerge --sync mode (no subtitle modification)',
                details={'method': 'mkvmerge_sync', 'delay_ms': total_delay_ms}
            )

        # Raw values mode: apply delay directly
        from ..data import SyncEventData

        log("[TimeBased] === Time-Based Sync (Raw Values) ===")
        log(f"[TimeBased] Events: {len(subtitle_data.events)}")
        log(f"[TimeBased] Delay: {total_delay_ms:+.3f}ms")

        events_synced = 0

        for event in subtitle_data.events:
            if event.is_comment:
                continue

            original_start = event.start_ms
            original_end = event.end_ms

            event.start_ms += total_delay_ms
            event.end_ms += total_delay_ms

            # Populate per-event sync metadata
            event.sync = SyncEventData(
                original_start_ms=original_start,
                original_end_ms=original_end,
                start_adjustment_ms=total_delay_ms,
                end_adjustment_ms=total_delay_ms,
                snapped_to_frame=False,
            )

            events_synced += 1

        record = OperationRecord(
            operation='sync',
            timestamp=datetime.now(),
            parameters={
                'mode': 'time-based-raw',
                'total_delay_ms': total_delay_ms,
            },
            events_affected=events_synced,
            summary=f"Applied {total_delay_ms:+.1f}ms delay to {events_synced} events"
        )
        subtitle_data.operations.append(record)

        log(f"[TimeBased] Applied delay to {events_synced} events")

        return OperationResult(
            success=True,
            operation='sync',
            events_affected=events_synced,
            summary=record.summary,
            details={'delay_ms': total_delay_ms, 'events_synced': events_synced}
        )
