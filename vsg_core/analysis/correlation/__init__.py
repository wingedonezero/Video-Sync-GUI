# vsg_core/analysis/correlation/__init__.py
"""
Audio correlation subpackage.

Provides audio decoding, filtering, chunk extraction, and pluggable
correlation methods for delay detection.
"""

from __future__ import annotations

# Import methods subpackage to trigger registration of all built-in plugins.
from . import methods as _methods  # pyright: ignore[reportUnusedImport]
from .chunking import AudioChunk, extract_chunks
from .decode import DEFAULT_SR, decode_audio, get_audio_stream_info, normalize_lang
from .filtering import apply_bandpass, apply_lowpass
from .registry import (
    CorrelationMethod,
    get_method,
    list_methods,
    register,
)
from .run import run_audio_correlation

__all__ = [
    "DEFAULT_SR",
    "AudioChunk",
    "CorrelationMethod",
    "apply_bandpass",
    "apply_lowpass",
    "decode_audio",
    "extract_chunks",
    "get_audio_stream_info",
    "get_method",
    "list_methods",
    "normalize_lang",
    "register",
    "run_audio_correlation",
]
