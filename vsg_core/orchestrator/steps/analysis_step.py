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
    """
    Selects the best delay from a list of chunk results using mode and tie-breaking.
    This logic was moved from the old correlation engine to the orchestrator.
    """
    accepted = [r for r in results if r.get('accepted', False)]

    # Log summary of accepted chunks
    total_chunks = len(results)
    accepted_count = len(accepted)
    accepted_pct = (accepted_count / total_chunks * 100.0) if total_chunks > 0 else 0.0
    runner._log_message(f"Accepted {accepted_count} / {total_chunks} chunks ({accepted_pct:.1f}%)")

    if not accepted:
        runner._log_message(f"No chunks met the minimum match threshold ({min_match_pct:.1f}%). Failing analysis step.")
        return None

    # Bin by rounded delay to find the mode (most frequent result)
    counts = Counter(r['delay'] for r in accepted)

    # Build summary of bins for logging and tie-breaking
    binned_results = {}
    for r in accepted:
        delay_bin = r['delay']
        if delay_bin not in binned_results:
            binned_results[delay_bin] = {'matches': [], 'raw_delays': []}
        binned_results[delay_bin]['matches'].append(r['match'])
        binned_results[delay_bin]['raw_delays'].append(r['raw_delay'])

    summary_bins = []
    for delay, data in binned_results.items():
        summary_bins.append({
            'delay': delay,
            'hits': len(data['matches']),
            'avg_match': np.mean(data['matches'])
        })

    # Sort by hits (desc), then by average match (desc)
    summary_bins.sort(key=lambda x: (x['hits'], x['avg_match']), reverse=True)

    # Log the top bins
    runner._log_message("Bins (rounded ms):")
    for b in summary_bins[:3]: # Log top 3
        runner._log_message(f"  {b['delay']:+d} ms → {b['hits']} hits (avg match {b['avg_match']:.1f}%)")

    winner = summary_bins[0]
    runner._log_message(f"{role_tag.capitalize()} delay candidate: {winner['delay']:+d} ms (mode).")

    return winner['delay']


class AnalysisStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        mode = ctx.settings.analysis_mode.value # Get string value from enum
        delay_sec: Optional[int] = None
        delay_ter: Optional[int] = None

        if ctx.sec_file:
            runner._log_message(f'Analyzing Secondary file ({mode})...')
            if mode == 'VideoDiff':
                delay_ms, err = run_videodiff(ctx.ref_file, ctx.sec_file, ctx.settings_dict, runner, ctx.tool_paths)
                if not (ctx.settings.videodiff_error_min <= err <= ctx.settings.videodiff_error_max):
                    raise RuntimeError(f"VideoDiff error ({err:.2f}) out of bounds [{ctx.settings.videodiff_error_min}, {ctx.settings.videodiff_error_max}].")
                delay_sec = delay_ms
            else:
                results = run_audio_correlation(
                    ctx.ref_file, ctx.sec_file, ctx.temp_dir, ctx.settings_dict,
                    runner, ctx.tool_paths, ref_lang=ctx.settings.analysis_lang_ref,
                    target_lang=ctx.settings.analysis_lang_sec, role_tag='sec'
                )
                delay_sec = _select_best_delay(results, ctx.settings.min_match_pct, runner, 'Sec')

            if delay_sec is None:
                raise RuntimeError('Audio analysis for Secondary yielded no valid result.')
            runner._log_message(f'Secondary delay determined: {delay_sec} ms')

        if ctx.ter_file:
            runner._log_message(f'Analyzing Tertiary file ({mode})...')
            if mode == 'VideoDiff':
                delay_ms, err = run_videodiff(ctx.ref_file, ctx.ter_file, ctx.settings_dict, runner, ctx.tool_paths)
                if not (ctx.settings.videodiff_error_min <= err <= ctx.settings.videodiff_error_max):
                    raise RuntimeError(f"VideoDiff error ({err:.2f}) out of bounds [{ctx.settings.videodiff_error_min}, {ctx.settings.videodiff_error_max}].")
                delay_ter = delay_ms
            else:
                results = run_audio_correlation(
                    ctx.ref_file, ctx.ter_file, ctx.temp_dir, ctx.settings_dict,
                    runner, ctx.tool_paths, ref_lang=ctx.settings.analysis_lang_ref,
                    target_lang=ctx.settings.analysis_lang_ter, role_tag='ter'
                )
                delay_ter = _select_best_delay(results, ctx.settings.min_match_pct, runner, 'Ter')

            if delay_ter is None:
                raise RuntimeError('Audio analysis for Tertiary yielded no valid result.')
            runner._log_message(f'Tertiary delay determined: {delay_ter} ms')

        present = [0]
        if delay_sec is not None: present.append(delay_sec)
        if delay_ter is not None: present.append(delay_ter)
        min_delay = min(present)
        global_shift = -min_delay if min_delay < 0 else 0

        ctx.delay_sec_val = delay_sec
        ctx.delay_ter_val = delay_ter
        ctx.delays = Delays(
            secondary_ms=delay_sec,
            tertiary_ms=delay_ter,
            global_shift_ms=global_shift
        )

        sec_disp = delay_sec if delay_sec is not None else 'N/A'
        ter_disp = delay_ter if delay_ter is not None else 'N/A'
        runner._log_message(f'[Delay] Raw delays (ms): ref=0, sec={sec_disp}, ter={ter_disp}')
        if global_shift > 0:
            runner._log_message(f'[Delay] Applying lossless global shift: +{global_shift} ms')

        return ctx
