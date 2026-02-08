# vsg_core/subtitles/sync_mode_plugins/video_verified/plugin.py
"""
VideoVerifiedSync plugin class.

This is the SyncPlugin entry point that integrates with the subtitle pipeline.
The actual frame matching algorithm lives in matcher.py.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ...sync_modes import SyncPlugin, register_sync_plugin
from .matcher import calculate_video_verified_offset

if TYPE_CHECKING:
    from ....models.settings import AppSettings
    from ...data import OperationResult, SubtitleData


@register_sync_plugin
class VideoVerifiedSync(SyncPlugin):
    """
    Video-Verified sync mode.

    Uses audio correlation as starting point, then verifies with frame
    matching to determine the TRUE video-to-video offset for subtitle timing.

    Now handles ANY offset size (not just small offsets) and provides
    sub-frame precision using actual PTS timestamps from the video container.

    Features:
    - Works with large offsets like -1001ms (24+ frames)
    - Sub-frame accurate timing via PTS comparison
    - Robust median calculation from multiple checkpoints
    """

    name = "video-verified"
    description = "Audio correlation verified against video frame matching with sub-frame precision"

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
        Apply video-verified sync to subtitle data.

        Algorithm:
        1. Use audio correlation as starting point (any size)
        2. Generate candidate frame offsets around the correlation value
        3. Test each candidate at multiple checkpoints
        4. Select best matching frame offset
        5. Calculate sub-frame precise offset using PTS timestamps
        6. Apply final offset + global shift to all events

        Args:
            subtitle_data: SubtitleData to modify
            total_delay_ms: Total delay WITH global shift baked in
            global_shift_ms: Global shift that was added
            target_fps: Target video FPS
            source_video: Path to source video
            target_video: Path to target video
            runner: CommandRunner for logging
            settings: AppSettings with video-verified parameters
            temp_dir: Temp directory for index files

        Returns:
            OperationResult with statistics
        """
        from ....models.settings import AppSettings
        from ...data import OperationResult

        if settings is None:
            settings = AppSettings()

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log("[VideoVerified] === Video-Verified Sync Mode ===")
        log(f"[VideoVerified] Events: {len(subtitle_data.events)}")

        if not source_video or not target_video:
            return OperationResult(
                success=False,
                operation="sync",
                error="Both source and target videos required for video-verified mode",
            )

        # Calculate pure correlation for reference
        pure_correlation_ms = total_delay_ms - global_shift_ms

        # Estimate duration from subtitle events if available
        video_duration = None
        if subtitle_data.events:
            video_duration = max(e.end_ms for e in subtitle_data.events) + 60000

        # Use the unified calculate function (handles everything)
        final_offset_ms, details = calculate_video_verified_offset(
            source_video=source_video,
            target_video=target_video,
            total_delay_ms=total_delay_ms,
            global_shift_ms=global_shift_ms,
            settings=settings,
            runner=runner,
            temp_dir=temp_dir,
            video_duration_ms=video_duration,
        )

        if final_offset_ms is None:
            # Fallback to correlation on error
            final_offset_ms = total_delay_ms
            details["reason"] = details.get("reason", "fallback-error")

        # Apply the calculated offset
        video_offset_ms = details.get("video_offset_ms", pure_correlation_ms)
        selection_reason = details.get("reason", "unknown")

        # Generate job name from target video + track label for unique audit filenames
        video_stem = Path(target_video).stem if target_video else "unknown"
        track_label = kwargs.get("track_label", "")
        job_name = f"{video_stem}_{track_label}" if track_label else video_stem

        return self._apply_offset(
            subtitle_data,
            final_offset_ms,
            global_shift_ms,
            pure_correlation_ms,
            video_offset_ms,
            selection_reason,
            details,
            runner,
            settings=settings,
            target_fps=target_fps,
            job_name=job_name,
            source_video=source_video,
            target_video=target_video,
            temp_dir=temp_dir,
        )

    def _apply_offset(
        self,
        subtitle_data: SubtitleData,
        final_offset_ms: float,
        global_shift_ms: float,
        audio_correlation_ms: float,
        video_offset_ms: float,
        selection_reason: str,
        details: dict,
        runner,
        settings: AppSettings | None = None,
        target_fps: float | None = None,
        job_name: str = "unknown",
        source_video: str | None = None,
        target_video: str | None = None,
        temp_dir: Path | None = None,
    ) -> OperationResult:
        """Apply the calculated offset to all events."""
        from ...data import OperationRecord, OperationResult
        from ...sync_utils import apply_delay_to_events

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log(
            f"[VideoVerified] Applying {final_offset_ms:+.3f}ms to {len(subtitle_data.events)} events"
        )

        events_synced = apply_delay_to_events(subtitle_data, final_offset_ms)

        # Run frame alignment audit if enabled
        if settings and settings.video_verified_frame_audit and target_fps:
            self._run_frame_audit(
                subtitle_data=subtitle_data,
                fps=target_fps,
                offset_ms=final_offset_ms,
                job_name=job_name,
                settings=settings,
                log=log,
            )

        # Run visual frame verification if enabled
        if (
            settings
            and settings.video_verified_visual_verify
            and source_video
            and target_video
        ):
            self._run_visual_verify(
                source_video=source_video,
                target_video=target_video,
                details=details,
                job_name=job_name,
                settings=settings,
                temp_dir=temp_dir,
                log=log,
            )

        # Build summary
        if abs(video_offset_ms - audio_correlation_ms) > 1.0:
            summary = (
                f"VideoVerified: {events_synced} events, {final_offset_ms:+.1f}ms "
                f"(audio={audio_correlation_ms:+.0f}→video={video_offset_ms:+.0f})"
            )
        else:
            summary = f"VideoVerified: {events_synced} events, {final_offset_ms:+.1f}ms"

        # Record operation
        record = OperationRecord(
            operation="sync",
            timestamp=datetime.now(),
            parameters={
                "mode": self.name,
                "final_offset_ms": final_offset_ms,
                "global_shift_ms": global_shift_ms,
                "audio_correlation_ms": audio_correlation_ms,
                "video_offset_ms": video_offset_ms,
                "selection_reason": selection_reason,
            },
            events_affected=events_synced,
            summary=summary,
        )
        subtitle_data.operations.append(record)

        log(f"[VideoVerified] Sync complete: {events_synced} events")
        log("[VideoVerified] ===================================")

        return OperationResult(
            success=True,
            operation="sync",
            events_affected=events_synced,
            summary=summary,
            details={
                "audio_correlation_ms": audio_correlation_ms,
                "video_offset_ms": video_offset_ms,
                "final_offset_ms": final_offset_ms,
                "selection_reason": selection_reason,
                **details,
            },
        )

    def _run_frame_audit(
        self,
        subtitle_data: SubtitleData,
        fps: float,
        offset_ms: float,
        job_name: str,
        settings: AppSettings,
        log,
    ) -> None:
        """Run frame alignment audit and write report.

        This checks whether centisecond rounding will cause any subtitle
        events to land on wrong frames, and writes a detailed report.
        """
        from ...frame_utils.frame_audit import run_frame_audit, write_audit_report

        log("[FrameAudit] Running frame alignment audit...")

        # Get rounding mode from settings
        rounding_mode = settings.subtitle_rounding or "floor"

        # Run the audit
        result = run_frame_audit(
            subtitle_data=subtitle_data,
            fps=fps,
            rounding_mode=rounding_mode,
            offset_ms=offset_ms,
            job_name=job_name,
            log=log,
        )

        # Determine output directory
        # Use the program's .config directory (same as other config files)
        config_dir = Path.cwd() / ".config" / "sync_checks"

        # Write the report
        report_path = write_audit_report(result, config_dir, log)

        # Log summary
        total = result.total_events
        if total > 0:
            start_pct = 100 * result.start_ok / total
            end_pct = 100 * result.end_ok / total
            log(
                f"[FrameAudit] Start times OK: {result.start_ok}/{total} ({start_pct:.1f}%)"
            )
            log(f"[FrameAudit] End times OK: {result.end_ok}/{total} ({end_pct:.1f}%)")

            if result.has_issues:
                log(
                    f"[FrameAudit] Issues found: {len(result.issues)} events with frame drift"
                )
                log(
                    f"[FrameAudit] Suggested rounding mode: {self._get_best_rounding_mode(result)}"
                )
            else:
                log("[FrameAudit] No frame drift issues detected")

        log(f"[FrameAudit] Report saved: {report_path}")

    def _get_best_rounding_mode(self, result) -> str:
        """Get the rounding mode with fewest issues."""
        modes = [
            ("floor", result.floor_issues),
            ("round", result.round_issues),
            ("ceil", result.ceil_issues),
        ]
        return min(modes, key=lambda x: x[1])[0]

    def _run_visual_verify(
        self,
        source_video: str,
        target_video: str,
        details: dict,
        job_name: str,
        settings: AppSettings,
        temp_dir: Path | None,
        log,
    ) -> None:
        """Run visual frame verification across entire video and write report.

        This opens both videos raw with FFMS2 (no deinterlace/IVTC), samples
        frames at regular intervals, and compares them using global SSIM to
        verify the calculated offset is correct.
        """
        from ...frame_utils.visual_verify import (
            run_visual_verify,
            write_visual_verify_report,
        )

        log("[VisualVerify] Running visual frame verification...")

        offset_ms = details.get("video_offset_ms", 0.0)
        frame_offset = details.get("frame_offset", 0)
        source_fps = details.get("source_fps", 29.97)
        target_fps = details.get("target_fps", 29.97)
        source_content_type = details.get("source_content_type", "unknown")
        target_content_type = details.get("target_content_type", "unknown")

        try:
            result = run_visual_verify(
                source_video=source_video,
                target_video=target_video,
                offset_ms=offset_ms,
                frame_offset=frame_offset,
                source_fps=source_fps,
                target_fps=target_fps,
                job_name=job_name,
                temp_dir=temp_dir,
                source_content_type=source_content_type,
                target_content_type=target_content_type,
                log=log,
            )

            # Determine output directory
            config_dir = Path.cwd() / ".config" / "sync_checks"

            # Write the report
            report_path = write_visual_verify_report(result, config_dir, log)

            # Log summary
            log(
                f"[VisualVerify] Samples: {result.total_samples}, "
                f"Main content accuracy (±2): {result.accuracy_pct:.1f}%"
            )
            if result.credits.detected:
                log(
                    f"[VisualVerify] Credits detected at "
                    f"{result.credits.boundary_time_s:.0f}s"
                )
            log(f"[VisualVerify] Report saved: {report_path}")

        except Exception as e:
            log(f"[VisualVerify] ERROR: Visual verification failed: {e}")
            log("[VisualVerify] Skipping visual verification")
