# vsg_core/correction/stepping/edl_builder.py
"""
Build transition zones and EDL segments from dense analysis data.

Replaces the old coarse-scan + binary-search pipeline by using the
cluster boundaries that DBSCAN already identified during analysis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .types import AudioSegment, SteppingData, TransitionZone

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...models.context_types import SegmentFlagsEntry
    from ...models.settings import AppSettings


def find_transition_zones(
    stepping_data: SteppingData,
    segment_flags: SegmentFlagsEntry,
    settings: AppSettings,
    log: Callable[[str], None],
    chapter_times: list[float] | None = None,
) -> list[TransitionZone]:
    """Identify transition zones between adjacent clusters.

    Each ``TransitionZone`` represents the gap in the reference timeline
    between the last window of one cluster and the first window of the next.
    Downstream code refines the precise splice point within this zone.

    Parameters
    ----------
    chapter_times:
        Source 2 chapter start times (seconds) for noise point recovery.
        If provided and ``stepping_noise_recovery_enabled`` is True,
        DBSCAN noise points near chapter markers are recovered as
        additional clusters.
    """
    valid_clusters = segment_flags.get("valid_clusters", {})
    if not valid_clusters:
        log("[EDL Builder] No valid clusters — nothing to build")
        return []

    # Map cluster_id → ClusterDiagnostic for fast lookup
    cluster_map = {c.cluster_id: c for c in stepping_data.clusters}

    # Keep only clusters that passed validation
    valid_ids = sorted(
        (cid for cid in valid_clusters if cid in cluster_map),
        key=lambda cid: cluster_map[cid].time_range[0],
    )

    if len(valid_ids) < 2:
        log("[EDL Builder] Only one valid cluster — no transitions to build")
        return []

    zones: list[TransitionZone] = []
    for i in range(len(valid_ids) - 1):
        c_before = cluster_map[valid_ids[i]]
        c_after = cluster_map[valid_ids[i + 1]]

        correction = c_after.mean_delay_ms - c_before.mean_delay_ms

        zone = TransitionZone(
            ref_start_s=c_before.time_range[1],
            ref_end_s=c_after.time_range[0],
            delay_before_ms=c_before.mean_delay_ms,
            delay_after_ms=c_after.mean_delay_ms,
            correction_ms=correction,
        )
        zones.append(zone)
        log(
            f"[EDL Builder] Transition {i + 1}: "
            f"ref [{zone.ref_start_s:.1f}s - {zone.ref_end_s:.1f}s]  "
            f"delay {c_before.mean_delay_ms:+.0f}ms → {c_after.mean_delay_ms:+.0f}ms  "
            f"correction {correction:+.0f}ms"
        )

    # --- Noise point recovery ---
    if (
        settings.stepping_noise_recovery_enabled
        and stepping_data.noise_points
        and chapter_times
    ):
        _recover_noise_clusters(
            stepping_data.noise_points,
            chapter_times,
            cluster_map,
            valid_ids,
            zones,
            settings,
            log,
        )

    log(f"[EDL Builder] Found {len(zones)} transition zone(s)")
    return zones


def _recover_noise_clusters(
    noise_points: tuple[tuple[float, float], ...],
    chapter_times: list[float],
    cluster_map: dict[int, object],
    valid_ids: list[int],
    zones: list[TransitionZone],
    settings: object,
    log: Callable[[str], None],
) -> None:
    """Check DBSCAN noise points for recoverable small clusters near chapters.

    Groups noise points by delay, and if a group of 2+ points has a
    consistent delay near a chapter marker, creates an additional
    ``TransitionZone`` and appends it to *zones*.
    """
    from collections import Counter

    import numpy as np

    if not noise_points:
        return

    # Get the last valid cluster for reference
    last_cluster = cluster_map[valid_ids[-1]]
    last_delay = last_cluster.mean_delay_ms  # type: ignore[attr-defined]
    last_end = last_cluster.time_range[1]  # type: ignore[attr-defined]

    # Group noise by rounded delay (within DBSCAN epsilon ~20ms)
    delay_counts: Counter[int] = Counter()
    delay_times: dict[int, list[float]] = {}
    for t, d in noise_points:
        rd = round(d)
        delay_counts[rd] += 1
        if rd not in delay_times:
            delay_times[rd] = []
        delay_times[rd].append(t)

    for rd, count in delay_counts.most_common():
        if count < 2:
            continue

        # Check if this noise group is near a chapter
        avg_time = float(np.mean(delay_times[rd]))
        # Convert to src2 timeline approximately (using anchor delay)
        anchor_delay = cluster_map[valid_ids[0]].mean_delay_ms  # type: ignore[attr-defined]
        avg_time_src2 = avg_time - anchor_delay / 1000.0

        near_chapter = None
        for ch_t in chapter_times:
            if abs(ch_t - avg_time_src2) < 10.0:
                near_chapter = ch_t
                break

        if near_chapter is None:
            continue

        jump_ms = rd - last_delay
        if abs(jump_ms) < 5:
            continue

        # Create recovery transition
        min_t = min(delay_times[rd])
        zone = TransitionZone(
            ref_start_s=last_end,
            ref_end_s=min_t,
            delay_before_ms=last_delay,
            delay_after_ms=float(rd),
            correction_ms=jump_ms,
        )
        zones.append(zone)
        log(
            f"[EDL Builder] RECOVERED Transition (from {count} noise points): "
            f"ref [{last_end:.1f}s - {min_t:.1f}s]  "
            f"delay {last_delay:+.0f}ms → {rd:+.0f}ms  "
            f"correction {jump_ms:+.0f}ms  "
            f"(near chapter {near_chapter:.1f}s)"
        )
        # Only recover one noise cluster (typically the end-of-episode segment)
        break


def build_segments_from_splice_points(
    anchor_delay_ms: int,
    anchor_delay_raw: float,
    splice_points: list[tuple[float, float, float]],
    log: Callable[[str], None],
) -> list[AudioSegment]:
    """Convert refined splice points into an EDL segment list.

    Parameters
    ----------
    anchor_delay_ms:
        The delay of the first cluster (anchor).
    anchor_delay_raw:
        Raw (unrounded) anchor delay for subtitle precision.
    splice_points:
        List of ``(src2_time_s, delay_after_ms, delay_after_raw)`` tuples,
        sorted by time.
    log:
        Logging callable.

    Returns
    -------
    list[AudioSegment]
        Sorted EDL with an anchor segment at t=0 followed by one segment
        per splice point.
    """
    edl: list[AudioSegment] = [
        AudioSegment(
            start_s=0.0,
            end_s=0.0,
            delay_ms=anchor_delay_ms,
            delay_raw=anchor_delay_raw,
        )
    ]

    for src2_time_s, delay_after_ms, delay_after_raw in splice_points:
        edl.append(
            AudioSegment(
                start_s=src2_time_s,
                end_s=src2_time_s,
                delay_ms=int(round(delay_after_ms)),
                delay_raw=delay_after_raw,
            )
        )

    edl.sort(key=lambda s: s.start_s)

    log(f"[EDL Builder] Built EDL with {len(edl)} segment(s):")
    for i, seg in enumerate(edl):
        log(
            f"  Segment {i + 1}: @{seg.start_s:.3f}s  "
            f"delay={seg.delay_ms:+d}ms (raw {seg.delay_raw:.3f}ms)"
        )

    return edl
