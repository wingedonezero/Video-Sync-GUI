# vsg_core/analysis/correlation/gcc_scot.py
"""
GCC-SCOT (Smoothed Coherence Transform) algorithm.

Similar to GCC-PHAT but weights by signal coherence instead of just phase.
Better than PHAT when one signal has more noise than the other, as it
accounts for the reliability of each frequency bin.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


class GccScotAlgorithm:
    """GCC-SCOT correlation algorithm."""

    name = "GCC-SCOT"
    key = "gcc_scot"

    def find_delay(
        self,
        ref_audio: NDArray[np.float32],
        target_audio: NDArray[np.float32],
        sample_rate: int,
        **kwargs,
    ) -> tuple[float, float]:
        """
        Calculate delay using GCC-SCOT (Smoothed Coherence Transform).

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

        # Cross-power spectrum
        G = R * np.conj(T)

        # SCOT weighting: normalize by geometric mean of auto-spectra
        # This gives more weight to frequencies where both signals are strong
        R_power = np.abs(R) ** 2
        T_power = np.abs(T) ** 2
        scot_weight = np.sqrt(R_power * T_power) + 1e-9

        G_scot = G / scot_weight
        r_scot = np.fft.ifft(G_scot)

        k = np.argmax(np.abs(r_scot))
        lag_samples = k - n if k > n / 2 else k
        delay_ms = (lag_samples / float(sample_rate)) * 1000.0

        # Match confidence based on peak prominence
        match_confidence = np.abs(r_scot[k]) / (np.mean(np.abs(r_scot)) + 1e-9) * 10
        match_confidence = min(100.0, match_confidence)

        return delay_ms, match_confidence
