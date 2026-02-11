# vsg_core/analysis/correlation/methods/gcc_scot.py
"""GCC-SCOT (Smoothed Coherence Transform)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class GccScot:
    """
    GCC-SCOT weights by signal coherence instead of just phase.

    Better than PHAT when one signal has more noise than the other,
    as it accounts for the reliability of each frequency bin.
    """

    name: str = "GCC-SCOT"
    config_key: str = "multi_corr_gcc_scot"

    def find_delay(
        self,
        ref_chunk: np.ndarray,
        tgt_chunk: np.ndarray,
        sr: int,
    ) -> tuple[float, float]:
        n = len(ref_chunk) + len(tgt_chunk) - 1
        R = np.fft.fft(ref_chunk, n)
        T = np.fft.fft(tgt_chunk, n)

        # Cross-power spectrum
        G = R * np.conj(T)

        # SCOT weighting: normalize by geometric mean of auto-spectra
        R_power = np.abs(R) ** 2
        T_power = np.abs(T) ** 2
        scot_weight = np.sqrt(R_power * T_power) + 1e-9

        G_scot = G / scot_weight
        r_scot = np.fft.ifft(G_scot)

        k = np.argmax(np.abs(r_scot))
        lag_samples = k - n if k > n / 2 else k
        delay_ms = float(lag_samples / float(sr) * 1000.0)

        # Match confidence based on peak prominence
        match_confidence = float(
            np.abs(r_scot[k]) / (np.mean(np.abs(r_scot)) + 1e-9) * 10
        )
        match_confidence = min(100.0, match_confidence)

        return delay_ms, match_confidence
