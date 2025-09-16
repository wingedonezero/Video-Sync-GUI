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
        self.fft_window_size = 4096
        self.hop_size = self.fft_window_size // 2
        self.freq_bands = 512

        # Peak detection parameters
        self.peak_neighborhood_size = 20
        self.min_peak_amplitude = 0.01
        self.max_peaks_per_frame = 5

        # Hash parameters
        self.target_zone_size = 5
        self.min_time_delta = 1

    def generate_fingerprint(self, audio_chunk: np.ndarray, duration_limit: float = 5.0) -> Optional[str]:
        """
        Generate a fingerprint for an audio chunk using spectrogram peaks.
        Returns a hash string representing the audio fingerprint.
        """
        if len(audio_chunk) < self.sample_rate:
            return None

        try:
            max_samples = int(duration_limit * self.sample_rate)
            if len(audio_chunk) > max_samples:
                start = (len(audio_chunk) - max_samples) // 2
                audio_chunk = audio_chunk[start:start + max_samples]

            spectrogram = self._generate_spectrogram(audio_chunk)
            peaks = self._find_peaks(spectrogram)
            hashes = self._generate_hashes(peaks)

            if not hashes:
                return None

            fingerprint = self._combine_hashes(hashes)
            return fingerprint

        except Exception as e:
            self.log(f"  [Fingerprint] Error generating fingerprint: {e}")
            return None

    def _generate_spectrogram(self, audio: np.ndarray) -> np.ndarray:
        # ... (this function remains the same)
        audio_float = audio.astype(np.float32) / (np.abs(audio).max() + 1e-9)
        window = signal.windows.hann(self.fft_window_size)
        _, _, Zxx = signal.stft(
            audio_float,
            fs=self.sample_rate,
            window=window,
            nperseg=self.fft_window_size,
            noverlap=self.fft_window_size - self.hop_size
        )
        magnitude = np.abs(Zxx[:self.freq_bands, :])
        magnitude = np.log1p(magnitude * 100)
        return magnitude

    def _find_peaks(self, spectrogram: np.ndarray) -> List[Tuple[int, int]]:
        # ... (this function remains the same)
        neighborhood = np.ones((self.peak_neighborhood_size, self.peak_neighborhood_size))
        local_max = maximum_filter(spectrogram, footprint=neighborhood, mode='constant')
        is_peak = (spectrogram == local_max) & (spectrogram > self.min_peak_amplitude)
        peak_coords = np.argwhere(is_peak)
        peak_amplitudes = spectrogram[is_peak]
        sorted_indices = np.argsort(peak_amplitudes)[::-1]
        peak_coords = peak_coords[sorted_indices]
        peaks = []
        time_frame_counts = {}
        for freq_idx, time_idx in peak_coords:
            if time_frame_counts.get(time_idx, 0) < self.max_peaks_per_frame:
                peaks.append((int(time_idx), int(freq_idx)))
                time_frame_counts[time_idx] = time_frame_counts.get(time_idx, 0) + 1
                if len(peaks) >= 200:
                    break
        return peaks

    def _generate_hashes(self, peaks: List[Tuple[int, int]]) -> List[str]:
        # ... (this function remains the same)
        hashes = []
        peaks_sorted = sorted(peaks)
        for i, (t1, f1) in enumerate(peaks_sorted):
            for j in range(i + self.min_time_delta, min(i + self.target_zone_size, len(peaks_sorted))):
                t2, f2 = peaks_sorted[j]
                time_delta = t2 - t1
                hash_input = f"{f1}|{f2}|{time_delta}"
                hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:16]
                hashes.append(hash_value)
                if len(hashes) >= 100:
                    return hashes
        return hashes

    def _combine_hashes(self, hashes: List[str]) -> str:
        # ... (this function remains the same)
        if not hashes: return ""
        hashes_sorted = sorted(hashes)
        combined = "|".join(hashes_sorted[:50])
        final_hash = hashlib.sha256(combined.encode()).hexdigest()
        return final_hash

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calculates the Levenshtein distance between two strings."""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def compare_fingerprints(self, fp1: str, fp2: str) -> float:
        """
        Compares two fingerprints using Levenshtein distance and returns a
        normalized similarity score from 0.0 (completely different) to 1.0 (identical).
        """
        if not fp1 or not fp2:
            return 0.0

        distance = self._levenshtein_distance(fp1, fp2)
        max_len = max(len(fp1), len(fp2))
        if max_len == 0:
            return 1.0 # Both are empty strings

        similarity = (max_len - distance) / max_len
        return max(0.0, similarity) # Ensure similarity is not negative
