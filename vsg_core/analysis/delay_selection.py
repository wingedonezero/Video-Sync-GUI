# vsg_core/analysis/delay_selection.py
"""
Delay selection logic for audio correlation analysis.

Pure functions that calculate final delay from dense correlation window results.
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
    override_early_pct: float | None = None,
) -> int | float | None:
    """
    Find the delay that dominates the early portion of the file.

    Looks at the first N% of accepted windows (configurable via
    first_stable_early_pct) and finds the most common delay in that region.
    If it has sufficient agreement (>=60%), uses it. Then averages ALL
    matching raw values across the whole file for sub-millisecond precision.

    For stepping files, this gives the dominant early delay even if
    later segments have different delays.

    Args:
        results: List of ChunkResult from dense correlation.
        settings: AppSettings instance.
        return_raw: If True, return the raw (unrounded) delay value.
        log: Logging function for messages.
        override_early_pct: Override first_stable_early_pct (for stepping mode).

    Returns:
        The delay value from the first stable region, or None if not found.
    """
    early_pct = (
        override_early_pct
        if override_early_pct is not None
        else settings.first_stable_early_pct
    )

    accepted = [r for r in results if r.accepted]
    if len(accepted) < 3:
        return None

    # Look at the first N% of accepted windows
    early_count = max(3, int(len(accepted) * early_pct / 100.0))
    early_windows = accepted[:early_count]

    # Find the dominant delay in the early region
    early_delays = [r.delay_ms for r in early_windows]
    early_counts = Counter(early_delays)
    top_delay, top_count = early_counts.most_common(1)[0]

    # Check agreement: the top delay must represent >=60% of early windows
    early_agreement = top_count / len(early_windows) * 100

    if early_agreement < 60.0:
        # Try +/-1ms cluster (handles sub-ms rounding splits)
        cluster_count = sum(
            c for d, c in early_counts.items() if abs(d - top_delay) <= 1
        )
        early_agreement = cluster_count / len(early_windows) * 100

        if early_agreement < 60.0:
            log(
                f"[First Stable] No dominant delay in first {len(early_windows)} "
                f"windows ({early_pct:.0f}% early region) "
                f"(best: {top_delay:+d}ms at {early_agreement:.0f}% agreement)"
            )
            return None

    # Collect ALL raw values matching this delay (+/-1ms) across the full file
    # for maximum precision
    matching_raw = [
        r.raw_delay_ms for r in accepted if abs(r.delay_ms - top_delay) <= 1
    ]

    raw_avg = sum(matching_raw) / len(matching_raw)
    rounded_avg = round(raw_avg)

    log(
        f"[First Stable] Dominant delay in first {len(early_windows)} windows "
        f"({early_pct:.0f}% early region): "
        f"{top_delay:+d}ms ({early_agreement:.0f}% agreement), "
        f"averaged {len(matching_raw)} matching windows -> "
        f"{rounded_avg:+d}ms (raw: {raw_avg:+.6f}ms)"
    )

    return raw_avg if return_raw else rounded_avg


def _find_early_cluster_delay(
    accepted: list[ChunkResult],
    settings: AppSettings,
    return_raw: bool,
    log: Callable[[str], None],
) -> int | float | None:
    """
    Find the delay from the earliest cluster in the early portion of the file.

    Unlike First Stable (which picks the dominant delay), Early Cluster picks
    whichever delay appears FIRST in time, as long as it has minimum presence
    in the early region. This is better for stepping files where the first
    segment may be short (e.g., 30 windows) but is the correct initial delay.

    Algorithm:
      1. Take the first early_cluster_early_pct% of accepted windows
      2. Find all delay clusters (+/-1ms grouping) present in that region
      3. Filter to clusters with at least early_cluster_min_presence_pct%
         of the early windows
      4. Pick the cluster that appears first in time order
      5. Average all matching raw values across the full file

    Args:
        accepted: Pre-filtered accepted windows.
        settings: AppSettings instance.
        return_raw: If True, return the raw (unrounded) delay value.
        log: Logging function for messages.

    Returns:
        The delay value from the earliest qualifying cluster, or None.
    """
    early_pct = settings.early_cluster_early_pct
    min_presence_pct = settings.early_cluster_min_presence_pct

    if len(accepted) < 3:
        return None

    early_count = max(3, int(len(accepted) * early_pct / 100.0))
    early_windows = accepted[:early_count]

    # Find all delay clusters in the early region
    counts = Counter(r.delay_ms for r in early_windows)
    cluster_info: dict[int, dict] = {}

    for delay_val in counts:
        cluster_raw_vals: list[float] = []
        early_presence = 0
        first_window_idx: int | None = None

        for idx, r in enumerate(accepted):
            if abs(r.delay_ms - delay_val) <= 1:
                cluster_raw_vals.append(r.raw_delay_ms)
                if idx < early_count:
                    early_presence += 1
                if first_window_idx is None:
                    first_window_idx = idx

        presence_pct = early_presence / len(early_windows) * 100

        cluster_info[delay_val] = {
            "raw_values": cluster_raw_vals,
            "early_presence": early_presence,
            "presence_pct": presence_pct,
            "first_window_idx": first_window_idx,
            "total_count": len(cluster_raw_vals),
        }

    # Filter to clusters with enough early presence
    qualifying = [
        (delay_val, info)
        for delay_val, info in cluster_info.items()
        if info["presence_pct"] >= min_presence_pct
    ]

    if qualifying:
        # Pick the cluster that appears first in time
        qualifying.sort(key=lambda x: x[1]["first_window_idx"])
        winner_delay, winner_info = qualifying[0]

        raw_avg = sum(winner_info["raw_values"]) / len(winner_info["raw_values"])
        rounded_avg = round(raw_avg)

        log(
            f"[Early Cluster] Found {len(qualifying)} qualifying cluster(s) "
            f"in first {len(early_windows)} windows ({early_pct:.0f}% early region), "
            f"selected earliest: {winner_delay:+d}ms with "
            f"{winner_info['early_presence']}/{len(early_windows)} early windows "
            f"({winner_info['presence_pct']:.1f}% presence), "
            f"total {winner_info['total_count']} matching windows, "
            f"raw avg: {raw_avg:+.6f}ms -> rounded to {rounded_avg:+d}ms"
        )

        return raw_avg if return_raw else rounded_avg

    log(
        f"[Early Cluster] No cluster met minimum presence "
        f"({min_presence_pct:.1f}%) in first {len(early_windows)} windows "
        f"({early_pct:.0f}% early region)"
    )
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
        results: List of ChunkResult from dense correlation.
        settings: AppSettings instance.
        delay_mode: Delay selection mode to use.
        log: Logging function for messages.
        role_tag: Source identifier for logging (e.g., "Source 2").

    Returns:
        DelayCalculation with both rounded and raw delays, or None if
        insufficient data.
    """
    accepted = [r for r in results if r.accepted]
    total_windows = len(results)
    # Calculate minimum from percentage (floor of 10 for very short files)
    min_accepted = max(10, int(total_windows * settings.min_accepted_pct / 100.0))
    if len(accepted) < min_accepted:
        actual_pct = len(accepted) / total_windows * 100 if total_windows else 0
        log(
            f"[ERROR] Analysis failed: Only {len(accepted)}/{total_windows} "
            f"windows accepted ({actual_pct:.1f}%, need {settings.min_accepted_pct:.0f}%)."
        )
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
            log("[WARNING] No stable early region found, falling back to mode (clustered).")
            counts = Counter(delays)
            mode_winner = counts.most_common(1)[0][0]
            cluster_raw = [
                r.raw_delay_ms for r in accepted if abs(r.delay_ms - mode_winner) <= 1
            ]
            if cluster_raw:
                winner_raw = sum(cluster_raw) / len(cluster_raw)
                winner = round(winner_raw)
            else:
                winner = mode_winner
                winner_raw = float(mode_winner)
            method_label = "mode clustered (first stable fallback)"
        else:
            winner = int(stable_rounded)
            winner_raw = float(stable_raw) if stable_raw is not None else float(winner)
            method_label = "first stable"

    elif delay_mode == "Mode (Early Cluster)":
        ec_rounded = _find_early_cluster_delay(accepted, settings, return_raw=False, log=log)
        ec_raw = _find_early_cluster_delay(accepted, settings, return_raw=True, log=log)

        if ec_rounded is None:
            log("[WARNING] No qualifying early cluster found, falling back to mode (clustered).")
            counts = Counter(delays)
            mode_winner = counts.most_common(1)[0][0]
            cluster_raw = [
                r.raw_delay_ms for r in accepted if abs(r.delay_ms - mode_winner) <= 1
            ]
            if cluster_raw:
                winner_raw = sum(cluster_raw) / len(cluster_raw)
                winner = round(winner_raw)
            else:
                winner = mode_winner
                winner_raw = float(mode_winner)
            method_label = "mode clustered (early cluster fallback)"
        else:
            winner = int(ec_rounded)
            winner_raw = float(ec_raw) if ec_raw is not None else float(winner)
            method_label = "early cluster"

    elif delay_mode == "Average":
        raw_avg = sum(raw_delays) / len(raw_delays)
        winner = round(raw_avg)
        winner_raw = raw_avg
        log(
            f"[Delay Selection] Average of {len(raw_delays)} raw values: "
            f"{raw_avg:+.6f}ms -> rounded to {winner:+d}ms"
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
                f"[Delay Selection] Mode (Clustered): most common = {mode_winner:+d}ms, "
                f"cluster [{mode_winner - 1} to {mode_winner + 1}] contains "
                f"{len(cluster_raw_values)}/{len(accepted)} windows "
                f"(breakdown: {dict(cluster_counts)}), "
                f"raw avg: {raw_avg:+.6f}ms -> rounded to {winner:+d}ms"
            )
            method_label = "mode (clustered)"
        else:
            winner = mode_winner
            winner_raw = float(mode_winner)
            log(
                f"[Delay Selection] Mode (Clustered): fallback to simple "
                f"mode = {winner:+d}ms"
            )
            method_label = "mode (clustered fallback)"

    else:  # Mode (Most Common) - default
        counts = Counter(delays)
        winner = counts.most_common(1)[0][0]
        matching_raw_values = [r.raw_delay_ms for r in accepted if r.delay_ms == winner]
        if matching_raw_values:
            winner_raw = sum(matching_raw_values) / len(matching_raw_values)
        else:
            winner_raw = float(winner)
        log(
            f"[Delay Selection] Mode (Most Common): {winner:+d}ms "
            f"({counts[winner]}/{len(accepted)} windows), "
            f"raw avg: {winner_raw:+.6f}ms"
        )
        method_label = "mode"

    log(
        f"{role_tag.capitalize()} delay determined: "
        f"{winner:+d}ms (raw: {winner_raw:+.6f}ms) [{method_label}]"
    )

    return DelayCalculation(
        rounded_ms=winner,
        raw_ms=winner_raw,
        selection_method=method_label,
        accepted_windows=len(accepted),
        total_windows=len(results),
    )
