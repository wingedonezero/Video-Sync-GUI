# vsg_core/orchestrator/steps/analysis_step.py
"""
Analysis step - micro-orchestrator for audio correlation analysis.

This step coordinates the analysis workflow:
1. Get container delays from Source 1
2. For each secondary source:
   - Select tracks for correlation
   - Build source-specific config
   - Run correlation
   - Run diagnosis (drift/stepping detection)
   - Select delay
   - Apply diagnosis flags
   - Calculate final delay with container chain
3. Calculate global shift if needed
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from vsg_core.analysis.audio_corr import run_audio_correlation, run_multi_correlation
from vsg_core.analysis.config_builder import (
    build_source_config,
    get_correlation_track_settings,
    get_reference_track_settings,
)
from vsg_core.analysis.delay_calculation import (
    apply_global_shift,
    calculate_final_delay,
    calculate_global_shift,
    convert_to_relative_delays,
    extract_container_delays,
)
from vsg_core.analysis.delay_selection import (
    find_first_stable_segment_delay,
    select_delay,
)
from vsg_core.analysis.diagnostics import (
    apply_diagnosis_flags,
    diagnose_audio_issue,
)
from vsg_core.analysis.sync_stability import analyze_sync_stability
from vsg_core.analysis.track_selection import (
    format_track_details,
    get_audio_tracks,
    select_audio_track,
)
from vsg_core.extraction.tracks import get_stream_info, get_stream_info_with_delays
from vsg_core.io.runner import CommandRunner
from vsg_core.models import Context, Delays


def _choose_delay(
    results: list[dict[str, Any]],
    config: dict[str, Any],
    runner: CommandRunner,
    role_tag: str,
) -> tuple[int | None, float | None]:
    """
    Select final delay from correlation results using configured mode.

    This is a thin wrapper around the modular delay_selection.select_delay() function.

    Args:
        results: Correlation chunk results
        config: Configuration with delay_selection_mode and related settings
        runner: CommandRunner for logging
        role_tag: Source identifier for log messages

    Returns:
        Tuple of (rounded_delay_ms, raw_delay_ms) or (None, None) if failed
    """
    delay_mode = config.get("delay_selection_mode", "Mode (Most Common)")
    rounded_ms, raw_ms = select_delay(
        results=results,
        mode=delay_mode,
        config=config,
        log=runner._log_message,
    )

    if rounded_ms is not None:
        # Format method label for logging
        method_label = delay_mode.lower().replace("(", "").replace(")", "").strip()
        runner._log_message(
            f"{role_tag.capitalize()} delay determined: {rounded_ms:+d} ms ({method_label})."
        )

    return rounded_ms, raw_ms


class AnalysisStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            raise ValueError("Context is missing Source 1 for analysis.")

        # --- Part 1: Determine if a global shift is required ---
        config = ctx.settings_dict
        sync_mode = config.get("sync_mode", "positive_only")

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

        # NEW: Skip analysis if only Source 1 (remux-only mode)
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
        raw_source_delays: dict[str, float] = (
            {}
        )  # Unrounded delays for VideoTimestamps precision

        # --- Step 1: Get Source 1's container delays for chain calculation ---
        runner._log_message("--- Getting Source 1 Container Delays for Analysis ---")
        source1_info = get_stream_info_with_delays(source1_file, runner, ctx.tool_paths)

        # Extract and convert container delays using modules
        source1_container_delays = extract_container_delays(
            source1_info, runner._log_message
        )
        source1_container_delays = convert_to_relative_delays(
            source1_container_delays, source1_info
        )

        # Select Source 1 audio track using track selection module
        ref_explicit_idx, ref_lang = get_reference_track_settings(
            ctx.source_settings, config
        )
        source1_selected = select_audio_track(
            source1_info,
            explicit_index=ref_explicit_idx,
            language=ref_lang,
        )

        source1_audio_track_id = source1_selected.track_id
        source1_audio_container_delay = 0.0

        # Log track selection
        if source1_selected.track_id is not None and source1_selected.track_info:
            source1_audio_track_id = (
                source1_selected.track_id
            )  # Narrow type for Pyright
            method_label = {
                "explicit": f"explicit index {source1_selected.track_index}",
                "language": f"lang={ref_lang}",
                "first": "first track",
            }.get(source1_selected.selection_method, source1_selected.selection_method)
            runner._log_message(
                f"[Source 1] Selected ({method_label}): "
                f"{format_track_details(source1_selected.track_info, source1_selected.track_index or 0)}"
            )

            # Get the relative delay for the selected track
            source1_audio_container_delay = source1_container_delays.get(
                source1_audio_track_id, 0
            )
            ctx.source1_audio_container_delay_ms = source1_audio_container_delay

            if source1_audio_container_delay != 0:
                runner._log_message(
                    f"[Container Delay] Audio track {source1_audio_track_id} relative delay (audio relative to video): "
                    f"{source1_audio_container_delay:+.1f}ms. "
                    f"This will be added to all correlation results."
                )

        # --- Step 2: Run correlation for other sources ---
        runner._log_message("\n--- Running Audio Correlation Analysis ---")

        # Track which sources have stepping for final report
        stepping_sources = []

        for source_key, source_file in sorted(ctx.sources.items()):
            if source_key == "Source 1":
                continue

            runner._log_message(f"\n[Analyzing {source_key}]")

            # Get track settings and build source config using modules
            correlation_source_track, tgt_lang = get_correlation_track_settings(
                source_key, ctx.source_settings, config
            )
            correlation_ref_track, _ = get_reference_track_settings(
                ctx.source_settings, config
            )

            # Build source-specific config (handles source separation overrides)
            source_config = build_source_config(config, source_key, ctx.source_settings)
            use_source_separated_settings = source_config.get(
                "_use_source_separation", False
            )

            # Log analysis config
            if use_source_separated_settings:
                runner._log_message(
                    "[Analysis Config] Source separation enabled - using:"
                )
            else:
                runner._log_message("[Analysis Config] Standard mode - using:")
            runner._log_message(
                f"  Correlation: {source_config.get('correlation_method', 'SCC (Sliding Cross-Correlation)')}"
            )
            runner._log_message(
                f"  Delay Mode: {source_config.get('delay_selection_mode', 'Mode (Most Common)')}"
            )

            # Get stream info for this source
            stream_info = get_stream_info(source_file, runner, ctx.tool_paths)
            if not stream_info:
                runner._log_message(
                    f"[WARN] Could not get stream info for {source_key}. Skipping."
                )
                continue

            audio_tracks = get_audio_tracks(stream_info)
            if not audio_tracks:
                runner._log_message(
                    f"[WARN] No audio tracks found in {source_key}. Skipping."
                )
                continue

            # Select target track using track selection module
            target_selected = select_audio_track(
                stream_info,
                explicit_index=correlation_source_track,
                language=tgt_lang,
            )

            if target_selected.track_id is None:
                runner._log_message(
                    f"[WARN] No suitable audio track found in {source_key} for analysis. Skipping."
                )
                continue

            # Log track selection (track_info is always set when track_id is not None)
            track_info = target_selected.track_info or {}
            method_label = {
                "explicit": f"explicit index {target_selected.track_index}",
                "language": f"lang={tgt_lang}",
                "first": "first track",
            }.get(target_selected.selection_method, target_selected.selection_method)
            runner._log_message(
                f"[{source_key}] Selected ({method_label}): "
                f"{format_track_details(track_info, target_selected.track_index or 0)}"
            )

            # Update correlation_source_track to match selected index (needed for run_audio_correlation)
            correlation_source_track = target_selected.track_index

            target_track_id = target_selected.track_id
            target_codec_id = track_info.get("properties", {}).get(
                "codec_id", "unknown"
            )

            # Check if multi-correlation comparison is enabled (Analyze Only mode only)
            multi_corr_enabled = bool(
                source_config.get("multi_correlation_enabled", False)
            ) and (not ctx.and_merge)

            if multi_corr_enabled:
                # Run multiple correlation methods for comparison
                # Returns dict mapping method names to their results
                # Note: Multi-correlation uses its own method selection (checkboxes), ignores correlation_method setting
                all_method_results = run_multi_correlation(
                    str(source1_file),
                    str(source_file),
                    source_config,
                    runner,
                    ctx.tool_paths,
                    ref_lang=source_config.get("analysis_lang_source1"),
                    target_lang=tgt_lang,
                    role_tag=source_key,
                    ref_track_index=correlation_ref_track,  # Use per-job setting if configured
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
                # (or the dropdown method if we want to be smarter about this)
                first_method = next(iter(all_method_results.keys()))
                results = all_method_results[first_method]
                runner._log_message(
                    f"[MULTI-CORRELATION] Using '{first_method}' results for delay calculation"
                )
            else:
                # Normal single-method correlation
                # Use source_config which already has the right correlation_method set
                results = run_audio_correlation(
                    str(source1_file),
                    str(source_file),
                    source_config,
                    runner,
                    ctx.tool_paths,
                    ref_lang=source_config.get("analysis_lang_source1"),
                    target_lang=tgt_lang,
                    role_tag=source_key,
                    ref_track_index=correlation_ref_track,  # Use per-job setting if configured
                    target_track_index=correlation_source_track,
                    use_source_separation=use_source_separated_settings,
                )

            # --- CRITICAL FIX: Detect stepping BEFORE calculating mode delay ---
            diagnosis = None
            details = {}
            stepping_override_delay = None
            stepping_override_delay_raw = None
            stepping_enabled = source_config.get("segmented_enabled", False)

            # ALWAYS run diagnosis to detect stepping (even if correction is disabled)
            diagnosis, details = diagnose_audio_issue(
                video_path=source1_file,
                chunks=results,
                config=source_config,
                runner=runner,
                tool_paths=ctx.tool_paths,
                codec_id=target_codec_id,
            )

            # If stepping detected, handle based on whether correction is enabled
            if diagnosis == "STEPPING":
                # CRITICAL: Stepping correction doesn't work on source-separated audio
                # Separated stems have fundamentally different waveform characteristics
                if stepping_enabled and not use_source_separated_settings:
                    # Stepping correction is ENABLED - proceed with correction logic
                    stepping_sources.append(source_key)  # Track for final report

                    # Check if any audio tracks from this source are being merged
                    has_audio_from_source = any(
                        t.get("type") == "audio" and t.get("source") == source_key
                        for t in ctx.manual_layout
                    )

                    if has_audio_from_source:
                        # Stepping correction will run, so use first segment delay
                        # Use stepping-specific stability criteria (separate from First Stable delay selection mode)
                        stepping_config = {
                            "first_stable_min_chunks": source_config.get(
                                "stepping_first_stable_min_chunks", 3
                            ),
                            "first_stable_skip_unstable": source_config.get(
                                "stepping_first_stable_skip_unstable", True
                            ),
                        }
                        # Get both rounded (for mkvmerge) and raw (for subtitle precision)
                        stable_result = find_first_stable_segment_delay(
                            results, stepping_config, runner._log_message
                        )
                        if stable_result is not None:
                            first_segment_delay, first_segment_delay_raw = stable_result
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
                        # Use normal delay selection mode instead
                        delay_mode = source_config.get(
                            "delay_selection_mode", "Mode (Most Common)"
                        )
                        runner._log_message(
                            f"[Stepping Detected] Found stepping in {source_key}"
                        )
                        runner._log_message(
                            "[Stepping] No audio tracks from this source are being merged"
                        )
                        runner._log_message(
                            f"[Stepping] Using delay_selection_mode='{delay_mode}' instead of first segment (stepping correction won't run)"
                        )
                        # Don't set stepping_override_delay - let normal flow handle it
                elif use_source_separated_settings:
                    # Source separation blocks stepping correction (unreliable on separated stems)
                    # Track for audit warning - user should manually review this file
                    ctx.stepping_detected_separated.append(source_key)
                    delay_mode = source_config.get(
                        "delay_selection_mode", "Mode (Clustered)"
                    )
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
                        f"[Stepping Disabled] Using delay_selection_mode='{delay_mode}' instead"
                    )
                    # Don't set stepping_override_delay - let normal flow handle it with source-separated delay mode
                else:
                    # Stepping correction is DISABLED globally - just warn the user
                    ctx.stepping_detected_disabled.append(
                        source_key
                    )  # Track for warning
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
                    # Use normal delay selection mode
                    # Don't set stepping_override_delay - let normal flow handle it

            # Use stepping override if available, otherwise calculate using configured mode
            # Get both rounded (for mkvmerge/audio) and raw (for subtitle sync precision)
            if stepping_override_delay is not None:
                correlation_delay_ms = stepping_override_delay
                correlation_delay_raw = (
                    stepping_override_delay_raw  # Use true raw, not float(int)
                )
                runner._log_message(
                    f"{source_key.capitalize()} delay determined: {correlation_delay_ms:+d} ms (first segment, stepping corrected)."
                )
            else:
                # Use source_config which already has the right delay_selection_mode set
                correlation_delay_ms, correlation_delay_raw = _choose_delay(
                    results, source_config, runner, source_key
                )

                if correlation_delay_ms is None or correlation_delay_raw is None:
                    # ENHANCED ERROR MESSAGE
                    accepted_count = len(
                        [r for r in results if r.get("accepted", False)]
                    )
                    min_required = source_config.get("min_accepted_chunks", 3)
                    total_chunks = len(results)

                    raise RuntimeError(
                        f"Analysis failed for {source_key}: Could not determine a reliable delay.\n"
                        f"  - Accepted chunks: {accepted_count}\n"
                        f"  - Minimum required: {min_required}\n"
                        f"  - Total chunks scanned: {total_chunks}\n"
                        f'  - Match threshold: {source_config.get("min_match_pct", 5.0)}%\n'
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

            # Type assertions for Pyright (both are guaranteed non-None after error check above)
            assert correlation_delay_ms is not None
            assert correlation_delay_raw is not None

            # --- Sync Stability Analysis ---
            # Check for variance in correlation results that may indicate sync issues
            # Pass stepping cluster info if available to avoid false positives
            stepping_clusters = None
            if diagnosis == "STEPPING" and details:
                stepping_clusters = details.get("cluster_info", [])

            stability_result = analyze_sync_stability(
                chunk_results=results,
                source_key=source_key,
                config=source_config,
                log=runner._log_message,
                stepping_clusters=stepping_clusters,
            )

            # Always add result so we can show "OK" vs "Not analyzed" in reports
            if stability_result:
                ctx.sync_stability_issues.append(stability_result)

            # Calculate final delay including container delay chain correction
            # CRITICAL: Use the container delay from the ACTUAL Source 1 track used for correlation
            actual_container_delay = source1_audio_container_delay

            # Try to determine which Source 1 track was actually used for correlation
            # This is needed when Source 1 has multiple audio tracks with different container delays
            if source1_info:
                source1_audio_tracks = [
                    t
                    for t in source1_info.get("tracks", [])
                    if t.get("type") == "audio"
                ]

                # Priority 1: Explicit per-job track selection
                if (
                    correlation_ref_track is not None
                    and 0 <= correlation_ref_track < len(source1_audio_tracks)
                ):
                    ref_track_id = source1_audio_tracks[correlation_ref_track].get("id")
                    track_container_delay = source1_container_delays.get(
                        ref_track_id, 0
                    )
                    if track_container_delay != source1_audio_container_delay:
                        actual_container_delay = track_container_delay
                        runner._log_message(
                            f"[Container Delay Override] Using Source 1 audio index {correlation_ref_track} (track ID {ref_track_id}) delay: "
                            f"{actual_container_delay:+.3f}ms (global reference was {source1_audio_container_delay:+.3f}ms)"
                        )
                # Priority 2: Language matching fallback
                elif source_config.get("analysis_lang_source1"):
                    ref_lang_str = str(source_config.get("analysis_lang_source1", ""))
                    for i, track in enumerate(source1_audio_tracks):
                        track_lang = (
                            (track.get("properties", {}).get("language", "") or "")
                            .strip()
                            .lower()
                        )
                        if track_lang == ref_lang_str.strip().lower():
                            ref_track_id = track.get("id")
                            track_container_delay = source1_container_delays.get(
                                ref_track_id, 0
                            )
                            if track_container_delay != source1_audio_container_delay:
                                actual_container_delay = track_container_delay
                                runner._log_message(
                                    f"[Container Delay Override] Using Source 1 audio index {i} (track ID {ref_track_id}, lang={ref_lang_str}) delay: "
                                    f"{actual_container_delay:+.3f}ms (global reference was {source1_audio_container_delay:+.3f}ms)"
                                )
                            break

            # Calculate final delay using module
            final_delay = calculate_final_delay(
                correlation_delay_ms=correlation_delay_ms,
                correlation_delay_raw=correlation_delay_raw,
                container_delay_ms=actual_container_delay,
            )
            final_delay_ms = final_delay.rounded_ms
            final_delay_raw = final_delay.raw_ms

            # Log the delay calculation chain for transparency
            runner._log_message(f"[Delay Calculation] {source_key} delay chain:")
            runner._log_message(
                f"[Delay Calculation]   Correlation delay: {final_delay.correlation_raw_ms:+.3f}ms (raw) → {final_delay.correlation_rounded_ms:+d}ms (rounded)"
            )
            if final_delay.container_delay_ms != 0:
                runner._log_message(
                    f"[Delay Calculation]   + Container delay:  {final_delay.container_delay_ms:+.3f}ms"
                )
                runner._log_message(
                    f"[Delay Calculation]   = Final delay:      {final_delay.raw_ms:+.3f}ms (raw) → {final_delay.rounded_ms:+d}ms (rounded)"
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
                    selection_method=source_config.get(
                        "delay_selection_mode", "Mode (Most Common)"
                    ),
                    accepted_chunks=accepted_count,
                    total_chunks=len(results),
                )

            # --- Handle drift detection flags ---
            # Delegate to diagnostics module for flag handling
            apply_diagnosis_flags(
                ctx=ctx,
                diagnosis=diagnosis,
                details=details,
                source_key=source_key,
                track_id=target_track_id,
                use_source_separation=use_source_separated_settings,
                final_delay_ms=final_delay_ms,
                config=config,
                log=runner._log_message,
            )

        # Store stepping sources in context for final report
        ctx.stepping_sources = stepping_sources

        # Initialize Source 1 with 0ms base delay so it gets the global shift
        source_delays["Source 1"] = 0
        raw_source_delays["Source 1"] = 0.0

        # --- Step 3: Calculate Global Shift to Handle Negative Delays ---
        runner._log_message("\n--- Calculating Global Shift ---")

        # Calculate global shift using module (only if required)
        global_shift_ms = 0
        raw_global_shift_ms = 0.0

        if ctx.global_shift_is_required:
            global_shift_ms, raw_global_shift_ms = calculate_global_shift(
                source_delays=source_delays,
                raw_source_delays=raw_source_delays,
                container_delays=source1_container_delays,
                stream_info=source1_info,
                layout=ctx.manual_layout,
                log=runner._log_message,
            )

        # Apply global shift if needed
        if global_shift_ms > 0:
            source_delays, raw_source_delays = apply_global_shift(
                source_delays=source_delays,
                raw_source_delays=raw_source_delays,
                shift_ms=global_shift_ms,
                raw_shift_ms=raw_global_shift_ms,
                log=runner._log_message,
            )

            # Log Source 1 container delay adjustments for transparency
            if source1_container_delays and source1_info:
                runner._log_message(
                    f"[Delay] Source 1 container delays (will have +{global_shift_ms}ms added during mux):"
                )
                for track in source1_info.get("tracks", []):
                    if track.get("type") in ["audio", "video"]:
                        tid = track.get("id")
                        delay = source1_container_delays.get(tid, 0)
                        final_delay = delay + global_shift_ms
                        track_type = track.get("type")

                        note = (
                            " (will be ignored - video defines timeline)"
                            if track_type == "video"
                            else ""
                        )
                        runner._log_message(
                            f"  - Track {tid} ({track_type}): {delay:+.1f}ms → {final_delay:+.1f}ms{note}"
                        )
        else:
            runner._log_message(
                "[Delay] All relevant delays are non-negative. No global shift needed."
            )

        # === AUDIT: Record global shift calculation ===
        if ctx.audit:
            # Derive most_negative from shift (shift = abs(most_negative))
            most_negative = -global_shift_ms if global_shift_ms > 0 else 0
            most_negative_raw = -raw_global_shift_ms if raw_global_shift_ms > 0 else 0.0
            ctx.audit.record_global_shift(
                most_negative_raw_ms=most_negative_raw,
                most_negative_rounded_ms=most_negative,
                shift_raw_ms=raw_global_shift_ms,
                shift_rounded_ms=global_shift_ms,
                sync_mode=sync_mode,
            )
            # Record final delays for each source
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
            global_shift_ms=global_shift_ms,
            raw_global_shift_ms=raw_global_shift_ms,
        )

        # Final summary
        runner._log_message(
            f"\n[Delay] === FINAL DELAYS (Sync Mode: {sync_mode.upper()}, Global Shift: +{global_shift_ms}ms) ==="
        )
        for source_key, delay_ms in sorted(source_delays.items()):
            runner._log_message(f"  - {source_key}: {delay_ms:+d}ms")

        if sync_mode == "allow_negative" and global_shift_ms == 0:
            runner._log_message(
                "\n[INFO] Negative delays retained (allow_negative mode). Secondary sources may have negative delays."
            )
        elif global_shift_ms > 0:
            runner._log_message(
                f"\n[INFO] All delays shifted by +{global_shift_ms}ms to eliminate negatives."
            )

        return ctx
