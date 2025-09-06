# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional, List, Dict, Any

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import Delays
from vsg_core import analysis as core_analysis


def _best_from_results(results: List[Dict[str, Any]], min_match_pct: float) -> Optional[Dict[str, Any]]:
    if not results:
        return None
    valid = [r for r in results if r.get('match', 0.0) > float(min_match_pct)]
    if not valid:
        return None
    from collections import Counter
    counts = Counter(r['delay'] for r in valid)
    max_freq = counts.most_common(1)[0][1]
    contenders = [d for d, f in counts.items() if f == max_freq]
    best_of_each = [
        max((r for r in valid if r['delay'] == d), key=lambda x: x['match'])
        for d in contenders
    ]
    return max(best_of_each, key=lambda x: x['match'])


class AnalysisStep:
    """
    Determines delays for Secondary and Tertiary via Audio Correlation or VideoDiff,
    preserves original guardrails and logging, and computes global shift.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        mode = ctx.settings.analysis_mode  # 'Audio Correlation' or 'VideoDiff'

        ref_lang = ctx.settings.analysis_lang_ref or None
        sec_lang = ctx.settings.analysis_lang_sec or None
        ter_lang = ctx.settings.analysis_lang_ter or None

        delay_sec: Optional[int] = None
        delay_ter: Optional[int] = None

        # Secondary
        if ctx.sec_file:
            runner._log_message(f'Analyzing Secondary file ({mode})...')
            if mode == 'VideoDiff':
                delay_ms, err = core_analysis.run_videodiff(ctx.ref_file, ctx.sec_file, ctx.settings_dict, runner, ctx.tool_paths)
                if not (ctx.settings.videodiff_error_min <= err <= ctx.settings.videodiff_error_max):
                    raise RuntimeError(f"VideoDiff error ({err:.2f}) out of bounds.")
                delay_sec = delay_ms
            else:
                results = core_analysis.run_audio_correlation(
                    ctx.ref_file, ctx.sec_file, ctx.temp_dir, ctx.settings_dict,
                    runner, ctx.tool_paths, ref_lang=ref_lang, target_lang=sec_lang, role_tag='sec'
                )
                best = _best_from_results(results, ctx.settings.min_match_pct)
                if not best:
                    raise RuntimeError('Audio analysis for Secondary yielded no valid result.')
                delay_sec = int(best['delay'])
            runner._log_message(f'Secondary delay determined: {delay_sec} ms')

        # Tertiary
        if ctx.ter_file:
            runner._log_message(f'Analyzing Tertiary file ({mode})...')
            if mode == 'VideoDiff':
                delay_ms, err = core_analysis.run_videodiff(ctx.ref_file, ctx.ter_file, ctx.settings_dict, runner, ctx.tool_paths)
                if not (ctx.settings.videodiff_error_min <= err <= ctx.settings.videodiff_error_max):
                    raise RuntimeError(f"VideoDiff error ({err:.2f}) out of bounds.")
                delay_ter = delay_ms
            else:
                results = core_analysis.run_audio_correlation(
                    ctx.ref_file, ctx.ter_file, ctx.temp_dir, ctx.settings_dict,
                    runner, ctx.tool_paths, ref_lang=ref_lang, target_lang=ter_lang, role_tag='ter'
                )
                best = _best_from_results(results, ctx.settings.min_match_pct)
                if not best:
                    raise RuntimeError('Audio analysis for Tertiary yielded no valid result.')
                delay_ter = int(best['delay'])
            runner._log_message(f'Tertiary delay determined: {delay_ter} ms')

        # Global shift (unchanged behavior)
        present = [0]
        if delay_sec is not None:
            present.append(delay_sec)
        if delay_ter is not None:
            present.append(delay_ter)
        min_delay = min(present)
        global_shift = -min_delay if min_delay < 0 else 0

        ctx.delay_sec_val = delay_sec
        ctx.delay_ter_val = delay_ter
        ctx.delays = Delays(
            secondary_ms=delay_sec if delay_sec is not None else 0,
            tertiary_ms=delay_ter if delay_ter is not None else 0,
            global_shift_ms=global_shift
        )

        sec_disp = delay_sec if delay_sec is not None else 0
        ter_disp = delay_ter if delay_ter is not None else 0
        runner._log_message(f'[Delay] Raw delays (ms): ref=0, sec={sec_disp}, ter={ter_disp}')
        runner._log_message(f'[Delay] Applying lossless global shift: +{global_shift} ms')

        return ctx
