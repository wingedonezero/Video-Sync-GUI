# vsg_core/analysis/drift_detection.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from typing import List, Dict, Any

import numpy as np
from sklearn.cluster import DBSCAN

from ..io.runner import CommandRunner

def _build_cluster_diagnostics(
    accepted_chunks: List[Dict[str, Any]],
    labels: np.ndarray,
    cluster_members: Dict[int, List[int]],
    delays: np.ndarray,
    runner: CommandRunner,
    config: Dict
) -> List[Dict[str, Any]]:
    """
    Builds detailed cluster composition and transition analysis.
    Returns a list of cluster info dictionaries.
    """
    verbose = config.get('stepping_diagnostics_verbose', True)

    # Sort clusters by their mean delay
    cluster_info = []
    for label in sorted(cluster_members.keys()):
        member_indices = cluster_members[label]
        member_delays = [delays[i] for i in member_indices]
        member_chunks = [accepted_chunks[i] for i in member_indices]

        # Calculate cluster statistics
        mean_delay = np.mean(member_delays)
        std_delay = np.std(member_delays)
        chunk_count = len(member_indices)

        # Get time range for this cluster
        start_times = [chunk['start'] for chunk in member_chunks]
        min_time = min(start_times)
        max_time = max(start_times)

        # Get chunk numbers (1-indexed for display)
        chunk_numbers = [i + 1 for i in member_indices]
        chunk_numbers.sort()

        # Get match scores for quality analysis
        match_scores = [chunk.get('match_pct', 0) for chunk in member_chunks]
        mean_match = np.mean(match_scores)
        min_match = min(match_scores)

        cluster_info.append({
            'cluster_id': label,
            'mean_delay_ms': mean_delay,
            'std_delay_ms': std_delay,
            'chunk_count': chunk_count,
            'chunk_numbers': chunk_numbers,
            'time_range': (min_time, max_time),
            'mean_match_pct': mean_match,
            'min_match_pct': min_match
        })

    # Sort by mean delay to show progression
    cluster_info.sort(key=lambda x: x['mean_delay_ms'])

    if verbose and cluster_info:
        runner._log_message("[Cluster Diagnostics] Detailed composition:")

        for i, cluster in enumerate(cluster_info):
            chunk_range = _format_chunk_range(cluster['chunk_numbers'])
            delay_jump = ""

            if i > 0:
                prev_delay = cluster_info[i-1]['mean_delay_ms']
                curr_delay = cluster['mean_delay_ms']
                jump = curr_delay - prev_delay
                direction = "↑" if jump > 0 else "↓"
                delay_jump = f" [{direction}{abs(jump):+.0f}ms jump]"

            runner._log_message(
                f"  Cluster {i+1}: delay={cluster['mean_delay_ms']:+.0f}±{cluster['std_delay_ms']:.1f}ms, "
                f"chunks {chunk_range} (@{cluster['time_range'][0]:.1f}s - @{cluster['time_range'][1]:.1f}s), "
                f"match={cluster['mean_match_pct']:.1f}% (min={cluster['min_match_pct']:.1f}%)"
                f"{delay_jump}"
            )

        # Analyze transition patterns
        _analyze_transition_patterns(cluster_info, runner)

    return cluster_info

def _format_chunk_range(chunk_numbers: List[int]) -> str:
    """Formats chunk numbers as ranges (e.g., '1-3,5-25,30-48')"""
    if not chunk_numbers:
        return ""

    ranges = []
    start = chunk_numbers[0]
    end = chunk_numbers[0]

    for num in chunk_numbers[1:]:
        if num == end + 1:
            end = num
        else:
            ranges.append(f"{start}-{end}" if start != end else f"{start}")
            start = num
            end = num

    ranges.append(f"{start}-{end}" if start != end else f"{start}")
    return ",".join(ranges)

def _analyze_transition_patterns(cluster_info: List[Dict[str, Any]], runner: CommandRunner):
    """Analyzes and reports patterns in delay transitions"""
    if len(cluster_info) < 2:
        return

    # Calculate all jumps
    jumps = []
    for i in range(1, len(cluster_info)):
        prev_delay = cluster_info[i-1]['mean_delay_ms']
        curr_delay = cluster_info[i]['mean_delay_ms']
        jump = curr_delay - prev_delay
        jumps.append(jump)

    # Pattern analysis
    all_positive = all(j > 0 for j in jumps)
    all_negative = all(j < 0 for j in jumps)

    # Check for consistent jump sizes (within 50ms tolerance)
    jump_sizes = [abs(j) for j in jumps]
    mean_jump = np.mean(jump_sizes)
    consistent_jumps = all(abs(j - mean_jump) < 50 for j in jump_sizes)

    runner._log_message("[Transition Analysis]:")

    if all_positive:
        runner._log_message(f"  → All delays INCREASE (accumulating lag = missing content)")
    elif all_negative:
        runner._log_message(f"  → All delays DECREASE (accumulating lead = extra content)")
    else:
        runner._log_message(f"  → Mixed pattern (some increases, some decreases)")

    if consistent_jumps and len(jumps) > 1:
        runner._log_message(f"  → Consistent jump size: ~{mean_jump:.0f}ms per transition")
        runner._log_message(f"  → Likely cause: Regular reel changes or commercial breaks")
    else:
        runner._log_message(f"  → Variable jump sizes: {', '.join(f'{j:+.0f}ms' for j in jumps)}")
        runner._log_message(f"  → Likely cause: Scene-specific edits or variable content changes")

    # Check for low match scores that might indicate content mismatches
    low_match_clusters = [c for c in cluster_info if c['min_match_pct'] < 70]
    if low_match_clusters:
        runner._log_message(f"  ⚠ {len(low_match_clusters)} clusters have chunks with match < 70%")
        runner._log_message(f"  → Possible silence sections or content mismatches at transitions")

def _get_video_framerate(video_path: str, runner: CommandRunner, tool_paths: dict) -> float:
    """Uses ffprobe to get the video's average frame rate."""
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=avg_frame_rate',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(video_path)
    ]
    out = runner.run(cmd, tool_paths)
    if not out or '/' not in out:
        return 0.0
    try:
        num, den = map(float, out.strip().split('/'))
        return num / den if den != 0 else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0

def diagnose_audio_issue(
    video_path: str,
    chunks: List[Dict[str, Any]],
    config: Dict,
    runner: CommandRunner,
    tool_paths: dict,
    codec_id: str
) -> (str, Dict):
    """
    Analyzes correlation chunks to diagnose the type of sync issue.
    Returns:
        A tuple of (diagnosis_string, details_dict).
    """
    accepted_chunks = [c for c in chunks if c.get('accepted', False)]
    if len(accepted_chunks) < 6:
        return "UNIFORM", {}

    times = np.array([c['start'] for c in accepted_chunks])
    delays = np.array([c['delay'] for c in accepted_chunks])

    # --- Test 1: Check for PAL Drift (Specific Linear Drift) ---
    framerate = _get_video_framerate(video_path, runner, tool_paths)
    is_pal_framerate = abs(framerate - 25.0) < 0.1
    if is_pal_framerate:
        slope, _ = np.polyfit(times, delays, 1)
        if abs(slope - 40.9) < 5.0:
            runner._log_message(f"[PAL Drift Detected] Framerate is ~25fps and audio drift rate is {slope:.2f} ms/s.")
            return "PAL_DRIFT", {"rate": slope}

    # --- Test 2: Check for Stepping (Clustered) ---
    epsilon_ms = config.get('detection_dbscan_epsilon_ms', 20.0)
    min_samples = config.get('detection_dbscan_min_samples', 2)
    delays_reshaped = delays.reshape(-1, 1)
    db = DBSCAN(eps=epsilon_ms, min_samples=min_samples).fit(delays_reshaped)
    unique_clusters = set(label for label in db.labels_ if label != -1)

    if len(unique_clusters) > 1:
        # CRITICAL FIX: Verify each cluster has enough chunks before declaring stepping
        # False positives occur when only 1-2 chunks differ at the end (credits, etc.)
        cluster_sizes = {}
        cluster_members = {}  # Track which chunks belong to each cluster
        for i, label in enumerate(db.labels_):
            if label != -1:  # Ignore noise points
                cluster_sizes[label] = cluster_sizes.get(label, 0) + 1
                if label not in cluster_members:
                    cluster_members[label] = []
                cluster_members[label].append(i)

        # Get the smallest cluster size
        min_cluster_size = min(cluster_sizes.values()) if cluster_sizes else 0

        # CONFIGURABLE SAFEGUARD: Require minimum chunks per cluster (default 3)
        # Real stepping episodes span multiple chunks; 1-2 chunk differences are usually noise/credits
        MIN_CHUNKS_PER_SEGMENT = config.get('stepping_min_cluster_size', 3)

        # Build detailed cluster composition for diagnostics
        cluster_details = _build_cluster_diagnostics(
            accepted_chunks, db.labels_, cluster_members, delays, runner, config
        )

        if min_cluster_size >= MIN_CHUNKS_PER_SEGMENT:
            runner._log_message(
                f"[Stepping Detected] Found {len(unique_clusters)} distinct timing clusters "
                f"(smallest has {min_cluster_size} chunks)."
            )
            return "STEPPING", {
                "clusters": len(unique_clusters),
                "min_cluster_size": min_cluster_size,
                "cluster_details": cluster_details
            }
        else:
            # Not enough evidence - likely end credits or brief scene change
            runner._log_message(
                f"[Stepping] Found {len(unique_clusters)} timing clusters, but smallest cluster "
                f"has only {min_cluster_size} chunks (need {MIN_CHUNKS_PER_SEGMENT}+). "
                f"Likely end credits or brief scene change - treating as uniform delay."
            )
            # Fall through to check for linear drift instead

    # --- Test 3: Check for General Linear Drift (Now Codec-Aware) ---
    slope, intercept = np.polyfit(times, delays, 1)

    # Use new settings from config
    codec_name_lower = (codec_id or '').lower()
    is_lossless = 'pcm' in codec_name_lower or 'flac' in codec_name_lower or 'truehd' in codec_name_lower

    slope_threshold = config.get('drift_detection_slope_threshold_lossless') if is_lossless else config.get('drift_detection_slope_threshold_lossy')
    r2_threshold = config.get('drift_detection_r2_threshold_lossless') if is_lossless else config.get('drift_detection_r2_threshold')

    runner._log_message(f"[DriftDiagnosis] Codec: {codec_name_lower} (lossless={is_lossless}). Using R²>{r2_threshold:.2f}, slope>{slope_threshold:.1f} ms/s.")

    if abs(slope) > slope_threshold:
        y_predicted = slope * times + intercept
        correlation_matrix = np.corrcoef(delays, y_predicted)
        r_squared = correlation_matrix[0, 1]**2

        if r_squared > r2_threshold:
            runner._log_message(f"[Linear Drift Detected] Delays fit a straight line with R-squared={r_squared:.3f} and slope={slope:.2f} ms/s.")
            return "LINEAR_DRIFT", {"rate": slope}

    # --- Default Case: Uniform Delay ---
    return "UNIFORM", {}
