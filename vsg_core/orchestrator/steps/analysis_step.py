# vsg_core/orchestrator/steps/analysis_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, List, Dict, Any
from collections import Counter

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import Delays
from vsg_core.analysis.audio_corr import run_audio_correlation
from vsg_core.analysis.drift_detection import diagnose_audio_issue
from vsg_core.extraction.tracks import get_stream_info, get_stream_info_with_delays

def _choose_final_delay(results: List[Dict[str, Any]], config: Dict, runner: CommandRunner, role_tag: str) -> Optional[int]:
    min_match_pct = float(config.get('min_match_pct', 5.0))
    min_accepted_chunks = int(config.get('min_accepted_chunks', 3))

    accepted = [r for r in results if r.get('accepted', False)]
    if len(accepted) < min_accepted_chunks:
        runner._log_message(f"[ERROR] Analysis failed: Only {len(accepted)} chunks were accepted.")
        return None

    counts = Counter(r['delay'] for r in accepted)
    winner = counts.most_common(1)[0][0]
    runner._log_message(f"{role_tag.capitalize()} delay determined: {winner:+d} ms (mode).")
    return winner

class AnalysisStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            raise ValueError("Context is missing Source 1 for analysis.")

        # --- Part 1: Determine if a global shift is required ---
        ctx.global_shift_is_required = any(
            t.get('type') == 'audio' and t.get('source') != 'Source 1'
            for t in ctx.manual_layout
        )
        if ctx.global_shift_is_required:
            runner._log_message("[INFO] Audio tracks from secondary sources are being merged. Global shift will be used if necessary.")
        else:
            runner._log_message("[INFO] No audio tracks from secondary sources. Global shift will not be applied.")

        # NEW: Skip analysis if only Source 1 (remux-only mode)
        if len(ctx.sources) == 1:
            runner._log_message("--- Analysis Phase: Skipped (Remux-only mode - no sync sources) ---")
            ctx.delays = Delays(source_delays_ms={}, global_shift_ms=0)
            return ctx

        config = ctx.settings_dict
        source_delays: Dict[str, int] = {}

        # --- Step 1: Get Source 1's container delays for chain calculation ---
        runner._log_message("--- Getting Source 1 Container Delays for Analysis ---")
        source1_info = get_stream_info_with_delays(source1_file, runner, ctx.tool_paths)
        source1_container_delays = {}

        if source1_info:
            for track in source1_info.get('tracks', []):
                tid = track.get('id')
                delay_ms = track.get('container_delay_ms', 0)
                source1_container_delays[tid] = delay_ms

                track_type = track.get('type')
                if delay_ms != 0 and track_type in ['video', 'audio']:
                    runner._log_message(f"[Container Delay] Source 1 {track_type} track {tid} has container delay: {delay_ms:+.1f}ms")

        # Find which audio track from Source 1 will be used for correlation
        source1_audio_track_id = None
        source1_audio_container_delay = 0

        ref_lang = config.get('analysis_lang_source1')
        if source1_info:
            audio_tracks = [t for t in source1_info.get('tracks', []) if t.get('type') == 'audio']

            if ref_lang:
                for track in audio_tracks:
                    if (track.get('properties', {}).get('language', '') or '').strip().lower() == ref_lang:
                        source1_audio_track_id = track.get('id')
                        break

            if source1_audio_track_id is None and audio_tracks:
                source1_audio_track_id = audio_tracks[0].get('id')

            if source1_audio_track_id is not None:
                source1_audio_container_delay = source1_container_delays.get(source1_audio_track_id, 0)
                ctx.source1_audio_container_delay_ms = source1_audio_container_delay

                if source1_audio_container_delay != 0:
                    runner._log_message(f"[Container Delay] The delay of the analysis audio track ({source1_audio_container_delay:+.1f}ms) will be added to all correlation results.")

        # --- Step 2: Run correlation for other sources ---
        runner._log_message("\n--- Running Audio Correlation Analysis ---")
        for source_key, source_file in sorted(ctx.sources.items()):
            if source_key == "Source 1":
                continue

            runner._log_message(f"\n[Analyzing {source_key}]")
            tgt_lang = config.get('analysis_lang_others')

            stream_info = get_stream_info(source_file, runner, ctx.tool_paths)
            if not stream_info:
                runner._log_message(f"[WARN] Could not get stream info for {source_key}. Skipping.")
                continue

            audio_tracks = [t for t in stream_info.get('tracks', []) if t.get('type') == 'audio']
            target_track_obj = None
            if not audio_tracks:
                runner._log_message(f"[WARN] No audio tracks found in {source_key}. Skipping.")
                continue
            if tgt_lang:
                for track in audio_tracks:
                    if (track.get('properties', {}).get('language', '') or '').strip().lower() == tgt_lang:
                        target_track_obj = track
                        break
            if not target_track_obj:
                target_track_obj = audio_tracks[0]

            target_track_id = target_track_obj.get('id')
            target_codec_id = target_track_obj.get('properties', {}).get('codec_id', 'unknown')

            if target_track_id is None:
                runner._log_message(f"[WARN] No suitable audio track found in {source_key} for analysis. Skipping.")
                continue

            results = run_audio_correlation(
                str(source1_file), str(source_file), config, runner, ctx.tool_paths,
                ref_lang=config.get('analysis_lang_source1'),
                target_lang=tgt_lang,
                role_tag=source_key
            )

            raw_delay_ms = _choose_final_delay(results, config, runner, source_key)
            if raw_delay_ms is None:
                # ENHANCED ERROR MESSAGE
                accepted_count = len([r for r in results if r.get('accepted', False)])
                min_required = config.get('min_accepted_chunks', 3)
                total_chunks = len(results)

                raise RuntimeError(
                    f'Analysis failed for {source_key}: Could not determine a reliable delay.\n'
                    f'  - Accepted chunks: {accepted_count}\n'
                    f'  - Minimum required: {min_required}\n'
                    f'  - Total chunks scanned: {total_chunks}\n'
                    f'  - Match threshold: {config.get("min_match_pct", 5.0)}%\n'
                    f'\n'
                    f'Possible causes:\n'
                    f'  - Audio quality is too poor for reliable correlation\n'
                    f'  - Audio tracks are not from the same source material\n'
                    f'  - Excessive noise or compression artifacts\n'
                    f'  - Wrong language tracks selected for analysis\n'
                    f'\n'
                    f'Solutions:\n'
                    f'  - Try lowering the "Minimum Match %" threshold in settings\n'
                    f'  - Increase "Chunk Count" for more sample points\n'
                    f'  - Try selecting different audio tracks (check language settings)\n'
                    f'  - Use VideoDiff mode instead of Audio Correlation\n'
                    f'  - Check that both files are from the same video source'
                )

            # Calculate final delay including container delay chain correction
            final_delay_ms = round(raw_delay_ms + source1_audio_container_delay)

            if source1_audio_container_delay != 0:
                runner._log_message(f"[Delay Chain] {source_key} raw correlation: {raw_delay_ms:+d}ms")
                runner._log_message(f"[Delay Chain] Adding Source 1 audio container delay: {source1_audio_container_delay:+.1f}ms")
                runner._log_message(f"[Delay Chain] Final delay for {source_key}: {final_delay_ms:+d}ms")

            source_delays[source_key] = final_delay_ms

            # --- Drift detection uses the raw correlation results ---
            if config.get('segmented_enabled', False):
                diagnosis, details = diagnose_audio_issue(
                    video_path=source1_file,
                    chunks=results,
                    config=config,
                    runner=runner,
                    tool_paths=ctx.tool_paths,
                    codec_id=target_codec_id
                )

                analysis_track_key = f"{source_key}_{target_track_id}"

                # FIX 1: Only add to drift flags if this source has audio tracks being used
                if diagnosis == "PAL_DRIFT":
                    source_has_audio_in_layout = any(
                        item.get('source') == source_key and item.get('type') == 'audio'
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
                    source_has_audio_in_layout = any(
                        item.get('source') == source_key and item.get('type') == 'audio'
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
                    source_has_audio_in_layout = any(
                        item.get('source') == source_key and item.get('type') == 'audio'
                        for item in ctx.manual_layout
                    )

                    if source_has_audio_in_layout:
                        ctx.segment_flags[analysis_track_key] = { 'base_delay': final_delay_ms }
                    else:
                        runner._log_message(
                            f"[Stepping Detected] Stepping detected in {source_key}, but no audio tracks "
                            f"from this source are being used. Skipping stepping correction for {source_key}."
                        )

        # Initialize Source 1 with 0ms base delay so it gets the global shift
        source_delays["Source 1"] = 0

        # --- Step 3: Calculate Global Shift to Handle Negative Delays ---
        runner._log_message("\n--- Calculating Global Shift ---")

        delays_to_consider = []
        if ctx.global_shift_is_required:
            runner._log_message("[Global Shift] Identifying delays from sources contributing audio tracks...")
            for item in ctx.manual_layout:
                item_source = item.get('source')
                item_type = item.get('type')
                if item_type == 'audio':
                    if item_source in source_delays and source_delays[item_source] not in delays_to_consider:
                        delays_to_consider.append(source_delays[item_source])
                        runner._log_message(f"  - Considering delay from {item_source}: {source_delays[item_source]}ms")

            if source1_container_delays and source1_info:
                audio_container_delays = []
                for track in source1_info.get('tracks', []):
                    if track.get('type') == 'audio':
                        tid = track.get('id')
                        delay = source1_container_delays.get(tid, 0)
                        if delay != 0:
                            audio_container_delays.append(delay)

                if audio_container_delays:
                    delays_to_consider.extend(audio_container_delays)
                    runner._log_message("  - Considering Source 1 audio container delays (video delays ignored).")

        most_negative = min(delays_to_consider) if delays_to_consider else 0
        global_shift_ms = 0

        if most_negative < 0:
            global_shift_ms = abs(most_negative)
            runner._log_message(f"[Delay] Most negative relevant delay: {most_negative}ms")
            runner._log_message(f"[Delay] Applying lossless global shift: +{global_shift_ms}ms")
            runner._log_message(f"[Delay] Adjusted delays after global shift:")
            for source_key in sorted(source_delays.keys()):
                original_delay = source_delays[source_key]
                source_delays[source_key] += global_shift_ms
                runner._log_message(f"  - {source_key}: {original_delay:+.1f}ms → {source_delays[source_key]:+.1f}ms")

            if source1_container_delays:
                runner._log_message(f"[Delay] Source 1 container delays (will have +{global_shift_ms}ms added during mux):")
                for track in source1_info.get('tracks', []):
                    if track.get('type') in ['audio', 'video']:
                        tid = track.get('id')
                        delay = source1_container_delays.get(tid, 0)
                        final_delay = delay + global_shift_ms
                        track_type = track.get('type')

                        note = " (will be ignored - video defines timeline)" if track_type == 'video' else ""
                        runner._log_message(f"  - Track {tid} ({track_type}): {delay:+.1f}ms → {final_delay:+.1f}ms{note}")
        else:
            runner._log_message(f"[Delay] All relevant delays are non-negative. No global shift needed.")

        # Store the calculated delays with global shift
        ctx.delays = Delays(source_delays_ms=source_delays, global_shift_ms=global_shift_ms)

        # Final summary
        runner._log_message(f"\n[Delay] === FINAL DELAYS (Global Shift: +{global_shift_ms}ms) ===")
        for source_key, delay_ms in sorted(source_delays.items()):
            runner._log_message(f"  - {source_key}: {delay_ms:+d}ms")

        return ctx
