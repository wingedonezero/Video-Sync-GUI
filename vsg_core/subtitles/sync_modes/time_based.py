# vsg_core/subtitles/sync_modes/time_based.py
# -*- coding: utf-8 -*-
"""
Time-based subtitle synchronization mode.

Applies raw audio delay directly to subtitle timestamps without frame verification.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
import pysubs2
import math
from ..metadata_preserver import SubtitleMetadata
from ..frame_utils import time_to_frame_floor


def _simulate_cs_rounding(time_ms: int) -> int:
    """
    Simulate how pysubs2 rounds to centiseconds when saving to ASS.

    pysubs2 uses standard rounding: round(ms / 10) * 10
    - Times ending in 0-4 round down
    - Times ending in 5-9 round up
    """
    return round(time_ms / 10) * 10


def _adjust_for_cs_frame_boundary(time_ms: int, fps: float, max_adjustment_ms: int = 30) -> int:
    """
    Adjust time_ms (if needed) so that when rounded to centiseconds,
    it stays in the same frame.

    Problem: ASS format only supports centiseconds (10ms precision).
    When rounding milliseconds to centiseconds, we can accidentally push
    a subtitle across a frame boundary, causing ±1 frame timing errors.

    Solution: Detect when CS rounding changes the frame, and micro-adjust
    by ±10-30ms to keep the subtitle in the intended frame.

    Args:
        time_ms: Original time in integer milliseconds
        fps: Target video frame rate
        max_adjustment_ms: Maximum adjustment allowed (default 30ms = 3 centiseconds)

    Returns:
        Adjusted time_ms that stays in correct frame after CS rounding

    Example at 23.976 fps:
        4171ms is in frame 100
        But CS rounding: 4171ms → 4170ms (now in frame 99) ❌
        Solution: Adjust to 4181ms → 4180ms (stays in frame 100) ✅
    """
    # Determine which frame this time is in
    intended_frame = time_to_frame_floor(time_ms, fps)

    # Check if CS rounding keeps us in the same frame
    cs_rounded = _simulate_cs_rounding(time_ms)
    actual_frame = time_to_frame_floor(cs_rounded, fps)

    if actual_frame == intended_frame:
        return time_ms  # No adjustment needed

    # Try small adjustments to get into correct frame
    # Try positive adjustments first (prefer later time to avoid early starts)
    for delta in [10, 20, 30, -10, -20, -30]:
        if abs(delta) > max_adjustment_ms:
            break

        adjusted = time_ms + delta
        cs_adjusted = _simulate_cs_rounding(adjusted)
        adjusted_frame = time_to_frame_floor(cs_adjusted, fps)

        if adjusted_frame == intended_frame:
            return adjusted

    # Can't fix without exceeding max adjustment - return original
    return time_ms


def _apply_frame_boundary_correction(subs, fps: float, runner) -> Dict[str, int]:
    """
    Apply frame boundary correction to all subtitle events.

    Call this AFTER applying correlation offset, BEFORE saving to ASS.
    Ensures centisecond rounding doesn't push subtitles into wrong frames.

    Args:
        subs: pysubs2.SSAFile object (events already have offset applied)
        fps: Target video frame rate
        runner: CommandRunner for logging

    Returns:
        Stats dict with correction counts
    """
    if not subs.events or fps <= 0:
        return {'corrected_starts': 0, 'corrected_ends': 0, 'total_events': len(subs.events) if subs.events else 0}

    corrected_starts = 0
    corrected_ends = 0

    for event in subs.events:
        # Check and correct start time
        original_start = event.start
        corrected_start = _adjust_for_cs_frame_boundary(event.start, fps)
        if corrected_start != original_start:
            event.start = corrected_start
            corrected_starts += 1

        # Check and correct end time
        original_end = event.end
        corrected_end = _adjust_for_cs_frame_boundary(event.end, fps)
        if corrected_end != original_end:
            event.end = corrected_end
            corrected_ends += 1

    return {
        'corrected_starts': corrected_starts,
        'corrected_ends': corrected_ends,
        'total_events': len(subs.events)
    }


def apply_raw_delay_sync(
    subtitle_path: str,
    total_delay_with_global_ms: float,
    raw_global_shift_ms: float,
    runner,
    config: dict = None,
    target_fps: Optional[float] = None,
    enable_frame_boundary_correction: bool = True
) -> Dict[str, Any]:
    """
    Apply raw audio delay using the same logic as correlation-frame-snap mode.

    This mode does everything correlation-frame-snap does EXCEPT scene detection:
    1. Load subtitles via pysubs2
    2. Apply raw delay with floor rounding at final step
    3. Optionally apply frame boundary correction (prevents ±1 frame errors from CS rounding)
    4. Preserve metadata (Aegisub extradata, etc.)
    5. Save subtitles

    Same calculations as correlation-frame-snap's no-scene-matches path.
    Use this when you want the benefits of pysubs2 processing without frame verification.

    Frame Boundary Correction (NEW):
        ASS format only supports centiseconds (10ms precision). When rounding milliseconds
        to centiseconds, we can accidentally push subtitles across frame boundaries,
        causing ±1 frame timing errors.

        If target_fps is provided and enable_frame_boundary_correction=True, this mode
        will detect when CS rounding changes frames and micro-adjust by ±10-30ms to
        keep subtitles in the intended frame. Only works for CFR (constant frame rate).

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        total_delay_with_global_ms: Total delay including global shift (from raw_source_delays_ms)
        raw_global_shift_ms: Global shift that was applied (for logging breakdown)
        runner: CommandRunner for logging
        config: Optional config dict
        target_fps: Target video frame rate (for frame boundary correction). If None, skips correction.
        enable_frame_boundary_correction: Whether to apply frame boundary correction (default True)

    Returns:
        Dict with report statistics
    """
    config = config or {}

    # Calculate pure correlation (same as correlation-frame-snap)
    pure_correlation_ms = total_delay_with_global_ms - raw_global_shift_ms

    runner._log_message(f"[Raw Delay Sync] ═══════════════════════════════════════")
    runner._log_message(f"[Raw Delay Sync] Raw Delay Mode (no scene detection)")
    runner._log_message(f"[Raw Delay Sync] ═══════════════════════════════════════")
    runner._log_message(f"[Raw Delay Sync] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[Raw Delay Sync] Input values:")
    runner._log_message(f"[Raw Delay Sync]   Total delay (with global): {total_delay_with_global_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   Global shift:              {raw_global_shift_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   Pure correlation:          {pure_correlation_ms:+.3f}ms")

    # Capture original metadata before pysubs2 processing
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Raw Delay Sync] ERROR: Failed to load subtitle file: {e}")
        return {'error': str(e)}

    if not subs.events:
        runner._log_message(f"[Raw Delay Sync] WARNING: No subtitle events found in file")
        return {
            'success': True,
            'total_events': 0,
            'pure_correlation_ms': pure_correlation_ms,
            'global_shift_ms': raw_global_shift_ms,
            'final_offset_applied': 0
        }

    runner._log_message(f"[Raw Delay Sync] Loaded {len(subs.events)} subtitle events")

    # Calculate final offset using floor (same as correlation-frame-snap)
    final_offset_ms = total_delay_with_global_ms
    final_offset_int = int(math.floor(final_offset_ms))

    runner._log_message(f"[Raw Delay Sync] ───────────────────────────────────────")
    runner._log_message(f"[Raw Delay Sync] Final offset calculation:")
    runner._log_message(f"[Raw Delay Sync]   Pure correlation:     {pure_correlation_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   + Global shift:       {raw_global_shift_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   ─────────────────────────────────────")
    runner._log_message(f"[Raw Delay Sync]   = Total delay:        {total_delay_with_global_ms:+.3f}ms")
    runner._log_message(f"[Raw Delay Sync]   Floor applied:        {final_offset_int:+d}ms")
    runner._log_message(f"[Raw Delay Sync] ───────────────────────────────────────")

    # Apply offset to all events (same as correlation-frame-snap)
    runner._log_message(f"[Raw Delay Sync] Applying offset to {len(subs.events)} events...")

    for event in subs.events:
        event.start += final_offset_int
        event.end += final_offset_int

    # Apply frame boundary correction (prevents ±1 frame errors from CS rounding)
    correction_stats = {'corrected_starts': 0, 'corrected_ends': 0, 'total_events': len(subs.events)}
    if target_fps and enable_frame_boundary_correction:
        runner._log_message(f"[Raw Delay Sync] ───────────────────────────────────────")
        runner._log_message(f"[Raw Delay Sync] Frame Boundary Correction (CFR)")
        runner._log_message(f"[Raw Delay Sync]   Target FPS: {target_fps}")
        runner._log_message(f"[Raw Delay Sync]   Frame duration: {1000.0/target_fps:.3f}ms")

        correction_stats = _apply_frame_boundary_correction(subs, target_fps, runner)

        if correction_stats['corrected_starts'] > 0 or correction_stats['corrected_ends'] > 0:
            runner._log_message(f"[Raw Delay Sync]   Corrected starts: {correction_stats['corrected_starts']}/{correction_stats['total_events']}")
            runner._log_message(f"[Raw Delay Sync]   Corrected ends:   {correction_stats['corrected_ends']}/{correction_stats['total_events']}")
            runner._log_message(f"[Raw Delay Sync]   Prevented CS rounding from causing frame errors")
        else:
            runner._log_message(f"[Raw Delay Sync]   No corrections needed (all times already frame-aligned)")
        runner._log_message(f"[Raw Delay Sync] ───────────────────────────────────────")

    # Save modified subtitle
    runner._log_message(f"[Raw Delay Sync] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[Raw Delay Sync] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Validate and restore lost metadata
    metadata.validate_and_restore(runner, expected_delay_ms=final_offset_int)

    runner._log_message(f"[Raw Delay Sync] Successfully synchronized {len(subs.events)} events")
    runner._log_message(f"[Raw Delay Sync] ═══════════════════════════════════════")

    return {
        'success': True,
        'total_events': len(subs.events),
        'pure_correlation_ms': pure_correlation_ms,
        'global_shift_ms': raw_global_shift_ms,
        'final_offset_ms': final_offset_ms,
        'final_offset_applied': final_offset_int,
        'frame_boundary_correction': correction_stats
    }
