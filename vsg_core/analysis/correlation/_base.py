# vsg_core/analysis/correlation/_base.py
"""
Base protocol for correlation algorithms.

All correlation algorithms must implement the CorrelationAlgorithm protocol
to ensure consistent interface across different methods.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class CorrelationAlgorithm(Protocol):
    """Protocol that all correlation algorithms must implement."""

    name: str  # Human-readable name (e.g., "Phase Correlation (GCC-PHAT)")
    key: str  # Config key (e.g., "gcc_phat")

    def find_delay(
        self,
        ref_audio: NDArray[np.float32],
        target_audio: NDArray[np.float32],
        sample_rate: int,
        **kwargs,
    ) -> tuple[float, float]:
        """
        Find delay between reference and target audio.

        Args:
            ref_audio: Reference audio as float32 numpy array
            target_audio: Target audio as float32 numpy array
            sample_rate: Sample rate in Hz
            **kwargs: Algorithm-specific parameters

        Returns:
            Tuple of (delay_ms, confidence)
            - delay_ms: Delay in milliseconds (positive = target behind reference)
            - confidence: Match confidence score (0-100)
        """
        ...


def normalize_peak_confidence(correlation_array: np.ndarray, peak_idx: int) -> float:
    """
    Normalize peak confidence by comparing to noise floor and second-best peak.

    This provides robust confidence estimation that's comparable across different
    videos with varying noise floors and signal characteristics.

    Uses three normalization strategies:
    1. peak / median (prominence over noise floor)
    2. peak / second_best (uniqueness of the match)
    3. peak / local_stddev (signal-to-noise ratio)

    Args:
        correlation_array: The correlation result array
        peak_idx: Index of the peak in the array

    Returns:
        Normalized confidence score (0-100)
    """
    abs_corr = np.abs(correlation_array)
    peak_value = abs_corr[peak_idx]

    # Metric 1: Noise floor using median (more robust than mean)
    noise_floor_median = np.median(abs_corr)
    prominence_ratio = peak_value / (noise_floor_median + 1e-9)

    # Metric 2: Find second-best peak (excluding immediate neighbors)
    # Create a mask to exclude the peak and its neighbors to avoid sidelobes
    mask = np.ones(len(abs_corr), dtype=bool)
    neighbor_range = max(1, len(abs_corr) // 100)  # Exclude 1% around peak
    start_mask = max(0, peak_idx - neighbor_range)
    end_mask = min(len(abs_corr), peak_idx + neighbor_range + 1)
    mask[start_mask:end_mask] = False

    second_best = np.max(abs_corr[mask]) if np.any(mask) else noise_floor_median
    uniqueness_ratio = peak_value / (second_best + 1e-9)

    # Metric 3: SNR using robust background estimation
    # Use standard deviation of lower 90% of values
    threshold_90 = np.percentile(abs_corr, 90)
    background = abs_corr[abs_corr < threshold_90]
    bg_stddev = np.std(background) if len(background) > 10 else 1e-9
    snr_ratio = peak_value / (bg_stddev + 1e-9)

    # Combine metrics with empirically tuned weights and scales
    # Prominence: scaled by 5 (typical good match: 10-30 → 50-150)
    # Uniqueness: scaled by 8 (typical good match: 2-5 → 16-40)
    # SNR: scaled by 1.5 (typical good match: 15-50 → 22-75)
    # Combined typical range: 88-265 for good matches
    confidence = (prominence_ratio * 5.0) + (uniqueness_ratio * 8.0) + (snr_ratio * 1.5)

    # Scale to 0-100 range: divide by 3 to bring typical good matches to ~30-90 range
    confidence = confidence / 3.0

    return min(100.0, max(0.0, confidence))
