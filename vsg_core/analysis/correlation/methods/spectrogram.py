# vsg_core/analysis/correlation/methods/spectrogram.py
"""Mel Spectrogram Cross-Correlation — GPU-accelerated via torchaudio."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SpectrogramCorrelation:
    """
    Correlates mel spectrograms along the time axis.

    Captures both frequency and time structure, making it robust
    to some types of audio differences while maintaining time precision.

    Uses torchaudio MelSpectrogram on GPU — no librosa dependency.
    """

    name: str = "Spectrogram Correlation"
    config_key: str = "multi_corr_spectrogram"

    def find_delay(
        self,
        ref_chunk: np.ndarray,
        tgt_chunk: np.ndarray,
        sr: int,
    ) -> tuple[float, float]:
        import torch

        from ..gpu_backend import get_device, get_mel_spectrogram_transform, to_torch
        from ..gpu_correlation import extract_peak_feature

        hop_length = 512
        n_mels = 64

        device = get_device()
        ref = to_torch(ref_chunk, device)
        tgt = to_torch(tgt_chunk, device)

        # Compute mel spectrograms using cached torchaudio transform
        mel_transform = get_mel_spectrogram_transform(
            sample_rate=sr, n_fft=2048, hop_length=hop_length,
            n_mels=n_mels, power=2.0,
        )

        ref_mel = mel_transform(ref)  # shape: (n_mels, n_frames)
        tgt_mel = mel_transform(tgt)

        # Convert to log dB scale (like librosa.power_to_db)
        ref_db = 10.0 * torch.log10(ref_mel.clamp(min=1e-10))
        tgt_db = 10.0 * torch.log10(tgt_mel.clamp(min=1e-10))

        # Normalize per-signal to max = 0 dB (like librosa's ref=np.max)
        ref_db = ref_db - ref_db.max()
        tgt_db = tgt_db - tgt_db.max()

        # Average across mel bands → time-series
        ref_flat = ref_db.mean(dim=0)
        tgt_flat = tgt_db.mean(dim=0)

        # Normalize (zero-mean, unit-variance)
        ref_norm = (ref_flat - torch.mean(ref_flat)) / (torch.std(ref_flat) + 1e-9)
        tgt_norm = (tgt_flat - torch.mean(tgt_flat)) / (torch.std(tgt_flat) + 1e-9)

        # Feature-domain parameters
        frame_sr = sr / hop_length  # ~93.75 Hz
        # No max_delay restriction for chunked mode — search the full range
        n_frames = min(len(ref_norm), len(tgt_norm))
        max_delay_frames = n_frames // 2

        # GCC-PHAT on mel time-series
        n = ref_norm.shape[0] + tgt_norm.shape[0] - 1
        n_fft = 1 << (n - 1).bit_length()

        R = torch.fft.rfft(ref_norm, n=n_fft)
        T = torch.fft.rfft(tgt_norm, n=n_fft)
        G = R * torch.conj(T)
        G_phat = G / (torch.abs(G) + 1e-9)
        corr = torch.fft.irfft(G_phat, n=n_fft)

        delay_ms, confidence = extract_peak_feature(
            corr, n_fft, max_delay_frames, frame_sr,
        )
        return delay_ms, confidence
