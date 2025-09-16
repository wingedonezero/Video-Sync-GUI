# vsg_core/analysis/segmentation/boundaries.py
# -*- coding: utf-8 -*-
"""
Phase I: Boundary detection using sync correlation and MFCC/energy analysis.
"""
from typing import List, Tuple, Optional
import numpy as np
import ruptures as rpt
from scipy.signal import correlate

try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False


class BoundaryDetector:
    """Detects segment boundaries using multiple methods."""

    def __init__(self, sample_rate: int, log_func=None):
        self.sample_rate = sample_rate
        self.log = log_func or print
        self.min_segment_duration = 5.0

    def find_sync_boundaries(self, ref_pcm: np.ndarray, target_pcm: np.ndarray) -> List[Tuple[int, int]]:
        """
        Find sync drift boundaries using dense correlation scanning.
        Fixed to properly calculate delays for each segment.
        """
        self.log("  [Boundaries] Performing dense sync analysis...")

        window_s = 2.0
        step_s = 0.25
        window_samples = int(window_s * self.sample_rate)
        step_samples = int(step_s * self.sample_rate)

        min_length = min(len(ref_pcm), len(target_pcm))
        num_chunks = int((min_length - window_samples) / step_samples)

        if num_chunks < 1:
            return [(0, 0), (len(ref_pcm), 0)]

        # Calculate delay for each chunk
        delay_signal = np.zeros(num_chunks)
        for i in range(num_chunks):
            start = i * step_samples
            end = start + window_samples

            ref_chunk = ref_pcm[start:end]
            target_chunk = target_pcm[start:end]

            r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
            t = (target_chunk - np.mean(target_chunk)) / (np.std(target_chunk) + 1e-9)
            c = correlate(r, t, mode='full', method='fft')
            k = np.argmax(np.abs(c))
            lag_samples = float(k - (len(t) - 1))
            delay_signal[i] = int(round((lag_samples / self.sample_rate) * 1000.0))

        self.log(f"  [Boundaries] Analyzed {num_chunks} chunks, finding change points...")

        algo = rpt.Binseg(model="l1").fit(delay_signal)
        penalty = np.log(num_chunks) * np.std(delay_signal)**2 * 0.1
        change_indices = algo.predict(pen=penalty)

        self.log(f"  [Boundaries] Ruptures found change points at indices: {change_indices}")

        # Build boundaries with proper delay calculation
        boundaries = []

        # Process each segment between change points
        segment_starts = [0] + change_indices[:-1]  # Exclude last (it's the end)
        segment_ends = change_indices

        for start_idx, end_idx in zip(segment_starts, segment_ends):
            # Calculate the median delay for THIS ENTIRE segment
            segment_delays = delay_signal[start_idx:end_idx]
            if len(segment_delays) > 0:
                segment_delay = int(np.median(segment_delays))
            else:
                segment_delay = 0

            # Convert chunk index to sample index
            sample_idx = start_idx * step_samples
            boundaries.append((sample_idx, segment_delay))

        # Add the final boundary (end of audio)
        boundaries.append((len(ref_pcm), boundaries[-1][1] if boundaries else 0))

        self.log(f"  [Boundaries] Final: {len(boundaries)-1} sync segments")
        for i in range(len(boundaries)-1):
            start_s = boundaries[i][0] / self.sample_rate
            end_s = boundaries[i+1][0] / self.sample_rate
            delay = boundaries[i][1]
            duration = end_s - start_s
            self.log(f"    - Segment {i+1}: {start_s:.1f}s - {end_s:.1f}s (duration: {duration:.1f}s) @ {delay}ms")

        return boundaries

    def find_structural_boundaries(self, audio: np.ndarray, use_mfcc: bool = True) -> List[int]:
        """
        Find structural boundaries for complex audio (commercials, silence, etc).
        Only used when we need to handle complex cases.
        """
        return [0, len(audio)]

    def merge_boundaries(self, sync_boundaries: List[Tuple[int, int]],
                         structural_boundaries: List[int],
                         min_gap_s: float = 5.0) -> List[Tuple[int, int]]:
        """
        For stepping correction, just use sync boundaries.
        Structural boundaries would only be merged for complex cases.
        """
        return sync_boundaries
