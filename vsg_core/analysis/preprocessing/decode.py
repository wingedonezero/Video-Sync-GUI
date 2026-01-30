# vsg_core/analysis/preprocessing/decode.py
"""
Audio decoding utilities for correlation analysis.

Provides functions to decode audio from video files to memory
using ffmpeg, with optional high-quality resampling via soxr.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner


def decode_to_memory(
    file_path: str,
    audio_index: int,
    sample_rate: int,
    use_soxr: bool,
    runner: CommandRunner,
    tool_paths: dict[str, str],
) -> np.ndarray:
    """
    Decode one audio stream to a mono float32 NumPy array.

    Args:
        file_path: Path to the video/audio file
        audio_index: 0-based audio stream index
        sample_rate: Target sample rate in Hz
        use_soxr: Whether to use soxr resampler for higher quality
        runner: CommandRunner for executing ffmpeg
        tool_paths: Paths to external tools

    Returns:
        Mono float32 numpy array of audio samples

    Raises:
        RuntimeError: If ffmpeg decode fails
    """
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(file_path),
        "-map",
        f"0:a:{audio_index}",
    ]

    if use_soxr:
        cmd.extend(["-resampler", "soxr"])

    cmd.extend(["-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-"])

    pcm_bytes = runner.run(cmd, tool_paths, is_binary=True)
    if not pcm_bytes or not isinstance(pcm_bytes, bytes):
        raise RuntimeError(f"ffmpeg decode failed for {Path(file_path).name}")

    # DEBUG: Log raw bytes info to diagnose corruption
    log = getattr(runner, "_log_message", None)
    if log:
        log(f"[DECODE RAW] Received {len(pcm_bytes)} bytes for {Path(file_path).name}")
        # Show first 100 bytes as hex to detect text/garbage
        first_bytes = pcm_bytes[:100]
        hex_dump = " ".join(f"{b:02x}" for b in first_bytes)
        log(f"[DECODE RAW] First 100 bytes (hex): {hex_dump}")
        # Check if first bytes look like ASCII text (would indicate stderr mixed in)
        try:
            text_check = first_bytes[:50].decode("ascii", errors="strict")
            log(f"[DECODE RAW] WARNING: First bytes decode as ASCII: {text_check!r}")
        except UnicodeDecodeError:
            pass  # Good - binary data as expected

    # Ensure buffer size is a multiple of element size (4 bytes for float32)
    # This fixes issues with Opus and other codecs that may produce unaligned output
    element_size = np.dtype(np.float32).itemsize
    aligned_size = (len(pcm_bytes) // element_size) * element_size
    if aligned_size != len(pcm_bytes):
        trimmed_bytes = len(pcm_bytes) - aligned_size
        if log:
            log(
                f"[BUFFER ALIGNMENT] Trimmed {trimmed_bytes} bytes from "
                f"{Path(file_path).name} (likely Opus/other codec)"
            )
        pcm_bytes = pcm_bytes[:aligned_size]

    # CRITICAL: Return a COPY, not a view over the buffer.
    # np.frombuffer() creates a view that can become invalid if the underlying
    # buffer is garbage collected. Using .copy() ensures we own the memory and
    # prevents segfaults in downstream operations like source separation.
    return np.frombuffer(pcm_bytes, dtype=np.float32).copy()
