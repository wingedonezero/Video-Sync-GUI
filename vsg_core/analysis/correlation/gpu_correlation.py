# vsg_core/analysis/correlation/gpu_correlation.py
"""
GPU-accelerated correlation utilities shared across methods.

Provides peak extraction and confidence scoring on torch tensors.
These are the GPU equivalents of the numpy-based functions in
confidence.py and the peak extraction logic in each method.
"""

from __future__ import annotations

import torch


def extract_peak(
    corr: torch.Tensor,
    n_fft: int,
    sr: int,
    peak_fit: bool = False,
) -> tuple[float, float, int]:
    """
    Extract delay and confidence from a waveform-domain correlation.

    Searches the full lag range (no max_delay restriction) for the
    strongest peak, then computes confidence.

    Args:
        corr: Correlation result from irfft (length n_fft).
        n_fft: FFT size used.
        sr: Sample rate in Hz.
        peak_fit: If True, apply parabolic sub-sample interpolation.

    Returns:
        (delay_ms, confidence, peak_index) — delay in ms, confidence 0-100,
        and the raw peak index in the correlation array.
    """
    n = n_fft
    abs_corr = torch.abs(corr)
    k = torch.argmax(abs_corr).item()

    # Convert circular index to signed lag
    lag_samples = float(k if k <= n // 2 else k - n)

    # Parabolic (sub-sample) peak fitting
    if peak_fit and 0 < k < len(abs_corr) - 1:
        y1 = abs_corr[k - 1].item()
        y2 = abs_corr[k].item()
        y3 = abs_corr[k + 1].item()
        denom = y1 - 2.0 * y2 + y3
        if abs(denom) > 1e-12:
            delta = 0.5 * (y1 - y3) / denom
            if -1.0 < delta < 1.0:
                lag_samples += delta

    delay_ms = lag_samples / float(sr) * 1000.0

    return delay_ms, k


def scc_confidence(
    corr: torch.Tensor,
    peak_idx: int,
    ref_norm: torch.Tensor,
    tgt_norm: torch.Tensor,
) -> float:
    """
    SCC-specific confidence: peak / sqrt(energy_ref * energy_tgt) * 100.

    This matches the existing SCC confidence formula.
    """
    peak_val = torch.abs(corr[peak_idx]).item()
    energy_ref = torch.sum(ref_norm ** 2).item()
    energy_tgt = torch.sum(tgt_norm ** 2).item()
    match_pct = peak_val / (((energy_ref * energy_tgt) ** 0.5) + 1e-9) * 100.0
    return min(100.0, max(0.0, match_pct))


def normalize_peak_confidence_torch(
    correlation: torch.Tensor,
    peak_idx: int,
) -> float:
    """
    GPU port of normalize_peak_confidence from confidence.py.

    Uses three metrics:
    1. Prominence: peak / median (over noise floor)
    2. Uniqueness: peak / second-best peak
    3. SNR: peak / background stddev

    Combined with empirical weights: (prom*5 + unique*8 + snr*1.5) / 3.
    Clamped to 0-100.
    """
    abs_corr = torch.abs(correlation)
    peak_value = abs_corr[peak_idx].item()

    # Metric 1: Prominence over noise floor (median)
    noise_floor = torch.median(abs_corr).item()
    prominence = peak_value / (noise_floor + 1e-9)

    # Metric 2: Uniqueness vs second-best peak (exclude 1% neighbors)
    n = len(abs_corr)
    neighbor = max(1, n // 100)
    mask = torch.ones(n, dtype=torch.bool, device=abs_corr.device)
    start = max(0, peak_idx - neighbor)
    end = min(n, peak_idx + neighbor + 1)
    mask[start:end] = False

    if mask.any():
        second_best = abs_corr[mask].max().item()
    else:
        second_best = noise_floor
    uniqueness = peak_value / (second_best + 1e-9)

    # Metric 3: SNR using robust background estimation
    # Use std of lower 90% of values
    threshold_90 = torch.quantile(abs_corr, 0.9).item()
    background = abs_corr[abs_corr < threshold_90]
    if len(background) > 10:
        bg_std = torch.std(background).item()
    else:
        bg_std = 1e-9
    snr = peak_value / (bg_std + 1e-9)

    # Combine with empirical weights
    confidence = (prominence * 5.0 + uniqueness * 8.0 + snr * 1.5) / 3.0
    return min(100.0, max(0.0, confidence))


def scot_confidence(
    corr: torch.Tensor,
    peak_idx: int,
) -> float:
    """
    GCC-SCOT confidence: peak / mean * 10.

    Matches the existing GCC-SCOT confidence formula.
    """
    abs_corr = torch.abs(corr)
    peak_val = abs_corr[peak_idx].item()
    mean_val = torch.mean(abs_corr).item()
    confidence = peak_val / (mean_val + 1e-9) * 10.0
    return min(100.0, max(0.0, confidence))


def extract_peak_feature(
    corr: torch.Tensor,
    n_fft: int,
    max_delay_frames: int,
    frame_sr: float,
) -> tuple[float, float]:
    """
    Extract delay and confidence from a feature-domain correlation.

    Works in the feature domain where sample rate = sr / hop_length
    (typically ~93.75 Hz for 48kHz / 512).

    Args:
        corr: Correlation result from irfft (length n_fft).
        n_fft: FFT size used.
        max_delay_frames: Maximum search range in feature frames.
        frame_sr: Feature-domain sample rate (sr / hop_length).

    Returns:
        (delay_ms, confidence).
    """
    # Build search region: [negative lags ... 0 ... positive lags]
    pos_part = corr[:max_delay_frames + 1]
    neg_part = corr[n_fft - max_delay_frames:]
    search_region = torch.cat([neg_part, pos_part])

    abs_search = torch.abs(search_region)
    k = torch.argmax(abs_search).item()
    lag_frames = float(k - max_delay_frames)

    delay_ms = lag_frames / frame_sr * 1000.0

    # Confidence: prominence + uniqueness
    peak_val = abs_search[k].item()
    median_val = torch.median(abs_search).item()
    neighbor = max(1, len(abs_search) // 100)
    mask = torch.ones_like(abs_search, dtype=torch.bool)
    mask[max(0, k - neighbor):min(len(abs_search), k + neighbor + 1)] = False
    second_best = abs_search[mask].max().item() if mask.any() else median_val

    prominence = peak_val / (median_val + 1e-9)
    uniqueness = peak_val / (second_best + 1e-9)
    confidence = min(100.0, max(0.0, (prominence * 5.0 + uniqueness * 8.0) / 2.0))

    return delay_ms, confidence
