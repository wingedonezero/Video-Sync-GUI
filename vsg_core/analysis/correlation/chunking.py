# vsg_core/analysis/correlation/chunking.py
"""
Chunk extraction for correlation analysis.

Computes scan positions and extracts matched ref/target audio
chunk pairs for per-chunk correlation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """A matched pair of ref/target audio chunks at a scan position."""

    index: int  # 1-based chunk number
    start_s: float  # Start time in seconds
    ref: np.ndarray  # Reference audio samples (float32)
    tgt: np.ndarray  # Target audio samples (float32)


def extract_chunks(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sr: int,
    chunk_count: int,
    chunk_duration_s: float,
    start_pct: float,
    end_pct: float,
) -> list[AudioChunk]:
    """
    Extract matched ref/target chunk pairs at evenly spaced scan positions.

    Distributes chunks evenly across the scannable region of the file
    (between start_pct and end_pct of the total duration).

    Args:
        ref_pcm: Full reference audio (mono float32).
        tgt_pcm: Full target audio (mono float32).
        sr: Sample rate in Hz.
        chunk_count: Number of chunks to extract.
        chunk_duration_s: Duration of each chunk in seconds.
        start_pct: Start of scan region as percentage (0-100).
        end_pct: End of scan region as percentage (0-100).

    Returns:
        List of AudioChunk with independent array copies.
    """
    duration_s = len(ref_pcm) / float(sr)

    # Validate scan range
    if not 0.0 <= start_pct < end_pct <= 100.0:
        start_pct, end_pct = 5.0, 95.0

    scan_start_s = duration_s * (start_pct / 100.0)
    scan_end_s = duration_s * (end_pct / 100.0)

    # Total scannable range, accounting for final chunk's length
    scan_range = max(0.0, (scan_end_s - scan_start_s) - chunk_duration_s)

    starts = [
        scan_start_s + (scan_range / max(1, chunk_count - 1) * i)
        for i in range(chunk_count)
    ]

    chunk_samples = int(round(chunk_duration_s * sr))
    chunks: list[AudioChunk] = []

    for i, t0 in enumerate(starts, 1):
        start_sample = int(round(t0 * sr))
        end_sample = start_sample + chunk_samples
        if end_sample > len(ref_pcm) or end_sample > len(tgt_pcm):
            continue

        # CRITICAL: Use .copy() to create independent arrays, not views.
        # numpy's pocketfft can segfault on array views under certain
        # conditions (memory pressure, specific sizes, threading).
        chunks.append(
            AudioChunk(
                index=i,
                start_s=t0,
                ref=ref_pcm[start_sample:end_sample].copy(),
                tgt=tgt_pcm[start_sample:end_sample].copy(),
            )
        )

    return chunks
