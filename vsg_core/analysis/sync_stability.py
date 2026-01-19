# vsg_core/analysis/sync_stability.py
# -*- coding: utf-8 -*-
"""
Sync stability analyzer for detecting variance in correlation results.

Analyzes per-chunk delay values to detect inconsistencies that may indicate
sync issues, even when the final rounded delay appears correct.
"""

from typing import List, Dict, Any, Optional, Callable
from statistics import mean, stdev, variance


def _to_float(value) -> float:
    """Convert numpy types to native Python float for JSON serialization."""
    return float(value)


def analyze_sync_stability(
    chunk_results: List[Dict[str, Any]],
    source_key: str,
    config: Dict[str, Any],
    log: Optional[Callable[[str], None]] = None,
    stepping_clusters: Optional[List[Dict]] = None
) -> Optional[Dict[str, Any]]:
    """
    Analyze correlation chunk results for variance/stability issues.

    This checks for variance in raw delay values that might indicate sync
    problems, even when results round to the same final delay.

    Args:
        chunk_results: List of chunk dicts with 'raw_delay', 'delay', 'match', 'accepted'
        source_key: Source identifier (e.g., 'Source 2')
        config: Config dict with sync_stability_* settings
        log: Optional logging callback
        stepping_clusters: Optional list of stepping clusters to exclude from variance check

    Returns:
        Dict with stability analysis results, or None if check disabled/skipped
    """
    # Check if enabled
    if not config.get('sync_stability_enabled', True):
        return None

    # Get settings
    variance_threshold = config.get('sync_stability_variance_threshold', 0.0)
    min_chunks = config.get('sync_stability_min_chunks', 3)
    outlier_mode = config.get('sync_stability_outlier_mode', 'any')
    outlier_threshold = config.get('sync_stability_outlier_threshold', 1.0)

    # Get accepted chunks with raw delays
    accepted = [r for r in chunk_results if r.get('accepted', False)]

    if len(accepted) < min_chunks:
        if log:
            log(f"[Sync Stability] {source_key}: Skipped - only {len(accepted)} chunks (need {min_chunks})")
        return None

    # Extract raw delay values
    raw_delays = [r.get('raw_delay', float(r.get('delay', 0))) for r in accepted]

    # If stepping clusters provided, analyze each cluster separately
    # Otherwise analyze all chunks as one group
    if stepping_clusters and len(stepping_clusters) > 1:
        return _analyze_with_clusters(
            accepted, raw_delays, source_key, config, log,
            stepping_clusters, variance_threshold, min_chunks,
            outlier_mode, outlier_threshold
        )
    else:
        return _analyze_uniform(
            accepted, raw_delays, source_key, config, log,
            variance_threshold, min_chunks, outlier_mode, outlier_threshold
        )


def _analyze_uniform(
    accepted: List[Dict],
    raw_delays: List[float],
    source_key: str,
    config: Dict[str, Any],
    log: Optional[Callable],
    variance_threshold: float,
    min_chunks: int,
    outlier_mode: str,
    outlier_threshold: float
) -> Dict[str, Any]:
    """Analyze chunks as a single uniform group (no stepping)."""

    # Calculate statistics
    mean_delay = mean(raw_delays)

    if len(raw_delays) < 2:
        return {
            'source': source_key,
            'variance_detected': False,
            'reason': 'insufficient_chunks',
            'chunk_count': len(raw_delays)
        }

    std_delay = stdev(raw_delays)
    var_delay = variance(raw_delays)

    # Find min/max
    min_delay = min(raw_delays)
    max_delay = max(raw_delays)
    max_variance = max_delay - min_delay

    # Detect outliers based on mode
    outliers = []
    if outlier_mode == 'any':
        # Any chunk that differs from the first is an outlier
        reference = raw_delays[0]
        for i, (chunk, raw) in enumerate(zip(accepted, raw_delays)):
            if abs(raw - reference) > 0.0001:  # Allow tiny floating point tolerance
                outliers.append({
                    'chunk_index': i + 1,
                    'time_s': _to_float(chunk.get('start', 0)),
                    'delay_ms': _to_float(raw),
                    'deviation_ms': _to_float(raw - reference)
                })
    else:
        # Custom threshold mode - outliers differ from mean by more than threshold
        for i, (chunk, raw) in enumerate(zip(accepted, raw_delays)):
            deviation = abs(raw - mean_delay)
            if deviation > outlier_threshold:
                outliers.append({
                    'chunk_index': i + 1,
                    'time_s': _to_float(chunk.get('start', 0)),
                    'delay_ms': _to_float(raw),
                    'deviation_ms': _to_float(raw - mean_delay)
                })

    # Determine if variance is detected based on threshold
    variance_detected = False

    if variance_threshold <= 0:
        # Strict mode: any variance at all
        variance_detected = max_variance > 0.0001
    else:
        # Threshold mode: variance must exceed threshold
        variance_detected = max_variance > variance_threshold

    # Build result - ensure all floats are native Python types for JSON serialization
    result = {
        'source': source_key,
        'variance_detected': variance_detected,
        'max_variance_ms': round(_to_float(max_variance), 4),
        'std_dev_ms': round(_to_float(std_delay), 4),
        'mean_delay_ms': round(_to_float(mean_delay), 4),
        'min_delay_ms': round(_to_float(min_delay), 4),
        'max_delay_ms': round(_to_float(max_delay), 4),
        'chunk_count': len(accepted),
        'outlier_count': len(outliers),
        'outliers': outliers[:10],  # Limit to first 10 outliers
        'cluster_count': 1,
        'is_stepping': False
    }

    # Log results
    if log:
        if variance_detected:
            log(f"[Sync Stability] {source_key}: Variance detected!")
            log(f"  - Max variance: {max_variance:.4f}ms (threshold: {variance_threshold}ms)")
            log(f"  - Std dev: {std_delay:.4f}ms")
            log(f"  - Range: {min_delay:.4f}ms to {max_delay:.4f}ms")
            if outliers:
                log(f"  - Outliers: {len(outliers)} chunk(s)")
                for o in outliers[:3]:
                    log(f"    * Chunk {o['chunk_index']} (@{o['time_s']:.1f}s): {o['delay_ms']:.4f}ms (deviation: {o['deviation_ms']:+.4f}ms)")
        else:
            log(f"[Sync Stability] {source_key}: OK - consistent results (variance: {max_variance:.4f}ms)")

    return result


def _analyze_with_clusters(
    accepted: List[Dict],
    raw_delays: List[float],
    source_key: str,
    config: Dict[str, Any],
    log: Optional[Callable],
    stepping_clusters: List[Dict],
    variance_threshold: float,
    min_chunks: int,
    outlier_mode: str,
    outlier_threshold: float
) -> Dict[str, Any]:
    """
    Analyze chunks with stepping clusters.

    Each cluster should be internally consistent - we check for variance
    WITHIN each cluster, not between clusters (that's stepping).
    """

    cluster_issues = []
    total_outliers = []
    max_cluster_variance = 0.0

    for cluster in stepping_clusters:
        cluster_delays = cluster.get('raw_delays', [])
        cluster_chunks = cluster.get('chunks', [])

        if len(cluster_delays) < 2:
            continue

        cluster_mean = mean(cluster_delays)
        cluster_std = stdev(cluster_delays)
        cluster_min = min(cluster_delays)
        cluster_max = max(cluster_delays)
        cluster_variance = cluster_max - cluster_min

        max_cluster_variance = max(max_cluster_variance, cluster_variance)

        # Check for outliers within this cluster
        cluster_outliers = []
        reference = cluster_delays[0]

        for i, raw in enumerate(cluster_delays):
            if outlier_mode == 'any':
                if abs(raw - reference) > 0.0001:
                    cluster_outliers.append({
                        'cluster_id': cluster.get('cluster_id', 0),
                        'chunk_index': cluster_chunks[i] if i < len(cluster_chunks) else i + 1,
                        'delay_ms': _to_float(raw),
                        'deviation_ms': _to_float(raw - reference)
                    })
            else:
                deviation = abs(raw - cluster_mean)
                if deviation > outlier_threshold:
                    cluster_outliers.append({
                        'cluster_id': cluster.get('cluster_id', 0),
                        'chunk_index': cluster_chunks[i] if i < len(cluster_chunks) else i + 1,
                        'delay_ms': _to_float(raw),
                        'deviation_ms': _to_float(raw - cluster_mean)
                    })

        if cluster_outliers:
            cluster_issues.append({
                'cluster_id': cluster.get('cluster_id', 0),
                'mean_delay': _to_float(cluster_mean),
                'variance': _to_float(cluster_variance),
                'outlier_count': len(cluster_outliers)
            })
            total_outliers.extend(cluster_outliers)

    # Determine if variance is an issue
    variance_detected = False
    if variance_threshold <= 0:
        variance_detected = max_cluster_variance > 0.0001
    else:
        variance_detected = max_cluster_variance > variance_threshold

    result = {
        'source': source_key,
        'variance_detected': variance_detected,
        'max_variance_ms': round(_to_float(max_cluster_variance), 4),
        'chunk_count': len(accepted),
        'outlier_count': len(total_outliers),
        'outliers': total_outliers[:10],
        'cluster_count': len(stepping_clusters),
        'is_stepping': True,
        'cluster_issues': cluster_issues
    }

    if log:
        if variance_detected:
            log(f"[Sync Stability] {source_key}: Variance within stepping clusters!")
            log(f"  - Max intra-cluster variance: {max_cluster_variance:.4f}ms")
            log(f"  - {len(cluster_issues)} cluster(s) with outliers")
        else:
            log(f"[Sync Stability] {source_key}: OK - clusters internally consistent")

    return result
