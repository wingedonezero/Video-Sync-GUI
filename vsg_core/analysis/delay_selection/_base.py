# vsg_core/analysis/delay_selection/_base.py
"""
Base protocol for delay selection strategies.

All delay selectors must implement the DelaySelector protocol to ensure
consistent interface across different selection methods.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class DelaySelector(Protocol):
    """Protocol that all delay selection strategies must implement."""

    name: str  # Human-readable name (e.g., "Mode (Most Common)")
    key: str  # Config key (e.g., "mode_simple")

    def select(
        self,
        accepted_results: list[dict[str, Any]],
        config: dict[str, Any],
        log: Callable[[str], None] | None = None,
    ) -> tuple[int, float]:
        """
        Select final delay from correlation results.

        Args:
            accepted_results: List of accepted chunk results with 'delay' and 'raw_delay' keys
            config: Configuration dictionary with selector-specific settings
            log: Optional logging callback

        Returns:
            Tuple of (rounded_delay_ms, raw_delay_ms)
        """
        ...
