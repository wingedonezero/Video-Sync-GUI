# vsg_core/analysis/delay_calculation.py
"""
Delay calculation utilities for analysis.

Handles container delay chains, global shift calculation, and
final delay computation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ContainerDelays:
    """Container delays for Source 1 tracks."""

    track_delays: dict[int, float]  # track_id -> delay_ms (relative to video)
    audio_track_id: int | None
    audio_delay: float
    video_delay: float


@dataclass
class FinalDelay:
    """Final calculated delay for a source."""

    rounded_ms: int
    raw_ms: float
    correlation_rounded_ms: int
    correlation_raw_ms: float
    container_delay_ms: float


def extract_container_delays(
    stream_info: dict[str, Any] | None,
    log: Callable[[str], None] | None = None,
) -> dict[int, float]:
    """
    Extract container delays from stream info.

    Args:
        stream_info: Stream info dict with "tracks" list
        log: Optional logging callback

    Returns:
        Dict mapping track_id to container_delay_ms
    """
    if not stream_info:
        return {}

    delays: dict[int, float] = {}

    for track in stream_info.get("tracks", []):
        tid = track.get("id")
        delay_ms = track.get("container_delay_ms", 0)
        if tid is not None:
            delays[tid] = delay_ms

            if delay_ms != 0 and log:
                track_type = track.get("type")
                if track_type in ["video", "audio"]:
                    log(
                        f"[Container Delay] {track_type} track {tid} has "
                        f"container delay: {delay_ms:+.1f}ms"
                    )

    return delays


def convert_to_relative_delays(
    container_delays: dict[int, float],
    stream_info: dict[str, Any] | None,
) -> dict[int, float]:
    """
    Convert absolute container delays to relative (audio relative to video).

    Args:
        container_delays: Dict mapping track_id to absolute delay
        stream_info: Stream info dict with "tracks" list

    Returns:
        Dict mapping track_id to relative delay (for audio tracks only)
    """
    if not stream_info:
        return container_delays

    # Find video track delay
    video_delay = 0.0
    for track in stream_info.get("tracks", []):
        if track.get("type") == "video":
            video_delay = container_delays.get(track.get("id"), 0)
            break

    # Convert audio track delays to relative
    relative_delays = dict(container_delays)
    for track in stream_info.get("tracks", []):
        if track.get("type") == "audio":
            tid = track.get("id")
            if tid is not None:
                absolute_delay = container_delays.get(tid, 0)
                relative_delays[tid] = absolute_delay - video_delay

    return relative_delays


def calculate_final_delay(
    correlation_delay_ms: int,
    correlation_delay_raw: float,
    container_delay_ms: float,
) -> FinalDelay:
    """
    Calculate final delay including container delay chain correction.

    Args:
        correlation_delay_ms: Rounded correlation delay
        correlation_delay_raw: Raw (unrounded) correlation delay
        container_delay_ms: Container delay to add

    Returns:
        FinalDelay with all delay values
    """
    final_rounded = round(correlation_delay_ms + container_delay_ms)
    final_raw = correlation_delay_raw + container_delay_ms

    return FinalDelay(
        rounded_ms=final_rounded,
        raw_ms=final_raw,
        correlation_rounded_ms=correlation_delay_ms,
        correlation_raw_ms=correlation_delay_raw,
        container_delay_ms=container_delay_ms,
    )


def calculate_global_shift(
    source_delays: dict[str, int],
    raw_source_delays: dict[str, float],
    container_delays: dict[int, float] | None,
    stream_info: dict[str, Any] | None,
    layout: list[dict[str, Any]],
    log: Callable[[str], None] | None = None,
) -> tuple[int, float]:
    """
    Calculate global shift needed to eliminate negative delays.

    Args:
        source_delays: Rounded delays per source
        raw_source_delays: Raw delays per source
        container_delays: Source 1 container delays
        stream_info: Source 1 stream info
        layout: Manual layout (to check which sources have audio)
        log: Optional logging callback

    Returns:
        Tuple of (rounded_shift_ms, raw_shift_ms)
    """
    delays_to_consider: list[int] = []
    raw_delays_to_consider: list[float] = []

    if log:
        log(
            "[Global Shift] Identifying delays from sources contributing audio tracks..."
        )

    # Collect delays from sources that have audio in the layout
    for item in layout:
        item_source = item.get("source")
        item_type = item.get("type")
        if item_type == "audio" and item_source in source_delays:
            delay = source_delays[item_source]
            if delay not in delays_to_consider:
                delays_to_consider.append(delay)
                raw_delays_to_consider.append(raw_source_delays[item_source])
                if log:
                    log(f"  - Considering delay from {item_source}: {delay}ms")

    # Also consider Source 1 audio container delays
    if container_delays and stream_info:
        for track in stream_info.get("tracks", []):
            if track.get("type") == "audio":
                tid = track.get("id")
                delay = container_delays.get(tid, 0)
                if delay != 0:
                    delays_to_consider.append(int(delay))

        if any(d != 0 for d in container_delays.values()):
            if log:
                log(
                    "  - Considering Source 1 audio container delays (video delays ignored)."
                )

    # Calculate shift
    most_negative = min(delays_to_consider) if delays_to_consider else 0
    most_negative_raw = min(raw_delays_to_consider) if raw_delays_to_consider else 0.0

    if most_negative < 0:
        return abs(most_negative), abs(most_negative_raw)

    return 0, 0.0


def apply_global_shift(
    source_delays: dict[str, int],
    raw_source_delays: dict[str, float],
    shift_ms: int,
    raw_shift_ms: float,
    log: Callable[[str], None] | None = None,
) -> tuple[dict[str, int], dict[str, float]]:
    """
    Apply global shift to all source delays.

    Args:
        source_delays: Rounded delays per source (modified in place)
        raw_source_delays: Raw delays per source (modified in place)
        shift_ms: Rounded shift to apply
        raw_shift_ms: Raw shift to apply
        log: Optional logging callback

    Returns:
        Tuple of (updated source_delays, updated raw_source_delays)
    """
    if shift_ms == 0:
        return source_delays, raw_source_delays

    if log:
        log(
            f"[Delay] Applying lossless global shift: +{shift_ms}ms (rounded), +{raw_shift_ms:.3f}ms (raw)"
        )
        log("[Delay] Adjusted delays after global shift:")

    for source_key in sorted(source_delays.keys()):
        original = source_delays[source_key]
        original_raw = raw_source_delays[source_key]
        source_delays[source_key] += shift_ms
        raw_source_delays[source_key] += raw_shift_ms
        if log:
            log(
                f"  - {source_key}: {original:+.1f}ms → {source_delays[source_key]:+.1f}ms "
                f"(raw: {original_raw:+.3f}ms → {raw_source_delays[source_key]:+.3f}ms)"
            )

    return source_delays, raw_source_delays
