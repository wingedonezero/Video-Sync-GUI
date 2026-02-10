# vsg_core/analysis/correlation/filtering.py
"""
Audio pre-processing filters for correlation analysis.

Pure functions that apply frequency-domain filtering to isolate
useful signal content before correlation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.signal import butter, firwin, lfilter

if TYPE_CHECKING:
    from collections.abc import Callable


def apply_bandpass(
    waveform: np.ndarray,
    sr: int,
    lowcut: float,
    highcut: float,
    order: int,
    log: Callable[[str], None] | None = None,
) -> np.ndarray:
    """
    Apply a Butterworth band-pass filter to isolate dialogue frequencies.

    Args:
        waveform: Input audio samples (float32).
        sr: Sample rate in Hz.
        lowcut: Lower cutoff frequency in Hz.
        highcut: Upper cutoff frequency in Hz.
        order: Filter order.
        log: Optional logging callback.

    Returns:
        Filtered waveform (float32).
    """
    try:
        nyquist = 0.5 * sr
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = butter(order, [low, high], btype="band")  # type: ignore[misc]
        return np.asarray(lfilter(b, a, waveform), dtype=np.float32)
    except Exception as e:
        if log:
            log(
                f"[FILTER WARNING] Band-pass filter failed ({e}), "
                f"using unfiltered waveform"
            )
        return waveform


def apply_lowpass(
    waveform: np.ndarray,
    sr: int,
    cutoff_hz: int,
    num_taps: int,
    log: Callable[[str], None] | None = None,
) -> np.ndarray:
    """
    Apply a simple FIR low-pass filter.

    Args:
        waveform: Input audio samples (float32).
        sr: Sample rate in Hz.
        cutoff_hz: Cutoff frequency in Hz. If <= 0, returns input unchanged.
        num_taps: Number of FIR filter taps.
        log: Optional logging callback.

    Returns:
        Filtered waveform (float32).
    """
    if cutoff_hz <= 0:
        return waveform
    try:
        nyquist = sr / 2
        hz = min(cutoff_hz, nyquist - 1)
        h = firwin(num_taps, hz / nyquist)
        return np.asarray(lfilter(h, 1.0, waveform), dtype=np.float32)
    except Exception as e:
        if log:
            log(
                f"[FILTER WARNING] Low-pass filter failed ({e}), "
                f"using unfiltered waveform"
            )
        return waveform
