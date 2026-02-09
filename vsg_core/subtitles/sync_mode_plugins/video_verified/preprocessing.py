# vsg_core/subtitles/sync_mode_plugins/video_verified/preprocessing.py
"""
Video-verified preprocessing for subtitle synchronization.

Pre-computes frame-corrected delays for all subtitle sources by running
video-to-video frame matching once per source (not per track).

This optimization:
- Runs frame matching ONCE per source (e.g., Source 2 vs Source 1)
- Caches result in ctx.video_verified_sources
- All subtitle tracks from that source use the cached delay
- Includes visual verification output if enabled
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context

from .matcher import calculate_video_verified_offset


def run_per_source_preprocessing(
    ctx: Context, runner: CommandRunner, source1_file: Path
) -> None:
    """
    Run video-verified frame matching once per unique source.

    This pre-computes the frame-corrected delays for all sources that have
    subtitle tracks, updating ctx.delays so that ALL subtitle tracks from
    each source (text, bitmap, OCR'd, preserved) use the corrected delay.

    Only runs in video-verified mode.

    Updates:
        ctx.video_verified_sources: Cache of computed delays per source
        ctx.delays.source_delays_ms: Rounded delays for mkvmerge
        ctx.delays.raw_source_delays_ms: Raw float delays for SubtitleData
    """
    runner._log_message(
        "[VideoVerified] ═══════════════════════════════════════════════════════"
    )
    runner._log_message("[VideoVerified] Video-to-Video Frame Alignment")
    runner._log_message(
        "[VideoVerified] ═══════════════════════════════════════════════════════"
    )
    runner._log_message(
        f"[VideoVerified] Reference: Source 1 ({Path(source1_file).name})"
    )

    # Find unique sources that have subtitle tracks
    sources_with_subs = set()
    for item in ctx.extracted_items:
        if item.track.type == "subtitles":
            source_key = (
                item.sync_to if item.track.source == "External" else item.track.source
            )
            # Skip Source 1 - it's the reference, delay is always 0 + global_shift
            if source_key != "Source 1":
                sources_with_subs.add(source_key)

    if not sources_with_subs:
        runner._log_message(
            "[VideoVerified] No subtitle tracks from other sources, skipping"
        )
        return

    runner._log_message(
        f"[VideoVerified] Aligning: {', '.join(sorted(sources_with_subs))} → Source 1"
    )

    # Process each source
    for source_key in sorted(sources_with_subs):
        source_video = ctx.sources.get(source_key)
        if not source_video:
            runner._log_message(
                f"[VideoVerified] WARNING: No video file for {source_key}, skipping"
            )
            continue

        runner._log_message(f"\n[VideoVerified] ─── {source_key} vs Source 1 ───")

        # Get delays for this source
        total_delay_ms = 0.0
        global_shift_ms = 0.0
        if ctx.delays:
            if source_key in ctx.delays.raw_source_delays_ms:
                total_delay_ms = ctx.delays.raw_source_delays_ms[source_key]
            global_shift_ms = ctx.delays.raw_global_shift_ms

        original_delay = total_delay_ms

        try:
            # Calculate frame-corrected delay
            corrected_delay_ms, details = calculate_video_verified_offset(
                source_video=str(source_video),
                target_video=str(source1_file),
                total_delay_ms=total_delay_ms,
                global_shift_ms=global_shift_ms,
                settings=ctx.settings,
                runner=runner,
                temp_dir=ctx.temp_dir,
            )

            if corrected_delay_ms is not None and ctx.delays:
                # Update both raw and rounded delays
                if source_key in ctx.delays.source_delays_ms:
                    ctx.delays.source_delays_ms[source_key] = round(corrected_delay_ms)
                if source_key in ctx.delays.raw_source_delays_ms:
                    ctx.delays.raw_source_delays_ms[source_key] = corrected_delay_ms

                # Store that we've processed this source
                ctx.video_verified_sources[source_key] = {
                    "original_delay_ms": original_delay,
                    "corrected_delay_ms": corrected_delay_ms,
                    "details": details,
                }

                # Report the result - always show both values for transparency
                frame_diff_ms = corrected_delay_ms - original_delay
                runner._log_message(
                    f"[VideoVerified] ✓ {source_key} → Source 1: {corrected_delay_ms:+.3f}ms "
                    f"(audio: {original_delay:+.3f}ms, delta: {frame_diff_ms:+.3f}ms)"
                )

                # Run visual verification once per source (not per track)
                job_name = (
                    f"{Path(str(source_video)).stem}_vs_{Path(str(source1_file)).stem}"
                )
                _run_visual_verify_if_enabled(
                    source_video=source_video,
                    target_video=source1_file,
                    details=details,
                    job_name=job_name,
                    ctx=ctx,
                    runner=runner,
                )
            else:
                runner._log_message(
                    f"[VideoVerified] ✗ {source_key}: frame matching failed, using audio correlation"
                )

        except Exception as e:
            runner._log_message(f"[VideoVerified] ✗ {source_key}: ERROR - {e}")

    runner._log_message(
        "\n[VideoVerified] ═══════════════════════════════════════════════════════"
    )
    runner._log_message("[VideoVerified] Frame alignment complete")
    runner._log_message(
        "[VideoVerified] ═══════════════════════════════════════════════════════\n"
    )


def apply_for_bitmap_subtitle(
    item, ctx: Context, runner: CommandRunner, source1_file: Path | None
) -> None:
    """
    Apply video-verified frame matching for bitmap subtitles (VobSub, PGS).

    NOTE: This method is now mostly a fallback. The main video-verified
    processing happens in run_per_source_preprocessing() which runs
    once per source at the start of the subtitles step.

    Since bitmap subtitles can't be loaded into SubtitleData, we use the
    video-verified logic to calculate the correct delay, then store it
    so mkvmerge can apply it via --sync.

    This provides frame-accurate sync for image-based subtitle formats
    without requiring OCR.
    """
    ext = item.extracted_path.suffix.lower() if item.extracted_path else "unknown"
    source_key = item.sync_to if item.track.source == "External" else item.track.source

    # Source 1 is the reference - no frame matching needed
    # (Would compare against itself which is meaningless)
    if source_key == "Source 1":
        runner._log_message(
            f"[VideoVerified] Bitmap track {item.track.id} ({ext}): Source 1 is reference, skipping frame matching"
        )
        return

    # Check if this source was already processed in the per-source pre-processing step
    if source_key in ctx.video_verified_sources:
        cached = ctx.video_verified_sources[source_key]
        runner._log_message(
            f"[VideoVerified] Bitmap track {item.track.id} ({ext}): using pre-computed delay for {source_key}"
        )
        runner._log_message(
            f"[VideoVerified]   Delay: {cached['corrected_delay_ms']:+.1f}ms (was {cached['original_delay_ms']:+.1f}ms)"
        )
        item.video_verified_bitmap = True
        item.video_verified_details = cached["details"]
        return

    # Fallback: run frame matching for this track if not pre-processed
    # This shouldn't normally happen, but provides a safety net
    runner._log_message(
        f"[VideoVerified] Processing bitmap subtitle track {item.track.id} ({ext}) (fallback mode)"
    )

    source_video = ctx.sources.get(source_key)
    target_video = source1_file

    if not source_video or not target_video:
        runner._log_message(
            f"[VideoVerified] Missing videos for track {item.track.id}, using correlation delay"
        )
        return

    # Get delays
    total_delay_ms = 0.0
    global_shift_ms = 0.0
    if ctx.delays:
        if source_key in ctx.delays.raw_source_delays_ms:
            total_delay_ms = ctx.delays.raw_source_delays_ms[source_key]
        global_shift_ms = ctx.delays.raw_global_shift_ms

    runner._log_message(
        f"[VideoVerified] Bitmap sub: Correlation delay = {total_delay_ms:+.3f}ms"
    )

    try:
        # Calculate frame-corrected delay using video matching
        corrected_delay_ms, details = calculate_video_verified_offset(
            source_video=str(source_video),
            target_video=str(target_video),
            total_delay_ms=total_delay_ms,
            global_shift_ms=global_shift_ms,
            settings=ctx.settings,
            runner=runner,
            temp_dir=ctx.temp_dir,
        )

        if corrected_delay_ms is not None:
            # Store the corrected delay for mkvmerge
            # Update the delay in the context so options_builder uses it
            if ctx.delays and source_key in ctx.delays.source_delays_ms:
                old_delay = ctx.delays.source_delays_ms[source_key]
                ctx.delays.source_delays_ms[source_key] = round(corrected_delay_ms)

                # Also update raw delays for consistency
                if source_key in ctx.delays.raw_source_delays_ms:
                    ctx.delays.raw_source_delays_ms[source_key] = corrected_delay_ms

                runner._log_message(
                    f"[VideoVerified] Bitmap sub delay updated: {old_delay}ms → {round(corrected_delay_ms)}ms"
                )

                # Mark that we applied video-verified correction
                item.video_verified_bitmap = True
                item.video_verified_details = details

                if abs(corrected_delay_ms - total_delay_ms) > 1:
                    runner._log_message(
                        f"[VideoVerified] ⚠ Frame correction changed delay by {corrected_delay_ms - total_delay_ms:+.1f}ms"
                    )
        else:
            runner._log_message(
                "[VideoVerified] Frame matching returned None, using correlation delay"
            )
            runner._log_message(
                f"[VideoVerified] Reason: {details.get('reason', 'unknown')}"
            )

    except Exception as e:
        runner._log_message(f"[VideoVerified] ERROR during frame matching: {e}")
        runner._log_message(
            f"[VideoVerified] Falling back to correlation delay for track {item.track.id}"
        )


def _run_visual_verify_if_enabled(
    source_video,
    target_video,
    details: dict,
    job_name: str,
    ctx: Context,
    runner: CommandRunner,
) -> None:
    """
    Run visual frame verification if enabled in settings.

    This is called from the per-source preprocessing to generate
    visual comparison reports for video-to-video frame alignment.
    """
    if not ctx.settings.video_verified_visual_verify:
        return
    if not source_video or not target_video:
        runner._log_message("[VisualVerify] Skipped: video paths not available")
        return

    try:
        from vsg_core.subtitles.frame_utils.visual_verify import (
            run_visual_verify,
            write_visual_verify_report,
        )

        runner._log_message("[VisualVerify] Running visual frame verification...")

        offset_ms = details.get("video_offset_ms", 0.0)
        frame_offset = details.get("frame_offset", 0)
        source_fps = details.get("source_fps", 29.97)
        target_fps = details.get("target_fps", 29.97)
        source_content_type = details.get("source_content_type", "unknown")
        target_content_type = details.get("target_content_type", "unknown")

        result = run_visual_verify(
            source_video=str(source_video),
            target_video=str(target_video),
            offset_ms=offset_ms,
            frame_offset=frame_offset,
            source_fps=source_fps,
            target_fps=target_fps,
            job_name=job_name,
            temp_dir=ctx.temp_dir,
            source_content_type=source_content_type,
            target_content_type=target_content_type,
            log=runner._log_message,
        )

        config_dir = Path.cwd() / ".config" / "sync_checks"
        report_path = write_visual_verify_report(
            result, config_dir, runner._log_message
        )

        runner._log_message(
            f"[VisualVerify] Samples: {result.total_samples}, "
            f"Main content accuracy (±2): {result.accuracy_pct:.1f}%"
        )
        if result.credits.detected:
            runner._log_message(
                f"[VisualVerify] Credits detected at "
                f"{result.credits.boundary_time_s:.0f}s"
            )
        runner._log_message(f"[VisualVerify] Report saved: {report_path}")

    except Exception as e:
        runner._log_message(f"[VisualVerify] WARNING: Verification failed - {e}")
