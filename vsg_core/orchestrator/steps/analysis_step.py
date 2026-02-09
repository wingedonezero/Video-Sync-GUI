# vsg_core/orchestrator/steps/analysis_step.py
"""
Analysis step - pure coordinator.

Orchestrates audio/video correlation analysis by coordinating:
- Track selection
- Correlation execution
- Delay calculation
- Drift/stepping detection
- Global shift calculation

NO business logic - delegates to vsg_core/analysis/ modules.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from vsg_core.analysis.audio_corr import run_audio_correlation, run_multi_correlation
from vsg_core.analysis.container_delays import (
    calculate_delay_chain,
    find_actual_correlation_track_delay,
    get_container_delay_info,
)
from vsg_core.analysis.delay_selection import calculate_delay
from vsg_core.analysis.drift_detection import diagnose_audio_issue
from vsg_core.analysis.global_shift import (
    apply_global_shift_to_delays,
    calculate_global_shift,
)
from vsg_core.analysis.sync_stability import analyze_sync_stability
from vsg_core.analysis.track_selection import (
    format_track_details,
    select_audio_track,
)
from vsg_core.extraction.tracks import get_stream_info
from vsg_core.models.jobs import Delays

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.models.settings import AppSettings
    from vsg_core.orchestrator.steps.context import Context


def _should_use_source_separated_mode(
    source_key: str, settings: AppSettings, source_settings: dict[str, dict[str, Any]]
) -> bool:
    """
    Check if this source should use source separation during correlation.

    Uses per-source settings from the job layout. Source separation is only applied
    when explicitly enabled for the specific source via use_source_separation flag.

    Args:
        source_key: The source being analyzed (e.g., "Source 2", "Source 3")
        settings: AppSettings instance
        source_settings: Per-source correlation settings from job layout

    Returns:
        True if source separation should be applied to this comparison, False otherwise
    """
    # Check if source separation is configured at all (mode must be set)
    if settings.source_separation_mode == "none":
        return False

    # Check per-source setting - source separation must be explicitly enabled per-source
    per_source = source_settings.get(source_key, {})
    return per_source.get("use_source_separation", False)


class AnalysisStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            raise ValueError("Context is missing Source 1 for analysis.")

        # --- Part 1: Determine if a global shift is required ---
        settings = ctx.settings
        sync_mode = settings.sync_mode

        # Check if there are audio tracks from secondary sources
        has_secondary_audio = any(
            t.get("type") == "audio" and t.get("source") != "Source 1"
            for t in ctx.manual_layout
        )

        # Store sync mode in context for auditor
        ctx.sync_mode = sync_mode

        # Determine if global shift should be applied based on sync mode
        runner._log_message("=" * 60)
        runner._log_message(f"=== TIMING SYNC MODE: {sync_mode.upper()} ===")
        runner._log_message("=" * 60)

        if sync_mode == "allow_negative":
            # Mode 2: Force allow negatives even with secondary audio
            ctx.global_shift_is_required = False
            runner._log_message(
                "[SYNC MODE] Negative delays are ALLOWED (no global shift)."
            )
            runner._log_message("[SYNC MODE] Source 1 remains reference (delay = 0).")
            runner._log_message(
                "[SYNC MODE] Secondary sources can have negative delays."
            )
        elif sync_mode == "positive_only":
            # Mode 1: Default behavior - only apply global shift if secondary audio exists
            ctx.global_shift_is_required = has_secondary_audio
            if ctx.global_shift_is_required:
                runner._log_message(
                    "[SYNC MODE] Positive-only mode - global shift will eliminate negative delays."
                )
                runner._log_message(
                    "[SYNC MODE] All tracks will be shifted to be non-negative."
                )
            else:
                runner._log_message(
                    "[SYNC MODE] Positive-only mode (but no secondary audio detected)."
                )
                runner._log_message(
                    "[SYNC MODE] Global shift will not be applied (subtitle-only exception)."
                )
        else:
            # Unknown mode - fallback to default (positive_only)
            runner._log_message(
                f"[WARNING] Unknown sync_mode '{sync_mode}', falling back to 'positive_only'."
            )
            ctx.global_shift_is_required = has_secondary_audio

        # Skip analysis if only Source 1 (remux-only mode)
        if len(ctx.sources) == 1:
            runner._log_message(
                "--- Analysis Phase: Skipped (Remux-only mode - no sync sources) ---"
            )
            ctx.delays = Delays(
                source_delays_ms={},
                raw_source_delays_ms={},
                global_shift_ms=0,
                raw_global_shift_ms=0.0,
            )
            return ctx

        source_delays: dict[str, int] = {}
        raw_source_delays: dict[str, float] = {}

        # --- Step 1: Get Source 1's container delays for chain calculation ---
        runner._log_message("--- Getting Source 1 Container Delays for Analysis ---")
        source1_container_info = get_container_delay_info(
            source1_file, runner, ctx.tool_paths, log=runner._log_message
        )

        source1_audio_container_delay = 0.0
        source1_video_container_delay = 0.0

        if source1_container_info:
            source1_video_container_delay = source1_container_info.video_delay_ms

            # Select which Source 1 audio track will be used for correlation
            ref_lang = settings.analysis_lang_source1
            source1_stream_info = get_stream_info(source1_file, runner, ctx.tool_paths)

            if source1_stream_info:
                source1_audio_tracks = [
                    t
                    for t in source1_stream_info.get("tracks", [])
                    if t.get("type") == "audio"
                ]

                # Check if Source 1 has per-job track selection configured
                source1_settings = ctx.source_settings.get("Source 1", {})
                correlation_ref_track = source1_settings.get("correlation_ref_track")

                # Use track selection module
                source1_track_selection = select_audio_track(
                    audio_tracks=source1_audio_tracks,
                    language=ref_lang,
                    explicit_index=correlation_ref_track,
                    log=runner._log_message,
                    source_label="Source 1",
                )

                if source1_track_selection:
                    source1_audio_container_delay = (
                        source1_container_info.audio_delays_ms.get(
                            source1_track_selection.track_id, 0
                        )
                    )
                    ctx.source1_audio_container_delay_ms = source1_audio_container_delay

                    if source1_audio_container_delay != 0:
                        runner._log_message(
                            f"[Container Delay] Audio track {source1_track_selection.track_id} relative delay (audio relative to video): "
                            f"{source1_audio_container_delay:+.1f}ms. "
                            f"This will be added to all correlation results."
                        )

        # --- Step 2: Run correlation/videodiff for other sources ---
        is_videodiff_mode = (
            settings.analysis_mode == "VideoDiff"
            or settings.correlation_method == "VideoDiff"
        )

        if is_videodiff_mode:
            runner._log_message("\n--- Running VideoDiff (Frame Matching) Analysis ---")
        else:
            runner._log_message("\n--- Running Audio Correlation Analysis ---")

        # Track which sources have stepping for final report
        stepping_sources = []

        for source_key, source_file in sorted(ctx.sources.items()):
            if source_key == "Source 1":
                continue

            runner._log_message(f"\n[Analyzing {source_key}]")

            # ===================================================================
            # VideoDiff mode: frame-based analysis (no audio tracks needed)
            # ===================================================================
            if is_videodiff_mode:
                from vsg_core.analysis.videodiff import run_native_videodiff

                vd_result = run_native_videodiff(
                    str(source1_file),
                    str(source_file),
                    settings,
                    runner,
                    ctx.tool_paths,
                )

                correlation_delay_ms = vd_result.offset_ms
                correlation_delay_raw = vd_result.raw_offset_ms

                # Container delay chain still applies (video container delays)
                actual_container_delay = source1_video_container_delay

                final_delay_ms, final_delay_raw = calculate_delay_chain(
                    correlation_delay_ms,
                    correlation_delay_raw,
                    actual_container_delay,
                    log=runner._log_message,
                    source_key=source_key,
                )

                runner._log_message(
                    f"[VideoDiff] Confidence: {vd_result.confidence} "
                    f"(inliers: {vd_result.inlier_count}/{vd_result.matched_frames}, "
                    f"residual: {vd_result.mean_residual_ms:.1f}ms)"
                )

                if vd_result.speed_drift_detected:
                    runner._log_message(
                        "[VideoDiff] WARNING: Speed drift detected between sources. "
                        "The offset is valid but timing may drift over the video duration."
                    )

                source_delays[source_key] = final_delay_ms
                raw_source_delays[source_key] = final_delay_raw

                if ctx.audit:
                    ctx.audit.record_delay_calculation(
                        source_key=source_key,
                        correlation_raw_ms=correlation_delay_raw,
                        correlation_rounded_ms=correlation_delay_ms,
                        container_delay_ms=actual_container_delay,
                        final_raw_ms=final_delay_raw,
                        final_rounded_ms=final_delay_ms,
                        selection_method="VideoDiff",
                        accepted_chunks=vd_result.inlier_count,
                        total_chunks=vd_result.matched_frames,
                    )

                continue  # Skip audio correlation path for this source

            # ===================================================================
            # Audio Correlation Mode
            # ===================================================================

            # Get per-source settings for this source
            per_source_settings = ctx.source_settings.get(source_key, {})

            # Get explicit track indices
            correlation_source_track = per_source_settings.get(
                "correlation_source_track"
            )
            source1_settings = ctx.source_settings.get("Source 1", {})
            correlation_ref_track = source1_settings.get("correlation_ref_track")

            # Determine target language
            if correlation_source_track is not None:
                tgt_lang = None  # Bypassed by explicit track index
            else:
                tgt_lang = settings.analysis_lang_others

            # Log Source 1 track selection if per-job override exists
            if correlation_ref_track is not None and source1_stream_info:
                source1_audio_tracks = [
                    t
                    for t in source1_stream_info.get("tracks", [])
                    if t.get("type") == "audio"
                ]
                if 0 <= correlation_ref_track < len(source1_audio_tracks):
                    ref_track = source1_audio_tracks[correlation_ref_track]
                    runner._log_message(
                        f"[Source 1] Selected (explicit): {format_track_details(ref_track, correlation_ref_track)}"
                    )
                else:
                    runner._log_message(
                        f"[Source 1] WARNING: Invalid track index {correlation_ref_track}, using previously selected track"
                    )

            # Determine if source separation was applied
            use_source_separated_settings = _should_use_source_separated_mode(
                source_key, settings, ctx.source_settings
            )

            # Determine effective delay selection mode for this source
            if use_source_separated_settings:
                effective_delay_mode = settings.delay_selection_mode_source_separated
                runner._log_message(
                    "[Analysis Config] Source separation enabled - using:"
                )
                runner._log_message(
                    f"  Correlation: {settings.correlation_method_source_separated}"
                )
                runner._log_message(f"  Delay Mode: {effective_delay_mode}")
            else:
                effective_delay_mode = settings.delay_selection_mode
                runner._log_message("[Analysis Config] Standard mode - using:")
                runner._log_message(f"  Correlation: {settings.correlation_method}")
                runner._log_message(f"  Delay Mode: {effective_delay_mode}")

            # Get stream info and select target track
            stream_info = get_stream_info(source_file, runner, ctx.tool_paths)
            if not stream_info:
                runner._log_message(
                    f"[WARN] Could not get stream info for {source_key}. Skipping."
                )
                continue

            audio_tracks = [
                t for t in stream_info.get("tracks", []) if t.get("type") == "audio"
            ]
            if not audio_tracks:
                runner._log_message(
                    f"[WARN] No audio tracks found in {source_key}. Skipping."
                )
                continue

            # Select target track using module
            target_track_selection = select_audio_track(
                audio_tracks=audio_tracks,
                language=tgt_lang,
                explicit_index=correlation_source_track,
                log=runner._log_message,
                source_label=source_key,
            )

            if not target_track_selection:
                runner._log_message(
                    f"[WARN] No suitable audio track found in {source_key} for analysis. Skipping."
                )
                continue

            target_track_id = target_track_selection.track_id
            target_codec_id = (
                audio_tracks[target_track_selection.track_index]
                .get("properties", {})
                .get("codec_id", "unknown")
            )

            # Check if multi-correlation comparison is enabled (Analyze Only mode only)
            multi_corr_enabled = settings.multi_correlation_enabled and (
                not ctx.and_merge
            )

            if multi_corr_enabled:
                # Run multiple correlation methods for comparison
                all_method_results = run_multi_correlation(
                    str(source1_file),
                    str(source_file),
                    settings,
                    runner,
                    ctx.tool_paths,
                    ref_lang=settings.analysis_lang_source1,
                    target_lang=tgt_lang,
                    role_tag=source_key,
                    ref_track_index=correlation_ref_track,
                    target_track_index=correlation_source_track,
                    use_source_separation=use_source_separated_settings,
                )

                # Log summary for each method
                runner._log_message(f"\n{'═' * 70}")
                runner._log_message("  MULTI-CORRELATION SUMMARY")
                runner._log_message(f"{'═' * 70}")

                for method_name, method_results in all_method_results.items():
                    accepted = [r for r in method_results if r.get("accepted", False)]
                    if accepted:
                        delays = [r["delay"] for r in accepted]
                        raw_delays = [r["raw_delay"] for r in accepted]
                        mode_delay = Counter(delays).most_common(1)[0][0]
                        avg_match = sum(r["match"] for r in accepted) / len(accepted)
                        avg_raw = sum(raw_delays) / len(raw_delays)
                        runner._log_message(
                            f"  {method_name}: {mode_delay:+d}ms (raw avg: {avg_raw:+.3f}ms) | "
                            f"match: {avg_match:.1f}% | accepted: {len(accepted)}/{len(method_results)}"
                        )
                    else:
                        runner._log_message(f"  {method_name}: NO ACCEPTED CHUNKS")

                runner._log_message(f"{'═' * 70}\n")

                # Use the first method's results for actual processing
                first_method = next(iter(all_method_results.keys()))
                results = all_method_results[first_method]
                runner._log_message(
                    f"[MULTI-CORRELATION] Using '{first_method}' results for delay calculation"
                )
            else:
                # Normal single-method correlation
                results = run_audio_correlation(
                    str(source1_file),
                    str(source_file),
                    settings,
                    runner,
                    ctx.tool_paths,
                    ref_lang=settings.analysis_lang_source1,
                    target_lang=tgt_lang,
                    role_tag=source_key,
                    ref_track_index=correlation_ref_track,
                    target_track_index=correlation_source_track,
                    use_source_separation=use_source_separated_settings,
                )

            # --- Detect stepping BEFORE calculating mode delay ---
            diagnosis = None
            details = {}
            stepping_override_delay: int | None = None
            stepping_override_delay_raw: float | None = None
            stepping_enabled = settings.segmented_enabled

            # ALWAYS run diagnosis to detect stepping (even if correction is disabled)
            diagnosis, details = diagnose_audio_issue(
                video_path=source1_file,
                chunks=results,
                settings=settings,
                runner=runner,
                tool_paths=ctx.tool_paths,
                codec_id=target_codec_id,
            )

            # If stepping detected, handle based on whether correction is enabled
            if diagnosis == "STEPPING":
                # CRITICAL: Stepping correction doesn't work on source-separated audio
                if stepping_enabled and not use_source_separated_settings:
                    # Stepping correction is ENABLED - proceed with correction logic
                    stepping_sources.append(source_key)

                    # Check if any audio tracks from this source are being merged
                    has_audio_from_source = any(
                        t.get("type") == "audio" and t.get("source") == source_key
                        for t in ctx.manual_layout
                    )

                    if has_audio_from_source:
                        # Use stepping-specific stability criteria
                        from vsg_core.analysis.delay_selection import (
                            find_first_stable_segment_delay,
                        )

                        first_segment_delay = find_first_stable_segment_delay(
                            results,
                            settings,
                            return_raw=False,
                            log=runner._log_message,
                            override_min_chunks=settings.stepping_first_stable_min_chunks,
                            override_skip_unstable=settings.stepping_first_stable_skip_unstable,
                        )
                        first_segment_delay_raw = find_first_stable_segment_delay(
                            results,
                            settings,
                            return_raw=True,
                            log=runner._log_message,
                            override_min_chunks=settings.stepping_first_stable_min_chunks,
                            override_skip_unstable=settings.stepping_first_stable_skip_unstable,
                        )
                        if first_segment_delay is not None:
                            stepping_override_delay = first_segment_delay
                            stepping_override_delay_raw = first_segment_delay_raw
                            runner._log_message(
                                f"[Stepping Detected] Found stepping in {source_key}"
                            )
                            runner._log_message(
                                f"[Stepping Override] Using first segment's delay: {stepping_override_delay:+d}ms (raw: {stepping_override_delay_raw:.3f}ms)"
                            )
                            runner._log_message(
                                f"[Stepping Override] This delay will be used for ALL tracks (audio + subtitles) from {source_key}"
                            )
                            runner._log_message(
                                "[Stepping Override] Stepping correction will be applied to audio tracks during processing"
                            )
                    else:
                        # No audio tracks from this source - stepping correction won't run
                        runner._log_message(
                            f"[Stepping Detected] Found stepping in {source_key}"
                        )
                        runner._log_message(
                            "[Stepping] No audio tracks from this source are being merged"
                        )
                        runner._log_message(
                            f"[Stepping] Using delay_selection_mode='{effective_delay_mode}' instead of first segment (stepping correction won't run)"
                        )

                elif use_source_separated_settings:
                    # Source separation blocks stepping correction
                    ctx.stepping_detected_separated.append(source_key)
                    runner._log_message(
                        f"[Stepping Detected] Found stepping in {source_key}"
                    )
                    runner._log_message(
                        "[Stepping Disabled] Source separation is enabled - stepping correction is unreliable on separated stems"
                    )
                    runner._log_message(
                        "[Stepping Disabled] Separated stems have different waveform characteristics that break stepping detection"
                    )
                    runner._log_message(
                        f"[Stepping Disabled] Using delay_selection_mode='{effective_delay_mode}' instead"
                    )

                else:
                    # Stepping correction is DISABLED globally
                    ctx.stepping_detected_disabled.append(source_key)
                    runner._log_message(
                        f"⚠️  [Stepping Detected] Found stepping in {source_key}"
                    )
                    runner._log_message(
                        "⚠️  [Stepping Disabled] Stepping correction is disabled - timing may be inconsistent"
                    )
                    runner._log_message(
                        "⚠️  [Recommendation] Enable 'Stepping Correction' in settings if you want automatic correction"
                    )
                    runner._log_message(
                        "⚠️  [Manual Review] You should manually review this file's sync quality"
                    )

            # Use stepping override if available, otherwise calculate using configured mode
            if (
                stepping_override_delay is not None
                and stepping_override_delay_raw is not None
            ):
                correlation_delay_ms: int = stepping_override_delay
                correlation_delay_raw: float = stepping_override_delay_raw
                runner._log_message(
                    f"{source_key.capitalize()} delay determined: {correlation_delay_ms:+d} ms (first segment, stepping corrected)."
                )
            else:
                # Use delay selection module
                delay_calc = calculate_delay(
                    results=results,
                    settings=settings,
                    delay_mode=effective_delay_mode,
                    log=runner._log_message,
                    role_tag=source_key,
                )

                if delay_calc is None:
                    # ENHANCED ERROR MESSAGE
                    accepted_count = len(
                        [r for r in results if r.get("accepted", False)]
                    )
                    min_required = settings.min_accepted_chunks
                    total_chunks = len(results)

                    raise RuntimeError(
                        f"Analysis failed for {source_key}: Could not determine a reliable delay.\n"
                        f"  - Accepted chunks: {accepted_count}\n"
                        f"  - Minimum required: {min_required}\n"
                        f"  - Total chunks scanned: {total_chunks}\n"
                        f"  - Match threshold: {settings.min_match_pct}%\n"
                        f"\n"
                        f"Possible causes:\n"
                        f"  - Audio quality is too poor for reliable correlation\n"
                        f"  - Audio tracks are not from the same source material\n"
                        f"  - Excessive noise or compression artifacts\n"
                        f"  - Wrong language tracks selected for analysis\n"
                        f"\n"
                        f"Solutions:\n"
                        f'  - Try lowering the "Minimum Match %" threshold in settings\n'
                        f'  - Increase "Chunk Count" for more sample points\n'
                        f"  - Try selecting different audio tracks (check language settings)\n"
                        f"  - Use VideoDiff mode instead of Audio Correlation\n"
                        f"  - Check that both files are from the same video source"
                    )

                correlation_delay_ms = delay_calc.rounded_ms
                correlation_delay_raw = delay_calc.raw_ms

            # --- Sync Stability Analysis ---
            stepping_clusters = None
            if diagnosis == "STEPPING" and details:
                stepping_clusters = details.get("cluster_info", [])

            stability_result = analyze_sync_stability(
                chunk_results=results,
                source_key=source_key,
                settings=settings,
                log=runner._log_message,
                stepping_clusters=stepping_clusters,
            )

            if stability_result:
                ctx.sync_stability_issues.append(stability_result)

            # Calculate final delay including container delay chain correction
            actual_container_delay = source1_audio_container_delay

            # Determine which Source 1 track was actually used for correlation
            if source1_container_info and source1_stream_info:
                actual_container_delay = find_actual_correlation_track_delay(
                    container_info=source1_container_info,
                    stream_info=source1_stream_info,
                    correlation_ref_track=correlation_ref_track,
                    ref_lang=settings.analysis_lang_source1,
                    default_delay_ms=source1_audio_container_delay,
                    log=runner._log_message,
                )

            # Calculate final delay chain
            final_delay_ms, final_delay_raw = calculate_delay_chain(
                correlation_delay_ms,
                correlation_delay_raw,
                actual_container_delay,
                log=runner._log_message,
                source_key=source_key,
            )

            source_delays[source_key] = final_delay_ms
            raw_source_delays[source_key] = final_delay_raw

            # === AUDIT: Record delay calculation chain ===
            if ctx.audit:
                accepted_count = len([r for r in results if r.get("accepted", False)])
                ctx.audit.record_delay_calculation(
                    source_key=source_key,
                    correlation_raw_ms=correlation_delay_raw,
                    correlation_rounded_ms=correlation_delay_ms,
                    container_delay_ms=actual_container_delay,
                    final_raw_ms=final_delay_raw,
                    final_rounded_ms=final_delay_ms,
                    selection_method=effective_delay_mode,
                    accepted_chunks=accepted_count,
                    total_chunks=len(results),
                )

            # --- Handle drift detection flags ---
            if diagnosis:
                analysis_track_key = f"{source_key}_{target_track_id}"

                if diagnosis == "PAL_DRIFT":
                    if use_source_separated_settings:
                        runner._log_message(
                            f"[PAL Drift Detected] PAL drift detected in {source_key}, but source separation "
                            f"is enabled. PAL correction is unreliable on separated stems - skipping."
                        )
                    else:
                        source_has_audio_in_layout = any(
                            item.get("source") == source_key
                            and item.get("type") == "audio"
                            for item in ctx.manual_layout
                        )

                        if source_has_audio_in_layout:
                            ctx.pal_drift_flags[analysis_track_key] = details
                        else:
                            runner._log_message(
                                f"[PAL Drift Detected] PAL drift detected in {source_key}, but no audio tracks "
                                f"from this source are being used. Skipping PAL correction for {source_key}."
                            )

                elif diagnosis == "LINEAR_DRIFT":
                    if use_source_separated_settings:
                        runner._log_message(
                            f"[Linear Drift Detected] Linear drift detected in {source_key}, but source separation "
                            f"is enabled. Linear drift correction is unreliable on separated stems - skipping."
                        )
                    else:
                        source_has_audio_in_layout = any(
                            item.get("source") == source_key
                            and item.get("type") == "audio"
                            for item in ctx.manual_layout
                        )

                        if source_has_audio_in_layout:
                            ctx.linear_drift_flags[analysis_track_key] = details
                        else:
                            runner._log_message(
                                f"[Linear Drift Detected] Linear drift detected in {source_key}, but no audio tracks "
                                f"from this source are being used. Skipping linear drift correction for {source_key}."
                            )

                elif diagnosis == "STEPPING":
                    if use_source_separated_settings:
                        pass  # Already handled above
                    else:
                        source_has_audio_in_layout = any(
                            item.get("source") == source_key
                            and item.get("type") == "audio"
                            for item in ctx.manual_layout
                        )
                        source_has_subs_in_layout = any(
                            item.get("source") == source_key
                            and item.get("type") == "subtitles"
                            for item in ctx.manual_layout
                        )

                        if source_has_audio_in_layout:
                            ctx.segment_flags[analysis_track_key] = {
                                "base_delay": final_delay_ms,
                                "cluster_details": details.get("cluster_details", []),
                                "valid_clusters": details.get("valid_clusters", {}),
                                "invalid_clusters": details.get("invalid_clusters", {}),
                                "validation_results": details.get(
                                    "validation_results", {}
                                ),
                                "correction_mode": details.get(
                                    "correction_mode", "full"
                                ),
                                "fallback_mode": details.get(
                                    "fallback_mode", "nearest"
                                ),
                                "subs_only": False,
                            }
                            runner._log_message(
                                f"[Stepping] Stepping correction will be applied to audio tracks from {source_key}."
                            )
                        elif (
                            source_has_subs_in_layout
                            and settings.stepping_adjust_subtitles_no_audio
                        ):
                            runner._log_message(
                                f"[Stepping Detected] Stepping detected in {source_key}. No audio tracks "
                                f"from this source, but subtitles will use verified stepping EDL."
                            )
                            ctx.segment_flags[analysis_track_key] = {
                                "base_delay": final_delay_ms,
                                "cluster_details": details.get("cluster_details", []),
                                "valid_clusters": details.get("valid_clusters", {}),
                                "invalid_clusters": details.get("invalid_clusters", {}),
                                "validation_results": details.get(
                                    "validation_results", {}
                                ),
                                "correction_mode": details.get(
                                    "correction_mode", "full"
                                ),
                                "fallback_mode": details.get(
                                    "fallback_mode", "nearest"
                                ),
                                "subs_only": True,
                            }
                            runner._log_message(
                                "[Stepping] Full stepping analysis will run for verified subtitle EDL."
                            )
                        else:
                            runner._log_message(
                                f"[Stepping Detected] Stepping detected in {source_key}, but no audio or subtitle tracks "
                                f"from this source are being used. Skipping stepping correction."
                            )

        # Store stepping sources in context for final report
        ctx.stepping_sources = stepping_sources

        # Initialize Source 1 with 0ms base delay so it gets the global shift
        source_delays["Source 1"] = 0
        raw_source_delays["Source 1"] = 0.0

        # --- Step 3: Calculate Global Shift to Handle Negative Delays ---
        runner._log_message("\n--- Calculating Global Shift ---")

        # Use global shift module
        shift = calculate_global_shift(
            source_delays=source_delays,
            raw_source_delays=raw_source_delays,
            manual_layout=ctx.manual_layout,
            container_info=source1_container_info,
            global_shift_required=ctx.global_shift_is_required,
            log=runner._log_message,
        )

        # Apply global shift if needed
        if shift.applied:
            source_delays, raw_source_delays = apply_global_shift_to_delays(
                source_delays=source_delays,
                raw_source_delays=raw_source_delays,
                shift=shift,
                log=runner._log_message,
            )

            # Log Source 1 container delays after shift
            if source1_container_info and source1_stream_info:
                runner._log_message(
                    f"[Delay] Source 1 container delays (will have +{shift.shift_ms}ms added during mux):"
                )
                for track in source1_stream_info.get("tracks", []):
                    if track.get("type") in ["audio", "video"]:
                        tid = track.get("id")
                        if track.get("type") == "audio":
                            delay = source1_container_info.audio_delays_ms.get(tid, 0)
                        else:
                            delay = source1_container_info.video_delay_ms
                        final_delay = delay + shift.shift_ms
                        track_type = track.get("type")

                        note = (
                            " (will be ignored - video defines timeline)"
                            if track_type == "video"
                            else ""
                        )
                        runner._log_message(
                            f"  - Track {tid} ({track_type}): {delay:+.1f}ms → {final_delay:+.1f}ms{note}"
                        )

        # === AUDIT: Record global shift and final delays ===
        if ctx.audit:
            ctx.audit.record_global_shift(
                most_negative_raw_ms=shift.most_negative_raw_ms,
                most_negative_rounded_ms=shift.most_negative_ms,
                shift_raw_ms=shift.raw_shift_ms,
                shift_rounded_ms=shift.shift_ms,
                sync_mode=sync_mode,
            )
            for src_key in sorted(source_delays.keys()):
                ctx.audit.record_final_delay(
                    source_key=src_key,
                    raw_ms=raw_source_delays[src_key],
                    rounded_ms=source_delays[src_key],
                    includes_global_shift=True,
                )

        # Store the calculated delays with global shift
        ctx.delays = Delays(
            source_delays_ms=source_delays,
            raw_source_delays_ms=raw_source_delays,
            global_shift_ms=shift.shift_ms,
            raw_global_shift_ms=shift.raw_shift_ms,
        )

        # Final summary
        runner._log_message(
            f"\n[Delay] === FINAL DELAYS (Sync Mode: {sync_mode.upper()}, Global Shift: +{shift.shift_ms}ms) ==="
        )
        for source_key, delay_ms in sorted(source_delays.items()):
            runner._log_message(f"  - {source_key}: {delay_ms:+d}ms")

        if sync_mode == "allow_negative" and shift.shift_ms == 0:
            runner._log_message(
                "\n[INFO] Negative delays retained (allow_negative mode). Secondary sources may have negative delays."
            )
        elif shift.shift_ms > 0:
            runner._log_message(
                f"\n[INFO] All delays shifted by +{shift.shift_ms}ms to eliminate negatives."
            )

        return ctx
