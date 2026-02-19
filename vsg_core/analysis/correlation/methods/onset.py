# vsg_core/analysis/correlation/methods/onset.py
"""Onset Detection Envelope Correlation — GPU-accelerated via torchaudio."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class OnsetDetection:
    """
    Correlates onset strength envelopes (transient detection).

    Detects transients like hits, speech onsets, and music attacks,
    then correlates those rather than raw waveforms. More robust to
    different audio mixes since it matches *when things happen*.

    Uses spectral flux (torchaudio Spectrogram) for onset detection,
    then GCC-PHAT on the onset envelopes for correlation.
    Runs entirely on GPU — no librosa dependency.
    """

    name: str = "Onset Detection"
    config_key: str = "multi_corr_onset"

    def find_delay(
        self,
        ref_chunk: np.ndarray,
        tgt_chunk: np.ndarray,
        sr: int,
    ) -> tuple[float, float]:
        import torch

        from ..gpu_backend import get_device, get_spectrogram_transform, to_torch
        from ..gpu_correlation import extract_peak_feature

        hop_length = 512

        device = get_device()
        ref = to_torch(ref_chunk, device)
        tgt = to_torch(tgt_chunk, device)

        # Compute magnitude spectrograms using cached torchaudio transform
        spec_transform = get_spectrogram_transform(
            n_fft=2048, hop_length=hop_length, power=1.0,
        )

        ref_spec = spec_transform(ref)  # shape: (n_freq, n_frames)
        tgt_spec = spec_transform(tgt)

        # Onset strength via spectral flux: diff along time → ReLU → mean over freq
        ref_flux = torch.clamp(torch.diff(ref_spec, dim=-1), min=0).mean(dim=0)
        tgt_flux = torch.clamp(torch.diff(tgt_spec, dim=-1), min=0).mean(dim=0)

        # Normalize envelopes (zero-mean, unit-variance)
        ref_env = (ref_flux - torch.mean(ref_flux)) / (torch.std(ref_flux) + 1e-9)
        tgt_env = (tgt_flux - torch.mean(tgt_flux)) / (torch.std(tgt_flux) + 1e-9)

        # Feature-domain parameters
        frame_sr = sr / hop_length  # ~93.75 Hz
        # No max_delay restriction for chunked mode — search the full range
        n_frames = min(len(ref_env), len(tgt_env))
        max_delay_frames = n_frames // 2

        # GCC-PHAT on onset envelopes
        n = ref_env.shape[0] + tgt_env.shape[0] - 1
        n_fft = 1 << (n - 1).bit_length()

        R = torch.fft.rfft(ref_env, n=n_fft)
        T = torch.fft.rfft(tgt_env, n=n_fft)
        G = R * torch.conj(T)
        G_phat = G / (torch.abs(G) + 1e-9)
        corr = torch.fft.irfft(G_phat, n=n_fft)

        delay_ms, confidence = extract_peak_feature(
            corr, n_fft, max_delay_frames, frame_sr,
        )
        return delay_ms, confidence
