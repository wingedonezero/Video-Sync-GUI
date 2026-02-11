# vsg_core/analysis/correlation/methods/scc.py
"""Standard Cross-Correlation (SCC) method."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import correlate


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
        r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
        t = (tgt_chunk - np.mean(tgt_chunk)) / (np.std(tgt_chunk) + 1e-9)
        c = correlate(r, t, mode="full", method="fft")
        k = np.argmax(np.abs(c))
        lag_samples = float(k - (len(t) - 1))

        if self.peak_fit and 0 < k < len(c) - 1:
            y1, y2, y3 = np.abs(c[k - 1 : k + 2])
            delta = 0.5 * (y1 - y3) / (y1 - 2 * y2 + y3)
            if -1 < delta < 1:
                lag_samples += delta

        raw_delay_s = lag_samples / float(sr)
        match_pct = (
            np.abs(c[k]) / (np.sqrt(np.sum(r**2) * np.sum(t**2)) + 1e-9)
        ) * 100.0
        return raw_delay_s * 1000.0, match_pct
