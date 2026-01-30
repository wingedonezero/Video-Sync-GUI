# vsg_core/analysis/correlation/__init__.py
"""
Correlation algorithm module with pluggable strategies.

This module provides various algorithms for audio cross-correlation
delay detection. Each algorithm is implemented as a separate class
following the CorrelationAlgorithm protocol.

Usage:
    from vsg_core.analysis.correlation import get_algorithm, run_correlation

    # Get a specific algorithm
    algorithm = get_algorithm("gcc_phat")
    delay_ms, confidence = algorithm.find_delay(ref_audio, tgt_audio, sample_rate)

    # Or run full correlation with preprocessing
    results = run_correlation(
        ref_file="source1.mkv",
        target_file="source2.mkv",
        config=config,
        runner=runner,
        tool_paths=tool_paths,
    )
"""

from __future__ import annotations

from ._base import CorrelationAlgorithm, normalize_peak_confidence
from ._runner import run_correlation, run_multi_correlation
from .dtw import DtwAlgorithm
from .gcc_phat import GccPhatAlgorithm
from .gcc_scot import GccScotAlgorithm
from .gcc_whiten import GccWhitenAlgorithm
from .onset import OnsetAlgorithm
from .scc import SccAlgorithm
from .spectrogram import SpectrogramAlgorithm

# Registry of available algorithms
ALGORITHMS: dict[str, type[CorrelationAlgorithm]] = {
    "Phase Correlation (GCC-PHAT)": GccPhatAlgorithm,
    "Standard Correlation (SCC)": SccAlgorithm,
    "Onset Detection": OnsetAlgorithm,
    "GCC-SCOT": GccScotAlgorithm,
    "Whitened Cross-Correlation": GccWhitenAlgorithm,
    "DTW (Dynamic Time Warping)": DtwAlgorithm,
    "Spectrogram Correlation": SpectrogramAlgorithm,
}

# Alternate key mappings for flexibility
_ALGORITHM_ALIASES: dict[str, str] = {
    "gcc_phat": "Phase Correlation (GCC-PHAT)",
    "scc": "Standard Correlation (SCC)",
    "onset": "Onset Detection",
    "gcc_scot": "GCC-SCOT",
    "gcc_whiten": "Whitened Cross-Correlation",
    "dtw": "DTW (Dynamic Time Warping)",
    "spectrogram": "Spectrogram Correlation",
}

# Multi-correlation method config keys
MULTI_CORR_METHODS = [
    ("Standard Correlation (SCC)", "multi_corr_scc"),
    ("Phase Correlation (GCC-PHAT)", "multi_corr_gcc_phat"),
    ("Onset Detection", "multi_corr_onset"),
    ("GCC-SCOT", "multi_corr_gcc_scot"),
    ("Whitened Cross-Correlation", "multi_corr_gcc_whiten"),
    ("DTW (Dynamic Time Warping)", "multi_corr_dtw"),
    ("Spectrogram Correlation", "multi_corr_spectrogram"),
]


def get_algorithm(name: str) -> CorrelationAlgorithm:
    """
    Get an algorithm instance by name or key.

    Args:
        name: Algorithm name (e.g., "Phase Correlation (GCC-PHAT)") or key (e.g., "gcc_phat")

    Returns:
        Instantiated algorithm

    Raises:
        ValueError: If algorithm name is not recognized
    """
    # Check aliases first
    if name in _ALGORITHM_ALIASES:
        name = _ALGORITHM_ALIASES[name]

    if name not in ALGORITHMS:
        available = list(ALGORITHMS.keys())
        raise ValueError(
            f"Unknown correlation algorithm: {name}. Available: {available}"
        )

    return ALGORITHMS[name]()


def get_algorithm_for_method(method_name: str) -> CorrelationAlgorithm:
    """
    Get algorithm instance for a correlation method name.

    Handles matching by substring for flexibility.

    Args:
        method_name: Method name from config (may be partial match)

    Returns:
        Algorithm instance
    """
    # Try exact match first
    if method_name in ALGORITHMS:
        return ALGORITHMS[method_name]()

    # Try alias match
    if method_name in _ALGORITHM_ALIASES:
        return ALGORITHMS[_ALGORITHM_ALIASES[method_name]]()

    # Try substring match
    method_lower = method_name.lower()
    if "gcc-phat" in method_lower or "phase" in method_lower:
        return GccPhatAlgorithm()
    elif "onset" in method_lower:
        return OnsetAlgorithm()
    elif "gcc-scot" in method_lower or "scot" in method_lower:
        return GccScotAlgorithm()
    elif "whiten" in method_lower:
        return GccWhitenAlgorithm()
    elif "dtw" in method_lower:
        return DtwAlgorithm()
    elif "spectrogram" in method_lower:
        return SpectrogramAlgorithm()
    else:
        # Default to SCC
        return SccAlgorithm()


__all__ = [
    # Main API
    "run_correlation",
    "run_multi_correlation",
    "get_algorithm",
    "get_algorithm_for_method",
    # Registry
    "ALGORITHMS",
    "MULTI_CORR_METHODS",
    # Protocol
    "CorrelationAlgorithm",
    # Utility
    "normalize_peak_confidence",
    # Algorithm classes (for direct use if needed)
    "GccPhatAlgorithm",
    "SccAlgorithm",
    "OnsetAlgorithm",
    "GccScotAlgorithm",
    "GccWhitenAlgorithm",
    "DtwAlgorithm",
    "SpectrogramAlgorithm",
]
