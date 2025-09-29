# vsg_core/subtitles/timing.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from collections import defaultdict
import pysubs2

def fix_subtitle_timing(subtitle_path: str, config: dict, runner) -> dict:
    """
    Applies various timing corrections to a subtitle file based on config.
    This function is a wrapper that calls specific fixing functions in the correct order.
    """
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
        report = defaultdict(int)

        # *** THE FIX IS HERE: Corrected order of operations ***

        # 1. Fix overlaps first to clean the initial state.
        if config.get('timing_fix_overlaps', False):
            fixed_count = fix_overlaps(subs, config.get('timing_overlap_min_gap_ms', 1))
            if fixed_count > 0:
                report['overlaps_fixed'] = fixed_count

        # 2. Fix short durations to ensure a minimum reading time for all subtitles.
        if config.get('timing_fix_short_durations', False):
            fixed_count = fix_short_durations(subs, config.get('timing_min_duration_ms', 500))
            if fixed_count > 0:
                report['short_durations_fixed'] = fixed_count

        # 3. Fix long durations last, to trim excess time without violating the minimum duration.
        if config.get('timing_fix_long_durations', False):
            fixed_count = fix_long_durations(subs, config.get('timing_max_cps', 20.0), config.get('timing_min_duration_ms', 500))
            if fixed_count > 0:
                report['long_durations_fixed'] = fixed_count

        if report:
            subs.save(subtitle_path, encoding='utf-8')

        return dict(report)

    except Exception as e:
        runner._log_message(f"[TimingFix] ERROR: Could not process file '{subtitle_path}': {e}")
        return {}

def fix_overlaps(subs: pysubs2.SSAFile, min_gap_ms: int = 1) -> int:
    """
    Fixes overlapping subtitles by adjusting the end time of the earlier subtitle.
    """
    fixed_count = 0
    for i in range(len(subs) - 1):
        line1 = subs[i]
        line2 = subs[i+1]

        if line1.end > line2.start:
            new_end = line2.start - min_gap_ms
            if new_end > line1.start:
                line1.end = new_end
                fixed_count += 1
    return fixed_count

def fix_short_durations(subs: pysubs2.SSAFile, min_duration_ms: int = 500) -> int:
    """
    Fixes subtitles with a display time shorter than the minimum duration.
    """
    fixed_count = 0
    for line in subs:
        duration = line.end - line.start
        if 0 < duration < min_duration_ms:
            line.end = line.start + min_duration_ms
            fixed_count += 1
    return fixed_count

def fix_long_durations(subs: pysubs2.SSAFile, max_cps: float = 20.0, min_duration_ms: int = 500) -> int:
    """
    Fixes subtitles with a display time longer than what's allowed by the max CPS,
    while respecting the minimum duration.
    """
    if max_cps <= 0:
        return 0

    fixed_count = 0
    for line in subs:
        num_chars = len(line.plaintext)
        if num_chars > 0:
            # Calculate the maximum duration based on reading speed
            max_duration = (num_chars / max_cps) * 1000

            # Ensure the max duration is at least the minimum duration
            max_duration = max(max_duration, min_duration_ms)

            if line.duration > max_duration:
                line.end = line.start + int(max_duration)
                fixed_count += 1
    return fixed_count
