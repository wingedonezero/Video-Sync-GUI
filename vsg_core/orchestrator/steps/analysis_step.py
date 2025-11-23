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

def _find_first_stable_segment_delay(results: List[Dict[str, Any]], runner: CommandRunner) -> Optional[int]:
    """
    Find the delay from the first stable segment of chunks.

    This function identifies consecutive accepted chunks that share the same delay value
    and returns the delay from the first such stable group.

    Args:
        results: List of correlation results with 'delay', 'accepted', and 'start' keys
        runner: CommandRunner for logging

    Returns:
        The delay value from the first stable segment, or None if no stable segment found
    """
    accepted = [r for r in results if r.get('accepted', False)]
    if len(accepted) < 3:
        return None

    # Group consecutive chunks with the same delay (within 1ms tolerance)
    segments = []
    current_segment = {'delay': accepted[0]['delay'], 'count': 1, 'start_time': accepted[0]['start']}

    for i in range(1, len(accepted)):
        if abs(accepted[i]['delay'] - current_segment['delay']) <= 1:
            # Same segment continues
            current_segment['count'] += 1
        else:
            # New segment starts
            segments.append(current_segment)
            current_segment = {'delay': accepted[i]['delay'], 'count': 1, 'start_time': accepted[i]['start']}

    # Don't forget the last segment
    segments.append(current_segment)

    # Return the delay from the first segment (which has the earliest start time)
    if segments:
        first_segment = segments[0]
        runner._log_message(
            f"[Stepping] First stable segment: {first_segment['count']} chunks at {first_segment['delay']}ms "
            f"(starting at {first_segment['start_time']:.1f}s)"
        )
        return first_segment['delay']

    return None

def _choose_final_delay(results: List[Dict[str, Any]], config: Dict, runner: CommandRunner, role_tag: str) -> Optional[int]:
    min_match_pct = float(config.get('min_match_pct', 5.0))
    min_accepted_chunks = int(config.get('min_accepted_chunks', 3))
    delay_mode = config.get('delay_selection_mode', 'Mode (Most Common)')

    accepted = [r for r in results if r.get('accepted', False)]
    if len(accepted) < min_accepted_chunks:
        runner._log_message(f"[ERROR] Analysis failed: Only {len(accepted)} chunks were accepted.")
        return None

    delays = [r['delay'] for r in accepted]

    if delay_mode == 'First Stable':
        # Use proper stability detection to find first stable segment
        winner = _find_first_stable_segment_delay(results, runner)
        if winner is None:
            # Fallback to mode if no stable segment found
            runner._log_message(f"[WARNING] No stable segment found, falling back to mode.")
            counts = Counter(delays)
            winner = counts.most_common(1)[0][0]
            method_label = "mode (fallback)"
        else:
            method_label = "first stable"
    elif delay_mode == 'Average':
        winner = round(sum(delays) / len(delays))
        method_label = "average"
    else:  # Mode (Most Common) - default
        counts = Counter(delays)
        winner = counts.most_common(1)[0][0]
        method_label = "mode"

    runner._log_message(f"{role_tag.capitalize()} delay determined: {winner:+d} ms ({method_label}).")
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
        source1_video_container_delay = 0

        ref_lang = config.get('analysis_lang_source1')
        if source1_info:
            # Get video track delay first
            video_tracks = [t for t in source1_info.get('tracks', []) if t.get('type') == 'video']
            if video_tracks:
                video_track_id = video_tracks[0].get('id')
                source1_video_container_delay = source1_container_delays.get(video_track_id, 0)

            # CRITICAL FIX: Convert ALL Source 1 audio tracks to relative delays
            # This ensures they're stored correctly for later use in extraction/mux
            for track in source1_info.get('tracks', []):
                if track.get('type') == 'audio':
                    tid = track.get('id')
                    absolute_delay = source1_container_delays.get(tid, 0)
                    relative_delay = absolute_delay - source1_video_container_delay
                    source1_container_delays[tid] = relative_delay  # Update with relative delay

            audio_tracks = [t for t in source1_info.get('tracks', []) if t.get('type') == 'audio']

            if ref_lang:
                for track in audio_tracks:
                    if (track.get('properties', {}).get('language', '') or '').strip().lower() == ref_lang:
                        source1_audio_track_id = track.get('id')
                        break

            if source1_audio_track_id is None and audio_tracks:
                source1_audio_track_id = audio_tracks[0].get('id')

            if source1_audio_track_id is not None:
                # Now get the relative delay (already corrected in the dict)
                source1_audio_container_delay = source1_container_delays.get(source1_audio_track_id, 0)
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

            # --- CRITICAL FIX: Detect stepping BEFORE calculating mode delay ---
            diagnosis = None
            details = {}
            stepping_override_delay = None

            if config.get('segmented_enabled', False):
                diagnosis, details = diagnose_audio_issue(
                    video_path=source1_file,
                    chunks=results,
                    config=config,
                    runner=runner,
                    tool_paths=ctx.tool_paths,
                    codec_id=target_codec_id
                )

                # If stepping detected, use first segment ONLY if stepping correction will actually run
                if diagnosis == "STEPPING":
                    stepping_sources.append(source_key)  # Track for final report

                    # Check if any audio tracks from this source are being merged
                    has_audio_from_source = any(
                        t.get('type') == 'audio' and t.get('source') == source_key
                        for t in ctx.manual_layout
                    )

                    if has_audio_from_source:
                        # Stepping correction will run, so use first segment delay
                        first_segment_delay = _find_first_stable_segment_delay(results, runner)
                        if first_segment_delay is not None:
                            stepping_override_delay = first_segment_delay
                            runner._log_message(f"[Stepping Detected] Found stepping in {source_key}")
                            runner._log_message(f"[Stepping Override] Using first segment's delay: {stepping_override_delay}ms")
                            runner._log_message(f"[Stepping Override] This delay will be used for ALL tracks (audio + subtitles) from {source_key}")
                            runner._log_message(f"[Stepping Override] Stepping correction will be applied to audio tracks during processing")
                    else:
                        # No audio tracks from this source - stepping correction won't run
                        # Use normal delay selection mode instead
                        delay_mode = config.get('delay_selection_mode', 'Mode (Most Common)')
                        runner._log_message(f"[Stepping Detected] Found stepping in {source_key}")
                        runner._log_message(f"[Stepping] No audio tracks from this source are being merged")
                        runner._log_message(f"[Stepping] Using delay_selection_mode='{delay_mode}' instead of first segment (stepping correction won't run)")
                        # Don't set stepping_override_delay - let normal flow handle it

            # Use stepping override if available, otherwise calculate mode
            if stepping_override_delay is not None:
                raw_delay_ms = stepping_override_delay
                runner._log_message(f"{source_key.capitalize()} delay determined: {raw_delay_ms:+d} ms (first segment, stepping corrected).")
            else:
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

            # --- Handle drift detection flags ---
            if diagnosis:
                analysis_track_key = f"{source_key}_{target_track_id}"

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
                        # Store stepping correction info with the corrected delay and cluster diagnostics
                        ctx.segment_flags[analysis_track_key] = {
                            'base_delay': final_delay_ms,
                            'cluster_details': details.get('cluster_details', [])
                        }
                        runner._log_message(
                            f"[Stepping] Stepping correction will be applied to audio tracks from {source_key}."
                        )
                    else:
                        runner._log_message(
                            f"[Stepping Detected] Stepping detected in {source_key}, but no audio tracks "
                            f"from this source are being used. Subtitle sync will still use first segment delay."
                        )

        # Store stepping sources in context for final report
        ctx.stepping_sources = stepping_sources

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
