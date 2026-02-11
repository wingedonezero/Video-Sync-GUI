# vsg_core/analysis/correlation/decode.py
"""
Audio decoding and stream selection for correlation analysis.

Pure functions for selecting audio streams via mkvmerge probe and
decoding them to in-memory float32 arrays via ffmpeg.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner

# --- Language Normalization (private to decode) ---

_LANG2TO3: dict[str, str] = {
    "en": "eng",
    "ja": "jpn",
    "jp": "jpn",
    "zh": "zho",
    "cn": "zho",
    "es": "spa",
    "de": "deu",
    "fr": "fra",
    "it": "ita",
    "pt": "por",
    "ru": "rus",
    "ko": "kor",
    "ar": "ara",
    "tr": "tur",
    "pl": "pol",
    "nl": "nld",
    "sv": "swe",
    "no": "nor",
    "fi": "fin",
    "da": "dan",
    "cs": "ces",
    "sk": "slk",
    "sl": "slv",
    "hu": "hun",
    "el": "ell",
    "he": "heb",
    "id": "ind",
    "vi": "vie",
    "th": "tha",
    "hi": "hin",
    "ur": "urd",
    "fa": "fas",
    "uk": "ukr",
    "ro": "ron",
    "bg": "bul",
    "sr": "srp",
    "hr": "hrv",
    "ms": "msa",
    "bn": "ben",
    "ta": "tam",
    "te": "tel",
}


def normalize_lang(lang: str | None) -> str | None:
    """Normalize a 2-letter language code to 3-letter ISO 639-2."""
    if not lang:
        return None
    s = lang.strip().lower()
    if not s or s == "und":
        return None
    return _LANG2TO3.get(s, s) if len(s) == 2 else s


# --- Stream Selection ---


def get_audio_stream_info(
    mkv_path: str,
    lang: str | None,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> tuple[int | None, int | None]:
    """
    Find the best audio stream and return its 0-based index and mkvmerge track ID.

    Args:
        mkv_path: Path to the MKV file.
        lang: Optional 3-letter language code (already normalized).
        runner: CommandRunner for executing mkvmerge.
        tool_paths: Tool path dictionary.

    Returns:
        (stream_index, track_id) or (None, None) if no audio found.
    """
    out = runner.run(["mkvmerge", "-J", str(mkv_path)], tool_paths)
    if not out or not isinstance(out, str):
        return None, None
    try:
        info = json.loads(out)
        audio_tracks = [t for t in info.get("tracks", []) if t.get("type") == "audio"]
        if not audio_tracks:
            return None, None
        if lang:
            for i, t in enumerate(audio_tracks):
                props = t.get("properties", {})
                if (props.get("language") or "").strip().lower() == lang:
                    return i, t.get("id")
        # Fallback to the first audio track
        first_track = audio_tracks[0]
        return 0, first_track.get("id")
    except (json.JSONDecodeError, IndexError):
        return None, None


# --- Audio Decoding ---

# Default sample rate for all correlation work
DEFAULT_SR = 48000


def decode_audio(
    file_path: str,
    stream_index: int,
    sr: int,
    use_soxr: bool,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> np.ndarray:
    """
    Decode one audio stream to a mono float32 NumPy array.

    Args:
        file_path: Path to the media file.
        stream_index: 0-based audio stream index.
        sr: Target sample rate in Hz.
        use_soxr: Use high-quality soxr resampler.
        runner: CommandRunner for executing ffmpeg.
        tool_paths: Tool path dictionary.

    Returns:
        1-D float32 NumPy array of audio samples.

    Raises:
        RuntimeError: If ffmpeg decode fails.
    """
    cmd: list[str] = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(file_path),
        "-map",
        f"0:a:{stream_index}",
    ]

    if use_soxr:
        cmd.extend(["-resampler", "soxr"])

    cmd.extend(["-ac", "1", "-ar", str(sr), "-f", "f32le", "-"])

    pcm_bytes = runner.run(cmd, tool_paths, is_binary=True)
    if not pcm_bytes or not isinstance(pcm_bytes, bytes):
        raise RuntimeError(f"ffmpeg decode failed for {Path(file_path).name}")

    log = getattr(runner, "_log_message", None)

    if log:
        log(f"[DECODE RAW] Received {len(pcm_bytes)} bytes for {Path(file_path).name}")
        # Show first 100 bytes as hex to detect text/garbage
        first_bytes = pcm_bytes[:100]
        hex_dump = " ".join(f"{b:02x}" for b in first_bytes)
        log(f"[DECODE RAW] First 100 bytes (hex): {hex_dump}")
        # Check if first bytes look like ASCII text (stderr mixed in)
        try:
            text_check = first_bytes[:50].decode("ascii", errors="strict")
            log(f"[DECODE RAW] WARNING: First bytes decode as ASCII: {text_check!r}")
        except UnicodeDecodeError:
            pass  # Good - binary data as expected

    # Ensure buffer size is a multiple of element size (4 bytes for float32)
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
    # buffer is garbage collected. Using .copy() ensures we own the memory.
    return np.frombuffer(pcm_bytes, dtype=np.float32).copy()
