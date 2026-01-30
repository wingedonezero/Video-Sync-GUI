# vsg_core/analysis/correlation/onset.py
"""
Onset Detection correlation algorithm.

Computes onset strength envelopes (detecting transients like hits, speech onsets,
music attacks) and correlates those rather than raw waveforms. More robust to
different audio mixes since it matches *when things happen* not exact waveform shape.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ._base import normalize_peak_confidence


class OnsetAlgorithm:
    """Onset Detection correlation algorithm."""

    name = "Onset Detection"
    key = "onset"

    def find_delay(
        self,
        ref_audio: NDArray[np.float32],
        target_audio: NDArray[np.float32],
        sample_rate: int,
        **kwargs,
    ) -> tuple[float, float]:
        """
        Calculate delay using onset detection envelope correlation.

        Uses GCC-PHAT on the onset envelopes for the actual correlation.

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
                "Onset Detection requires librosa. Install with: pip install librosa"
            )

        # Onset detection parameters
        # hop_length=512 at 48kHz gives ~10.7ms resolution per frame
        hop_length = 512

        # Compute onset strength envelopes
        # This detects transients (attacks, hits, speech onsets) and creates
        # a 1D envelope showing "onset-ness" over time
        ref_env = librosa.onset.onset_strength(
            y=ref_audio, sr=sample_rate, hop_length=hop_length
        )
        tgt_env = librosa.onset.onset_strength(
            y=target_audio, sr=sample_rate, hop_length=hop_length
        )

        # Normalize envelopes
        ref_env = (ref_env - np.mean(ref_env)) / (np.std(ref_env) + 1e-9)
        tgt_env = (tgt_env - np.mean(tgt_env)) / (np.std(tgt_env) + 1e-9)

        # Cross-correlate envelopes using GCC-PHAT for robustness
        # The envelope sample rate is sr / hop_length
        envelope_sr = sample_rate / hop_length  # ~93.75 Hz at 48kHz with hop=512

        n = len(ref_env) + len(tgt_env) - 1
        R = np.fft.fft(ref_env, n)
        T = np.fft.fft(tgt_env, n)
        G = R * np.conj(T)
        G_phat = G / (np.abs(G) + 1e-9)
        r_phat = np.fft.ifft(G_phat)

        k = np.argmax(np.abs(r_phat))
        lag_frames = k - n if k > n / 2 else k

        # Convert frame lag to milliseconds
        delay_ms = (lag_frames / envelope_sr) * 1000.0
        match_confidence = normalize_peak_confidence(r_phat, k)

        return delay_ms, match_confidence
