# vsg_core/analysis/delay_selection/mode_early_cluster.py
"""
Early cluster mode delay selection.

Finds clusters using ±1ms tolerance, prioritizing clusters that appear
early and consistently in the file. Falls back to Mode (Clustered) if
no cluster meets the early stability threshold.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any


class ModeEarlyClusterSelector:
    """Select delay prioritizing early-appearing stable clusters."""

    name = "Mode (Early Cluster)"
    key = "mode_early_cluster"

    def select(
        self,
        accepted_results: list[dict[str, Any]],
        config: dict[str, Any],
        log: Callable[[str], None] | None = None,
    ) -> tuple[int, float]:
        """
        Find clusters, prioritize early stability.

        Config options:
            early_cluster_window: Number of early chunks to consider (default: 10)
            early_cluster_threshold: Minimum chunks in early window (default: 5)

        Returns:
            Tuple of (rounded_delay_ms, raw_delay_ms)
        """
        early_window = int(config.get("early_cluster_window", 10))
        early_threshold = int(config.get("early_cluster_threshold", 5))

        delays = [r["delay"] for r in accepted_results]
        counts = Counter(delays)

        # Build clusters: group delays within ±1ms of each other
        # key: representative delay, value: {raw_values, early_count, first_chunk_idx}
        cluster_info: dict[int, dict[str, Any]] = {}

        for delay_val in counts.keys():
            # Collect all chunks within ±1ms of this delay value
            cluster_raw_values = []
            early_count = 0
            first_chunk_idx = None

            for idx, r in enumerate(accepted_results):
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

            if log:
                log(
                    f"[Delay Selection] Mode (Early Cluster): found {len(early_stable_clusters)} "
                    f"early stable cluster(s), selected cluster at {winner}ms with "
                    f"{winner_info['early_count']}/{early_window} early chunks, "
                    f"total {winner_info['total_count']} chunks, first appears at "
                    f"chunk {winner_info['first_chunk_idx']+1}, raw avg: {raw_avg:.3f}ms → "
                    f"rounded to {winner}ms"
                )
            return winner, raw_avg

        # No cluster meets early threshold - fall back to Mode (Clustered)
        mode_winner = counts.most_common(1)[0][0]
        cluster_raw_values = [
            r.get("raw_delay", float(r["delay"]))
            for r in accepted_results
            if abs(r["delay"] - mode_winner) <= 1
        ]

        if cluster_raw_values:
            raw_avg = sum(cluster_raw_values) / len(cluster_raw_values)
            winner = round(raw_avg)

            if log:
                log(
                    f"[Delay Selection] Mode (Early Cluster): no cluster met early threshold "
                    f"({early_threshold} in first {early_window}), falling back to "
                    f"Mode (Clustered): {winner}ms (raw avg: {raw_avg:.3f}ms)"
                )
            return winner, raw_avg
        else:
            if log:
                log(
                    f"[Delay Selection] Mode (Early Cluster): fallback to simple mode = {mode_winner}ms"
                )
            return mode_winner, float(mode_winner)
