# vsg_core/analysis/correlation/__init__.py
"""
Audio correlation subpackage.

Provides audio decoding, filtering, and pluggable correlation methods
for delay detection.
"""

from __future__ import annotations

# Import methods subpackage to trigger registration of all built-in plugins.
from . import methods as _methods  # pyright: ignore[reportUnusedImport]
from .decode import DEFAULT_SR, decode_audio, get_audio_stream_info, normalize_lang
from .filtering import apply_bandpass, apply_lowpass
from .gpu_backend import cleanup_gpu
from .registry import (
    CorrelationMethod,
    get_method,
    list_methods,
    register,
)

__all__ = [
    "DEFAULT_SR",
    "CorrelationMethod",
    "apply_bandpass",
    "apply_lowpass",
    "cleanup_gpu",
    "decode_audio",
    "get_audio_stream_info",
    "get_method",
    "list_methods",
    "normalize_lang",
    "register",
]
