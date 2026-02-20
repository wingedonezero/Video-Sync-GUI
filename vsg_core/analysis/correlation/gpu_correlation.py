# vsg_core/analysis/correlation/gpu_correlation.py
"""
GPU-accelerated correlation utilities shared across methods.

Provides peak extraction and confidence scoring on torch tensors.
These are the GPU equivalents of the numpy-based functions in
confidence.py and the peak extraction logic in each method.
"""

from __future__ import annotations

import torch


def bandpass_mask(
    n_fft: int,
    sr: int,
    lo_hz: float = 300.0,
    hi_hz: float = 6000.0,
    device: torch.device | str | None = None,
) -> torch.Tensor:
    """
    Create a frequency-domain bandpass mask for rfft output.

    Zeroes out bins below lo_hz and above hi_hz to remove frequencies
    with ambiguous phase that cause false peaks in phase-only methods
    (GCC-PHAT, GCC-SCOT, GCC-Whiten).

    Args:
        n_fft: FFT size.
        sr: Sample rate in Hz.
        lo_hz: Lower cutoff frequency (default 300 Hz).
        hi_hz: Upper cutoff frequency (default 6000 Hz).
        device: Torch device for the output tensor.

    Returns:
        Boolean tensor of shape (n_fft // 2 + 1,) — True for bins to keep.
    """
    freqs = torch.fft.rfftfreq(n_fft, 1.0 / sr, device=device)
    return (freqs >= lo_hz) & (freqs <= hi_hz)


def extract_peak(
    corr: torch.Tensor,
    n_fft: int,
    sr: int,
    peak_fit: bool = False,
) -> tuple[float, int]:
    """
    Extract delay and peak index from a waveform-domain correlation.

    Searches the full lag range (no max_delay restriction) for the
    strongest peak. Confidence is computed separately by each method
    using the returned peak_index.

    Args:
        corr: Correlation result from irfft (length n_fft).
        n_fft: FFT size used.
        sr: Sample rate in Hz.
        peak_fit: If True, apply parabolic sub-sample interpolation.

    Returns:
        (delay_ms, peak_index) — delay in ms (raw float) and the
        peak index in the correlation array for confidence scoring.
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


def psr_confidence(
    corr: torch.Tensor,
    peak_idx: int,
    exclude_radius: int = 100,
) -> float:
    """
    Peak-to-Sidelobe Ratio (PSR) confidence for phase-only methods.

    Standard metric from radar/sonar/tracking literature for measuring
    peak reliability in white-noise-like correlation outputs (exactly
    what GCC-PHAT, GCC-SCOT, and GCC-Whiten produce).

    PSR = (peak - mean_sidelobes) / std_sidelobes

    Empirically measured noise floor for 10s windows at 48kHz
    (n_fft ~1M): PSR 7.6-9.7 (mean ~8.4).  Real delays produce
    PSR in the hundreds to thousands.

    Mapped to 0-100 scale:
      PSR <= 10  → 0%   (noise floor, unreliable)
      PSR  = 15  → 50%  (borderline)
      PSR >= 20  → 100% (confident)

    Args:
        corr: Correlation output from irfft.
        peak_idx: Index of the peak in the correlation array.
        exclude_radius: Number of samples around peak to exclude from
            sidelobe statistics (the "mainlobe exclusion zone").
    """
    abs_corr = torch.abs(corr)
    peak_value = abs_corr[peak_idx].item()
    n = len(abs_corr)

    # Exclude mainlobe region around the peak
    mask = torch.ones(n, dtype=torch.bool, device=abs_corr.device)
    lo = max(0, peak_idx - exclude_radius)
    hi = min(n, peak_idx + exclude_radius + 1)
    mask[lo:hi] = False

    sidelobes = abs_corr[mask]
    if len(sidelobes) < 10:
        return 0.0

    mean_sl = sidelobes.mean().item()
    std_sl = sidelobes.std().item()

    if std_sl < 1e-12:
        return 0.0

    psr = (peak_value - mean_sl) / std_sl

    # Map PSR to 0-100 confidence scale
    # Noise floor is PSR ~8-10 for 10s windows at 48kHz.
    # PSR <= 10: noise (0%), PSR 15: borderline (50%), PSR >= 20: confident (100%)
    if psr <= 10.0:
        return 0.0
    if psr >= 20.0:
        return 100.0
    # Linear interpolation between 10 and 20
    return (psr - 10.0) / 10.0 * 100.0


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
