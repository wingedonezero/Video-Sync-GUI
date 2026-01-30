# vsg_core/analysis/delay_selection/mode_simple.py
"""
Simple mode (most common) delay selection.

Returns the most frequently occurring rounded delay value,
with the raw delay averaged from all chunks with that value.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any


class ModeSimpleSelector:
    """Select delay using simple mode (most common rounded value)."""

    name = "Mode (Most Common)"
    key = "mode_simple"

    def select(
        self,
        accepted_results: list[dict[str, Any]],
        config: dict[str, Any],
        log: Callable[[str], None] | None = None,
    ) -> tuple[int, float]:
        """
        Select the most common rounded delay value.

        Returns:
            Tuple of (rounded_delay_ms, raw_delay_ms averaged from matching chunks)
        """
        delays = [r["delay"] for r in accepted_results]
        counts = Counter(delays)
        winner_rounded = counts.most_common(1)[0][0]

        # Average raw values from all chunks matching the most common rounded delay
        matching_raw_values = [
            r.get("raw_delay", float(winner_rounded))
            for r in accepted_results
            if r.get("delay") == winner_rounded
        ]

        if matching_raw_values:
            winner_raw = sum(matching_raw_values) / len(matching_raw_values)
        else:
            winner_raw = float(winner_rounded)

        if log:
            log(f"[Delay Selection] Mode: most common = {winner_rounded}ms")

        return winner_rounded, winner_raw
