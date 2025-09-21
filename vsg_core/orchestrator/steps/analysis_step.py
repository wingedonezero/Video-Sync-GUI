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
from vsg_core.extraction.tracks import get_stream_info

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

        config = ctx.settings_dict
        source_delays: Dict[str, int] = {}

        for source_key, source_file in sorted(ctx.sources.items()):
            if source_key == "Source 1":
                continue

            runner._log_message(f"--- Analyzing {source_key} ---")
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

            delay_ms = _choose_final_delay(results, config, runner, source_key)
            if delay_ms is None:
                raise RuntimeError(f'Analysis for {source_key} failed to determine a reliable delay.')

            source_delays[source_key] = delay_ms

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

                if diagnosis == "PAL_DRIFT":
                    ctx.pal_drift_flags[analysis_track_key] = details
                elif diagnosis == "LINEAR_DRIFT":
                    ctx.linear_drift_flags[analysis_track_key] = details
                elif diagnosis == "STEPPING":
                    ctx.segment_flags[analysis_track_key] = { 'base_delay': delay_ms }

        # --- MODIFICATION START ---
        # The global_shift logic is removed entirely. Source 1 is now the immutable
        # zero-point, and other tracks will have their direct delays applied.
        ctx.delays = Delays(source_delays_ms=source_delays, global_shift_ms=0)
        runner._log_message(f"[Delay] Source delays calculated. Source 1 is the zero-point reference.")
        # --- MODIFICATION END ---

        return ctx
