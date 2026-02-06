# vsg_core/subtitles/sync_mode_plugins/correlation_frame_snap.py
"""
Correlation + Frame Snap sync plugin for SubtitleData.

Uses audio correlation as guide, then verifies frame alignment with scene detection
and sliding window matching.

All timing is float ms internally - rounding happens only at final save.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..sync_modes import SyncPlugin, register_sync_plugin

if TYPE_CHECKING:
    from pathlib import Path

    from ...models.settings import AppSettings
    from ..data import OperationResult, SubtitleData


@register_sync_plugin
class CorrelationFrameSnapSync(SyncPlugin):
    """
    Correlation + Frame Snap sync mode.

    Uses audio correlation as guide, then verifies with scene detection.
    """

    name = "correlation-frame-snap"
    description = "Audio correlation with frame snap verification"

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
        cached_frame_correction: dict[str, Any] | None = None,
        **kwargs,
    ) -> OperationResult:
        """
        Apply correlation + frame snap sync to subtitle data.

        Algorithm:
        1. Use correlation to guide where to search for matching frames
        2. At checkpoints, find actual matching frames via perceptual hashing
        3. Calculate precise offset from verified frame times
        4. Apply offset to all events

        Args:
            subtitle_data: SubtitleData to modify
            total_delay_ms: Total delay WITH global shift baked in
            global_shift_ms: Global shift that was added
            target_fps: Target video FPS
            source_video: Path to source video
            target_video: Path to target video
            runner: CommandRunner for logging
            settings: AppSettings instance
            cached_frame_correction: Optional cached result from previous track

        Returns:
            OperationResult with statistics
        """
        from ...models.settings import AppSettings
        from ..data import OperationRecord, OperationResult, SyncEventData
        from ..frame_utils import detect_video_fps
        from ..frame_verification import verify_correlation_with_frame_snap

        if settings is None:
            settings = AppSettings()

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log("[CorrFrameSnap] === Correlation + Frame Snap Sync ===")
        log(f"[CorrFrameSnap] Events: {len(subtitle_data.events)}")

        if not source_video or not target_video:
            return OperationResult(
                success=False,
                operation="sync",
                error="Both source and target videos required for correlation-frame-snap",
            )

        # Calculate pure correlation by subtracting global shift
        # total_delay_ms already has global_shift baked in from analysis
        pure_correlation_ms = total_delay_ms - global_shift_ms

        log(f"[CorrFrameSnap] Total delay (with global): {total_delay_ms:+.3f}ms")
        log(f"[CorrFrameSnap] Global shift: {global_shift_ms:+.3f}ms")
        log(f"[CorrFrameSnap] Pure correlation: {pure_correlation_ms:+.3f}ms")

        # Detect FPS
        fps = target_fps or detect_video_fps(source_video, runner)
        if not fps:
            fps = 23.976
            log(f"[CorrFrameSnap] FPS detection failed, using default: {fps}")

        frame_duration_ms = 1000.0 / fps
        log(f"[CorrFrameSnap] FPS: {fps:.3f} (frame: {frame_duration_ms:.3f}ms)")

        # Check for cached frame correction
        frame_correction_ms = 0.0
        verification_result = {}

        if cached_frame_correction is not None:
            cached_correction_ms = cached_frame_correction.get(
                "frame_correction_ms", 0.0
            )
            cached_num_scenes = cached_frame_correction.get("num_scene_matches", 0)

            log(
                f"[CorrFrameSnap] Using cached frame correction: {cached_correction_ms:+.3f}ms"
            )
            log(f"[CorrFrameSnap] (from {cached_num_scenes} scene matches)")

            frame_correction_ms = cached_correction_ms
            verification_result = {
                "valid": True,
                "cached": True,
                "frame_correction_ms": cached_correction_ms,
                "num_scene_matches": cached_num_scenes,
            }
        else:
            # Run scene detection and frame verification
            use_scene_changes = settings.correlation_snap_use_scene_changes

            if use_scene_changes:
                log("[CorrFrameSnap] Detecting scene changes...")

                # Create event wrapper for verification function
                class EventWrapper:
                    def __init__(self, event):
                        self.start = int(event.start_ms)
                        self.end = int(event.end_ms)
                        self.style = event.style

                wrapped_events = [
                    EventWrapper(e) for e in subtitle_data.events if not e.is_comment
                ]

                verification_result = verify_correlation_with_frame_snap(
                    source_video,
                    target_video,
                    wrapped_events,
                    pure_correlation_ms,
                    fps,
                    runner,
                    settings,
                )

                if verification_result.get("valid"):
                    frame_correction_ms = verification_result.get(
                        "frame_correction_ms", 0.0
                    )
                    num_matches = verification_result.get("num_scene_matches", 0)
                    log(
                        f"[CorrFrameSnap] ✓ Verification passed: {num_matches} scene matches"
                    )
                    log(
                        f"[CorrFrameSnap] Frame correction: {frame_correction_ms:+.3f}ms"
                    )
                else:
                    # Verification failed - handle fallback
                    fallback_mode = settings.correlation_snap_fallback_mode
                    log(
                        f"[CorrFrameSnap] Verification failed, fallback: {fallback_mode}"
                    )

                    if fallback_mode == "abort":
                        return OperationResult(
                            success=False,
                            operation="sync",
                            error="Frame verification failed",
                        )
                    elif fallback_mode == "use-raw":
                        frame_correction_ms = 0.0
                        log("[CorrFrameSnap] Using raw correlation (no correction)")
                    else:  # snap-to-frame
                        frame_delta = verification_result.get("frame_delta", 0)
                        frame_correction_ms = frame_delta * frame_duration_ms
                        log(
                            f"[CorrFrameSnap] Snapping to frame: {frame_delta} frames = {frame_correction_ms:+.3f}ms"
                        )

        # Calculate final offset
        # total_delay_ms already includes global_shift, just add frame correction
        final_offset_ms = total_delay_ms + frame_correction_ms

        log("[CorrFrameSnap] ───────────────────────────────────────")
        log("[CorrFrameSnap] Final offset calculation:")
        log(f"[CorrFrameSnap]   Total delay:       {total_delay_ms:+.3f}ms")
        log(f"[CorrFrameSnap]   + Frame correction: {frame_correction_ms:+.3f}ms")
        log(f"[CorrFrameSnap]   = Final offset:    {final_offset_ms:+.3f}ms")
        log("[CorrFrameSnap] ───────────────────────────────────────")

        # Apply offset to all events
        log(
            f"[CorrFrameSnap] Applying {final_offset_ms:+.3f}ms to {len(subtitle_data.events)} events"
        )

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
        summary = (
            f"Correlation+FrameSnap: {events_synced} events, {final_offset_ms:+.1f}ms"
        )
        if verification_result.get("valid"):
            num_matches = verification_result.get("num_scene_matches", 0)
            summary += f" ({num_matches} scenes verified)"
        elif verification_result.get("cached"):
            summary += " (cached)"

        # Record operation
        record = OperationRecord(
            operation="sync",
            timestamp=datetime.now(),
            parameters={
                "mode": self.name,
                "total_delay_ms": total_delay_ms,
                "global_shift_ms": global_shift_ms,
                "pure_correlation_ms": pure_correlation_ms,
                "frame_correction_ms": frame_correction_ms,
                "final_offset_ms": final_offset_ms,
                "fps": fps,
            },
            events_affected=events_synced,
            summary=summary,
        )
        subtitle_data.operations.append(record)

        log(f"[CorrFrameSnap] Sync complete: {events_synced} events")
        log("[CorrFrameSnap] ===================================")

        return OperationResult(
            success=True,
            operation="sync",
            events_affected=events_synced,
            summary=summary,
            details={
                "pure_correlation_ms": pure_correlation_ms,
                "frame_correction_ms": frame_correction_ms,
                "final_offset_ms": final_offset_ms,
                "verification": verification_result,
                "num_scene_matches": verification_result.get("num_scene_matches", 0),
            },
        )
