# vsg_core/analysis/delay_selection.py
"""
Delay selection logic for audio correlation analysis.

Pure functions that calculate final delay from correlation chunk results.
All business logic for delay selection modes (Mode, Average, First Stable, etc.).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .types import ChunkResult, DelayCalculation

if TYPE_CHECKING:
    from collections.abc import Callable

    from vsg_core.models.settings import AppSettings


def find_first_stable_segment_delay(
    results: list[ChunkResult],
    settings: AppSettings,
    return_raw: bool,
    log: Callable[[str], None],
    *,
    override_min_chunks: int | None = None,
    override_skip_unstable: bool | None = None,
) -> int | float | None:
    """
    Find the delay from the first stable segment of chunks.

    Identifies consecutive accepted chunks that share the same delay value
    and returns the delay from the first such stable group that meets
    stability criteria.

    Args:
        results: List of ChunkResult from correlation.
        settings: AppSettings instance.
        return_raw: If True, return the raw (unrounded) delay value.
        log: Logging function for messages.
        override_min_chunks: Override first_stable_min_chunks (for stepping mode).
        override_skip_unstable: Override first_stable_skip_unstable (for stepping mode).

    Returns:
        The delay value from the first stable segment, or None if not found.
    """
    min_chunks = (
        override_min_chunks
        if override_min_chunks is not None
        else settings.first_stable_min_chunks
    )
    skip_unstable = (
        override_skip_unstable
        if override_skip_unstable is not None
        else settings.first_stable_skip_unstable
    )

    accepted = [r for r in results if r.accepted]
    if len(accepted) < min_chunks:
        return None

    # Group consecutive chunks with the same delay (within 1ms tolerance)
    segments: list[dict] = []
    current_segment = {
        "delay": accepted[0].delay_ms,
        "raw_delays": [accepted[0].raw_delay_ms],
        "count": 1,
        "start_time": accepted[0].start_s,
    }

    for i in range(1, len(accepted)):
        if abs(accepted[i].delay_ms - current_segment["delay"]) <= 1:
            current_segment["count"] += 1
            current_segment["raw_delays"].append(accepted[i].raw_delay_ms)
        else:
            segments.append(current_segment)
            current_segment = {
                "delay": accepted[i].delay_ms,
                "raw_delays": [accepted[i].raw_delay_ms],
                "count": 1,
                "start_time": accepted[i].start_s,
            }

    segments.append(current_segment)

    def _get_segment_raw(segment: dict) -> float:
        return sum(segment["raw_delays"]) / len(segment["raw_delays"])

    if skip_unstable:
        for segment in segments:
            if segment["count"] >= min_chunks:
                raw_avg = _get_segment_raw(segment)
                # CRITICAL: Round the raw average, not first chunk's delay
                rounded_avg = round(raw_avg)
                log(
                    f"[First Stable] Found stable segment: {segment['count']} chunks "
                    f"at {rounded_avg:+d}ms (raw avg: {raw_avg:.3f}ms, "
                    f"starting at {segment['start_time']:.1f}s)"
                )
                return raw_avg if return_raw else rounded_avg

        log(
            f"[First Stable] No segment found with minimum {min_chunks} chunks. "
            f"Largest segment: {max((s['count'] for s in segments), default=0)} chunks"
        )
        return None

    elif segments:
        first_segment = segments[0]
        raw_avg = _get_segment_raw(first_segment)
        # CRITICAL: Round the raw average, not first chunk's delay
        rounded_avg = round(raw_avg)
        if first_segment["count"] < min_chunks:
            log(
                f"[First Stable] Warning: First segment has only "
                f"{first_segment['count']} chunks (minimum: {min_chunks}), "
                f"but using it anyway (skip_unstable=False)"
            )
        log(
            f"[First Stable] Using first segment: {first_segment['count']} chunks "
            f"at {rounded_avg:+d}ms (raw avg: {raw_avg:.3f}ms, "
            f"starting at {first_segment['start_time']:.1f}s)"
        )
        return raw_avg if return_raw else rounded_avg

    return None


def calculate_delay(
    results: list[ChunkResult],
    settings: AppSettings,
    delay_mode: str,
    log: Callable[[str], None],
    role_tag: str,
) -> DelayCalculation | None:
    """
    Select final delay from correlation results using configured mode.

    Args:
        results: List of ChunkResult from correlation.
        settings: AppSettings instance.
        delay_mode: Delay selection mode to use.
        log: Logging function for messages.
        role_tag: Source identifier for logging (e.g., "Source 2").

    Returns:
        DelayCalculation with both rounded and raw delays, or None if
        insufficient data.
    """
    min_accepted_chunks = settings.min_accepted_chunks

    accepted = [r for r in results if r.accepted]
    if len(accepted) < min_accepted_chunks:
        log(f"[ERROR] Analysis failed: Only {len(accepted)} chunks were accepted.")
        return None

    delays = [r.delay_ms for r in accepted]
    raw_delays = [r.raw_delay_ms for r in accepted]

    winner: int
    winner_raw: float

    if delay_mode == "First Stable":
        stable_rounded = find_first_stable_segment_delay(
            results, settings, return_raw=False, log=log
        )
        stable_raw = find_first_stable_segment_delay(
            results, settings, return_raw=True, log=log
        )
        if stable_rounded is None:
            log("[WARNING] No stable segment found, falling back to mode.")
            counts = Counter(delays)
            winner = counts.most_common(1)[0][0]
            winner_raw = float(winner)
            method_label = "mode (fallback)"
        else:
            winner = int(stable_rounded)
            winner_raw = float(stable_raw) if stable_raw is not None else float(winner)
            method_label = "first stable"

    elif delay_mode == "Average":
        raw_avg = sum(raw_delays) / len(raw_delays)
        winner = round(raw_avg)
        winner_raw = raw_avg
        log(
            f"[Delay Selection] Average of {len(raw_delays)} raw values: "
            f"{raw_avg:.3f}ms -> rounded to {winner}ms"
        )
        method_label = "average"

    elif delay_mode == "Mode (Clustered)":
        counts = Counter(delays)
        mode_winner = counts.most_common(1)[0][0]

        cluster_raw_values: list[float] = []
        cluster_delays: list[int] = []
        for r in accepted:
            if abs(r.delay_ms - mode_winner) <= 1:
                cluster_raw_values.append(r.raw_delay_ms)
                cluster_delays.append(r.delay_ms)

        if cluster_raw_values:
            raw_avg = sum(cluster_raw_values) / len(cluster_raw_values)
            winner = round(raw_avg)
            winner_raw = raw_avg
            cluster_counts = Counter(cluster_delays)
            log(
                f"[Delay Selection] Mode (Clustered): most common = {mode_winner}ms, "
                f"cluster [{mode_winner - 1} to {mode_winner + 1}] contains "
                f"{len(cluster_raw_values)}/{len(accepted)} chunks "
                f"(breakdown: {dict(cluster_counts)}), "
                f"raw avg: {raw_avg:.3f}ms -> rounded to {winner}ms"
            )
            method_label = "mode (clustered)"
        else:
            winner = mode_winner
            winner_raw = float(mode_winner)
            log(
                f"[Delay Selection] Mode (Clustered): fallback to simple "
                f"mode = {winner}ms"
            )
            method_label = "mode (clustered fallback)"

    elif delay_mode == "Mode (Early Cluster)":
        early_window = settings.early_cluster_window
        early_threshold = settings.early_cluster_threshold

        counts = Counter(delays)
        cluster_info: dict[int, dict] = {}

        for delay_val in counts:
            cluster_raw_vals: list[float] = []
            early_count = 0
            first_chunk_idx: int | None = None

            for idx, r in enumerate(accepted):
                if abs(r.delay_ms - delay_val) <= 1:
                    cluster_raw_vals.append(r.raw_delay_ms)
                    if idx < early_window:
                        early_count += 1
                    if first_chunk_idx is None:
                        first_chunk_idx = idx

            cluster_info[delay_val] = {
                "raw_values": cluster_raw_vals,
                "early_count": early_count,
                "first_chunk_idx": first_chunk_idx,
                "total_count": len(cluster_raw_vals),
            }

        early_stable_clusters = [
            (delay_val, info)
            for delay_val, info in cluster_info.items()
            if info["early_count"] >= early_threshold
        ]

        if early_stable_clusters:
            early_stable_clusters.sort(key=lambda x: x[1]["first_chunk_idx"])
            _winner_delay, winner_info = early_stable_clusters[0]

            raw_avg = sum(winner_info["raw_values"]) / len(winner_info["raw_values"])
            winner = round(raw_avg)
            winner_raw = raw_avg

            log(
                f"[Delay Selection] Mode (Early Cluster): found "
                f"{len(early_stable_clusters)} early stable cluster(s), "
                f"selected cluster at {winner}ms with "
                f"{winner_info['early_count']}/{early_window} early chunks, "
                f"total {winner_info['total_count']} chunks, "
                f"first appears at chunk {winner_info['first_chunk_idx'] + 1}, "
                f"raw avg: {raw_avg:.3f}ms -> rounded to {winner}ms"
            )
            method_label = "mode (early cluster)"
        else:
            mode_winner = counts.most_common(1)[0][0]
            fb_raw_values = [
                r.raw_delay_ms for r in accepted if abs(r.delay_ms - mode_winner) <= 1
            ]

            if fb_raw_values:
                raw_avg = sum(fb_raw_values) / len(fb_raw_values)
                winner = round(raw_avg)
                winner_raw = raw_avg
                log(
                    f"[Delay Selection] Mode (Early Cluster): no cluster met "
                    f"early threshold ({early_threshold} in first "
                    f"{early_window}), falling back to Mode (Clustered): "
                    f"{winner}ms (raw avg: {raw_avg:.3f}ms)"
                )
                method_label = "mode (early cluster - clustered fallback)"
            else:
                winner = mode_winner
                winner_raw = float(mode_winner)
                log(
                    f"[Delay Selection] Mode (Early Cluster): fallback to "
                    f"simple mode = {winner}ms"
                )
                method_label = "mode (early cluster - simple fallback)"

    else:  # Mode (Most Common) - default
        counts = Counter(delays)
        winner = counts.most_common(1)[0][0]
        matching_raw_values = [r.raw_delay_ms for r in accepted if r.delay_ms == winner]
        if matching_raw_values:
            winner_raw = sum(matching_raw_values) / len(matching_raw_values)
        else:
            winner_raw = float(winner)
        method_label = "mode"

    log(f"{role_tag.capitalize()} delay determined: {winner:+d} ms ({method_label}).")

    return DelayCalculation(
        rounded_ms=winner,
        raw_ms=winner_raw,
        selection_method=method_label,
        accepted_chunks=len(accepted),
        total_chunks=len(results),
    )
