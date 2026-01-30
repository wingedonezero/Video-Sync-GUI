# vsg_core/analysis/track_selection.py
"""
Audio track selection for correlation analysis.

Handles selecting which audio tracks to use for correlation based on:
- Explicit track index (highest priority)
- Language matching
- Fallback to first track
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SelectedTrack:
    """Result of track selection."""

    track_id: int | None
    track_index: int | None
    selection_method: str  # "explicit", "language", "first"
    track_info: dict[str, Any] | None = None


def format_track_details(track: dict[str, Any], index: int) -> str:
    """
    Format audio track details for logging.

    Args:
        track: Track dictionary from mkvmerge JSON
        index: 0-based audio track index

    Returns:
        Formatted string like "Track 0: Japanese (jpn), FLAC 2.0, 'Commentary'"
    """
    props = track.get("properties", {})

    # Language
    lang = props.get("language", "und")

    # Codec - extract readable name from codec_id
    codec_id = props.get("codec_id", "unknown")
    codec_map = {
        "A_FLAC": "FLAC",
        "A_AAC": "AAC",
        "A_AC3": "AC3",
        "A_EAC3": "E-AC3",
        "A_DTS": "DTS",
        "A_TRUEHD": "TrueHD",
        "A_OPUS": "Opus",
        "A_VORBIS": "Vorbis",
        "A_PCM": "PCM",
        "A_MP3": "MP3",
    }
    # Try exact match first, then prefix match
    codec_name = codec_map.get(codec_id)
    if not codec_name:
        for prefix, name in codec_map.items():
            if codec_id.startswith(prefix):
                codec_name = name
                break
    if not codec_name:
        codec_name = codec_id.replace("A_", "")

    # Channels
    channels = props.get("audio_channels", 2)
    channel_str = {1: "Mono", 2: "2.0", 6: "5.1", 8: "7.1"}.get(
        channels, f"{channels}ch"
    )

    # Track name (if set)
    track_name = props.get("track_name", "")

    # Build the string
    parts = [f"Track {index}: {lang}"]
    parts.append(f"{codec_name} {channel_str}")
    if track_name:
        parts.append(f"'{track_name}'")

    return ", ".join(parts)


def select_audio_track(
    stream_info: dict[str, Any] | None,
    explicit_index: int | None = None,
    language: str | None = None,
) -> SelectedTrack:
    """
    Select an audio track from stream info.

    Priority:
    1. Explicit track index (if valid)
    2. Language match (if specified)
    3. First audio track (fallback)

    Args:
        stream_info: Stream info dict with "tracks" list
        explicit_index: Explicit 0-based audio track index
        language: Language code to match (e.g., "jpn", "eng")

    Returns:
        SelectedTrack with track_id, index, and selection method
    """
    if not stream_info:
        return SelectedTrack(
            track_id=None,
            track_index=None,
            selection_method="none",
            track_info=None,
        )

    audio_tracks = [
        t for t in stream_info.get("tracks", []) if t.get("type") == "audio"
    ]

    if not audio_tracks:
        return SelectedTrack(
            track_id=None,
            track_index=None,
            selection_method="none",
            track_info=None,
        )

    # Priority 1: Explicit track index
    if explicit_index is not None:
        if 0 <= explicit_index < len(audio_tracks):
            track = audio_tracks[explicit_index]
            return SelectedTrack(
                track_id=track.get("id"),
                track_index=explicit_index,
                selection_method="explicit",
                track_info=track,
            )
        # Invalid index - fall through to other methods

    # Priority 2: Language matching
    if language:
        lang_lower = language.strip().lower()
        for idx, track in enumerate(audio_tracks):
            track_lang = (
                (track.get("properties", {}).get("language", "") or "").strip().lower()
            )
            if track_lang == lang_lower:
                return SelectedTrack(
                    track_id=track.get("id"),
                    track_index=idx,
                    selection_method="language",
                    track_info=track,
                )

    # Priority 3: First track (fallback)
    first_track = audio_tracks[0]
    return SelectedTrack(
        track_id=first_track.get("id"),
        track_index=0,
        selection_method="first",
        track_info=first_track,
    )


def get_audio_tracks(stream_info: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Get list of audio tracks from stream info."""
    if not stream_info:
        return []
    return [t for t in stream_info.get("tracks", []) if t.get("type") == "audio"]


def get_video_tracks(stream_info: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Get list of video tracks from stream info."""
    if not stream_info:
        return []
    return [t for t in stream_info.get("tracks", []) if t.get("type") == "video"]
