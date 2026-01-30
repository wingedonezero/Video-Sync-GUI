# vsg_core/analysis/correlation/gcc_phat.py
"""
GCC-PHAT (Generalized Cross-Correlation with Phase Transform) algorithm.

This algorithm normalizes the cross-power spectrum by its magnitude,
emphasizing phase information for robust delay detection.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ._base import normalize_peak_confidence


class GccPhatAlgorithm:
    """GCC-PHAT correlation algorithm."""

    name = "Phase Correlation (GCC-PHAT)"
    key = "gcc_phat"

    def find_delay(
        self,
        ref_audio: NDArray[np.float32],
        target_audio: NDArray[np.float32],
        sample_rate: int,
        **kwargs,
    ) -> tuple[float, float]:
        """
        Calculate delay using Generalized Cross-Correlation with Phase Transform.

        Args:
            ref_audio: Reference audio chunk
            target_audio: Target audio chunk
            sample_rate: Sample rate in Hz

        Returns:
            Tuple of (delay_ms, confidence)
        """
        n = len(ref_audio) + len(target_audio) - 1
        R = np.fft.fft(ref_audio, n)
        T = np.fft.fft(target_audio, n)
        G = R * np.conj(T)
        G_phat = G / (np.abs(G) + 1e-9)
        r_phat = np.fft.ifft(G_phat)
        k = np.argmax(np.abs(r_phat))
        lag_samples = k - n if k > n / 2 else k
        delay_ms = (lag_samples / float(sample_rate)) * 1000.0
        match_confidence = normalize_peak_confidence(r_phat, k)
        return delay_ms, match_confidence
