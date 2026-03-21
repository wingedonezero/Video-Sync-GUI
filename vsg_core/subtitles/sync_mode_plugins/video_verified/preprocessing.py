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


def _calculate_offset_for_method(
    source_video: str,
    target_video: str,
    total_delay_ms: float,
    global_shift_ms: float,
    ctx,
    runner,
    source_key: str = "",
) -> tuple[float | None, dict]:
    """Dispatch to classic or neural matcher based on settings.

    For neural mode, optionally runs in a subprocess to isolate GPU usage.
    """
    method = getattr(ctx.settings, "video_verified_method", "classic")

    if method == "neural":
        return _run_neural_matching(
            source_video=source_video,
            target_video=target_video,
            total_delay_ms=total_delay_ms,
            global_shift_ms=global_shift_ms,
            ctx=ctx,
            runner=runner,
            source_key=source_key,
        )

    # Classic method (default)
    return calculate_video_verified_offset(
        source_video=source_video,
        target_video=target_video,
        total_delay_ms=total_delay_ms,
        global_shift_ms=global_shift_ms,
        settings=ctx.settings,
        runner=runner,
        temp_dir=ctx.temp_dir,
    )


def _run_neural_matching(
    source_video: str,
    target_video: str,
    total_delay_ms: float,
    global_shift_ms: float,
    ctx,
    runner,
    source_key: str = "",
) -> tuple[float | None, dict]:
    """Run neural feature matching, optionally in a subprocess."""
    import json

    use_subprocess = getattr(ctx.settings, "neural_run_in_subprocess", True)

    # Determine debug output dir
    debug_output_dir = None
    if getattr(ctx.settings, "neural_debug_report", False):
        debug_paths = getattr(ctx, "debug_paths", None)
        if debug_paths and debug_paths.neural_verify_dir:
            debug_output_dir = debug_paths.neural_verify_dir

    if not use_subprocess:
        # Run in-process (simpler, but shares GPU memory with main app)
        from .neural_matcher import calculate_neural_verified_offset

        return calculate_neural_verified_offset(
            source_video=source_video,
            target_video=target_video,
            total_delay_ms=total_delay_ms,
            global_shift_ms=global_shift_ms,
            settings=ctx.settings,
            runner=runner,
            temp_dir=ctx.temp_dir,
            debug_output_dir=debug_output_dir,
            source_key=source_key,
        )

    # Subprocess mode — isolate ISC model in separate process
    import subprocess
    import sys

    runner._log_message("[NeuralVerified] Running in subprocess (GPU isolation)...")

    # Write config JSON for subprocess
    config_path = Path(ctx.temp_dir) / "neural_config.json"
    output_path = Path(ctx.temp_dir) / "neural_result.json"

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(ctx.settings.model_dump(), f, indent=2, ensure_ascii=False)

    # Build subprocess command
    # NOTE: Use --flag=value syntax for numeric args to prevent argparse
    # from misinterpreting negative numbers (e.g. -3.36e-09) as flags
    cmd = [
        sys.executable,
        "-m",
        "vsg_core.subtitles.sync_mode_plugins.video_verified.neural_subprocess",
        "--source-video",
        str(source_video),
        "--target-video",
        str(target_video),
        f"--total-delay-ms={total_delay_ms}",
        f"--global-shift-ms={global_shift_ms}",
        "--config-json",
        str(config_path),
        "--output-json",
        str(output_path),
    ]

    if source_key:
        cmd.extend(["--source-key", source_key])

    if ctx.temp_dir:
        cmd.extend(["--temp-dir", str(ctx.temp_dir)])

    if debug_output_dir:
        cmd.extend(["--debug-output-dir", str(debug_output_dir)])

    # Log command for debugging (shows exact argument values)
    runner._log_message(
        f"[NeuralVerified] Subprocess cmd: {' '.join(repr(c) for c in cmd)}"
    )

    # Run subprocess
    json_prefix = "__VSG_NEURAL_JSON__ "
    json_payload = None

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        # Forward stdout (log messages + JSON result)
        if process.stdout:
            for line in process.stdout:
                line = line.rstrip("\n")
                if line.startswith(json_prefix):
                    try:
                        json_payload = json.loads(line.split(json_prefix, 1)[1])
                    except json.JSONDecodeError:
                        json_payload = None
                elif line:
                    runner._log_message(line)

        return_code = process.wait()

        # Log any stderr (filter noise from model libraries)
        if process.stderr:
            for line in process.stderr:
                line = line.rstrip("\n")
                if line and not line.startswith("Downloading:"):
                    runner._log_message(f"[NeuralVerified] stderr: {line}")

        if return_code != 0:
            error_detail = None
            if json_payload and not json_payload.get("success"):
                error_detail = json_payload.get("error")
            runner._log_message(
                f"[NeuralVerified] ERROR: Subprocess failed (code {return_code})"
            )
            if error_detail:
                runner._log_message(f"[NeuralVerified] ERROR: {error_detail}")
            return None, {
                "reason": "fallback-subprocess-failed",
                "error": error_detail or f"Exit code {return_code}",
            }

        if not json_payload or not json_payload.get("success"):
            runner._log_message("[NeuralVerified] ERROR: Subprocess returned no result")
            return None, {"reason": "fallback-subprocess-no-result"}

        # Load result from JSON
        with open(output_path, encoding="utf-8") as f:
            result = json.load(f)

        return result["final_offset_ms"], result["details"]

    except Exception as e:
        runner._log_message(f"[NeuralVerified] ERROR: Subprocess launch failed: {e}")
        return None, {"reason": "fallback-subprocess-error", "error": str(e)}


def run_per_source_preprocessing(
    ctx: Context, runner: CommandRunner, source1_file: Path
) -> None:
    """
    Run video-verified frame matching once per unique source.

    This pre-computes the frame-corrected delays for all sources that have
    subtitle tracks, storing them in ctx.subtitle_delays_ms so that ALL subtitle
    tracks from each source (text, bitmap, OCR'd, preserved) use the corrected delay.

    CRITICAL: Does NOT modify ctx.delays.source_delays_ms (used by audio tracks).
    Only runs in video-verified mode.

    Updates:
        ctx.video_verified_sources: Cache of computed delays per source
        ctx.subtitle_delays_ms: Frame-corrected delays for subtitle tracks only
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

    # Detect Source 1 properties and cache for later use
    from ...frame_utils import detect_video_properties

    source1_props = detect_video_properties(str(source1_file), runner)
    ctx.video_properties["Source 1"] = source1_props

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

        # Detect source video properties and cache
        source_props = detect_video_properties(str(source_video), runner)
        ctx.video_properties[source_key] = source_props

        # Gate: skip frame matching for MPEG-2 (DVD) or interlaced content.
        # MPEG-2 metadata is unreliable for distinguishing soft telecine,
        # hard telecine, and true interlaced — all use correlation for now.
        # Non-MPEG-2 interlaced (e.g., H.264 Blu-ray) is reliably detected
        # by ffprobe and also skips frame matching.
        codec = source_props.get("codec_name", "")
        is_mpeg2 = codec in ("mpeg2video", "mpeg1video")
        content_type = source_props.get("content_type", "unknown")

        if is_mpeg2 or content_type == "interlaced":
            reason = "MPEG-2" if is_mpeg2 else "interlaced"
            runner._log_message(
                f"[VideoVerified] {source_key}: {reason} content detected "
                f"(type={content_type}, codec={codec})"
            )
            runner._log_message(
                f"[VideoVerified] {source_key}: skipping frame matching, "
                f"using audio correlation ({original_delay:+.1f}ms)"
            )
            ctx.video_verified_sources[source_key] = {
                "original_delay_ms": original_delay,
                "corrected_delay_ms": original_delay,
                "details": {
                    "reason": f"skipped-{reason}-content",
                    "content_type": content_type,
                    "codec": codec,
                },
                "fallback": True,
            }
            ctx.subtitle_delays_ms[source_key] = original_delay
            continue

        try:
            # Calculate frame-corrected delay (dispatches to classic or neural)
            corrected_delay_ms, details = _calculate_offset_for_method(
                source_video=str(source_video),
                target_video=str(source1_file),
                total_delay_ms=total_delay_ms,
                global_shift_ms=global_shift_ms,
                source_key=source_key,
                ctx=ctx,
                runner=runner,
            )

            if corrected_delay_ms is not None and ctx.delays:
                # CRITICAL: Store video-verified delay in SUBTITLE-SPECIFIC storage
                # This ensures audio tracks continue using audio correlation delays
                # while subtitle tracks get frame-corrected delays
                ctx.subtitle_delays_ms[source_key] = corrected_delay_ms

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
                # Store fallback so per-track processing uses audio correlation
                # instead of re-running classic frame matching from scratch
                ctx.video_verified_sources[source_key] = {
                    "original_delay_ms": original_delay,
                    "corrected_delay_ms": original_delay,
                    "details": details,
                    "fallback": True,
                }
                ctx.subtitle_delays_ms[source_key] = original_delay

        except Exception as e:
            runner._log_message(f"[VideoVerified] ✗ {source_key}: ERROR - {e}")
            # Store fallback on exception too — same reasoning
            ctx.video_verified_sources[source_key] = {
                "original_delay_ms": original_delay,
                "corrected_delay_ms": original_delay,
                "details": {"reason": f"fallback-exception: {e}"},
                "fallback": True,
            }
            ctx.subtitle_delays_ms[source_key] = original_delay

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
        # Calculate frame-corrected delay (dispatches to classic or neural)
        corrected_delay_ms, details = _calculate_offset_for_method(
            source_video=str(source_video),
            target_video=str(target_video),
            total_delay_ms=total_delay_ms,
            global_shift_ms=global_shift_ms,
            ctx=ctx,
            runner=runner,
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

        # Use debug_paths if available (new organized structure), fallback to old location
        if ctx.debug_paths and ctx.debug_paths.visual_verify_dir:
            config_dir = ctx.debug_paths.visual_verify_dir
        else:
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
