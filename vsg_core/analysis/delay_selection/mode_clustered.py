# vsg_core/analysis/delay_selection/mode_clustered.py
"""
Clustered mode delay selection.

Finds the most common rounded delay, then includes chunks within ±1ms tolerance
and averages their raw values.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vsg_core.models import ChunkResult


class ModeClusteredSelector:
    """Select delay using clustered mode with ±1ms tolerance."""

    name = "Mode (Clustered)"
    key = "mode_clustered"

    def select(
        self,
        accepted_results: list[ChunkResult],
        config: dict[str, Any],
        log: Callable[[str], None] | None = None,
    ) -> tuple[int, float]:
        """
        Find most common delay, then cluster within ±1ms and average.

        Returns:
            Tuple of (rounded_delay_ms, raw_delay_ms)
        """
        delays = [r.delay_ms for r in accepted_results]

        counts = Counter(delays)
        mode_winner = counts.most_common(1)[0][0]

        # Collect raw values from chunks within ±1ms of the mode
        cluster_raw_values = []
        cluster_delays = []
        for r in accepted_results:
            if abs(r.delay_ms - mode_winner) <= 1:
                cluster_raw_values.append(r.raw_delay_ms)
                cluster_delays.append(r.delay_ms)

        # Average the clustered raw values
        if cluster_raw_values:
            raw_avg = sum(cluster_raw_values) / len(cluster_raw_values)
            winner = round(raw_avg)
            cluster_counts = Counter(cluster_delays)

            if log:
                log(
                    f"[Delay Selection] Mode (Clustered): most common = {mode_winner}ms, "
                    f"cluster [{mode_winner-1} to {mode_winner+1}] contains "
                    f"{len(cluster_raw_values)}/{len(accepted_results)} chunks "
                    f"(breakdown: {dict(cluster_counts)}), raw avg: {raw_avg:.3f}ms → "
                    f"rounded to {winner}ms"
                )
            return winner, raw_avg
        else:
            # Fallback to simple mode if clustering fails
            if log:
                log(
                    f"[Delay Selection] Mode (Clustered): fallback to simple mode = {mode_winner}ms"
                )
            return mode_winner, float(mode_winner)
