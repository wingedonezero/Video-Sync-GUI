# vsg_core/analysis/delay_selection/first_stable.py
"""
First stable segment delay selection.

Identifies consecutive accepted chunks that share the same delay value
and returns the delay from the first stable group meeting stability criteria.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vsg_core.models import ChunkResult


class FirstStableSelector:
    """Select delay from the first stable segment of chunks."""

    name = "First Stable"
    key = "first_stable"

    def select(
        self,
        accepted_results: list[ChunkResult],
        config: dict[str, Any],
        log: Callable[[str], None] | None = None,
    ) -> tuple[int, float]:
        """
        Find the first stable segment and return its delay.

        Config options:
            first_stable_min_chunks: Minimum chunks for stability (default: 3)
            first_stable_skip_unstable: Skip segments below min (default: True)

        Returns:
            Tuple of (rounded_delay_ms, raw_delay_ms)
        """
        result = find_first_stable_segment_delay(accepted_results, config, log)

        if result is not None:
            return result

        # Fallback to mode if no stable segment found
        if log:
            log("[WARNING] No stable segment found, falling back to mode.")

        delays = [r.delay_ms for r in accepted_results]
        counts = Counter(delays)
        winner_rounded = counts.most_common(1)[0][0]

        # Get raw value for the mode
        for r in accepted_results:
            if r.delay_ms == winner_rounded:
                return winner_rounded, r.raw_delay_ms

        return winner_rounded, float(winner_rounded)


def find_first_stable_segment_delay(
    results: list[ChunkResult],
    config: dict[str, Any],
    log: Callable[[str], None] | None = None,
) -> tuple[int, float] | None:
    """
    Find the delay from the first stable segment of chunks.

    This function identifies consecutive accepted chunks that share the same delay value
    and returns the delay from the first such stable group that meets stability criteria.

    Args:
        results: List of ChunkResult dataclasses (may include rejected chunks)
        config: Configuration dictionary with stability settings
        log: Optional logging callback

    Returns:
        Tuple of (rounded_delay_ms, raw_delay_ms) or None if no stable segment found
    """
    min_chunks = int(config.get("first_stable_min_chunks", 3))
    skip_unstable = config.get("first_stable_skip_unstable", True)

    accepted = [r for r in results if r.accepted]
    if len(accepted) < min_chunks:
        return None

    # Group consecutive chunks with the same delay (within 1ms tolerance)
    # Track both rounded and raw delays for each segment
    segments: list[dict[str, Any]] = []
    current_segment = {
        "delay": accepted[0].delay_ms,
        "raw_delays": [accepted[0].raw_delay_ms],
        "count": 1,
        "start_time": accepted[0].start_time,
    }

    for i in range(1, len(accepted)):
        if abs(accepted[i].delay_ms - current_segment["delay"]) <= 1:
            # Same segment continues - accumulate raw delays for averaging
            current_segment["count"] += 1
            current_segment["raw_delays"].append(accepted[i].raw_delay_ms)
        else:
            # New segment starts
            segments.append(current_segment)
            current_segment = {
                "delay": accepted[i].delay_ms,
                "raw_delays": [accepted[i].raw_delay_ms],
                "count": 1,
                "start_time": accepted[i].start_time,
            }

    # Don't forget the last segment
    segments.append(current_segment)

    # Helper to get raw value from segment (average of all raw delays in segment)
    def get_segment_raw(segment: dict[str, Any]) -> float:
        return sum(segment["raw_delays"]) / len(segment["raw_delays"])

    # Find the first stable segment based on configuration
    if skip_unstable:
        # Skip segments that don't meet minimum chunk count
        for segment in segments:
            if segment["count"] >= min_chunks:
                raw_avg = get_segment_raw(segment)
                # CRITICAL: Round the raw average, don't use first chunk's delay!
                # segment['delay'] is just the first chunk's rounded value, which may differ
                # from the properly rounded average
                rounded_avg = round(raw_avg)

                if log:
                    log(
                        f"[First Stable] Found stable segment: {segment['count']} chunks "
                        f"at {rounded_avg:+d}ms (raw avg: {raw_avg:.3f}ms, "
                        f"starting at {segment['start_time']:.1f}s)"
                    )
                return rounded_avg, raw_avg

        # No segment met the minimum chunk count
        if log:
            max_count = max((s["count"] for s in segments), default=0)
            log(
                f"[First Stable] No segment found with minimum {min_chunks} chunks. "
                f"Largest segment: {max_count} chunks"
            )
        return None
    else:
        # Use the first segment regardless of chunk count
        if segments:
            first_segment = segments[0]
            raw_avg = get_segment_raw(first_segment)
            # CRITICAL: Round the raw average, don't use first chunk's delay!
            rounded_avg = round(raw_avg)

            if first_segment["count"] < min_chunks and log:
                log(
                    f"[First Stable] Warning: First segment has only {first_segment['count']} "
                    f"chunks (minimum: {min_chunks}), but using it anyway (skip_unstable=False)"
                )

            if log:
                log(
                    f"[First Stable] Using first segment: {first_segment['count']} chunks "
                    f"at {rounded_avg:+d}ms (raw avg: {raw_avg:.3f}ms, "
                    f"starting at {first_segment['start_time']:.1f}s)"
                )
            return rounded_avg, raw_avg

    return None
