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
) -> list[TransitionZone]:
    """Identify transition zones between adjacent clusters.

    Each ``TransitionZone`` represents the gap in the reference timeline
    between the last window of one cluster and the first window of the next.
    Downstream code refines the precise splice point within this zone.
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

    log(f"[EDL Builder] Found {len(zones)} transition zone(s)")
    return zones


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
