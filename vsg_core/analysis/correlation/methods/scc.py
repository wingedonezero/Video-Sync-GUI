# vsg_core/analysis/correlation/methods/scc.py
"""Standard Cross-Correlation (SCC) method — GPU-accelerated."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Scc:
    """Standard cross-correlation with optional parabolic peak fitting."""

    name: str = "Standard Correlation (SCC)"
    config_key: str = "multi_corr_scc"
    peak_fit: bool = False

    def find_delay(
        self,
        ref_chunk: np.ndarray,
        tgt_chunk: np.ndarray,
        sr: int,
    ) -> tuple[float, float]:
        import torch

        from ..gpu_backend import get_device, to_torch
        from ..gpu_correlation import extract_peak, scc_confidence

        device = get_device()
        ref = to_torch(ref_chunk, device)
        tgt = to_torch(tgt_chunk, device)

        # Normalize (zero-mean, unit-variance)
        ref_n = (ref - torch.mean(ref)) / (torch.std(ref) + 1e-9)
        tgt_n = (tgt - torch.mean(tgt)) / (torch.std(tgt) + 1e-9)

        # Cross-correlation via FFT
        n = ref_n.shape[0] + tgt_n.shape[0] - 1
        n_fft = 1 << (n - 1).bit_length()

        R = torch.fft.rfft(ref_n, n=n_fft)
        T = torch.fft.rfft(tgt_n, n=n_fft)
        G = R * torch.conj(T)
        corr = torch.fft.irfft(G, n=n_fft)

        delay_ms, peak_idx = extract_peak(
            corr, n_fft, sr, peak_fit=self.peak_fit,
        )
        confidence = scc_confidence(corr, peak_idx, ref_n, tgt_n)

        return delay_ms, confidence
