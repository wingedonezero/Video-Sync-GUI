# vsg_core/analysis/correlation/methods/gcc_whiten.py
"""GCC with Spectral Whitening (Whitened Cross-Correlation)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..confidence import normalize_peak_confidence


@dataclass(frozen=True, slots=True)
class GccWhiten:
    """
    Whitening equalizes magnitude spectra before correlation.

    Robust to spectral differences caused by source separation,
    different recording conditions, or frequency-dependent effects.
    Focuses on timing/phase alignment rather than spectral content.
    """

    name: str = "Whitened Cross-Correlation"
    config_key: str = "multi_corr_gcc_whiten"

    def find_delay(
        self,
        ref_chunk: np.ndarray,
        tgt_chunk: np.ndarray,
        sr: int,
    ) -> tuple[float, float]:
        n = len(ref_chunk) + len(tgt_chunk) - 1
        R = np.fft.fft(ref_chunk, n)
        T = np.fft.fft(tgt_chunk, n)

        # Whiten: normalize magnitude while preserving phase
        R_whitened = R / (np.abs(R) + 1e-9)
        T_whitened = T / (np.abs(T) + 1e-9)

        # Cross-correlation in whitened space
        G_whitened = R_whitened * np.conj(T_whitened)
        r_whitened = np.fft.ifft(G_whitened)

        k = np.argmax(np.abs(r_whitened))
        lag_samples = k - n if k > n / 2 else k
        delay_ms = float(lag_samples / float(sr) * 1000.0)

        match_confidence = normalize_peak_confidence(r_whitened, k)
        return delay_ms, match_confidence
