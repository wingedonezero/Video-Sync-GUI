# vsg_core/analysis/delay_selection/__init__.py
"""
Delay selection module with pluggable strategies.

This module provides various strategies for selecting the final delay
from a set of correlation chunk results. Each strategy is implemented
as a separate class following the DelaySelector protocol.

Usage:
    from vsg_core.analysis.delay_selection import select_delay

    # Select delay using configured mode
    rounded, raw = select_delay(
        results=chunk_results,
        mode="Mode (Most Common)",
        config=config,
        log=runner._log_message,
    )
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ._base import DelaySelector
from .average import AverageSelector
from .first_stable import FirstStableSelector, find_first_stable_segment_delay
from .mode_clustered import ModeClusteredSelector
from .mode_early_cluster import ModeEarlyClusterSelector
from .mode_simple import ModeSimpleSelector

# Registry of available selectors
SELECTORS: dict[str, type[DelaySelector]] = {
    "Mode (Most Common)": ModeSimpleSelector,
    "Average": AverageSelector,
    "Mode (Clustered)": ModeClusteredSelector,
    "Mode (Early Cluster)": ModeEarlyClusterSelector,
    "First Stable": FirstStableSelector,
}

# Alternate key mappings for flexibility
_SELECTOR_ALIASES: dict[str, str] = {
    "mode": "Mode (Most Common)",
    "mode_simple": "Mode (Most Common)",
    "average": "Average",
    "mode_clustered": "Mode (Clustered)",
    "mode_early_cluster": "Mode (Early Cluster)",
    "first_stable": "First Stable",
}


def get_selector(mode: str) -> DelaySelector:
    """
    Get a selector instance by mode name.

    Args:
        mode: Mode name (e.g., "Mode (Most Common)") or alias (e.g., "mode_simple")

    Returns:
        Instantiated selector

    Raises:
        ValueError: If mode is not recognized
    """
    # Check aliases first
    if mode in _SELECTOR_ALIASES:
        mode = _SELECTOR_ALIASES[mode]

    if mode not in SELECTORS:
        available = list(SELECTORS.keys())
        raise ValueError(
            f"Unknown delay selection mode: {mode}. Available: {available}"
        )

    return SELECTORS[mode]()


def select_delay(
    results: list[dict[str, Any]],
    mode: str,
    config: dict[str, Any],
    log: Callable[[str], None] | None = None,
    min_accepted_chunks: int | None = None,
) -> tuple[int, float] | tuple[None, None]:
    """
    Select final delay from correlation results using the specified mode.

    This is the main entry point for delay selection. It filters accepted
    chunks and delegates to the appropriate selector.

    Args:
        results: List of all chunk results (accepted and rejected)
        mode: Selection mode name (e.g., "Mode (Most Common)")
        config: Configuration dictionary with mode-specific settings
        log: Optional logging callback
        min_accepted_chunks: Minimum accepted chunks required (default from config)

    Returns:
        Tuple of (rounded_delay_ms, raw_delay_ms) or (None, None) if insufficient chunks
    """
    if min_accepted_chunks is None:
        min_accepted_chunks = int(config.get("min_accepted_chunks", 3))

    accepted = [r for r in results if r.get("accepted", False)]

    if len(accepted) < min_accepted_chunks:
        if log:
            log(
                f"[ERROR] Analysis failed: Only {len(accepted)} chunks were accepted "
                f"(minimum: {min_accepted_chunks})."
            )
        return None, None

    selector = get_selector(mode)
    return selector.select(accepted, config, log)


def select_delay_with_tag(
    results: list[dict[str, Any]],
    mode: str,
    config: dict[str, Any],
    log: Callable[[str], None] | None = None,
    role_tag: str = "",
) -> tuple[int | None, float | None, str]:
    """
    Select final delay and return the method label used.

    Similar to select_delay but also returns the method label for logging.

    Args:
        results: List of all chunk results
        mode: Selection mode name
        config: Configuration dictionary
        log: Optional logging callback
        role_tag: Source identifier for logging

    Returns:
        Tuple of (rounded_delay_ms, raw_delay_ms, method_label)
    """
    rounded, raw = select_delay(results, mode, config, log)

    if rounded is None:
        return None, None, "failed"

    # Determine method label based on selector
    selector = get_selector(mode)
    method_label = (
        selector.name.lower().replace(" ", "_").replace("(", "").replace(")", "")
    )

    if log and role_tag:
        log(
            f"{role_tag.capitalize()} delay determined: {rounded:+d} ms ({method_label})."
        )

    return rounded, raw, method_label


__all__ = [
    # Main API
    "select_delay",
    "select_delay_with_tag",
    "get_selector",
    "find_first_stable_segment_delay",
    # Registry
    "SELECTORS",
    # Protocol
    "DelaySelector",
    # Selector classes (for direct use if needed)
    "ModeSimpleSelector",
    "AverageSelector",
    "ModeClusteredSelector",
    "ModeEarlyClusterSelector",
    "FirstStableSelector",
]
