# vsg_core/analysis/global_shift.py
"""
Global shift calculation to eliminate negative delays.

Pure functions for calculating the global shift needed to make all
audio track delays non-negative (required for mkvmerge compatibility).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .types import GlobalShiftCalculation

if TYPE_CHECKING:
    from collections.abc import Callable

    from vsg_core.analysis.container_delays import ContainerDelayInfo
    from vsg_core.models.context_types import ManualLayoutItem


def calculate_global_shift(
    source_delays: dict[str, int],
    raw_source_delays: dict[str, float],
    manual_layout: list[ManualLayoutItem],
    container_info: ContainerDelayInfo | None,
    global_shift_required: bool,
    log: Callable[[str], None],
) -> GlobalShiftCalculation:
    """
    Calculate global shift to eliminate negative delays.

    In positive_only sync mode with secondary audio sources, we need to
    ensure all audio delays are non-negative (mkvmerge requirement).
    This is done by finding the most negative delay and shifting all
    tracks by that amount.

    Args:
        source_delays: Dict mapping source keys to rounded delays
        raw_source_delays: Dict mapping source keys to raw (float) delays
        manual_layout: List of track layout items from context
        container_info: Container delay info for Source 1, or None
        global_shift_required: Whether global shift should be applied
        log: Logging function for messages

    Returns:
        GlobalShiftCalculation with shift amounts and metadata
    """
    delays_to_consider = []
    raw_delays_to_consider = []

    if global_shift_required:
        log(
            "[Global Shift] Identifying delays from sources contributing audio tracks..."
        )

        # Collect delays from all audio sources in the layout
        for item in manual_layout:
            item_source = item.get("source")
            item_type = item.get("type")
            if item_type == "audio":
                if (
                    item_source in source_delays
                    and source_delays[item_source] not in delays_to_consider
                ):
                    delays_to_consider.append(source_delays[item_source])
                    raw_delays_to_consider.append(raw_source_delays[item_source])
                    log(
                        f"  - Considering delay from {item_source}: {source_delays[item_source]}ms"
                    )

        # Also consider Source 1 audio container delays
        if container_info:
            audio_container_delays = list(container_info.audio_delays_ms.values())
            if audio_container_delays and any(d != 0 for d in audio_container_delays):
                delays_to_consider.extend(audio_container_delays)
                log(
                    "  - Considering Source 1 audio container delays (video delays ignored)."
                )

    # Find most negative delay
    most_negative = min(delays_to_consider) if delays_to_consider else 0
    most_negative_raw = min(raw_delays_to_consider) if raw_delays_to_consider else 0.0

    # Calculate shift if needed
    if most_negative < 0:
        global_shift_ms = abs(most_negative)
        raw_global_shift_ms = abs(most_negative_raw)

        log(
            f"[Delay] Most negative relevant delay: {most_negative}ms (rounded), {most_negative_raw:.3f}ms (raw)"
        )
        log(
            f"[Delay] Applying lossless global shift: +{global_shift_ms}ms (rounded), +{raw_global_shift_ms:.3f}ms (raw)"
        )

        return GlobalShiftCalculation(
            shift_ms=global_shift_ms,
            raw_shift_ms=raw_global_shift_ms,
            most_negative_ms=most_negative,
            most_negative_raw_ms=most_negative_raw,
            applied=True,
        )
    else:
        log("[Delay] All relevant delays are non-negative. No global shift needed.")
        return GlobalShiftCalculation(
            shift_ms=0,
            raw_shift_ms=0.0,
            most_negative_ms=most_negative,
            most_negative_raw_ms=most_negative_raw,
            applied=False,
        )


def apply_global_shift_to_delays(
    source_delays: dict[str, int],
    raw_source_delays: dict[str, float],
    shift: GlobalShiftCalculation,
    log: Callable[[str], None],
) -> tuple[dict[str, int], dict[str, float]]:
    """
    Apply global shift to all source delays.

    Args:
        source_delays: Dict mapping source keys to rounded delays
        raw_source_delays: Dict mapping source keys to raw delays
        shift: GlobalShiftCalculation with shift amounts
        log: Logging function for messages

    Returns:
        Tuple of (updated_source_delays, updated_raw_source_delays)
    """
    if not shift.applied:
        return source_delays, raw_source_delays

    updated_delays = {}
    updated_raw_delays = {}

    log("[Delay] Adjusted delays after global shift:")
    for source_key in sorted(source_delays.keys()):
        original_delay = source_delays[source_key]
        original_raw_delay = raw_source_delays[source_key]

        updated_delays[source_key] = original_delay + shift.shift_ms
        updated_raw_delays[source_key] = original_raw_delay + shift.raw_shift_ms

        log(
            f"  - {source_key}: {original_delay:+.1f}ms → {updated_delays[source_key]:+.1f}ms "
            f"(raw: {original_raw_delay:+.3f}ms → {updated_raw_delays[source_key]:+.3f}ms)"
        )

    return updated_delays, updated_raw_delays
