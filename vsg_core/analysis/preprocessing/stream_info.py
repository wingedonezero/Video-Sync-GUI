# vsg_core/analysis/preprocessing/stream_info.py
"""
Audio stream information utilities.

Provides functions to query audio stream metadata from video files
using mkvmerge, including language detection and track selection.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner


# Language code normalization (2-letter to 3-letter ISO 639)
_LANG2TO3 = {
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
    """
    Normalize language code to 3-letter ISO 639 format.

    Args:
        lang: Language code (2 or 3 letter)

    Returns:
        Normalized 3-letter code, or None if invalid/undefined
    """
    if not lang:
        return None
    s = lang.strip().lower()
    if not s or s == "und":
        return None
    return _LANG2TO3.get(s, s) if len(s) == 2 else s


def get_audio_stream_info(
    mkv_path: str,
    lang: str | None,
    runner: CommandRunner,
    tool_paths: dict[str, str],
) -> tuple[int | None, int | None]:
    """
    Find the best audio stream and return its 0-based index and mkvmerge track ID.

    Args:
        mkv_path: Path to the video file
        lang: Optional language code to match
        runner: CommandRunner for executing mkvmerge
        tool_paths: Paths to external tools

    Returns:
        Tuple of (stream_index, track_id) or (None, None) if not found
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


def get_audio_tracks_info(
    mkv_path: str,
    runner: CommandRunner,
    tool_paths: dict[str, str],
) -> list[dict]:
    """
    Get information about all audio tracks in a file.

    Args:
        mkv_path: Path to the video file
        runner: CommandRunner for executing mkvmerge
        tool_paths: Paths to external tools

    Returns:
        List of track info dictionaries with id, language, codec, channels, etc.
    """
    out = runner.run(["mkvmerge", "-J", str(mkv_path)], tool_paths)
    if not out or not isinstance(out, str):
        return []

    try:
        info = json.loads(out)
        return [t for t in info.get("tracks", []) if t.get("type") == "audio"]
    except (json.JSONDecodeError, IndexError):
        return []
