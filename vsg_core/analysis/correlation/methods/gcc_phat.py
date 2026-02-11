# vsg_core/analysis/correlation/methods/gcc_phat.py
"""Generalized Cross-Correlation with Phase Transform (GCC-PHAT)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..confidence import normalize_peak_confidence


@dataclass(frozen=True, slots=True)
class GccPhat:
    """GCC-PHAT uses only phase information for delay estimation."""

    name: str = "Phase Correlation (GCC-PHAT)"
    config_key: str = "multi_corr_gcc_phat"

    def find_delay(
        self,
        ref_chunk: np.ndarray,
        tgt_chunk: np.ndarray,
        sr: int,
    ) -> tuple[float, float]:
        n = len(ref_chunk) + len(tgt_chunk) - 1
        R = np.fft.fft(ref_chunk, n)
        T = np.fft.fft(tgt_chunk, n)
        G = R * np.conj(T)
        G_phat = G / (np.abs(G) + 1e-9)
        r_phat = np.fft.ifft(G_phat)
        k = np.argmax(np.abs(r_phat))
        lag_samples = k - n if k > n / 2 else k
        delay_ms = float(lag_samples / float(sr) * 1000.0)
        match_confidence = normalize_peak_confidence(r_phat, k)
        return delay_ms, match_confidence
