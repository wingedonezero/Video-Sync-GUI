# vsg_core/subtitles/sync_mode_plugins/duration_align.py
"""
Duration-align sync plugin for SubtitleData.

Aligns subtitles by total video duration difference (frame alignment).
Optionally verifies alignment using hybrid frame matching.

All timing is float ms internally - rounding happens only at final save.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..sync_modes import SyncPlugin, register_sync_plugin

if TYPE_CHECKING:
    from ...models.settings import AppSettings
    from ..data import OperationResult, SubtitleData


@register_sync_plugin
class DurationAlignSync(SyncPlugin):
    """
    Duration-align sync mode.

    Aligns subtitles by total video duration difference.
    """

    name = "duration-align"
    description = "Align subtitles by total video duration difference"

    def apply(
        self,
        subtitle_data: SubtitleData,
        total_delay_ms: float,
        global_shift_ms: float,
        target_fps: float | None = None,
        source_video: str | None = None,
        target_video: str | None = None,
        runner=None,
        settings: AppSettings | None = None,
        temp_dir: Path | None = None,
        **kwargs,
    ) -> OperationResult:
        """
        Apply duration-align sync to subtitle data.

        Algorithm:
        1. Get total duration of source video (where subs are from)
        2. Get total duration of target video (Source 1)
        3. Calculate duration_offset = target_duration - source_duration
        4. Apply duration_offset + global_shift to all subtitle times
        5. Optionally verify with frame matching

        Args:
            subtitle_data: SubtitleData to modify
            total_delay_ms: Total delay (unused - we calculate from duration)
            global_shift_ms: Global shift from delays
            target_fps: Target video FPS
            source_video: Path to source video (where subs are from)
            target_video: Path to target video (Source 1)
            runner: CommandRunner for logging
            settings: AppSettings instance
            temp_dir: Temp directory for index files

        Returns:
            OperationResult with statistics
        """
        from ...models.settings import AppSettings
        from ..data import OperationRecord, OperationResult, SyncEventData
        from ..frame_utils import (
            detect_video_fps,
            frame_to_time_vfr,
            get_vapoursynth_frame_info,
            validate_frame_alignment,
        )
        from ..frame_verification import verify_alignment_with_sliding_window

        if settings is None:
            settings = AppSettings()

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log("[DurationAlign] === Duration-Align Sync ===")
        log(f"[DurationAlign] Events: {len(subtitle_data.events)}")

        if not source_video or not target_video:
            return OperationResult(
                success=False,
                operation="sync",
                error="Both source and target videos required for duration-align",
            )

        # Try to import VideoTimestamps
        try:
            from video_timestamps import FPSTimestamps, VideoTimestamps
        except ImportError:
            return OperationResult(
                success=False,
                operation="sync",
                error="VideoTimestamps library not installed",
            )

        log(f"[DurationAlign] Source: {Path(source_video).name}")
        log(f"[DurationAlign] Target: {Path(target_video).name}")

        # Get video durations - try VapourSynth first, fallback to ffprobe
        use_vapoursynth = settings.frame_use_vapoursynth

        source_frame_count = None
        source_duration_ms = None
        target_frame_count = None
        target_duration_ms = None

        if use_vapoursynth:
            log("[DurationAlign] Using VapourSynth for frame indexing")

            source_info = get_vapoursynth_frame_info(source_video, runner, temp_dir)
            if source_info:
                source_frame_count, source_duration_ms = source_info

            target_info = get_vapoursynth_frame_info(target_video, runner, temp_dir)
            if target_info:
                target_frame_count, target_duration_ms = target_info

        # Fallback to ffprobe if needed
        if source_duration_ms is None or target_duration_ms is None:
            log("[DurationAlign] Using ffprobe for duration detection")

            source_fps = (
                detect_video_fps(source_video, runner)
                if not source_duration_ms
                else None
            )
            target_fps_detected = (
                detect_video_fps(target_video, runner)
                if not target_duration_ms
                else None
            )

            try:
                import json
                import os
                import subprocess

                env = os.environ.copy()
                env["AV_LOG_FORCE_NOCOLOR"] = "1"

                if source_duration_ms is None:
                    cmd = [
                        "ffprobe",
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-count_frames",
                        "-show_entries",
                        "stream=nb_read_frames",
                        "-print_format",
                        "json",
                        source_video,
                    ]
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, env=env
                    )
                    source_info = json.loads(result.stdout)
                    source_frame_count = int(
                        source_info["streams"][0]["nb_read_frames"]
                    )
                    source_duration_ms = frame_to_time_vfr(
                        source_frame_count - 1,
                        source_video,
                        source_fps,
                        runner,
                        settings.to_dict(),
                    )

                if target_duration_ms is None:
                    cmd = [
                        "ffprobe",
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-count_frames",
                        "-show_entries",
                        "stream=nb_read_frames",
                        "-print_format",
                        "json",
                        target_video,
                    ]
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, env=env
                    )
                    target_info = json.loads(result.stdout)
                    target_frame_count = int(
                        target_info["streams"][0]["nb_read_frames"]
                    )
                    target_duration_ms = frame_to_time_vfr(
                        target_frame_count - 1,
                        target_video,
                        target_fps_detected or target_fps,
                        runner,
                        settings.to_dict(),
                    )

            except Exception as e:
                return OperationResult(
                    success=False,
                    operation="sync",
                    error=f"Failed to get video durations: {e}",
                )

        if source_duration_ms is None or target_duration_ms is None:
            return OperationResult(
                success=False,
                operation="sync",
                error="Failed to determine video durations",
            )

        # Calculate duration offset
        duration_offset_ms = float(target_duration_ms) - float(source_duration_ms)

        log(f"[DurationAlign] Source duration: {source_duration_ms}ms")
        log(f"[DurationAlign] Target duration: {target_duration_ms}ms")
        log(f"[DurationAlign] Duration offset: {duration_offset_ms:+.3f}ms")
        log(f"[DurationAlign] Global shift: {global_shift_ms:+.3f}ms")

        # Total shift = duration offset + global shift
        total_shift_ms = duration_offset_ms + global_shift_ms
        log(f"[DurationAlign] Total shift: {total_shift_ms:+.3f}ms")

        # Optionally verify with frame matching
        validation_result = {}
        use_hybrid_verification = settings.duration_align_verify_with_frames
        validate_enabled = settings.duration_align_validate

        if use_hybrid_verification:
            # Convert SubtitleData events to format expected by verification
            class EventWrapper:
                def __init__(self, event):
                    self.start = int(event.start_ms)
                    self.end = int(event.end_ms)
                    self.style = event.style

            wrapped_events = [
                EventWrapper(e) for e in subtitle_data.events if not e.is_comment
            ]

            validation_result = verify_alignment_with_sliding_window(
                source_video,
                target_video,
                wrapped_events,
                duration_offset_ms,
                runner,
                settings.to_dict(),
            )

            if validation_result.get("valid"):
                precise_offset = validation_result["precise_offset_ms"]
                log(f"[DurationAlign] ✓ Using precise offset: {precise_offset:+.3f}ms")
                total_shift_ms = precise_offset + global_shift_ms
            else:
                fallback_mode = settings.duration_align_fallback_mode
                log(f"[DurationAlign] Verification failed, fallback: {fallback_mode}")

                if fallback_mode == "abort":
                    return OperationResult(
                        success=False,
                        operation="sync",
                        error=f"Frame verification failed: {validation_result.get('error', 'Unknown')}",
                    )
                # Otherwise continue with duration offset

        elif validate_enabled:
            # Simple validation
            class EventWrapper:
                def __init__(self, event):
                    self.start = int(event.start_ms)
                    self.end = int(event.end_ms)
                    self.style = event.style

            wrapped_events = [
                EventWrapper(e) for e in subtitle_data.events if not e.is_comment
            ]

            validation_result = validate_frame_alignment(
                source_video,
                target_video,
                wrapped_events,
                duration_offset_ms,
                runner,
                settings.to_dict(),
                temp_dir,
            )

            if validation_result.get("enabled") and not validation_result.get("valid"):
                fallback_mode = settings.duration_align_fallback_mode
                log(f"[DurationAlign] Validation failed, fallback: {fallback_mode}")

                if fallback_mode == "abort":
                    return OperationResult(
                        success=False,
                        operation="sync",
                        error="Frame alignment validation failed",
                    )

        # Apply total shift to all events
        log(
            f"[DurationAlign] Applying {total_shift_ms:+.3f}ms to {len(subtitle_data.events)} events"
        )

        events_synced = 0
        for event in subtitle_data.events:
            if event.is_comment:
                continue

            original_start = event.start_ms
            original_end = event.end_ms

            event.start_ms += total_shift_ms
            event.end_ms += total_shift_ms

            # Populate per-event sync metadata
            event.sync = SyncEventData(
                original_start_ms=original_start,
                original_end_ms=original_end,
                start_adjustment_ms=total_shift_ms,
                end_adjustment_ms=total_shift_ms,
                snapped_to_frame=False,
            )

            events_synced += 1

        # Build summary
        summary = f"Duration-align: {events_synced} events, {total_shift_ms:+.1f}ms"
        if validation_result.get("valid"):
            summary += " (verified)"
        elif validation_result.get("warning"):
            summary += " (unverified)"

        # Record operation
        record = OperationRecord(
            operation="sync",
            timestamp=datetime.now(),
            parameters={
                "mode": self.name,
                "duration_offset_ms": duration_offset_ms,
                "global_shift_ms": global_shift_ms,
                "total_shift_ms": total_shift_ms,
                "source_duration_ms": source_duration_ms,
                "target_duration_ms": target_duration_ms,
            },
            events_affected=events_synced,
            summary=summary,
        )
        subtitle_data.operations.append(record)

        log(f"[DurationAlign] Sync complete: {events_synced} events")
        log("[DurationAlign] ===================================")

        return OperationResult(
            success=True,
            operation="sync",
            events_affected=events_synced,
            summary=summary,
            details={
                "duration_offset_ms": duration_offset_ms,
                "global_shift_ms": global_shift_ms,
                "total_shift_ms": total_shift_ms,
                "validation": validation_result,
            },
        )
