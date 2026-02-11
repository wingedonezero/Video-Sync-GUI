# vsg_core/orchestrator/steps/analysis_step.py
"""
Analysis step - pure coordinator.

Orchestrates audio/video correlation analysis by coordinating:
- Track selection
- Audio decoding and filtering
- Correlation method dispatch (plugin-based)
- Delay calculation
- Drift/stepping detection
- Global shift calculation

NO business logic - delegates to vsg_core/analysis/ modules.
"""

from __future__ import annotations

import gc
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vsg_core.analysis.container_delays import (
    calculate_delay_chain,
    find_actual_correlation_track_delay,
    get_container_delay_info,
)
from vsg_core.analysis.correlation import (
    DEFAULT_SR,
    apply_bandpass,
    apply_lowpass,
    decode_audio,
    extract_chunks,
    get_audio_stream_info,
    get_method,
    list_methods,
    normalize_lang,
)
from vsg_core.analysis.correlation.methods.scc import Scc
from vsg_core.analysis.delay_selection import (
    calculate_delay,
    find_first_stable_segment_delay,
)
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
from vsg_core.analysis.types import ChunkResult, DriftDiagnosis, SteppingDiagnosis
from vsg_core.extraction.tracks import get_stream_info
from vsg_core.models.jobs import Delays

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from vsg_core.analysis.correlation.chunking import AudioChunk
    from vsg_core.analysis.correlation.registry import CorrelationMethod
    from vsg_core.analysis.types import DiagnosisResult
    from vsg_core.io.runner import CommandRunner
    from vsg_core.models.context_types import (
        Source1Settings,
        SourceNSettings,
    )
    from vsg_core.models.settings import AppSettings
    from vsg_core.orchestrator.steps.context import Context


def _should_use_source_separated_mode(
    source_key: str,
    settings: AppSettings,
    source_settings: dict[str, Source1Settings | SourceNSettings],
) -> bool:
    """
    Check if this source should use source separation during correlation.

    Uses per-source settings from the job layout. Source separation is only
    applied when explicitly enabled for the specific source.
    """
    if settings.source_separation_mode == "none":
        return False
    per_source = source_settings.get(source_key, {})
    return per_source.get("use_source_separation", False)


def _resolve_method(
    settings: AppSettings, *, source_separated: bool
) -> CorrelationMethod:
    """
    Resolve the correlation method to use based on settings.

    For SCC, creates a fresh instance with the peak_fit setting applied.
    For all other methods, looks up the registered instance.
    """
    method_name = (
        settings.correlation_method_source_separated
        if source_separated
        else settings.correlation_method
    )

    # SCC is special: it has a configurable peak_fit parameter
    if "Standard Correlation" in method_name or "SCC" in method_name:
        return Scc(peak_fit=settings.audio_peak_fit)

    return get_method(method_name)


def _apply_source_separation(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sr: int,
    settings: AppSettings,
    log: Callable[[str], None],
    role_tag: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply source separation if configured. Returns (ref, tgt) arrays."""
    separation_mode = settings.source_separation_mode
    if not separation_mode or separation_mode == "none":
        return ref_pcm, tgt_pcm

    try:
        from vsg_core.analysis.source_separation import apply_source_separation

        return apply_source_separation(ref_pcm, tgt_pcm, sr, settings, log, role_tag)
    except ImportError as e:
        log(
            "WARNING: Source separation was enabled but dependencies are not available!"
        )
        log(f"[SOURCE SEPARATION] Error: {e}")
        log(
            "[SOURCE SEPARATION] Falling back to standard correlation "
            "without separation."
        )
        log(
            "[SOURCE SEPARATION] To fix: Install dependencies with "
            "'pip install demucs torch'"
        )
    except Exception as e:
        log("WARNING: Source separation failed with an error!")
        log(f"[SOURCE SEPARATION] Error: {e}")
        log(
            "[SOURCE SEPARATION] Falling back to standard correlation "
            "without separation."
        )

    return ref_pcm, tgt_pcm


def _apply_filtering(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sr: int,
    settings: AppSettings,
    log: Callable[[str], None],
) -> tuple[np.ndarray, np.ndarray]:
    """Apply configured audio filtering. Returns (ref, tgt) arrays."""
    filtering_method = settings.filtering_method

    if filtering_method == "Dialogue Band-Pass Filter":
        log("Applying Dialogue Band-Pass filter...")
        lowcut = settings.filter_bandpass_lowcut_hz
        highcut = settings.filter_bandpass_highcut_hz
        order = settings.filter_bandpass_order
        ref_pcm = apply_bandpass(ref_pcm, sr, lowcut, highcut, order, log)
        tgt_pcm = apply_bandpass(tgt_pcm, sr, lowcut, highcut, order, log)
    elif filtering_method == "Low-Pass Filter":
        cutoff = settings.audio_bandlimit_hz
        if cutoff > 0:
            log(f"Applying Low-Pass filter at {cutoff} Hz...")
            taps = settings.filter_lowpass_taps
            ref_pcm = apply_lowpass(ref_pcm, sr, cutoff, taps, log)
            tgt_pcm = apply_lowpass(tgt_pcm, sr, cutoff, taps, log)

    return ref_pcm, tgt_pcm


def _correlate_chunks(
    chunks: list[AudioChunk],
    method: CorrelationMethod,
    sr: int,
    min_match: float,
    log: Callable[[str], None],
    chunk_count: int,
) -> list[ChunkResult]:
    """
    Run a correlation method on all chunks and return typed results.

    This is the inner loop that was duplicated in both run_audio_correlation
    and run_multi_correlation. Now exists once, used by both paths.
    """
    results: list[ChunkResult] = []

    for chunk in chunks:
        raw_ms, match = method.find_delay(chunk.ref, chunk.tgt, sr)

        accepted = match >= min_match
        status_str = "ACCEPTED" if accepted else f"REJECTED (below {min_match:.1f})"
        log(
            f"  Chunk {chunk.index}/{chunk_count} (@{chunk.start_s:.1f}s): "
            f"delay = {int(round(raw_ms)):+d} ms "
            f"(raw={raw_ms:+.3f}, match={match:.2f}) "
            f"— {status_str}"
        )
        results.append(
            ChunkResult(
                delay_ms=int(round(raw_ms)),
                raw_delay_ms=raw_ms,
                match_pct=match,
                start_s=chunk.start_s,
                accepted=accepted,
            )
        )

    return results


class AnalysisStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            raise ValueError("Context is missing Source 1 for analysis.")

        log = runner._log_message
        settings = ctx.settings

        # --- Part 1: Determine if a global shift is required ---
        sync_mode = settings.sync_mode
        has_secondary_audio = any(
            t.get("type") == "audio" and t.get("source") != "Source 1"
            for t in ctx.manual_layout
        )
        ctx.sync_mode = sync_mode

        log("=" * 60)
        log(f"=== TIMING SYNC MODE: {sync_mode.upper()} ===")
        log("=" * 60)

        if sync_mode == "allow_negative":
            ctx.global_shift_is_required = False
            log("[SYNC MODE] Negative delays are ALLOWED (no global shift).")
            log("[SYNC MODE] Source 1 remains reference (delay = 0).")
            log("[SYNC MODE] Secondary sources can have negative delays.")
        elif sync_mode == "positive_only":
            ctx.global_shift_is_required = has_secondary_audio
            if ctx.global_shift_is_required:
                log(
                    "[SYNC MODE] Positive-only mode - global shift will "
                    "eliminate negative delays."
                )
                log("[SYNC MODE] All tracks will be shifted to be non-negative.")
            else:
                log("[SYNC MODE] Positive-only mode (but no secondary audio detected).")
                log(
                    "[SYNC MODE] Global shift will not be applied "
                    "(subtitle-only exception)."
                )
        else:
            log(
                f"[WARNING] Unknown sync_mode '{sync_mode}', "
                f"falling back to 'positive_only'."
            )
            ctx.global_shift_is_required = has_secondary_audio

        # Skip analysis if only Source 1 (remux-only mode)
        if len(ctx.sources) == 1:
            log("--- Analysis Phase: Skipped (Remux-only mode - no sync sources) ---")
            ctx.delays = Delays(
                source_delays_ms={},
                raw_source_delays_ms={},
                global_shift_ms=0,
                raw_global_shift_ms=0.0,
            )
            return ctx

        source_delays: dict[str, int] = {}
        raw_source_delays: dict[str, float] = {}

        # --- Step 1: Get Source 1's container delays ---
        log("--- Getting Source 1 Container Delays for Analysis ---")
        source1_container_info = get_container_delay_info(
            source1_file,
            runner,
            ctx.tool_paths,
            log=log,
        )

        source1_audio_container_delay = 0.0
        source1_video_container_delay = 0.0
        source1_stream_info = None

        if source1_container_info:
            source1_video_container_delay = source1_container_info.video_delay_ms

            ref_lang = settings.analysis_lang_source1
            source1_stream_info = get_stream_info(source1_file, runner, ctx.tool_paths)

            if source1_stream_info:
                source1_audio_tracks = [
                    t
                    for t in source1_stream_info.get("tracks", [])
                    if t.get("type") == "audio"
                ]

                source1_settings = ctx.source_settings.get("Source 1", {})
                correlation_ref_track = source1_settings.get("correlation_ref_track")

                source1_track_selection = select_audio_track(
                    audio_tracks=source1_audio_tracks,
                    language=ref_lang,
                    explicit_index=correlation_ref_track,
                    log=log,
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
                        log(
                            f"[Container Delay] Audio track "
                            f"{source1_track_selection.track_id} relative "
                            f"delay (audio relative to video): "
                            f"{source1_audio_container_delay:+.1f}ms. "
                            f"This will be added to all correlation results."
                        )

        # --- Step 2: Run correlation/videodiff for other sources ---
        is_videodiff_mode = (
            settings.analysis_mode == "VideoDiff"
            or settings.correlation_method == "VideoDiff"
        )

        if is_videodiff_mode:
            log("\n--- Running VideoDiff (Frame Matching) Analysis ---")
        else:
            log("\n--- Running Audio Correlation Analysis ---")

        stepping_sources: list[str] = []

        for source_key, source_file in sorted(ctx.sources.items()):
            if source_key == "Source 1":
                continue

            log(f"\n[Analyzing {source_key}]")

            # =============================================================
            # VideoDiff mode: frame-based analysis (no audio tracks needed)
            # =============================================================
            if is_videodiff_mode:
                self._run_videodiff_analysis(
                    ctx,
                    runner,
                    source_key,
                    source_file,
                    source1_file,
                    source1_video_container_delay,
                    source_delays,
                    raw_source_delays,
                )
                continue

            # =============================================================
            # Audio Correlation Mode
            # =============================================================
            self._run_audio_analysis(
                ctx,
                runner,
                source_key,
                source_file,
                source1_file,
                source1_audio_container_delay,
                source1_container_info,
                source1_stream_info,
                source_delays,
                raw_source_delays,
                stepping_sources,
            )

        # Store stepping sources in context
        ctx.stepping_sources = stepping_sources

        # Initialize Source 1 with 0ms base delay
        source_delays["Source 1"] = 0
        raw_source_delays["Source 1"] = 0.0

        # --- Step 3: Calculate Global Shift ---
        log("\n--- Calculating Global Shift ---")

        shift = calculate_global_shift(
            source_delays=source_delays,
            raw_source_delays=raw_source_delays,
            manual_layout=ctx.manual_layout,
            container_info=source1_container_info,
            global_shift_required=ctx.global_shift_is_required,
            log=log,
        )

        if shift.applied:
            source_delays, raw_source_delays = apply_global_shift_to_delays(
                source_delays=source_delays,
                raw_source_delays=raw_source_delays,
                shift=shift,
                log=log,
            )

            if source1_container_info and source1_stream_info:
                log(
                    f"[Delay] Source 1 container delays "
                    f"(will have +{shift.shift_ms}ms added during mux):"
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
                        log(
                            f"  - Track {tid} ({track_type}): "
                            f"{delay:+.1f}ms -> {final_delay:+.1f}ms{note}"
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

        # Store calculated delays
        ctx.delays = Delays(
            source_delays_ms=source_delays,
            raw_source_delays_ms=raw_source_delays,
            global_shift_ms=shift.shift_ms,
            raw_global_shift_ms=shift.raw_shift_ms,
        )

        # Final summary
        log(
            f"\n[Delay] === FINAL DELAYS (Sync Mode: {sync_mode.upper()}, "
            f"Global Shift: +{shift.shift_ms}ms) ==="
        )
        for source_key, delay_ms in sorted(source_delays.items()):
            log(f"  - {source_key}: {delay_ms:+d}ms")

        if sync_mode == "allow_negative" and shift.shift_ms == 0:
            log(
                "\n[INFO] Negative delays retained (allow_negative mode). "
                "Secondary sources may have negative delays."
            )
        elif shift.shift_ms > 0:
            log(
                f"\n[INFO] All delays shifted by +{shift.shift_ms}ms "
                f"to eliminate negatives."
            )

        return ctx

    # -----------------------------------------------------------------
    # Private helpers - each handles one analysis path
    # -----------------------------------------------------------------

    def _run_videodiff_analysis(
        self,
        ctx: Context,
        runner: CommandRunner,
        source_key: str,
        source_file: str,
        source1_file: str,
        source1_video_container_delay: float,
        source_delays: dict[str, int],
        raw_source_delays: dict[str, float],
    ) -> None:
        """Handle VideoDiff (frame-based) analysis for one source."""
        from vsg_core.analysis.videodiff import run_native_videodiff

        log = runner._log_message

        vd_result = run_native_videodiff(
            str(source1_file),
            str(source_file),
            ctx.settings,
            runner,
            ctx.tool_paths,
        )

        correlation_delay_ms = vd_result.offset_ms
        correlation_delay_raw = vd_result.raw_offset_ms
        actual_container_delay = source1_video_container_delay

        final_delay_ms, final_delay_raw = calculate_delay_chain(
            correlation_delay_ms,
            correlation_delay_raw,
            actual_container_delay,
            log=log,
            source_key=source_key,
        )

        log(
            f"[VideoDiff] Confidence: {vd_result.confidence} "
            f"(inliers: {vd_result.inlier_count}/{vd_result.matched_frames}, "
            f"residual: {vd_result.mean_residual_ms:.1f}ms)"
        )

        if vd_result.speed_drift_detected:
            log(
                "[VideoDiff] WARNING: Speed drift detected between sources. "
                "The offset is valid but timing may drift over the video "
                "duration."
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

    def _run_audio_analysis(
        self,
        ctx: Context,
        runner: CommandRunner,
        source_key: str,
        source_file: str,
        source1_file: str,
        source1_audio_container_delay: float,
        source1_container_info: Any,
        source1_stream_info: dict[str, Any] | None,
        source_delays: dict[str, int],
        raw_source_delays: dict[str, float],
        stepping_sources: list[str],
    ) -> None:
        """Handle audio correlation analysis for one source."""
        log = runner._log_message
        settings = ctx.settings

        # --- Get per-source settings ---
        per_source_settings = ctx.source_settings.get(source_key, {})
        correlation_source_track = per_source_settings.get("correlation_source_track")
        source1_settings = ctx.source_settings.get("Source 1", {})
        correlation_ref_track = source1_settings.get("correlation_ref_track")

        # Determine target language
        if correlation_source_track is not None:
            tgt_lang = None
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
                log(
                    f"[Source 1] Selected (explicit): "
                    f"{format_track_details(ref_track, correlation_ref_track)}"
                )
            else:
                log(
                    f"[Source 1] WARNING: Invalid track index "
                    f"{correlation_ref_track}, using previously selected track"
                )

        # Determine if source separation should be applied
        use_source_separated_settings = _should_use_source_separated_mode(
            source_key, settings, ctx.source_settings
        )

        # Determine effective delay selection mode
        if use_source_separated_settings:
            effective_delay_mode = settings.delay_selection_mode_source_separated
            log("[Analysis Config] Source separation enabled - using:")
            log(f"  Correlation: {settings.correlation_method_source_separated}")
            log(f"  Delay Mode: {effective_delay_mode}")
        else:
            effective_delay_mode = settings.delay_selection_mode
            log("[Analysis Config] Standard mode - using:")
            log(f"  Correlation: {settings.correlation_method}")
            log(f"  Delay Mode: {effective_delay_mode}")

        # --- Get stream info and select target track ---
        stream_info = get_stream_info(source_file, runner, ctx.tool_paths)
        if not stream_info:
            log(f"[WARN] Could not get stream info for {source_key}. Skipping.")
            return

        audio_tracks = [
            t for t in stream_info.get("tracks", []) if t.get("type") == "audio"
        ]
        if not audio_tracks:
            log(f"[WARN] No audio tracks found in {source_key}. Skipping.")
            return

        target_track_selection = select_audio_track(
            audio_tracks=audio_tracks,
            language=tgt_lang,
            explicit_index=correlation_source_track,
            log=log,
            source_label=source_key,
        )

        if not target_track_selection:
            log(
                f"[WARN] No suitable audio track found in {source_key} "
                f"for analysis. Skipping."
            )
            return

        target_track_id = target_track_selection.track_id
        target_codec_id = (
            audio_tracks[target_track_selection.track_index]
            .get("properties", {})
            .get("codec_id", "unknown")
        )

        # --- Decode, separate, filter, chunk, correlate ---
        results = self._decode_and_correlate(
            ctx=ctx,
            runner=runner,
            source_key=source_key,
            source1_file=source1_file,
            source_file=source_file,
            correlation_ref_track=correlation_ref_track,
            correlation_source_track=correlation_source_track,
            tgt_lang=tgt_lang,
            use_source_separated_settings=use_source_separated_settings,
        )

        # --- Detect stepping BEFORE calculating mode delay ---
        diagnosis = diagnose_audio_issue(
            video_path=source1_file,
            chunks=results,
            settings=settings,
            runner=runner,
            tool_paths=ctx.tool_paths,
            codec_id=target_codec_id,
        )

        stepping_override_delay: int | None = None
        stepping_override_delay_raw: float | None = None
        stepping_enabled = settings.segmented_enabled

        if isinstance(diagnosis, SteppingDiagnosis):
            stepping_override_delay, stepping_override_delay_raw = (
                self._handle_stepping(
                    ctx=ctx,
                    runner=runner,
                    source_key=source_key,
                    results=results,
                    stepping_enabled=stepping_enabled,
                    use_source_separated_settings=use_source_separated_settings,
                    effective_delay_mode=effective_delay_mode,
                    stepping_sources=stepping_sources,
                )
            )

        # --- Calculate delay ---
        if (
            stepping_override_delay is not None
            and stepping_override_delay_raw is not None
        ):
            correlation_delay_ms = stepping_override_delay
            correlation_delay_raw = stepping_override_delay_raw
            log(
                f"{source_key.capitalize()} delay determined: "
                f"{correlation_delay_ms:+d} ms "
                f"(first segment, stepping corrected)."
            )
        else:
            delay_calc = calculate_delay(
                results=results,
                settings=settings,
                delay_mode=effective_delay_mode,
                log=log,
                role_tag=source_key,
            )

            if delay_calc is None:
                accepted_count = len([r for r in results if r.accepted])
                min_required = settings.min_accepted_chunks
                total_chunks = len(results)

                raise RuntimeError(
                    f"Analysis failed for {source_key}: Could not determine "
                    f"a reliable delay.\n"
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
                    f'  - Try lowering the "Minimum Match %" threshold\n'
                    f'  - Increase "Chunk Count" for more sample points\n'
                    f"  - Try selecting different audio tracks\n"
                    f"  - Use VideoDiff mode instead of Audio Correlation\n"
                    f"  - Check that both files are from the same video source"
                )

            correlation_delay_ms = delay_calc.rounded_ms
            correlation_delay_raw = delay_calc.raw_ms

        # --- Sync Stability Analysis ---
        stepping_clusters = None
        if isinstance(diagnosis, SteppingDiagnosis):
            stepping_clusters = diagnosis.cluster_details or None

        stability_result = analyze_sync_stability(
            chunk_results=results,
            source_key=source_key,
            settings=settings,
            log=log,
            stepping_clusters=stepping_clusters,
        )

        if stability_result:
            ctx.sync_stability_issues.append(stability_result)

        # --- Calculate final delay chain ---
        actual_container_delay = source1_audio_container_delay

        if source1_container_info and source1_stream_info:
            actual_container_delay = find_actual_correlation_track_delay(
                container_info=source1_container_info,
                stream_info=source1_stream_info,
                correlation_ref_track=correlation_ref_track,
                ref_lang=settings.analysis_lang_source1,
                default_delay_ms=source1_audio_container_delay,
                log=log,
            )

        final_delay_ms, final_delay_raw = calculate_delay_chain(
            correlation_delay_ms,
            correlation_delay_raw,
            actual_container_delay,
            log=log,
            source_key=source_key,
        )

        source_delays[source_key] = final_delay_ms
        raw_source_delays[source_key] = final_delay_raw

        # === AUDIT ===
        if ctx.audit:
            accepted_count = len([r for r in results if r.accepted])
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
        self._record_drift_flags(
            ctx=ctx,
            runner=runner,
            source_key=source_key,
            target_track_id=target_track_id,
            diagnosis=diagnosis,
            final_delay_ms=final_delay_ms,
            use_source_separated_settings=use_source_separated_settings,
        )

    def _decode_and_correlate(
        self,
        ctx: Context,
        runner: CommandRunner,
        source_key: str,
        source1_file: str,
        source_file: str,
        correlation_ref_track: int | None,
        correlation_source_track: int | None,
        tgt_lang: str | None,
        use_source_separated_settings: bool,
    ) -> list[ChunkResult]:
        """
        Decode audio, apply separation/filtering, extract chunks, and
        run correlation. Handles both single-method and multi-method paths.
        """
        log = runner._log_message
        settings = ctx.settings

        # --- 1. Select streams ---
        if correlation_ref_track is not None:
            idx_ref = correlation_ref_track
            log(f"Using explicit reference track index: {correlation_ref_track}")
        else:
            ref_norm = normalize_lang(settings.analysis_lang_source1)
            idx_ref, _ = get_audio_stream_info(
                source1_file, ref_norm, runner, ctx.tool_paths
            )

        if correlation_source_track is not None:
            idx_tgt = correlation_source_track
            id_tgt = None
            log(f"Using explicit target track index: {correlation_source_track}")
        else:
            tgt_norm = normalize_lang(tgt_lang)
            idx_tgt, id_tgt = get_audio_stream_info(
                source_file, tgt_norm, runner, ctx.tool_paths
            )

        if idx_ref is None or idx_tgt is None:
            raise ValueError("Could not locate required audio streams for correlation.")

        # Log stream selection
        if correlation_ref_track is not None:
            ref_desc = f"explicit track {correlation_ref_track}"
        else:
            ref_desc = (
                f"lang='{normalize_lang(settings.analysis_lang_source1) or 'first'}'"
            )

        if correlation_source_track is not None:
            tgt_desc = f"explicit track {correlation_source_track}"
        else:
            tgt_desc = f"lang='{normalize_lang(tgt_lang) or 'first'}'"

        log(
            f"Selected streams: REF ({ref_desc}, index={idx_ref}), "
            f"{source_key.upper()} ({tgt_desc}, index={idx_tgt}"
            + (f", track_id={id_tgt}" if id_tgt is not None else "")
            + ")"
        )

        # --- 2. Decode ---
        use_soxr = settings.use_soxr
        log(
            f"[DECODE DEBUG] Decoding ref: -map 0:a:{idx_ref} "
            f"from {Path(source1_file).name}"
        )
        ref_pcm = decode_audio(
            source1_file, idx_ref, DEFAULT_SR, use_soxr, runner, ctx.tool_paths
        )
        log(
            f"[DECODE DEBUG] Decoding tgt: -map 0:a:{idx_tgt} "
            f"from {Path(source_file).name}"
        )
        tgt_pcm = decode_audio(
            source_file, idx_tgt, DEFAULT_SR, use_soxr, runner, ctx.tool_paths
        )

        # Log audio stats
        log(
            f"[DECODE DEBUG] ref_pcm: shape={ref_pcm.shape}, "
            f"min={ref_pcm.min():.6f}, max={ref_pcm.max():.6f}, "
            f"std={ref_pcm.std():.6f}"
        )
        log(
            f"[DECODE DEBUG] tgt_pcm: shape={tgt_pcm.shape}, "
            f"min={tgt_pcm.min():.6f}, max={tgt_pcm.max():.6f}, "
            f"std={tgt_pcm.std():.6f}"
        )

        # --- 2b. Source Separation (Optional) ---
        if use_source_separated_settings:
            ref_pcm, tgt_pcm = _apply_source_separation(
                ref_pcm, tgt_pcm, DEFAULT_SR, settings, log, source_key
            )

        # --- 3. Filtering ---
        ref_pcm, tgt_pcm = _apply_filtering(ref_pcm, tgt_pcm, DEFAULT_SR, settings, log)

        # --- 4. Extract chunks ---
        chunks = extract_chunks(
            ref_pcm=ref_pcm,
            tgt_pcm=tgt_pcm,
            sr=DEFAULT_SR,
            chunk_count=settings.scan_chunk_count,
            chunk_duration_s=float(settings.scan_chunk_duration),
            start_pct=settings.scan_start_percentage,
            end_pct=settings.scan_end_percentage,
        )

        # --- 5. Correlate ---
        min_match = float(settings.min_match_pct)
        chunk_count = settings.scan_chunk_count

        multi_corr_enabled = settings.multi_correlation_enabled and (not ctx.and_merge)

        if multi_corr_enabled:
            results = self._run_multi_correlation(
                chunks=chunks,
                settings=settings,
                use_source_separated=use_source_separated_settings,
                min_match=min_match,
                chunk_count=chunk_count,
                log=log,
            )
        else:
            method = _resolve_method(
                settings, source_separated=use_source_separated_settings
            )
            results = _correlate_chunks(
                chunks, method, DEFAULT_SR, min_match, log, chunk_count
            )

        # Release audio arrays immediately
        del ref_pcm
        del tgt_pcm
        gc.collect()

        return results

    def _run_multi_correlation(
        self,
        chunks: list[AudioChunk],
        settings: AppSettings,
        use_source_separated: bool,
        min_match: float,
        chunk_count: int,
        log: Callable[[str], None],
    ) -> list[ChunkResult]:
        """
        Run multiple correlation methods on the same chunks for comparison.

        Returns the first method's results for actual delay calculation.
        """
        # Find enabled methods
        enabled_methods: list[CorrelationMethod] = []
        for method in list_methods():
            if getattr(settings, method.config_key, False):
                # Handle SCC's peak_fit setting
                if isinstance(method, Scc):
                    method = Scc(peak_fit=settings.audio_peak_fit)
                enabled_methods.append(method)

        if not enabled_methods:
            log("[MULTI-CORRELATION] No methods enabled, falling back to single method")
            method = _resolve_method(settings, source_separated=use_source_separated)
            return _correlate_chunks(
                chunks, method, DEFAULT_SR, min_match, log, chunk_count
            )

        log(
            f"\n[MULTI-CORRELATION] Running {len(enabled_methods)} methods "
            f"on {len(chunks)} chunks"
        )

        all_results: dict[str, list[ChunkResult]] = {}

        for method in enabled_methods:
            log(f"\n{'=' * 70}")
            log(f"  MULTI-CORRELATION: {method.name}")
            log(f"{'=' * 70}")

            results = _correlate_chunks(
                chunks, method, DEFAULT_SR, min_match, log, chunk_count
            )
            all_results[method.name] = results

        # Log summary
        log(f"\n{'=' * 70}")
        log("  MULTI-CORRELATION SUMMARY")
        log(f"{'=' * 70}")

        for method_name, method_results in all_results.items():
            accepted = [r for r in method_results if r.accepted]
            if accepted:
                delays = [r.delay_ms for r in accepted]
                raw_delays = [r.raw_delay_ms for r in accepted]
                mode_delay = Counter(delays).most_common(1)[0][0]
                avg_match = sum(r.match_pct for r in accepted) / len(accepted)
                avg_raw = sum(raw_delays) / len(raw_delays)
                log(
                    f"  {method_name}: {mode_delay:+d}ms "
                    f"(raw avg: {avg_raw:+.3f}ms) | "
                    f"match: {avg_match:.1f}% | "
                    f"accepted: {len(accepted)}/{len(method_results)}"
                )
            else:
                log(f"  {method_name}: NO ACCEPTED CHUNKS")

        log(f"{'=' * 70}\n")

        # Use first method's results for actual processing
        first_method_name = next(iter(all_results.keys()))
        log(
            f"[MULTI-CORRELATION] Using '{first_method_name}' results "
            f"for delay calculation"
        )
        return all_results[first_method_name]

    def _handle_stepping(
        self,
        ctx: Context,
        runner: CommandRunner,
        source_key: str,
        results: list[ChunkResult],
        stepping_enabled: bool,
        use_source_separated_settings: bool,
        effective_delay_mode: str,
        stepping_sources: list[str],
    ) -> tuple[int | None, float | None]:
        """
        Handle stepping detection result. Returns override delay if applicable.
        """
        log = runner._log_message
        settings = ctx.settings

        if stepping_enabled and not use_source_separated_settings:
            stepping_sources.append(source_key)

            has_audio_from_source = any(
                t.get("type") == "audio" and t.get("source") == source_key
                for t in ctx.manual_layout
            )

            if has_audio_from_source:
                first_segment_delay = find_first_stable_segment_delay(
                    results,
                    settings,
                    return_raw=False,
                    log=log,
                    override_min_chunks=settings.stepping_first_stable_min_chunks,
                    override_skip_unstable=settings.stepping_first_stable_skip_unstable,
                )
                first_segment_delay_raw = find_first_stable_segment_delay(
                    results,
                    settings,
                    return_raw=True,
                    log=log,
                    override_min_chunks=settings.stepping_first_stable_min_chunks,
                    override_skip_unstable=settings.stepping_first_stable_skip_unstable,
                )
                if first_segment_delay is not None:
                    log(f"[Stepping Detected] Found stepping in {source_key}")
                    log(
                        f"[Stepping Override] Using first segment's delay: "
                        f"{first_segment_delay:+d}ms "
                        f"(raw: {first_segment_delay_raw:.3f}ms)"
                    )
                    log(
                        f"[Stepping Override] This delay will be used for "
                        f"ALL tracks (audio + subtitles) from {source_key}"
                    )
                    log(
                        "[Stepping Override] Stepping correction will be "
                        "applied to audio tracks during processing"
                    )
                    return int(first_segment_delay), first_segment_delay_raw
            else:
                log(f"[Stepping Detected] Found stepping in {source_key}")
                log("[Stepping] No audio tracks from this source are being merged")
                log(
                    f"[Stepping] Using delay_selection_mode="
                    f"'{effective_delay_mode}' instead of first segment "
                    f"(stepping correction won't run)"
                )

        elif use_source_separated_settings:
            ctx.stepping_detected_separated.append(source_key)
            log(f"[Stepping Detected] Found stepping in {source_key}")
            log(
                "[Stepping Disabled] Source separation is enabled - "
                "stepping correction is unreliable on separated stems"
            )
            log(
                "[Stepping Disabled] Separated stems have different "
                "waveform characteristics that break stepping detection"
            )
            log(
                f"[Stepping Disabled] Using delay_selection_mode="
                f"'{effective_delay_mode}' instead"
            )

        else:
            ctx.stepping_detected_disabled.append(source_key)
            log(f"[Stepping Detected] Found stepping in {source_key}")
            log(
                "[Stepping Disabled] Stepping correction is disabled "
                "- timing may be inconsistent"
            )
            log(
                "[Recommendation] Enable 'Stepping Correction' in "
                "settings if you want automatic correction"
            )
            log("[Manual Review] You should manually review this file's sync quality")

        return None, None

    def _record_drift_flags(
        self,
        ctx: Context,
        runner: CommandRunner,
        source_key: str,
        target_track_id: int,
        diagnosis: DiagnosisResult,
        final_delay_ms: int,
        use_source_separated_settings: bool,
    ) -> None:
        """Record drift/stepping detection flags in context."""
        from vsg_core.analysis.types import UniformDiagnosis

        if isinstance(diagnosis, UniformDiagnosis):
            return

        log = runner._log_message
        settings = ctx.settings
        analysis_track_key = f"{source_key}_{target_track_id}"

        if isinstance(diagnosis, DriftDiagnosis) and diagnosis.diagnosis == "PAL_DRIFT":
            if use_source_separated_settings:
                log(
                    f"[PAL Drift Detected] PAL drift detected in "
                    f"{source_key}, but source separation is enabled. "
                    f"PAL correction is unreliable on separated stems "
                    f"- skipping."
                )
            else:
                source_has_audio = any(
                    item.get("source") == source_key and item.get("type") == "audio"
                    for item in ctx.manual_layout
                )
                if source_has_audio:
                    ctx.pal_drift_flags[analysis_track_key] = {"rate": diagnosis.rate}
                else:
                    log(
                        f"[PAL Drift Detected] PAL drift detected in "
                        f"{source_key}, but no audio tracks from this "
                        f"source are being used. Skipping PAL correction "
                        f"for {source_key}."
                    )

        elif (
            isinstance(diagnosis, DriftDiagnosis)
            and diagnosis.diagnosis == "LINEAR_DRIFT"
        ):
            if use_source_separated_settings:
                log(
                    f"[Linear Drift Detected] Linear drift detected in "
                    f"{source_key}, but source separation is enabled. "
                    f"Linear drift correction is unreliable on separated "
                    f"stems - skipping."
                )
            else:
                source_has_audio = any(
                    item.get("source") == source_key and item.get("type") == "audio"
                    for item in ctx.manual_layout
                )
                if source_has_audio:
                    ctx.linear_drift_flags[analysis_track_key] = {
                        "rate": diagnosis.rate
                    }
                else:
                    log(
                        f"[Linear Drift Detected] Linear drift detected in "
                        f"{source_key}, but no audio tracks from this "
                        f"source are being used. Skipping linear drift "
                        f"correction for {source_key}."
                    )

        elif isinstance(diagnosis, SteppingDiagnosis):
            if use_source_separated_settings:
                pass  # Already handled in _handle_stepping
            else:
                source_has_audio = any(
                    item.get("source") == source_key and item.get("type") == "audio"
                    for item in ctx.manual_layout
                )
                source_has_subs = any(
                    item.get("source") == source_key and item.get("type") == "subtitles"
                    for item in ctx.manual_layout
                )

                if source_has_audio:
                    ctx.segment_flags[analysis_track_key] = {
                        "base_delay": final_delay_ms,
                        "cluster_details": diagnosis.cluster_details,
                        "valid_clusters": diagnosis.valid_clusters,
                        "invalid_clusters": diagnosis.invalid_clusters,
                        "validation_results": diagnosis.validation_results,
                        "correction_mode": diagnosis.correction_mode,
                        "fallback_mode": diagnosis.fallback_mode or "nearest",
                        "subs_only": False,
                    }
                    log(
                        f"[Stepping] Stepping correction will be applied "
                        f"to audio tracks from {source_key}."
                    )
                elif source_has_subs and settings.stepping_adjust_subtitles_no_audio:
                    log(
                        f"[Stepping Detected] Stepping detected in "
                        f"{source_key}. No audio tracks from this source, "
                        f"but subtitles will use verified stepping EDL."
                    )
                    ctx.segment_flags[analysis_track_key] = {
                        "base_delay": final_delay_ms,
                        "cluster_details": diagnosis.cluster_details,
                        "valid_clusters": diagnosis.valid_clusters,
                        "invalid_clusters": diagnosis.invalid_clusters,
                        "validation_results": diagnosis.validation_results,
                        "correction_mode": diagnosis.correction_mode,
                        "fallback_mode": diagnosis.fallback_mode or "nearest",
                        "subs_only": True,
                    }
                    log(
                        "[Stepping] Full stepping analysis will run "
                        "for verified subtitle EDL."
                    )
                else:
                    log(
                        f"[Stepping Detected] Stepping detected in "
                        f"{source_key}, but no audio or subtitle tracks "
                        f"from this source are being used. Skipping "
                        f"stepping correction."
                    )
