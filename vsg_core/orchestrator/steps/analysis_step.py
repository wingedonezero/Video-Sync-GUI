# vsg_core/orchestrator/steps/analysis_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, List, Dict, Any
from collections import Counter

import numpy as np
from sklearn.cluster import DBSCAN

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import Delays
from vsg_core.analysis.audio_corr import run_audio_correlation, get_audio_stream_info
from vsg_core.analysis.videodiff import run_videodiff


def _choose_final_delay(results: List[Dict[str, Any]], config: Dict, runner: CommandRunner, role_tag: str) -> Optional[int]:
    min_match_pct = float(config.get('min_match_pct', 5.0))
    min_accepted_chunks = int(config.get('min_accepted_chunks', 3))

    accepted = [r for r in results if r.get('accepted', False)]
    if len(accepted) < min_accepted_chunks:
        runner._log_message(f"[ERROR] Analysis failed: Only {len(accepted)} chunks were accepted.")
        return None

    # Use the mode (most common delay) for the simple delay value
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
            _, target_track_id = get_audio_stream_info(source_file, tgt_lang, runner, ctx.tool_paths)

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

            # --- Smart Stepping Detection using DBSCAN ---
            if config.get('segmented_enabled', False):
                accepted_chunks = [r for r in results if r.get('accepted', False)]
                accepted_delays = [c['delay'] for c in accepted_chunks]

                # Read DBSCAN parameters from config, with sensible defaults
                epsilon_ms = config.get('detection_dbscan_epsilon_ms', 20.0)
                min_samples = config.get('detection_dbscan_min_samples', 2)
                min_chunks_for_test = 6

                if len(accepted_delays) >= min_chunks_for_test:
                    delays_array = np.array(accepted_delays).reshape(-1, 1)
                    db = DBSCAN(eps=epsilon_ms, min_samples=min_samples).fit(delays_array)
                    labels = db.labels_
                    unique_clusters = set(label for label in labels if label != -1)

                    if len(unique_clusters) > 1:
                        runner._log_message(f"[Stepping Detected] Found {len(unique_clusters)} distinct timing clusters for {source_key}. Flagging for detailed correction.")
                        analysis_track_key = f"{source_key}_{target_track_id}"
                        ctx.segment_flags[analysis_track_key] = {
                            'has_segments': True,
                            'base_delay': delay_ms,
                            'analysis_track_key': analysis_track_key
                        }

        min_delay = min([0] + list(source_delays.values()))
        global_shift = -min_delay if min_delay < 0 else 0
        ctx.delays = Delays(source_delays_ms=source_delays, global_shift_ms=global_shift)
        runner._log_message(f"[Delay] Global shift will be: +{global_shift} ms")

        return ctx
