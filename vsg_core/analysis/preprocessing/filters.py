# vsg_core/analysis/preprocessing/filters.py
"""
Audio filtering utilities for correlation analysis.

Provides bandpass and lowpass filters to isolate relevant frequency
ranges for improved correlation accuracy.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy.signal import butter, firwin, lfilter


def apply_bandpass(
    waveform: np.ndarray,
    sample_rate: int,
    lowcut: float,
    highcut: float,
    order: int = 5,
    log: Callable[[str], None] | None = None,
) -> np.ndarray:
    """
    Apply a Butterworth band-pass filter to isolate dialogue frequencies.

    Args:
        waveform: Input audio as float32 numpy array
        sample_rate: Sample rate in Hz
        lowcut: Low cutoff frequency in Hz
        highcut: High cutoff frequency in Hz
        order: Filter order (default: 5)
        log: Optional logging callback

    Returns:
        Filtered audio as float32 numpy array
    """
    try:
        nyquist = 0.5 * sample_rate
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = butter(order, [low, high], btype="band")
        return lfilter(b, a, waveform).astype(np.float32)
    except Exception as e:
        if log:
            log(
                f"[FILTER WARNING] Band-pass filter failed ({e}), using unfiltered waveform"
            )
        return waveform


def apply_lowpass(
    waveform: np.ndarray,
    sample_rate: int,
    cutoff_hz: int,
    num_taps: int = 101,
    log: Callable[[str], None] | None = None,
) -> np.ndarray:
    """
    Apply a simple FIR low-pass filter.

    Args:
        waveform: Input audio as float32 numpy array
        sample_rate: Sample rate in Hz
        cutoff_hz: Cutoff frequency in Hz
        num_taps: Number of filter taps (default: 101)
        log: Optional logging callback

    Returns:
        Filtered audio as float32 numpy array
    """
    if cutoff_hz <= 0:
        return waveform
    try:
        nyquist = sample_rate / 2
        hz = min(cutoff_hz, nyquist - 1)
        h = firwin(num_taps, hz / nyquist)
        return lfilter(h, 1.0, waveform).astype(np.float32)
    except Exception as e:
        if log:
            log(
                f"[FILTER WARNING] Low-pass filter failed ({e}), using unfiltered waveform"
            )
        return waveform


def apply_filter(
    waveform: np.ndarray,
    sample_rate: int,
    config: dict,
    log: Callable[[str], None] | None = None,
) -> np.ndarray:
    """
    Apply configured filtering to audio waveform.

    Reads filter settings from config and applies the appropriate filter.

    Args:
        waveform: Input audio as float32 numpy array
        sample_rate: Sample rate in Hz
        config: Configuration dictionary with filter settings
        log: Optional logging callback

    Returns:
        Filtered audio as float32 numpy array
    """
    filtering_method = config.get("filtering_method", "None")

    if filtering_method == "Dialogue Band-Pass Filter":
        if log:
            log("Applying Dialogue Band-Pass filter...")
        lowcut = config.get("filter_bandpass_lowcut_hz", 300.0)
        highcut = config.get("filter_bandpass_highcut_hz", 3400.0)
        order = config.get("filter_bandpass_order", 5)
        return apply_bandpass(waveform, sample_rate, lowcut, highcut, order, log)

    elif filtering_method == "Low-Pass Filter":
        cutoff = int(config.get("audio_bandlimit_hz", 0))
        if cutoff > 0:
            if log:
                log(f"Applying Low-Pass filter at {cutoff} Hz...")
            taps = config.get("filter_lowpass_taps", 101)
            return apply_lowpass(waveform, sample_rate, cutoff, taps, log)

    return waveform
