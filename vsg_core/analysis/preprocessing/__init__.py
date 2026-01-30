# vsg_core/analysis/preprocessing/__init__.py
"""
Audio preprocessing module for correlation analysis.

This module provides utilities for decoding, filtering, and chunking
audio in preparation for correlation analysis.

Usage:
    from vsg_core.analysis.preprocessing import (
        decode_to_memory,
        apply_filter,
        extract_chunks,
        get_audio_stream_info,
    )

    # Decode audio
    ref_pcm = decode_to_memory(ref_file, 0, 48000, False, runner, tool_paths)

    # Apply filtering
    ref_pcm = apply_filter(ref_pcm, 48000, config, log)

    # Extract chunks for correlation
    chunks = extract_chunks(ref_pcm, tgt_pcm, 48000, get_chunk_config(config))
"""

from __future__ import annotations

from .chunking import AudioChunk, ChunkConfig, extract_chunks, get_chunk_config
from .decode import decode_to_memory
from .filters import apply_bandpass, apply_filter, apply_lowpass
from .stream_info import (
    get_audio_stream_info,
    get_audio_tracks_info,
    normalize_lang,
)

__all__ = [
    # Decoding
    "decode_to_memory",
    # Filtering
    "apply_filter",
    "apply_bandpass",
    "apply_lowpass",
    # Stream info
    "get_audio_stream_info",
    "get_audio_tracks_info",
    "normalize_lang",
    # Chunking
    "extract_chunks",
    "get_chunk_config",
    "AudioChunk",
    "ChunkConfig",
]
