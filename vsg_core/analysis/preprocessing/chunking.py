# vsg_core/analysis/preprocessing/chunking.py
"""
Audio chunking utilities for correlation analysis.

Provides functions to extract chunks from audio for analysis,
including configurable chunk count, duration, and scan range.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ChunkConfig:
    """Configuration for chunk extraction."""

    chunk_count: int = 10
    chunk_duration: float = 15.0  # seconds
    start_percentage: float = 5.0  # start scan at 5% of duration
    end_percentage: float = 95.0  # end scan at 95% of duration


@dataclass
class AudioChunk:
    """A single audio chunk for correlation."""

    index: int  # 1-based chunk index
    start_time: float  # Start time in seconds
    ref_audio: np.ndarray  # Reference audio samples
    target_audio: np.ndarray  # Target audio samples


def get_chunk_config(config: dict) -> ChunkConfig:
    """
    Extract chunk configuration from settings dictionary.

    Args:
        config: Configuration dictionary

    Returns:
        ChunkConfig with extracted settings
    """
    start_pct = config.get("scan_start_percentage", 5.0)
    end_pct = config.get("scan_end_percentage", 95.0)

    # Sanity check
    if not 0.0 <= start_pct < end_pct <= 100.0:
        start_pct, end_pct = 5.0, 95.0

    return ChunkConfig(
        chunk_count=int(config.get("scan_chunk_count", 10)),
        chunk_duration=float(config.get("scan_chunk_duration", 15.0)),
        start_percentage=start_pct,
        end_percentage=end_pct,
    )


def extract_chunks(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sample_rate: int,
    config: ChunkConfig,
) -> list[AudioChunk]:
    """
    Extract chunks from reference and target audio.

    Args:
        ref_pcm: Reference audio as float32 numpy array
        tgt_pcm: Target audio as float32 numpy array
        sample_rate: Sample rate in Hz
        config: Chunk extraction configuration

    Returns:
        List of AudioChunk objects
    """
    duration_s = len(ref_pcm) / float(sample_rate)
    chunk_samples = int(round(config.chunk_duration * sample_rate))

    scan_start_s = duration_s * (config.start_percentage / 100.0)
    scan_end_s = duration_s * (config.end_percentage / 100.0)

    # Total duration of the scannable area, accounting for the final chunk's length
    scan_range = max(0.0, (scan_end_s - scan_start_s) - config.chunk_duration)
    start_offset = scan_start_s

    # Calculate start times for each chunk
    starts = [
        start_offset + (scan_range / max(1, config.chunk_count - 1) * i)
        for i in range(config.chunk_count)
    ]

    chunks = []
    for i, t0 in enumerate(starts, 1):
        start_sample = int(round(t0 * sample_rate))
        end_sample = start_sample + chunk_samples

        if end_sample > len(ref_pcm) or end_sample > len(tgt_pcm):
            continue

        # CRITICAL: Use .copy() to create independent arrays, not views.
        # numpy's pocketfft can segfault on array views under certain conditions
        # (memory pressure, specific sizes, threading). Explicit copies are safer.
        ref_chunk = ref_pcm[start_sample:end_sample].copy()
        tgt_chunk = tgt_pcm[start_sample:end_sample].copy()

        chunks.append(
            AudioChunk(
                index=i,
                start_time=t0,
                ref_audio=ref_chunk,
                target_audio=tgt_chunk,
            )
        )

    return chunks
