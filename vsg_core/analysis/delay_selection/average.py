# vsg_core/analysis/delay_selection/average.py
"""
Average delay selection.

Averages all raw delay values and rounds once at the end.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vsg_core.models import ChunkResult


class AverageSelector:
    """Select delay by averaging all raw values."""

    name = "Average"
    key = "average"

    def select(
        self,
        accepted_results: list[ChunkResult],
        config: dict[str, Any],
        log: Callable[[str], None] | None = None,
    ) -> tuple[int, float]:
        """
        Average all raw delay values, round once at the end.

        Returns:
            Tuple of (rounded_delay_ms, raw_delay_ms)
        """
        raw_delays = [r.raw_delay_ms for r in accepted_results]

        raw_avg = sum(raw_delays) / len(raw_delays)
        rounded = round(raw_avg)

        if log:
            log(
                f"[Delay Selection] Average of {len(raw_delays)} raw values: "
                f"{raw_avg:.3f}ms → rounded to {rounded}ms"
            )

        return rounded, raw_avg
