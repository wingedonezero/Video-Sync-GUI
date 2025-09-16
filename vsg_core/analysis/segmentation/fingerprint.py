# vsg_core/analysis/segmentation/fingerprint.py
# -*- coding: utf-8 -*-
"""
Phase II: Audio fingerprinting using spectrogram peak analysis.
Custom implementation inspired by Shazam's algorithm.
"""
import hashlib
from typing import Optional, List, Tuple
import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter


class AudioFingerprinter:
    """Generate robust audio fingerprints using spectrogram peaks."""

    def __init__(self, sample_rate: int, log_func=None):
        self.sample_rate = sample_rate
        self.log = log_func or print

        # Fingerprinting parameters
        self.fft_window_size = 4096  # ~85ms at 48kHz
        self.hop_size = self.fft_window_size // 2
        self.freq_bands = 512  # Number of frequency bins to use

        # Peak detection parameters
        self.peak_neighborhood_size = 20  # Size of local maxima filter
        self.min_peak_amplitude = 0.01  # Minimum peak amplitude threshold
        self.max_peaks_per_frame = 5  # Limit peaks per time frame

        # Hash parameters
        self.target_zone_size = 5  # Number of future frames to pair with
        self.min_time_delta = 1  # Minimum time between paired peaks

    def generate_fingerprint(self, audio_chunk: np.ndarray, duration_limit: float = 5.0) -> Optional[str]:
        """
        Generate a fingerprint for an audio chunk using spectrogram peaks.
        Returns a hash string representing the audio fingerprint.
        """
        if len(audio_chunk) < self.sample_rate:
            return None

        try:
            # Limit duration to reduce memory usage
            max_samples = int(duration_limit * self.sample_rate)
            if len(audio_chunk) > max_samples:
                # Take from middle of chunk for best representation
                start = (len(audio_chunk) - max_samples) // 2
                audio_chunk = audio_chunk[start:start + max_samples]

            # Generate spectrogram
            spectrogram = self._generate_spectrogram(audio_chunk)

            # Find peaks in spectrogram
            peaks = self._find_peaks(spectrogram)

            # Generate hashes from peak pairs
            hashes = self._generate_hashes(peaks)

            if not hashes:
                return None

            # Combine hashes into single fingerprint
            fingerprint = self._combine_hashes(hashes)

            return fingerprint

        except Exception as e:
            self.log(f"  [Fingerprint] Error generating fingerprint: {e}")
            return None

    def _generate_spectrogram(self, audio: np.ndarray) -> np.ndarray:
        """Generate a spectrogram using STFT."""
        # Convert to float and normalize
        audio_float = audio.astype(np.float32) / (np.abs(audio).max() + 1e-9)

        # Apply window to reduce spectral leakage
        window = signal.windows.hann(self.fft_window_size)

        # Compute STFT
        freqs, times, Zxx = signal.stft(
            audio_float,
            fs=self.sample_rate,
            window=window,
            nperseg=self.fft_window_size,
            noverlap=self.fft_window_size - self.hop_size
        )

        # Take magnitude and limit frequency range
        magnitude = np.abs(Zxx[:self.freq_bands, :])

        # Apply log scaling for better peak detection
        magnitude = np.log1p(magnitude * 100)

        return magnitude

    def _find_peaks(self, spectrogram: np.ndarray) -> List[Tuple[int, int]]:
        """
        Find peaks in the spectrogram using local maxima detection.
        Returns list of (time_idx, freq_idx) tuples.
        """
        # Apply local maximum filter
        neighborhood = np.ones((self.peak_neighborhood_size, self.peak_neighborhood_size))
        local_max = maximum_filter(spectrogram, footprint=neighborhood, mode='constant')

        # Find points that are local maxima and above threshold
        is_peak = (spectrogram == local_max) & (spectrogram > self.min_peak_amplitude)

        # Get peak coordinates
        peak_coords = np.argwhere(is_peak)

        # Sort by amplitude (strongest peaks first)
        peak_amplitudes = spectrogram[is_peak]
        sorted_indices = np.argsort(peak_amplitudes)[::-1]
        peak_coords = peak_coords[sorted_indices]

        # Limit peaks per time frame to reduce memory
        peaks = []
        time_frame_counts = {}

        for freq_idx, time_idx in peak_coords:
            if time_frame_counts.get(time_idx, 0) < self.max_peaks_per_frame:
                peaks.append((int(time_idx), int(freq_idx)))
                time_frame_counts[time_idx] = time_frame_counts.get(time_idx, 0) + 1

                # Limit total number of peaks
                if len(peaks) >= 200:
                    break

        return peaks

    def _generate_hashes(self, peaks: List[Tuple[int, int]]) -> List[str]:
        """
        Generate hashes from peak pairs.
        Each hash encodes the relationship between two peaks.
        """
        hashes = []
        peaks_sorted = sorted(peaks)  # Sort by time

        for i, (t1, f1) in enumerate(peaks_sorted):
            # Pair with future peaks in target zone
            for j in range(i + self.min_time_delta,
                          min(i + self.target_zone_size, len(peaks_sorted))):
                t2, f2 = peaks_sorted[j]

                # Create hash from peak pair relationship
                # Format: freq1|freq2|time_delta
                time_delta = t2 - t1
                hash_input = f"{f1}|{f2}|{time_delta}"

                # Generate hash
                hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:16]
                hashes.append(hash_value)

                # Limit number of hashes to prevent memory issues
                if len(hashes) >= 100:
                    return hashes

        return hashes

    def _combine_hashes(self, hashes: List[str]) -> str:
        """Combine individual hashes into a single fingerprint."""
        if not hashes:
            return ""

        # Sort hashes for consistency
        hashes_sorted = sorted(hashes)

        # Take first N hashes and combine
        combined = "|".join(hashes_sorted[:50])

        # Generate final hash
        final_hash = hashlib.sha256(combined.encode()).hexdigest()

        return final_hash

    def compare_fingerprints(self, fp1: str, fp2: str) -> float:
        """
        Compare two fingerprints and return similarity score (0-1).
        Simple comparison for now - can be enhanced with fuzzy matching.
        """
        if not fp1 or not fp2:
            return 0.0

        # Simple exact match for now
        # Could enhance with Hamming distance or other similarity metrics
        return 1.0 if fp1 == fp2 else 0.0
