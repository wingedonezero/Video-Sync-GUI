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

    Groups noise points by delay (within ±5 ms tolerance on the float
    delay — *not* rounded to int ms), and if a group of 2+ points has a
    consistent delay near a chapter marker, creates an additional
    ``TransitionZone`` and appends it to *zones* using the float mean of
    the group's delays.  Preserves sub-ms precision the same way the
    regular DBSCAN clusters do.
    """
    import numpy as np

    if not noise_points:
        return

    # Get the last valid cluster for reference
    last_cluster = cluster_map[valid_ids[-1]]
    last_delay = last_cluster.mean_delay_ms  # type: ignore[attr-defined]
    last_end = last_cluster.time_range[1]  # type: ignore[attr-defined]

    # Agglomerate noise points within ±5 ms of the running mean — same
    # idea as DBSCAN's epsilon but inline since we usually have only a
    # handful of noise points.  Sort by delay so adjacent points are
    # candidates to merge.
    sorted_noise = sorted(noise_points, key=lambda np_: np_[1])
    groups: list[list[tuple[float, float]]] = []
    GROUPING_TOL_MS = 5.0
    for t, d in sorted_noise:
        if groups:
            cur_mean = sum(p[1] for p in groups[-1]) / len(groups[-1])
            if abs(d - cur_mean) <= GROUPING_TOL_MS:
                groups[-1].append((t, d))
                continue
        groups.append([(t, d)])

    # Try largest groups first
    groups.sort(key=len, reverse=True)

    anchor_delay = cluster_map[valid_ids[0]].mean_delay_ms  # type: ignore[attr-defined]

    for group in groups:
        if len(group) < 2:
            continue

        times = [p[0] for p in group]
        delays = [p[1] for p in group]
        avg_delay = float(np.mean(delays))  # sub-ms float, not rounded
        avg_time = float(np.mean(times))
        # Convert to src2 timeline approximately (using anchor delay)
        avg_time_src2 = avg_time - anchor_delay / 1000.0

        near_chapter = None
        for ch_t in chapter_times:
            if abs(ch_t - avg_time_src2) < 10.0:
                near_chapter = ch_t
                break

        if near_chapter is None:
            continue

        jump_ms = avg_delay - last_delay
        if abs(jump_ms) < 5:
            continue

        # Create recovery transition with sub-ms precision
        min_t = min(times)
        zone = TransitionZone(
            ref_start_s=last_end,
            ref_end_s=min_t,
            delay_before_ms=last_delay,
            delay_after_ms=avg_delay,
            correction_ms=jump_ms,
        )
        zones.append(zone)
        log(
            f"[EDL Builder] RECOVERED Transition (from {len(group)} noise "
            f"points): ref [{last_end:.1f}s - {min_t:.1f}s]  "
            f"delay {last_delay:+.3f}ms → {avg_delay:+.3f}ms  "
            f"correction {jump_ms:+.3f}ms  "
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
