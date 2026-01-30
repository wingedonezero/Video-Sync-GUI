# vsg_core/analysis/correlation/spectrogram.py
"""
Spectrogram-based correlation algorithm.

Computes mel spectrograms of both signals and correlates them along the
time axis. Captures both frequency and time structure, making it robust
to some types of audio differences while maintaining time precision.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ._base import normalize_peak_confidence


class SpectrogramAlgorithm:
    """Spectrogram-based correlation algorithm."""

    name = "Spectrogram Correlation"
    key = "spectrogram"

    def find_delay(
        self,
        ref_audio: NDArray[np.float32],
        target_audio: NDArray[np.float32],
        sample_rate: int,
        **kwargs,
    ) -> tuple[float, float]:
        """
        Calculate delay using spectrogram cross-correlation.

        Args:
            ref_audio: Reference audio chunk
            target_audio: Target audio chunk
            sample_rate: Sample rate in Hz

        Returns:
            Tuple of (delay_ms, confidence)

        Raises:
            ImportError: If librosa is not installed
        """
        try:
            import librosa
        except ImportError:
            raise ImportError(
                "Spectrogram correlation requires librosa. Install with: pip install librosa"
            )

        hop_length = 512
        n_mels = 64  # Number of mel bands

        # Compute mel spectrograms (log-scaled for better dynamic range)
        ref_mel = librosa.feature.melspectrogram(
            y=ref_audio, sr=sample_rate, hop_length=hop_length, n_mels=n_mels
        )
        tgt_mel = librosa.feature.melspectrogram(
            y=target_audio, sr=sample_rate, hop_length=hop_length, n_mels=n_mels
        )

        # Convert to log scale (dB)
        ref_mel_db = librosa.power_to_db(ref_mel, ref=np.max)
        tgt_mel_db = librosa.power_to_db(tgt_mel, ref=np.max)

        # Flatten spectrograms along frequency axis to get time-series of spectral features
        # Then correlate these feature vectors
        ref_flat = ref_mel_db.mean(axis=0)  # Average across mel bands
        tgt_flat = tgt_mel_db.mean(axis=0)

        # Normalize
        ref_norm = (ref_flat - np.mean(ref_flat)) / (np.std(ref_flat) + 1e-9)
        tgt_norm = (tgt_flat - np.mean(tgt_flat)) / (np.std(tgt_flat) + 1e-9)

        # Cross-correlate using GCC-PHAT for robustness
        n = len(ref_norm) + len(tgt_norm) - 1
        R = np.fft.fft(ref_norm, n)
        T = np.fft.fft(tgt_norm, n)
        G = R * np.conj(T)
        G_phat = G / (np.abs(G) + 1e-9)
        r_phat = np.fft.ifft(G_phat)

        k = np.argmax(np.abs(r_phat))
        lag_frames = k - n if k > n / 2 else k

        # Convert frame lag to milliseconds
        frame_duration_ms = (hop_length / sample_rate) * 1000.0
        delay_ms = lag_frames * frame_duration_ms

        match_confidence = normalize_peak_confidence(r_phat, k)

        return delay_ms, match_confidence
