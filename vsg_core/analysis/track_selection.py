# vsg_core/analysis/track_selection.py
"""
Audio track selection logic for correlation analysis.

Pure functions for selecting which audio tracks to use for correlation,
with support for language matching and explicit track index selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .types import TrackSelection

if TYPE_CHECKING:
    from collections.abc import Callable


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
    # Common codec_id mappings
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
    audio_tracks: list[dict[str, Any]],
    language: str | None,
    explicit_index: int | None,
    log: Callable[[str], None],
    source_label: str,
) -> TrackSelection | None:
    """
    Select an audio track for correlation analysis.

    Priority order:
    1. Explicit track index (if provided)
    2. Language matching (if language specified)
    3. First audio track (fallback)

    Args:
        audio_tracks: List of audio track dicts from mkvmerge JSON
        language: Preferred language code (e.g., "jpn", "eng"), or None
        explicit_index: Explicit 0-based track index to use, or None
        log: Logging function for messages
        source_label: Label for this source (e.g., "Source 1", "Source 2")

    Returns:
        TrackSelection with selected track info, or None if no audio tracks
    """
    if not audio_tracks:
        log(f"[WARN] No audio tracks found in {source_label}.")
        return None

    selected_track = None
    selected_index: int = 0
    selection_reason: str = "first"

    # Priority 1: Explicit track index
    if explicit_index is not None:
        if 0 <= explicit_index < len(audio_tracks):
            selected_track = audio_tracks[explicit_index]
            selected_index = explicit_index
            selection_reason = "explicit"
            log(
                f"[{source_label}] Selected (explicit): {format_track_details(selected_track, explicit_index)}"
            )
        else:
            log(
                f"[WARN] Invalid track index {explicit_index}, falling back to first track"
            )
            selected_track = audio_tracks[0]
            selected_index = 0
            selection_reason = "first"
            log(
                f"[{source_label}] Selected (fallback): {format_track_details(selected_track, 0)}"
            )

    # Priority 2: Language matching
    elif language:
        for idx, track in enumerate(audio_tracks):
            track_lang = (
                (track.get("properties", {}).get("language", "") or "").strip().lower()
            )
            if track_lang == language.strip().lower():
                selected_track = track
                selected_index = idx
                selection_reason = "language"
                log(
                    f"[{source_label}] Selected (lang={language}): {format_track_details(track, idx)}"
                )
                break

    # Priority 3: First track fallback
    if selected_track is None:
        selected_track = audio_tracks[0]
        selected_index = 0
        selection_reason = "first"
        log(
            f"[{source_label}] Selected (first track): {format_track_details(selected_track, 0)}"
        )

    # Extract track information
    track_id = selected_track.get("id")
    if track_id is None:
        log(f"[WARN] Selected audio track has no ID in {source_label}. Cannot proceed.")
        return None

    props = selected_track.get("properties", {})
    lang_code = props.get("language", "und")
    codec_id = props.get("codec_id", "unknown")
    channels = props.get("audio_channels", 2)

    # Extract readable codec name
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
    codec_name = codec_map.get(codec_id)
    if not codec_name:
        for prefix, name in codec_map.items():
            if codec_id.startswith(prefix):
                codec_name = name
                break
    if not codec_name:
        codec_name = codec_id.replace("A_", "")

    return TrackSelection(
        track_id=track_id,
        track_index=selected_index,
        selected_by=selection_reason,
        language=lang_code,
        codec=codec_name,
        channels=channels,
        formatted_name=format_track_details(selected_track, selected_index),
    )
