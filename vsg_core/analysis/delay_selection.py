# vsg_core/analysis/delay_selection.py
"""
Delay selection logic for audio correlation analysis.

Pure functions that calculate final delay from correlation chunk results.
All business logic for delay selection modes (Mode, Average, First Stable, etc.).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from .types import DelayCalculation

if TYPE_CHECKING:
    from collections.abc import Callable

    from vsg_core.models.settings import AppSettings


def find_first_stable_segment_delay(
    results: list[dict[str, Any]],
    settings: AppSettings,
    return_raw: bool,
    log: Callable[[str], None],
    *,
    override_min_chunks: int | None = None,
    override_skip_unstable: bool | None = None,
) -> int | float | None:
    """
    Find the delay from the first stable segment of chunks.

    This function identifies consecutive accepted chunks that share the same delay value
    and returns the delay from the first such stable group that meets stability criteria.

    Args:
        results: List of correlation results with 'delay', 'raw_delay', 'accepted', and 'start' keys
        settings: AppSettings instance
        return_raw: If True, return the raw (unrounded) delay value
        log: Logging function for messages
        override_min_chunks: Override first_stable_min_chunks (for stepping mode)
        override_skip_unstable: Override first_stable_skip_unstable (for stepping mode)

    Returns:
        The delay value from the first stable segment, or None if no stable segment found
    """
    min_chunks = (
        override_min_chunks
        if override_min_chunks is not None
        else settings.first_stable_min_chunks
    )
    skip_unstable = (
        override_skip_unstable
        if override_skip_unstable is not None
        else settings.first_stable_skip_unstable
    )

    accepted = [r for r in results if r.get("accepted", False)]
    if len(accepted) < min_chunks:
        return None

    # Group consecutive chunks with the same delay (within 1ms tolerance)
    # Track both rounded and raw delays for each segment
    segments = []
    current_segment = {
        "delay": accepted[0]["delay"],
        "raw_delays": [accepted[0].get("raw_delay", float(accepted[0]["delay"]))],
        "count": 1,
        "start_time": accepted[0]["start"],
    }

    for i in range(1, len(accepted)):
        if abs(accepted[i]["delay"] - current_segment["delay"]) <= 1:
            # Same segment continues - accumulate raw delays for averaging
            current_segment["count"] += 1
            current_segment["raw_delays"].append(
                accepted[i].get("raw_delay", float(accepted[i]["delay"]))
            )
        else:
            # New segment starts
            segments.append(current_segment)
            current_segment = {
                "delay": accepted[i]["delay"],
                "raw_delays": [
                    accepted[i].get("raw_delay", float(accepted[i]["delay"]))
                ],
                "count": 1,
                "start_time": accepted[i]["start"],
            }

    # Don't forget the last segment
    segments.append(current_segment)

    # Helper to get raw value from segment (average of all raw delays in segment)
    def get_segment_raw(segment):
        return sum(segment["raw_delays"]) / len(segment["raw_delays"])

    # Find the first stable segment based on configuration
    if skip_unstable:
        # Skip segments that don't meet minimum chunk count
        for segment in segments:
            if segment["count"] >= min_chunks:
                raw_avg = get_segment_raw(segment)
                # CRITICAL: Round the raw average, don't use first chunk's delay!
                # segment['delay'] is just the first chunk's rounded value, which may differ
                # from the properly rounded average (e.g., raw avg -1001.825 should be -1002,
                # but first chunk might have been -1001)
                rounded_avg = round(raw_avg)
                log(
                    f"[First Stable] Found stable segment: {segment['count']} chunks at {rounded_avg:+d}ms "
                    f"(raw avg: {raw_avg:.3f}ms, starting at {segment['start_time']:.1f}s)"
                )
                return raw_avg if return_raw else rounded_avg

        # No segment met the minimum chunk count
        log(
            f"[First Stable] No segment found with minimum {min_chunks} chunks. "
            f"Largest segment: {max((s['count'] for s in segments), default=0)} chunks"
        )
        return None
    # Use the first segment regardless of chunk count
    elif segments:
        first_segment = segments[0]
        raw_avg = get_segment_raw(first_segment)
        # CRITICAL: Round the raw average, don't use first chunk's delay!
        rounded_avg = round(raw_avg)
        if first_segment["count"] < min_chunks:
            log(
                f"[First Stable] Warning: First segment has only {first_segment['count']} chunks "
                f"(minimum: {min_chunks}), but using it anyway (skip_unstable=False)"
            )
        log(
            f"[First Stable] Using first segment: {first_segment['count']} chunks at {rounded_avg:+d}ms "
            f"(raw avg: {raw_avg:.3f}ms, starting at {first_segment['start_time']:.1f}s)"
        )
        return raw_avg if return_raw else rounded_avg

    return None


def calculate_delay(
    results: list[dict[str, Any]],
    settings: AppSettings,
    delay_mode: str,
    log: Callable[[str], None],
    role_tag: str,
) -> DelayCalculation | None:
    """
    Select final delay from correlation results using configured mode.

    Args:
        results: List of correlation chunk results
        settings: AppSettings instance
        delay_mode: Delay selection mode to use
        log: Logging function for messages
        role_tag: Source identifier for logging (e.g., "Source 2")

    Returns:
        DelayCalculation with both rounded and raw delays, or None if insufficient data
    """
    min_accepted_chunks = settings.min_accepted_chunks

    accepted = [r for r in results if r.get("accepted", False)]
    if len(accepted) < min_accepted_chunks:
        log(f"[ERROR] Analysis failed: Only {len(accepted)} chunks were accepted.")
        return None

    delays = [r["delay"] for r in accepted]
    raw_delays = [r.get("raw_delay", float(r["delay"])) for r in accepted]

    if delay_mode == "First Stable":
        # Use proper stability detection to find first stable segment
        winner = find_first_stable_segment_delay(
            results, settings, return_raw=False, log=log
        )
        winner_raw = find_first_stable_segment_delay(
            results, settings, return_raw=True, log=log
        )
        if winner is None:
            # Fallback to mode if no stable segment found
            log("[WARNING] No stable segment found, falling back to mode.")
            counts = Counter(delays)
            winner = counts.most_common(1)[0][0]
            winner_raw = float(winner)
            method_label = "mode (fallback)"
        else:
            method_label = "first stable"

    elif delay_mode == "Average":
        # Average the RAW float values, then round once at the end
        raw_avg = sum(raw_delays) / len(raw_delays)
        winner = round(raw_avg)
        winner_raw = raw_avg
        log(
            f"[Delay Selection] Average of {len(raw_delays)} raw values: {raw_avg:.3f}ms → rounded to {winner}ms"
        )
        method_label = "average"

    elif delay_mode == "Mode (Clustered)":
        # Find most common rounded delay, then include chunks within ±1ms tolerance
        counts = Counter(delays)
        mode_winner = counts.most_common(1)[0][0]

        # Collect raw values from chunks within ±1ms of the mode
        cluster_raw_values = []
        cluster_delays = []
        for r in accepted:
            if abs(r["delay"] - mode_winner) <= 1:
                cluster_raw_values.append(r.get("raw_delay", float(r["delay"])))
                cluster_delays.append(r["delay"])

        # Average the clustered raw values
        if cluster_raw_values:
            raw_avg = sum(cluster_raw_values) / len(cluster_raw_values)
            winner = round(raw_avg)
            winner_raw = raw_avg
            cluster_counts = Counter(cluster_delays)
            log(
                f"[Delay Selection] Mode (Clustered): most common = {mode_winner}ms, "
                f"cluster [{mode_winner - 1} to {mode_winner + 1}] contains {len(cluster_raw_values)}/{len(accepted)} chunks "
                f"(breakdown: {dict(cluster_counts)}), raw avg: {raw_avg:.3f}ms → rounded to {winner}ms"
            )
            method_label = "mode (clustered)"
        else:
            # Fallback to simple mode if clustering fails
            winner = mode_winner
            winner_raw = float(mode_winner)
            log(
                f"[Delay Selection] Mode (Clustered): fallback to simple mode = {winner}ms"
            )
            method_label = "mode (clustered fallback)"

    elif delay_mode == "Mode (Early Cluster)":
        # Find clusters using ±1ms tolerance, prioritizing early stability
        early_window = settings.early_cluster_window
        early_threshold = settings.early_cluster_threshold

        # Build clusters: group delays within ±1ms of each other
        counts = Counter(delays)
        cluster_info = {}  # key: representative delay, value: {raw_values, early_count, first_chunk_idx}

        for delay_val in counts:
            # Collect all chunks within ±1ms of this delay value
            cluster_raw_values = []
            early_count = 0
            first_chunk_idx = None

            for idx, r in enumerate(accepted):
                if abs(r["delay"] - delay_val) <= 1:
                    cluster_raw_values.append(r.get("raw_delay", float(r["delay"])))
                    if idx < early_window:
                        early_count += 1
                    if first_chunk_idx is None:
                        first_chunk_idx = idx

            cluster_info[delay_val] = {
                "raw_values": cluster_raw_values,
                "early_count": early_count,
                "first_chunk_idx": first_chunk_idx,
                "total_count": len(cluster_raw_values),
            }

        # Find early stable clusters (meet threshold in early window)
        early_stable_clusters = [
            (delay_val, info)
            for delay_val, info in cluster_info.items()
            if info["early_count"] >= early_threshold
        ]

        if early_stable_clusters:
            # Pick the cluster that appears earliest
            early_stable_clusters.sort(key=lambda x: x[1]["first_chunk_idx"])
            _winner_delay, winner_info = early_stable_clusters[0]

            # Average the raw values in this cluster
            raw_avg = sum(winner_info["raw_values"]) / len(winner_info["raw_values"])
            winner = round(raw_avg)
            winner_raw = raw_avg

            log(
                f"[Delay Selection] Mode (Early Cluster): found {len(early_stable_clusters)} early stable cluster(s), "
                f"selected cluster at {winner}ms with {winner_info['early_count']}/{early_window} early chunks, "
                f"total {winner_info['total_count']} chunks, first appears at chunk {winner_info['first_chunk_idx'] + 1}, "
                f"raw avg: {raw_avg:.3f}ms → rounded to {winner}ms"
            )
            method_label = "mode (early cluster)"
        else:
            # No cluster meets early threshold - fall back to Mode (Clustered)
            mode_winner = counts.most_common(1)[0][0]
            cluster_raw_values = [
                r.get("raw_delay", float(r["delay"]))
                for r in accepted
                if abs(r["delay"] - mode_winner) <= 1
            ]

            if cluster_raw_values:
                raw_avg = sum(cluster_raw_values) / len(cluster_raw_values)
                winner = round(raw_avg)
                winner_raw = raw_avg
                log(
                    f"[Delay Selection] Mode (Early Cluster): no cluster met early threshold ({early_threshold} in first {early_window}), "
                    f"falling back to Mode (Clustered): {winner}ms (raw avg: {raw_avg:.3f}ms)"
                )
                method_label = "mode (early cluster - clustered fallback)"
            else:
                winner = mode_winner
                winner_raw = float(mode_winner)
                log(
                    f"[Delay Selection] Mode (Early Cluster): fallback to simple mode = {winner}ms"
                )
                method_label = "mode (early cluster - simple fallback)"

    else:  # Mode (Most Common) - default
        counts = Counter(delays)
        winner = counts.most_common(1)[0][0]
        # Average raw values from all chunks matching the most common rounded delay
        matching_raw_values = [
            r.get("raw_delay", float(winner))
            for r in accepted
            if r.get("delay") == winner
        ]
        if matching_raw_values:
            winner_raw = sum(matching_raw_values) / len(matching_raw_values)
        else:
            winner_raw = float(winner)
        method_label = "mode"

    log(f"{role_tag.capitalize()} delay determined: {winner:+d} ms ({method_label}).")

    return DelayCalculation(
        rounded_ms=winner,
        raw_ms=winner_raw,
        selection_method=method_label,
        accepted_chunks=len(accepted),
        total_chunks=len(results),
    )
