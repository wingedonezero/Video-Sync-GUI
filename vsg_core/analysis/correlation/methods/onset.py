# vsg_core/analysis/correlation/methods/onset.py
"""Onset Detection Envelope Correlation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..confidence import normalize_peak_confidence


@dataclass(frozen=True, slots=True)
class OnsetDetection:
    """
    Correlates onset strength envelopes (transient detection).

    Detects transients like hits, speech onsets, and music attacks,
    then correlates those rather than raw waveforms. More robust to
    different audio mixes since it matches *when things happen*.

    Uses GCC-PHAT on the onset envelopes for the actual correlation.
    Requires librosa.
    """

    name: str = "Onset Detection"
    config_key: str = "multi_corr_onset"

    def find_delay(
        self,
        ref_chunk: np.ndarray,
        tgt_chunk: np.ndarray,
        sr: int,
    ) -> tuple[float, float]:
        try:
            import librosa
        except ImportError:
            raise ImportError(
                "Onset Detection requires librosa. Install with: pip install librosa"
            )

        hop_length = 512

        # Compute onset strength envelopes
        ref_env = librosa.onset.onset_strength(
            y=ref_chunk, sr=sr, hop_length=hop_length
        )
        tgt_env = librosa.onset.onset_strength(
            y=tgt_chunk, sr=sr, hop_length=hop_length
        )

        # Normalize envelopes
        ref_env = (ref_env - np.mean(ref_env)) / (np.std(ref_env) + 1e-9)
        tgt_env = (tgt_env - np.mean(tgt_env)) / (np.std(tgt_env) + 1e-9)

        # Cross-correlate using GCC-PHAT
        envelope_sr = sr / hop_length  # ~93.75 Hz at 48kHz with hop=512

        n = len(ref_env) + len(tgt_env) - 1
        R = np.fft.fft(ref_env, n)
        T = np.fft.fft(tgt_env, n)
        G = R * np.conj(T)
        G_phat = G / (np.abs(G) + 1e-9)
        r_phat = np.fft.ifft(G_phat)

        k = np.argmax(np.abs(r_phat))
        lag_frames = k - n if k > n / 2 else k

        delay_ms = float(lag_frames / envelope_sr * 1000.0)
        match_confidence = normalize_peak_confidence(r_phat, k)

        return delay_ms, match_confidence
