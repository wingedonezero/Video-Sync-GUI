# vsg_core/analysis/correlation/methods/gcc_scot.py
"""GCC-SCOT (Smoothed Coherence Transform) — GPU-accelerated."""

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
        import torch

        from ..gpu_backend import get_device, to_torch
        from ..gpu_correlation import extract_peak, scot_confidence

        device = get_device()
        ref = to_torch(ref_chunk, device)
        tgt = to_torch(tgt_chunk, device)

        n = ref.shape[0] + tgt.shape[0] - 1
        n_fft = 1 << (n - 1).bit_length()

        R = torch.fft.rfft(ref, n=n_fft)
        T = torch.fft.rfft(tgt, n=n_fft)
        G = R * torch.conj(T)

        # SCOT weighting: normalize by geometric mean of auto-spectra
        R_power = torch.abs(R) ** 2
        T_power = torch.abs(T) ** 2
        scot_weight = torch.sqrt(R_power * T_power) + 1e-9

        G_scot = G / scot_weight
        corr = torch.fft.irfft(G_scot, n=n_fft)

        delay_ms, peak_idx = extract_peak(corr, n_fft, sr)
        confidence = scot_confidence(corr, peak_idx, ref.shape[0])

        return delay_ms, confidence
