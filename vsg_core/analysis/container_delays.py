# vsg_core/analysis/container_delays.py
"""
Container delay extraction and processing.

Pure functions for reading and processing container-level delays from media files.
Container delays are per-track timing offsets stored in the container format.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vsg_core.extraction.tracks import get_stream_info_with_delays

from .types import ContainerDelayInfo

if TYPE_CHECKING:
    from collections.abc import Callable

    from vsg_core.io.runner import CommandRunner


def get_container_delay_info(
    source_file: str,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
    log: Callable[[str], None],
) -> ContainerDelayInfo | None:
    """
    Extract container delay information from a media file.

    Reads container-level delays and converts audio track delays to be
    relative to the video track (since video defines the timeline).

    Args:
        source_file: Path to media file
        runner: CommandRunner for executing mkvmerge
        tool_paths: Dict of tool paths
        log: Logging function for messages

    Returns:
        ContainerDelayInfo with video and audio delays, or None if extraction fails
    """
    stream_info = get_stream_info_with_delays(source_file, runner, tool_paths)
    if not stream_info:
        log(f"[WARN] Could not extract stream info from {source_file}")
        return None

    tracks = stream_info.get("tracks", [])

    # Extract all container delays
    container_delays = {}
    for track in tracks:
        tid = track.get("id")
        delay_ms = track.get("container_delay_ms", 0)
        container_delays[tid] = delay_ms

        track_type = track.get("type")
        if delay_ms != 0 and track_type in ["video", "audio"]:
            log(
                f"[Container Delay] {track_type.capitalize()} track {tid} has container delay: {delay_ms:+.1f}ms"
            )

    # Find video track delay (video defines the timeline)
    video_tracks = [t for t in tracks if t.get("type") == "video"]
    video_delay_ms = 0.0
    if video_tracks:
        video_track_id = video_tracks[0].get("id")
        video_delay_ms = container_delays.get(video_track_id, 0)

    # Convert audio track delays to be relative to video
    # This ensures they're stored correctly for later use
    audio_delays_relative = {}
    audio_tracks = [t for t in tracks if t.get("type") == "audio"]

    for track in audio_tracks:
        tid = track.get("id")
        absolute_delay = container_delays.get(tid, 0)
        relative_delay = absolute_delay - video_delay_ms
        audio_delays_relative[tid] = relative_delay

    return ContainerDelayInfo(
        video_delay_ms=video_delay_ms,
        audio_delays_ms=audio_delays_relative,
        selected_audio_delay_ms=0.0,  # Will be set by caller based on track selection
    )


def calculate_delay_chain(
    correlation_delay_ms: int,
    correlation_delay_raw: float,
    container_delay_ms: float,
    log: Callable[[str], None],
    source_key: str,
) -> tuple[int, float]:
    """
    Calculate final delay by combining correlation and container delays.

    Args:
        correlation_delay_ms: Rounded correlation delay
        correlation_delay_raw: Raw (unrounded) correlation delay
        container_delay_ms: Container delay for the audio track
        log: Logging function for messages
        source_key: Source identifier for logging

    Returns:
        Tuple of (final_rounded_ms, final_raw_ms)
    """
    final_delay_ms = round(correlation_delay_ms + container_delay_ms)
    final_delay_raw = correlation_delay_raw + container_delay_ms

    # Log the delay calculation chain for transparency
    log(f"[Delay Calculation] {source_key} delay chain:")
    log(
        f"[Delay Calculation]   Correlation delay: {correlation_delay_raw:+.3f}ms (raw) → {correlation_delay_ms:+d}ms (rounded)"
    )
    if container_delay_ms != 0:
        log(f"[Delay Calculation]   + Container delay:  {container_delay_ms:+.3f}ms")
        log(
            f"[Delay Calculation]   = Final delay:      {final_delay_raw:+.3f}ms (raw) → {final_delay_ms:+d}ms (rounded)"
        )

    return final_delay_ms, final_delay_raw


def find_actual_correlation_track_delay(
    container_info: ContainerDelayInfo,
    stream_info: dict[str, Any] | None,
    correlation_ref_track: int | None,
    ref_lang: str | None,
    default_delay_ms: float,
    log: Callable[[str], None],
) -> float:
    """
    Determine which Source 1 audio track was actually used for correlation.

    This is needed when Source 1 has multiple audio tracks with different
    container delays. We need to apply the correct delay for the track
    that was actually used in correlation.

    Args:
        container_info: Container delay information
        stream_info: Stream info dict from mkvmerge, or None
        correlation_ref_track: Explicit track index used, or None
        ref_lang: Language used for selection, or None
        default_delay_ms: Default delay to use if no override found
        log: Logging function for messages

    Returns:
        Container delay for the track that was actually used
    """
    if not stream_info:
        return default_delay_ms

    audio_tracks = [
        t for t in stream_info.get("tracks", []) if t.get("type") == "audio"
    ]

    # Priority 1: Explicit per-job track selection
    if correlation_ref_track is not None and 0 <= correlation_ref_track < len(
        audio_tracks
    ):
        ref_track_id = audio_tracks[correlation_ref_track].get("id")
        track_delay = container_info.audio_delays_ms.get(ref_track_id, 0)
        if track_delay != default_delay_ms:
            log(
                f"[Container Delay Override] Using Source 1 audio index {correlation_ref_track} (track ID {ref_track_id}) delay: "
                f"{track_delay:+.3f}ms (global reference was {default_delay_ms:+.3f}ms)"
            )
            return track_delay

    # Priority 2: Language matching fallback
    elif ref_lang:
        for i, track in enumerate(audio_tracks):
            track_lang = (
                (track.get("properties", {}).get("language", "") or "").strip().lower()
            )
            if track_lang == ref_lang.strip().lower():
                ref_track_id = track.get("id")
                track_delay = container_info.audio_delays_ms.get(ref_track_id, 0)
                if track_delay != default_delay_ms:
                    log(
                        f"[Container Delay Override] Using Source 1 audio index {i} (track ID {ref_track_id}, lang={ref_lang}) delay: "
                        f"{track_delay:+.3f}ms (global reference was {default_delay_ms:+.3f}ms)"
                    )
                    return track_delay
                break

    return default_delay_ms
