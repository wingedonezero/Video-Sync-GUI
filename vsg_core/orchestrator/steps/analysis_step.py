# vsg_core/orchestrator/steps/analysis_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, List, Dict, Any, Tuple
from collections import Counter
import numpy as np

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import Delays
from vsg_core.analysis import run_audio_correlation, run_videodiff

def _detect_step_segments(accepted_chunks: List[Dict], runner: CommandRunner, role_tag: str) -> Optional[List[Dict]]:
    """Detect if there are distinct delay segments and create an EDL."""
    if len(accepted_chunks) < 5:
        return None

    delays = [chunk['delay'] for chunk in accepted_chunks]

    # Group consecutive chunks with similar delays (within 50ms tolerance)
    segments = []
    current_delay = delays[0]
    current_start_time = accepted_chunks[0]['start']
    current_chunks = [accepted_chunks[0]]

    for i, chunk in enumerate(accepted_chunks[1:], 1):
        if abs(chunk['delay'] - current_delay) <= 50:  # Same segment
            current_chunks.append(chunk)
        else:  # New segment detected
            # Close current segment
            segments.append({
                'start_time': current_start_time,
                'end_time': current_chunks[-1]['start'] + 15,  # chunk duration
                'delay_ms': current_delay,
                'chunk_count': len(current_chunks)
            })
            # Start new segment
            current_delay = chunk['delay']
            current_start_time = chunk['start']
            current_chunks = [chunk]

    # Close final segment
    segments.append({
        'start_time': current_start_time,
        'end_time': current_chunks[-1]['start'] + 15,
        'delay_ms': current_delay,
        'chunk_count': len(current_chunks)
    })

    if len(segments) > 1:
        runner._log_message(f"[Stepping] Detected {len(segments)} delay segments in {role_tag}")
        for i, seg in enumerate(segments):
            runner._log_message(f"  Segment {i+1}: {seg['start_time']:.1f}s-{seg['end_time']:.1f}s, delay={seg['delay_ms']:+d}ms ({seg['chunk_count']} chunks)")
        return segments

    return None

# NEW: More robust result selection logic with stepping detection
def _choose_final_delay(results: List[Dict[str, Any]], config: Dict, runner: CommandRunner, role_tag: str) -> Tuple[Optional[int], Optional[List[Dict]]]:
    min_match_pct = float(config.get('min_match_pct', 5.0))
    min_accepted_chunks = int(config.get('min_accepted_chunks', 3))
    correlation_method = config.get('correlation_method', 'Standard Correlation (SCC)')

    accepted = [r for r in results if r.get('accepted', False)]
    total_chunks, accepted_count = len(results), len(accepted)
    accepted_pct = (accepted_count / total_chunks * 100.0) if total_chunks > 0 else 0.0
    runner._log_message(f"Accepted {accepted_count} / {total_chunks} chunks ({accepted_pct:.1f}%)")

    # NEW: Enforce minimum number of accepted chunks
    if accepted_count < min_accepted_chunks:
        runner._log_message(f"[ERROR] Analysis failed: Only {accepted_count} chunks were accepted, which is below the required minimum of {min_accepted_chunks}.")
        return None, None

    # NEW: Log drift metric if enabled
    if config.get('log_audio_drift', True) and accepted_count >= 2:
        sorted_chunks = sorted(accepted, key=lambda r: r['start'])
        first_delay = sorted_chunks[0]['delay']
        last_delay = sorted_chunks[-1]['delay']
        drift = last_delay - first_delay
        if drift != 0:
             runner._log_message(f"[Drift] Detected {drift:+} ms drift between the first and last accepted chunks.")

    # NEW: Check for stepping if segmented correction is enabled
    segment_edl = None
    if config.get('segmented_enabled', False) and accepted_count >= 5:
        segment_edl = _detect_step_segments(accepted, runner, role_tag)

    # NEW: Use weighted median for GCC-PHAT for better statistical stability
    if 'Phase Correlation (GCC-PHAT)' in correlation_method:
        delays = np.array([r['delay'] for r in accepted])
        weights = np.array([r['match'] for r in accepted]).astype(int) # Weights must be integers for np.repeat

        weighted_delays = np.repeat(delays, weights)
        median_delay = int(round(np.median(weighted_delays)))

        runner._log_message(f"{role_tag.capitalize()} delay determined: {median_delay:+d} ms (weighted median).")
        return median_delay, segment_edl
    else:
        # LEGACY METHOD: Use mode for Standard Correlation
        counts = Counter(r['delay'] for r in accepted)
        binned_results = {delay: {'matches': [], 'raw_delays': []} for delay in counts}
        for r in accepted:
            binned_results[r['delay']]['matches'].append(r['match'])
            binned_results[r['delay']]['raw_delays'].append(r['raw_delay'])

        summary_bins = [{'delay': d, 'hits': len(data['matches']), 'avg_match': np.mean(data['matches'])} for d, data in binned_results.items()]
        summary_bins.sort(key=lambda x: (x['hits'], x['avg_match']), reverse=True)

        winner = summary_bins[0]
        runner._log_message(f"{role_tag.capitalize()} delay determined: {winner['delay']:+d} ms (mode).")
        return winner['delay'], segment_edl


class AnalysisStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            raise ValueError("Context is missing Source 1 for analysis.")

        # NEW: Router logic based on settings
        config = ctx.settings_dict
        correlation_method = config.get('correlation_method', 'Standard Correlation (SCC)')

        # NEW: Handle unimplemented features gracefully
        if config.get('source_separation_model') == 'Demucs (Isolate Dialogue)':
            raise NotImplementedError("Demucs source separation is not yet implemented. Please select 'None' in settings.")

        source_delays: Dict[str, int] = {}
        segment_edls: Dict[str, List[Dict]] = {}  # NEW: Store EDLs

        for source_key, source_file in sorted(ctx.sources.items()):
            if source_key == "Source 1":
                continue

            runner._log_message(f"Analyzing {source_key} file ({correlation_method})...")

            delay_ms: Optional[int] = None
            edl: Optional[List[Dict]] = None

            if correlation_method == 'VideoDiff':
                delay, err = run_videodiff(str(source1_file), str(source_file), config, runner, ctx.tool_paths)
                if not (ctx.settings.videodiff_error_min <= err <= ctx.settings.videodiff_error_max):
                    raise RuntimeError(f"VideoDiff error for {source_key} ({err:.2f}) out of bounds [{ctx.settings.videodiff_error_min:.2f}-{ctx.settings.videodiff_error_max:.2f}].")
                delay_ms = delay
            else: # Handle all audio correlation methods
                results = run_audio_correlation(
                    str(source1_file), str(source_file), config, runner, ctx.tool_paths,
                    ref_lang=ctx.settings.analysis_lang_source1,
                    target_lang=ctx.settings.analysis_lang_others,
                    role_tag=source_key
                )
                delay_ms, edl = _choose_final_delay(results, config, runner, source_key)

            if delay_ms is None:
                raise RuntimeError(f'Analysis for {source_key} failed to determine a reliable delay.')

            runner._log_message(f'Final {source_key} delay: {delay_ms} ms')
            source_delays[source_key] = delay_ms

            # NEW: Store EDL if detected
            if edl:
                segment_edls[source_key] = edl

        present_delays = [0] + list(source_delays.values())
        min_delay = min(present_delays)
        global_shift = -min_delay if min_delay < 0 else 0

        ctx.delays = Delays(
            source_delays_ms=source_delays,
            global_shift_ms=global_shift
        )

        # NEW: Store segment EDLs in context
        ctx.segment_edls = segment_edls

        delay_str = ", ".join([f"{k}={v}" for k, v in source_delays.items()])
        runner._log_message(f'[Delay] Raw delays (ms): Source 1=0, {delay_str}')
        if global_shift > 0:
            runner._log_message(f'[Delay] Applying lossless global shift: +{global_shift} ms')

        return ctx
