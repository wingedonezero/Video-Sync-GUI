# vsg_core/analysis/correlation/dtw.py
"""
DTW (Dynamic Time Warping) correlation algorithm.

DTW finds the optimal alignment between two sequences, handling tempo
variations and non-linear time differences. Uses MFCC features which
are robust to amplitude and timbral differences.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


class DtwAlgorithm:
    """Dynamic Time Warping correlation algorithm."""

    name = "DTW (Dynamic Time Warping)"
    key = "dtw"

    def find_delay(
        self,
        ref_audio: NDArray[np.float32],
        target_audio: NDArray[np.float32],
        sample_rate: int,
        **kwargs,
    ) -> tuple[float, float]:
        """
        Calculate delay using Dynamic Time Warping on MFCC features.

        Returns the median offset from the warping path as the delay estimate.

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
            raise ImportError("DTW requires librosa. Install with: pip install librosa")

        # Downsample for DTW efficiency (DTW is O(n*m) complexity)
        # Use a lower sample rate for feature extraction
        hop_length = 512

        # Extract MFCC features - robust to amplitude/timbre differences
        ref_mfcc = librosa.feature.mfcc(
            y=ref_audio, sr=sample_rate, n_mfcc=13, hop_length=hop_length
        )
        tgt_mfcc = librosa.feature.mfcc(
            y=target_audio, sr=sample_rate, n_mfcc=13, hop_length=hop_length
        )

        # Compute DTW alignment
        # D is the accumulated cost matrix, wp is the warping path
        D, wp = librosa.sequence.dtw(X=ref_mfcc, Y=tgt_mfcc, metric="euclidean")

        # wp is array of (ref_frame, tgt_frame) pairs along optimal path
        # Calculate the offset at each point in the path
        offsets_frames = wp[:, 1] - wp[:, 0]  # tgt - ref frame indices

        # Use median offset (robust to outliers at boundaries)
        median_offset_frames = np.median(offsets_frames)

        # Convert frame offset to milliseconds
        frame_duration_ms = (hop_length / sample_rate) * 1000.0
        delay_ms = median_offset_frames * frame_duration_ms

        # Match confidence based on normalized DTW distance
        # Lower distance = better match
        path_length = len(wp)
        avg_cost = (
            D[wp[-1, 0], wp[-1, 1]] / path_length if path_length > 0 else float("inf")
        )

        # Convert to 0-100 scale (lower cost = higher confidence)
        # Empirically, good matches have avg_cost < 50, poor matches > 200
        match_confidence = max(0, min(100, 100 - avg_cost * 0.5))

        return delay_ms, match_confidence
