# vsg_core/analysis/correlation/methods/gcc_phat.py
"""Generalized Cross-Correlation with Phase Transform (GCC-PHAT) — GPU-accelerated."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


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
        import torch

        from ..gpu_backend import get_device, to_torch
        from ..gpu_correlation import bandpass_mask, extract_peak, psr_confidence

        device = get_device()
        ref = to_torch(ref_chunk, device)
        tgt = to_torch(tgt_chunk, device)

        n = ref.shape[0] + tgt.shape[0] - 1
        n_fft = 1 << (n - 1).bit_length()

        R = torch.fft.rfft(ref, n=n_fft)
        T = torch.fft.rfft(tgt, n=n_fft)
        G = R * torch.conj(T)

        # Bandpass 300Hz-6kHz: remove bins with ambiguous phase that
        # cause false peaks at 0ms and ±10000ms in phase-only methods
        bp = bandpass_mask(n_fft, sr, device=device)
        G[~bp] = 0

        # PHAT weighting: normalize by magnitude
        G_phat = G / (torch.abs(G) + 1e-9)
        G_phat[~bp] = 0  # Re-zero filtered bins after normalization
        corr = torch.fft.irfft(G_phat, n=n_fft)

        delay_ms, peak_idx = extract_peak(corr, n_fft, sr)
        confidence = psr_confidence(corr, peak_idx)

        return delay_ms, confidence
