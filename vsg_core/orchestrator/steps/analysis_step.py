# vsg_core/orchestrator/steps/analysis_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, List, Dict, Any
from collections import Counter
import numpy as np

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import Delays
from vsg_core.analysis import run_audio_correlation, run_videodiff

def _select_best_delay(results: List[Dict[str, Any]], min_match_pct: float, runner: CommandRunner, role_tag: str) -> Optional[int]:
    accepted = [r for r in results if r.get('accepted', False)]
    total_chunks, accepted_count = len(results), len(accepted)
    accepted_pct = (accepted_count / total_chunks * 100.0) if total_chunks > 0 else 0.0
    runner._log_message(f"Accepted {accepted_count} / {total_chunks} chunks ({accepted_pct:.1f}%)")

    if not accepted:
        runner._log_message(f"No chunks met the minimum match threshold ({min_match_pct:.1f}%). Failing analysis step.")
        return None

    counts = Counter(r['delay'] for r in accepted)
    binned_results = {delay: {'matches': [], 'raw_delays': []} for delay in counts}
    for r in accepted:
        binned_results[r['delay']]['matches'].append(r['match'])
        binned_results[r['delay']]['raw_delays'].append(r['raw_delay'])

    summary_bins = [{'delay': d, 'hits': len(data['matches']), 'avg_match': np.mean(data['matches'])} for d, data in binned_results.items()]
    summary_bins.sort(key=lambda x: (x['hits'], x['avg_match']), reverse=True)

    runner._log_message("Bins (rounded ms):")
    for b in summary_bins[:3]:
        runner._log_message(f"  {b['delay']:+d} ms → {b['hits']} hits (avg match {b['avg_match']:.1f}%)")

    winner = summary_bins[0]
    runner._log_message(f"{role_tag.capitalize()} delay candidate: {winner['delay']:+d} ms (mode).")
    return winner['delay']

class AnalysisStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        mode = ctx.settings.analysis_mode.value
        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            raise ValueError("Context is missing Source 1 for analysis.")

        source_delays: Dict[str, int] = {}

        # Loop through all other sources and compare them to Source 1
        for source_key, source_file in sorted(ctx.sources.items()):
            if source_key == "Source 1":
                continue

            runner._log_message(f'Analyzing {source_key} file ({mode})...')

            delay_ms: Optional[int] = None
            if mode == 'VideoDiff':
                delay, err = run_videodiff(str(source1_file), str(source_file), ctx.settings_dict, runner, ctx.tool_paths)
                if not (ctx.settings.videodiff_error_min <= err <= ctx.settings.videodiff_error_max):
                    raise RuntimeError(f"VideoDiff error for {source_key} ({err:.2f}) out of bounds.")
                delay_ms = delay
            else:
                results = run_audio_correlation(
                    str(source1_file), str(source_file), ctx.temp_dir, ctx.settings_dict, runner, ctx.tool_paths,
                    ref_lang=ctx.settings.analysis_lang_source1,
                    target_lang=ctx.settings.analysis_lang_others,
                    role_tag=source_key
                )
                delay_ms = _select_best_delay(results, ctx.settings.min_match_pct, runner, source_key)

            if delay_ms is None:
                raise RuntimeError(f'Analysis for {source_key} yielded no valid result.')

            runner._log_message(f'{source_key} delay determined: {delay_ms} ms')
            source_delays[source_key] = delay_ms

        present_delays = [0] + list(source_delays.values())
        min_delay = min(present_delays)
        global_shift = -min_delay if min_delay < 0 else 0

        ctx.delays = Delays(
            source_delays_ms=source_delays,
            global_shift_ms=global_shift
        )

        delay_str = ", ".join([f"{k}={v}" for k, v in source_delays.items()])
        runner._log_message(f'[Delay] Raw delays (ms): Source 1=0, {delay_str}')
        if global_shift > 0:
            runner._log_message(f'[Delay] Applying lossless global shift: +{global_shift} ms')

        return ctx
