# vsg_core/analysis/correlation/gpu_backend.py
"""
GPU backend for correlation methods.

Provides device management, torchaudio transform caching, and
cleanup utilities. All methods share this module to avoid
recreating GPU resources per chunk.

Usage:
    from .gpu_backend import get_device, to_torch, cleanup_gpu

    device = get_device()
    ref_gpu = to_torch(ref_chunk, device)
    # ... do GPU work ...
    cleanup_gpu()  # call after job finishes
"""

from __future__ import annotations

import gc
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Module State ────────────────────────────────────────────────────────────

_device: Any = None  # torch.device, lazily initialized
_transform_cache: dict[tuple, Any] = {}


# ── Device Management ──────────────────────────────────────────────────────


def get_device() -> Any:
    """
    Get the torch device to use for correlation.

    Returns CUDA device if available, otherwise CPU.
    Caches the result for the process lifetime.
    """
    global _device
    if _device is not None:
        return _device

    import torch

    if torch.cuda.is_available():
        _device = torch.device("cuda")
        gpu_name = torch.cuda.get_device_name(0)
        logger.info("GPU correlation backend: %s", gpu_name)
    else:
        _device = torch.device("cpu")
        logger.info("GPU correlation backend: CPU fallback (no CUDA)")

    return _device


def to_torch(arr: Any, device: Any | None = None) -> Any:
    """
    Convert a numpy array to a torch tensor on the target device.

    Args:
        arr: numpy float32 array.
        device: torch.device (uses get_device() if None).

    Returns:
        torch.Tensor on the target device.
    """
    import torch

    if device is None:
        device = get_device()
    return torch.from_numpy(arr).to(device)


# ── Transform Caching ──────────────────────────────────────────────────────


def get_spectrogram_transform(
    n_fft: int = 2048,
    hop_length: int = 512,
    power: float = 1.0,
) -> Any:
    """
    Get a cached torchaudio Spectrogram transform.

    Creates on first call with these parameters, reuses afterwards.
    """
    key = ("spectrogram", n_fft, hop_length, power)
    if key not in _transform_cache:
        import torchaudio

        device = get_device()
        _transform_cache[key] = torchaudio.transforms.Spectrogram(
            n_fft=n_fft, hop_length=hop_length, power=power,
        ).to(device)

    return _transform_cache[key]


def get_mel_spectrogram_transform(
    sample_rate: int = 48000,
    n_fft: int = 2048,
    hop_length: int = 512,
    n_mels: int = 64,
    power: float = 2.0,
) -> Any:
    """
    Get a cached torchaudio MelSpectrogram transform.

    Creates on first call with these parameters, reuses afterwards.
    """
    key = ("melspectrogram", sample_rate, n_fft, hop_length, n_mels, power)
    if key not in _transform_cache:
        import torchaudio

        device = get_device()
        _transform_cache[key] = torchaudio.transforms.MelSpectrogram(
            sample_rate=sample_rate,
            n_fft=n_fft,
            hop_length=hop_length,
            n_mels=n_mels,
            power=power,
        ).to(device)

    return _transform_cache[key]


# ── Cleanup ────────────────────────────────────────────────────────────────


def cleanup_gpu() -> None:
    """
    Release all cached GPU resources.

    Call this after each job's correlation finishes to prevent
    GPU memory accumulation across jobs. Works with both CUDA
    and ROCm (HIP) backends — PyTorch maps cuda API to HIP.
    """
    global _transform_cache

    # Clear cached torchaudio transforms (hold GPU memory)
    _transform_cache.clear()

    # GC first so Python drops tensor references before we free GPU memory
    gc.collect()

    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            # Reset peak memory tracking for monitoring
            torch.cuda.reset_peak_memory_stats()
    except ImportError:
        pass

    gc.collect()
