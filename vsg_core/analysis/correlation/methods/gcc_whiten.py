# vsg_core/analysis/correlation/methods/gcc_whiten.py
"""GCC with Spectral Whitening (Whitened Cross-Correlation) — GPU-accelerated."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


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
        import torch

        from ..gpu_backend import get_device, to_torch
        from ..gpu_correlation import extract_peak, normalize_peak_confidence_torch

        device = get_device()
        ref = to_torch(ref_chunk, device)
        tgt = to_torch(tgt_chunk, device)

        n = ref.shape[0] + tgt.shape[0] - 1
        n_fft = 1 << (n - 1).bit_length()

        R = torch.fft.rfft(ref, n=n_fft)
        T = torch.fft.rfft(tgt, n=n_fft)

        # Whiten: normalize magnitude while preserving phase
        R_white = R / (torch.abs(R) + 1e-9)
        T_white = T / (torch.abs(T) + 1e-9)

        G_white = R_white * torch.conj(T_white)
        corr = torch.fft.irfft(G_white, n=n_fft)

        delay_ms, peak_idx = extract_peak(corr, n_fft, sr)
        confidence = normalize_peak_confidence_torch(corr, peak_idx)

        return delay_ms, confidence
