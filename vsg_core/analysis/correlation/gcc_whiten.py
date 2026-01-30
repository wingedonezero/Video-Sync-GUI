# vsg_core/analysis/correlation/gcc_whiten.py
"""
Whitened Cross-Correlation algorithm.

Whitening equalizes the magnitude spectrum of both signals before correlation,
making it robust to spectral differences caused by processing (like source
separation), different recording conditions, or frequency-dependent effects.

This is particularly useful when comparing audio that has been processed
differently (e.g., separated instrumental vs. original mix) as it focuses
on timing/phase alignment rather than spectral content matching.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ._base import normalize_peak_confidence


class GccWhitenAlgorithm:
    """Whitened Cross-Correlation algorithm."""

    name = "Whitened Cross-Correlation"
    key = "gcc_whiten"

    def find_delay(
        self,
        ref_audio: NDArray[np.float32],
        target_audio: NDArray[np.float32],
        sample_rate: int,
        **kwargs,
    ) -> tuple[float, float]:
        """
        Calculate delay using GCC with Spectral Whitening.

        The whitening process:
        1. Transform both signals to frequency domain
        2. Normalize the magnitude spectrum (keeping phase intact)
        3. Compute cross-correlation in whitened space
        4. Find peak delay from the correlation result

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

        # Whiten both signals: normalize magnitude while preserving phase
        # This makes the method robust to spectral differences
        R_whitened = R / (np.abs(R) + 1e-9)
        T_whitened = T / (np.abs(T) + 1e-9)

        # Cross-correlation in whitened space
        G_whitened = R_whitened * np.conj(T_whitened)
        r_whitened = np.fft.ifft(G_whitened)

        k = np.argmax(np.abs(r_whitened))
        lag_samples = k - n if k > n / 2 else k
        delay_ms = (lag_samples / float(sample_rate)) * 1000.0

        # Match confidence based on peak sharpness
        # Whitening tends to produce sharper peaks for aligned signals
        match_confidence = normalize_peak_confidence(r_whitened, k)

        return delay_ms, match_confidence
