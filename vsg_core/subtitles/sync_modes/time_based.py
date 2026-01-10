# vsg_core/subtitles/sync_modes/time_based.py
# -*- coding: utf-8 -*-
"""
Time-based subtitle synchronization mode.

Applies raw audio delay directly to subtitle timestamps without frame verification.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
import pysubs2
import math
from ..metadata_preserver import SubtitleMetadata


def apply_raw_delay_sync(
    subtitle_path: str,
    total_delay_with_global_ms: float,
    raw_global_shift_ms: float,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Apply raw audio delay using the same logic as correlation-frame-snap mode.

    This mode does everything correlation-frame-snap does EXCEPT scene detection:
    1. Load subtitles via pysubs2
    2. Apply raw delay with floor rounding at final step
    3. Preserve metadata (Aegisub extradata, etc.)
    4. Save subtitles

    Same calculations as correlation-frame-snap's no-scene-matches path.
    Use this when you want the benefits of pysubs2 processing without frame verification.

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        total_delay_with_global_ms: Total delay including global shift (from raw_source_delays_ms)
        raw_global_shift_ms: Global shift that was applied (for logging breakdown)
        runner: CommandRunner for logging
        config: Optional config dict

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
        'final_offset_applied': final_offset_int
    }
