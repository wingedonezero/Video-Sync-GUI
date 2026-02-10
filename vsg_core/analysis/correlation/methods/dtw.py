# vsg_core/analysis/correlation/methods/dtw.py
"""Dynamic Time Warping (DTW) on MFCC features."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Dtw:
    """
    DTW finds optimal alignment between two sequences.

    Handles tempo variations and non-linear time differences.
    Uses MFCC features which are robust to amplitude and timbral differences.
    Returns the median offset from the warping path as the delay estimate.

    Requires librosa.
    """

    name: str = "DTW (Dynamic Time Warping)"
    config_key: str = "multi_corr_dtw"

    def find_delay(
        self,
        ref_chunk: np.ndarray,
        tgt_chunk: np.ndarray,
        sr: int,
    ) -> tuple[float, float]:
        try:
            import librosa
        except ImportError:
            raise ImportError("DTW requires librosa. Install with: pip install librosa")

        hop_length = 512

        # Extract MFCC features - robust to amplitude/timbre differences
        ref_mfcc = librosa.feature.mfcc(
            y=ref_chunk, sr=sr, n_mfcc=13, hop_length=hop_length
        )
        tgt_mfcc = librosa.feature.mfcc(
            y=tgt_chunk, sr=sr, n_mfcc=13, hop_length=hop_length
        )

        # Compute DTW alignment
        D, wp = librosa.sequence.dtw(X=ref_mfcc, Y=tgt_mfcc, metric="euclidean")

        # wp is array of (ref_frame, tgt_frame) pairs along optimal path
        offsets_frames = wp[:, 1] - wp[:, 0]

        # Use median offset (robust to outliers at boundaries)
        median_offset_frames = np.median(offsets_frames)

        # Convert frame offset to milliseconds
        frame_duration_ms = (hop_length / sr) * 1000.0
        delay_ms = float(median_offset_frames * frame_duration_ms)

        # Confidence from normalized DTW distance
        # Lower distance = better match
        path_length = len(wp)
        avg_cost = float(
            D[wp[-1, 0], wp[-1, 1]] / path_length if path_length > 0 else float("inf")
        )

        # Convert to 0-100 scale (lower cost = higher confidence)
        # Empirically, good matches have avg_cost < 50, poor > 200
        match_confidence = max(0.0, min(100.0, 100.0 - avg_cost * 0.5))

        return delay_ms, match_confidence
