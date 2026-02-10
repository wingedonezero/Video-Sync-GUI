# vsg_core/analysis/correlation/methods/spectrogram.py
"""Mel Spectrogram Cross-Correlation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..confidence import normalize_peak_confidence


@dataclass(frozen=True, slots=True)
class SpectrogramCorrelation:
    """
    Correlates mel spectrograms along the time axis.

    Captures both frequency and time structure, making it robust
    to some types of audio differences while maintaining time precision.

    Requires librosa.
    """

    name: str = "Spectrogram Correlation"
    config_key: str = "multi_corr_spectrogram"

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
                "Spectrogram correlation requires librosa. "
                "Install with: pip install librosa"
            )

        hop_length = 512
        n_mels = 64

        # Compute mel spectrograms (log-scaled)
        ref_mel = librosa.feature.melspectrogram(
            y=ref_chunk, sr=sr, hop_length=hop_length, n_mels=n_mels
        )
        tgt_mel = librosa.feature.melspectrogram(
            y=tgt_chunk, sr=sr, hop_length=hop_length, n_mels=n_mels
        )

        # Convert to log scale (dB)
        ref_mel_db = librosa.power_to_db(ref_mel, ref=np.max)
        tgt_mel_db = librosa.power_to_db(tgt_mel, ref=np.max)

        # Average across mel bands to get time-series
        ref_flat = ref_mel_db.mean(axis=0)
        tgt_flat = tgt_mel_db.mean(axis=0)

        # Normalize
        ref_norm = (ref_flat - np.mean(ref_flat)) / (np.std(ref_flat) + 1e-9)
        tgt_norm = (tgt_flat - np.mean(tgt_flat)) / (np.std(tgt_flat) + 1e-9)

        # Cross-correlate using GCC-PHAT
        n = len(ref_norm) + len(tgt_norm) - 1
        R = np.fft.fft(ref_norm, n)
        T = np.fft.fft(tgt_norm, n)
        G = R * np.conj(T)
        G_phat = G / (np.abs(G) + 1e-9)
        r_phat = np.fft.ifft(G_phat)

        k = np.argmax(np.abs(r_phat))
        lag_frames = k - n if k > n / 2 else k

        frame_duration_ms = (hop_length / sr) * 1000.0
        delay_ms = float(lag_frames * frame_duration_ms)

        match_confidence = normalize_peak_confidence(r_phat, k)
        return delay_ms, match_confidence
