# vsg_core/analysis/correlation/scc.py
"""
SCC (Standard Cross-Correlation) algorithm.

Classic normalized cross-correlation with optional peak fitting
for sub-sample accuracy.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.signal import correlate


class SccAlgorithm:
    """Standard Cross-Correlation algorithm."""

    name = "Standard Correlation (SCC)"
    key = "scc"

    def find_delay(
        self,
        ref_audio: NDArray[np.float32],
        target_audio: NDArray[np.float32],
        sample_rate: int,
        peak_fit: bool = False,
        **kwargs,
    ) -> tuple[float, float]:
        """
        Calculate delay using standard cross-correlation.

        Args:
            ref_audio: Reference audio chunk
            target_audio: Target audio chunk
            sample_rate: Sample rate in Hz
            peak_fit: Whether to use parabolic peak fitting for sub-sample accuracy

        Returns:
            Tuple of (delay_ms, confidence)
        """
        # Normalize the signals
        r = (ref_audio - np.mean(ref_audio)) / (np.std(ref_audio) + 1e-9)
        t = (target_audio - np.mean(target_audio)) / (np.std(target_audio) + 1e-9)

        c = correlate(r, t, mode="full", method="fft")
        k = np.argmax(np.abs(c))
        lag_samples = float(k - (len(t) - 1))

        # Optional parabolic peak fitting for sub-sample accuracy
        if peak_fit and 0 < k < len(c) - 1:
            y1, y2, y3 = np.abs(c[k - 1 : k + 2])
            delta = 0.5 * (y1 - y3) / (y1 - 2 * y2 + y3)
            if -1 < delta < 1:
                lag_samples += delta

        raw_delay_s = lag_samples / float(sample_rate)
        match_pct = (
            np.abs(c[k]) / (np.sqrt(np.sum(r**2) * np.sum(t**2)) + 1e-9)
        ) * 100.0

        return raw_delay_s * 1000.0, match_pct
