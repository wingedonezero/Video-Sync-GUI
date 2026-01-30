# vsg_core/analysis/drift_detection.py
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

import numpy as np
from sklearn.cluster import DBSCAN

from ..io.runner import CommandRunner

if TYPE_CHECKING:
    from vsg_core.models import ChunkResult


def _build_cluster_diagnostics(
    accepted_chunks: list[ChunkResult],
    labels: np.ndarray,
    cluster_members: dict[int, list[int]],
    delays: np.ndarray,
    runner: CommandRunner,
    config: dict,
) -> list[dict[str, Any]]:
    """
    Builds detailed cluster composition and transition analysis.
    Returns a list of cluster info dictionaries.
    """
    verbose = config.get("stepping_diagnostics_verbose", True)

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
        start_times = [chunk.start_time for chunk in member_chunks]
        min_time = min(start_times)
        max_time = max(start_times)

        # Get chunk numbers (1-indexed for display)
        chunk_numbers = [i + 1 for i in member_indices]
        chunk_numbers.sort()

        # Get match scores for quality analysis
        match_scores = [chunk.confidence for chunk in member_chunks]
        mean_match = np.mean(match_scores)
        min_match = min(match_scores)

        cluster_info.append(
            {
                "cluster_id": label,
                "mean_delay_ms": mean_delay,
                "std_delay_ms": std_delay,
                "chunk_count": chunk_count,
                "chunk_numbers": chunk_numbers,
                "time_range": (min_time, max_time),
                "mean_match_pct": mean_match,
                "min_match_pct": min_match,
            }
        )

    # Sort by mean delay to show progression
    cluster_info.sort(key=lambda x: x["mean_delay_ms"])

    if verbose and cluster_info:
        runner._log_message("[Cluster Diagnostics] Detailed composition:")

        for i, cluster in enumerate(cluster_info):
            chunk_range = _format_chunk_range(cluster["chunk_numbers"])
            delay_jump = ""

            if i > 0:
                prev_delay = cluster_info[i - 1]["mean_delay_ms"]
                curr_delay = cluster["mean_delay_ms"]
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


def _format_chunk_range(chunk_numbers: list[int]) -> str:
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


def _analyze_transition_patterns(
    cluster_info: list[dict[str, Any]], runner: CommandRunner
):
    """Analyzes and reports patterns in delay transitions"""
    if len(cluster_info) < 2:
        return

    # Calculate all jumps
    jumps = []
    for i in range(1, len(cluster_info)):
        prev_delay = cluster_info[i - 1]["mean_delay_ms"]
        curr_delay = cluster_info[i]["mean_delay_ms"]
        jump = curr_delay - prev_delay
        jumps.append(jump)

    # Pattern analysis
    all_positive = all(j > 0 for j in jumps)
    all_negative = all(j < 0 for j in jumps)

    # Check for consistent jump sizes
    # 50ms tolerance: Jumps within ±50ms of the mean are considered "consistent"
    # This helps identify regular patterns (e.g., reel changes) vs random edits
    jump_sizes = [abs(j) for j in jumps]
    mean_jump = np.mean(jump_sizes)
    consistent_jumps = all(abs(j - mean_jump) < 50 for j in jump_sizes)

    runner._log_message("[Transition Analysis]:")

    if all_positive:
        runner._log_message(
            "  → All delays INCREASE (accumulating lag = missing content)"
        )
    elif all_negative:
        runner._log_message(
            "  → All delays DECREASE (accumulating lead = extra content)"
        )
    else:
        runner._log_message("  → Mixed pattern (some increases, some decreases)")

    if consistent_jumps and len(jumps) > 1:
        runner._log_message(
            f"  → Consistent jump size: ~{mean_jump:.0f}ms per transition"
        )
        runner._log_message(
            "  → Likely cause: Regular reel changes or commercial breaks"
        )
    else:
        runner._log_message(
            f"  → Variable jump sizes: {', '.join(f'{j:+.0f}ms' for j in jumps)}"
        )
        runner._log_message(
            "  → Likely cause: Scene-specific edits or variable content changes"
        )

    # Check for low match scores that might indicate content mismatches
    # 70% threshold: Match scores below this suggest silence or mismatched content
    # This is diagnostic only - doesn't affect processing
    low_match_clusters = [c for c in cluster_info if c["min_match_pct"] < 70]
    if low_match_clusters:
        runner._log_message(
            f"  ⚠ {len(low_match_clusters)} clusters have chunks with match < 70%"
        )
        runner._log_message(
            "  → Possible silence sections or content mismatches at transitions"
        )


def _get_video_framerate(
    video_path: str, runner: CommandRunner, tool_paths: dict
) -> float:
    """Uses ffprobe to get the video's average frame rate."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    out = runner.run(cmd, tool_paths)
    if not out or "/" not in out:
        return 0.0
    try:
        num, den = map(float, out.strip().split("/"))
        return num / den if den != 0 else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def _get_quality_thresholds(config: dict) -> dict[str, Any]:
    """
    Returns quality validation thresholds based on the selected quality mode.
    Modes: 'strict', 'normal', 'lenient', 'custom'
    """
    quality_mode = config.get("stepping_quality_mode", "normal")

    # Preset modes
    presets = {
        "strict": {
            "min_chunks_per_cluster": 3,
            "min_cluster_percentage": 10.0,
            "min_cluster_duration_s": 30.0,
            "min_match_quality_pct": 90.0,
            "min_total_clusters": 3,
        },
        "normal": {
            "min_chunks_per_cluster": 3,
            "min_cluster_percentage": 5.0,
            "min_cluster_duration_s": 20.0,
            "min_match_quality_pct": 85.0,
            "min_total_clusters": 2,
        },
        "lenient": {
            "min_chunks_per_cluster": 2,
            "min_cluster_percentage": 3.0,
            "min_cluster_duration_s": 10.0,
            "min_match_quality_pct": 75.0,
            "min_total_clusters": 2,
        },
    }

    # If custom mode, use user-configured values
    if quality_mode == "custom":
        return {
            "min_chunks_per_cluster": config.get("stepping_min_chunks_per_cluster", 3),
            "min_cluster_percentage": config.get(
                "stepping_min_cluster_percentage", 5.0
            ),
            "min_cluster_duration_s": config.get(
                "stepping_min_cluster_duration_s", 20.0
            ),
            "min_match_quality_pct": config.get("stepping_min_match_quality_pct", 85.0),
            "min_total_clusters": config.get("stepping_min_total_clusters", 2),
        }

    # Return preset or default to normal
    return presets.get(quality_mode, presets["normal"])


def _validate_cluster(
    cluster_label: int,
    cluster_members: list[int],
    accepted_chunks: list[ChunkResult],
    total_chunks: int,
    thresholds: dict[str, Any],
    chunk_duration: float = 15.0,
) -> dict[str, Any]:
    """
    Validates a single cluster against quality thresholds.
    Returns a dict with validation results and reasons.

    Args:
        chunk_duration: Duration of each chunk in seconds (from config 'scan_chunk_duration')
    """
    # Get cluster data
    cluster_size = len(cluster_members)
    cluster_percentage = (
        (cluster_size / total_chunks * 100.0) if total_chunks > 0 else 0.0
    )

    # Calculate duration
    chunk_times = [accepted_chunks[i].start_time for i in cluster_members]
    min_time = min(chunk_times)
    max_time = max(chunk_times)
    # chunk_duration comes from config, not from chunk data
    cluster_duration_s = (max_time - min_time) + chunk_duration

    # Calculate match quality
    match_qualities = [accepted_chunks[i].confidence for i in cluster_members]
    avg_match_quality = np.mean(match_qualities) if match_qualities else 0.0
    min_match_quality = min(match_qualities) if match_qualities else 0.0

    # Perform validation checks
    checks = {
        "chunks": {
            "passed": cluster_size >= thresholds["min_chunks_per_cluster"],
            "value": cluster_size,
            "threshold": thresholds["min_chunks_per_cluster"],
            "label": "Chunks",
        },
        "percentage": {
            "passed": cluster_percentage >= thresholds["min_cluster_percentage"],
            "value": cluster_percentage,
            "threshold": thresholds["min_cluster_percentage"],
            "label": "Percentage",
        },
        "duration": {
            "passed": cluster_duration_s >= thresholds["min_cluster_duration_s"],
            "value": cluster_duration_s,
            "threshold": thresholds["min_cluster_duration_s"],
            "label": "Duration",
        },
        "match_quality": {
            "passed": avg_match_quality >= thresholds["min_match_quality_pct"],
            "value": avg_match_quality,
            "threshold": thresholds["min_match_quality_pct"],
            "label": "Match quality",
        },
    }

    # Overall validation
    all_passed = all(check["passed"] for check in checks.values())
    passed_count = sum(1 for check in checks.values() if check["passed"])
    total_checks = len(checks)

    return {
        "valid": all_passed,
        "checks": checks,
        "passed_count": passed_count,
        "total_checks": total_checks,
        "cluster_size": cluster_size,
        "cluster_percentage": cluster_percentage,
        "cluster_duration_s": cluster_duration_s,
        "avg_match_quality": avg_match_quality,
        "min_match_quality": min_match_quality,
        "time_range": (min_time, max_time + chunk_duration),
    }


def _filter_clusters(
    cluster_members: dict[int, list[int]],
    accepted_chunks: list[ChunkResult],
    delays: np.ndarray,
    thresholds: dict[str, Any],
    runner: CommandRunner,
    config: dict,
) -> tuple:
    """
    Filters clusters based on quality validation.
    Returns (valid_clusters, invalid_clusters, validation_results)
    """
    total_chunks = len(accepted_chunks)
    valid_clusters = {}
    invalid_clusters = {}
    validation_results = {}

    # Get chunk duration from config (used for cluster duration calculation)
    chunk_duration = float(config.get("scan_chunk_duration", 15.0))

    for label, members in cluster_members.items():
        validation = _validate_cluster(
            label, members, accepted_chunks, total_chunks, thresholds, chunk_duration
        )
        validation_results[label] = validation

        if validation["valid"]:
            valid_clusters[label] = members
        else:
            invalid_clusters[label] = members

    return valid_clusters, invalid_clusters, validation_results


def diagnose_audio_issue(
    video_path: str,
    chunks: list[ChunkResult],
    config: dict,
    runner: CommandRunner,
    tool_paths: dict,
    codec_id: str,
) -> tuple[str, dict]:
    """
    Analyzes correlation chunks to diagnose the type of sync issue.
    Returns:
        A tuple of (diagnosis_string, details_dict).
    """
    accepted_chunks = [c for c in chunks if c.accepted]
    if len(accepted_chunks) < 6:
        return "UNIFORM", {}

    times = np.array([c.start_time for c in accepted_chunks])
    delays = np.array([c.delay_ms for c in accepted_chunks])

    # --- Test 1: Check for PAL Drift (Specific Linear Drift) ---
    framerate = _get_video_framerate(video_path, runner, tool_paths)
    is_pal_framerate = abs(framerate - 25.0) < 0.1  # PAL standard is 25fps
    if is_pal_framerate:
        slope, _ = np.polyfit(times, delays, 1)
        # PAL speedup: 23.976fps NTSC film → 25fps PAL = 40.88 ms/s drift rate
        # Formula: (25/23.976 - 1) * 1000 ≈ 40.9 ms/s
        # ±5ms tolerance accounts for encoding variations
        if abs(slope - 40.9) < 5.0:
            runner._log_message(
                f"[PAL Drift Detected] Framerate is ~25fps and audio drift rate is {slope:.2f} ms/s."
            )
            return "PAL_DRIFT", {"rate": slope}

    # --- Test 2: Check for Stepping (Clustered) ---
    # Use DBSCAN (Density-Based Spatial Clustering) to detect delay clustering
    # eps: Maximum distance (ms) between delays to be in same cluster
    # min_samples: Minimum delays required to form a cluster (reject noise)
    epsilon_ms = config.get("detection_dbscan_epsilon_ms", 20.0)
    min_samples = config.get("detection_dbscan_min_samples", 2)
    delays_reshaped = delays.reshape(-1, 1)
    db = DBSCAN(eps=epsilon_ms, min_samples=min_samples).fit(delays_reshaped)
    unique_clusters = {label for label in db.labels_ if label != -1}

    if len(unique_clusters) > 1:
        # Build cluster membership data
        cluster_sizes = {}
        cluster_members = {}  # Track which chunks belong to each cluster
        for i, label in enumerate(db.labels_):
            if label != -1:  # Ignore noise points
                cluster_sizes[label] = cluster_sizes.get(label, 0) + 1
                if label not in cluster_members:
                    cluster_members[label] = []
                cluster_members[label].append(i)

        # Get correction mode and quality thresholds
        correction_mode = config.get("stepping_correction_mode", "full")
        quality_mode = config.get("stepping_quality_mode", "normal")

        # Check if stepping correction is disabled
        if correction_mode == "disabled":
            runner._log_message(
                f"[Stepping] Found {len(unique_clusters)} timing clusters, but stepping correction is disabled."
            )
            return "UNIFORM", {}

        # Get quality thresholds based on mode
        thresholds = _get_quality_thresholds(config)

        # Log detection
        runner._log_message(
            f"[Stepping Detection] Found {len(unique_clusters)} timing clusters"
        )
        runner._log_message(
            f"[Stepping] Correction mode: {correction_mode}, Quality mode: {quality_mode}"
        )

        # Perform cluster filtering/validation
        valid_clusters, invalid_clusters, validation_results = _filter_clusters(
            cluster_members, accepted_chunks, delays, thresholds, runner, config
        )

        # Log validation results with enhanced diagnostics
        runner._log_message(f"[Quality Validation - Mode: {quality_mode}]")
        for label in sorted(cluster_members.keys()):
            validation = validation_results[label]
            members = cluster_members[label]

            # Get cluster delay info
            cluster_delays = [delays[i] for i in members]
            mean_delay = np.mean(cluster_delays)

            # Get time range
            time_start, time_end = validation["time_range"]

            # Log cluster info
            status = "ACCEPTED" if validation["valid"] else "FILTERED OUT"
            status_symbol = "✓" if validation["valid"] else "✗"

            runner._log_message(
                f"  Cluster {label+1} (@{time_start:.1f}s - {time_end:.1f}s): {mean_delay:+.0f}ms"
            )

            # Log each validation check
            for check_name, check_data in validation["checks"].items():
                check_symbol = "✓" if check_data["passed"] else "✗"
                value = check_data["value"]
                threshold = check_data["threshold"]
                label_text = check_data["label"]

                if check_name == "percentage":
                    runner._log_message(
                        f"    {check_symbol} {label_text}: {value:.1f}% (need {threshold:.1f}%+)"
                    )
                elif check_name == "duration":
                    runner._log_message(
                        f"    {check_symbol} {label_text}: {value:.1f}s (need {threshold:.1f}s+)"
                    )
                elif check_name == "match_quality":
                    runner._log_message(
                        f"    {check_symbol} {label_text}: {value:.1f}% (need {threshold:.1f}%+)"
                    )
                else:  # chunks
                    runner._log_message(
                        f"    {check_symbol} {label_text}: {int(value)} (need {int(threshold)}+)"
                    )

            runner._log_message(
                f"    → STATUS: {status} ({validation['passed_count']}/{validation['total_checks']} checks passed)"
            )

        # Build detailed cluster composition for diagnostics (for all clusters)
        cluster_details = _build_cluster_diagnostics(
            accepted_chunks, db.labels_, cluster_members, delays, runner, config
        )

        # Decide whether to accept stepping based on correction mode
        if correction_mode == "full" or correction_mode == "strict":
            # Full/Strict mode: Reject if ANY cluster is invalid
            if len(invalid_clusters) > 0:
                runner._log_message(
                    f"[Stepping Rejected] {len(invalid_clusters)}/{len(cluster_members)} clusters failed validation in '{correction_mode}' mode."
                )
                runner._log_message(
                    "  → Treating as uniform delay. Switch to 'filtered' mode to use valid clusters only."
                )
                return "UNIFORM", {}

            # Also check minimum total clusters requirement
            if len(valid_clusters) < thresholds["min_total_clusters"]:
                runner._log_message(
                    f"[Stepping Rejected] Only {len(valid_clusters)} clusters (need {thresholds['min_total_clusters']}+)."
                )
                return "UNIFORM", {}

            # All clusters passed - accept stepping
            runner._log_message(
                f"[Stepping Accepted] All {len(valid_clusters)} clusters passed validation."
            )
            return "STEPPING", {
                "clusters": len(valid_clusters),
                "cluster_details": cluster_details,
                "valid_clusters": valid_clusters,
                "invalid_clusters": invalid_clusters,
                "validation_results": validation_results,
                "correction_mode": correction_mode,
            }

        elif correction_mode == "filtered":
            # Filtered mode: Use only valid clusters, filter out invalid ones
            if len(valid_clusters) < thresholds["min_total_clusters"]:
                runner._log_message(
                    f"[Filtered Stepping Rejected] Only {len(valid_clusters)} valid clusters (need {thresholds['min_total_clusters']}+)."
                )
                return "UNIFORM", {}

            # Check fallback mode
            fallback_mode = config.get("stepping_filtered_fallback", "nearest")
            if fallback_mode == "reject" and len(invalid_clusters) > 0:
                runner._log_message(
                    f"[Filtered Stepping Rejected] Fallback mode is 'reject' and {len(invalid_clusters)} clusters were filtered."
                )
                return "UNIFORM", {}

            # Accept filtered stepping
            runner._log_message(
                f"[Filtered Stepping Accepted] Using {len(valid_clusters)}/{len(cluster_members)} valid clusters (filtered {len(invalid_clusters)})."
            )
            if len(invalid_clusters) > 0:
                runner._log_message(
                    f"  → Filtered regions will use fallback mode: '{fallback_mode}'"
                )

            return "STEPPING", {
                "clusters": len(valid_clusters),
                "cluster_details": cluster_details,
                "valid_clusters": valid_clusters,
                "invalid_clusters": invalid_clusters,
                "validation_results": validation_results,
                "correction_mode": correction_mode,
                "fallback_mode": fallback_mode,
            }

        else:
            # Unknown mode - fall back to legacy behavior
            min_cluster_size = min(cluster_sizes.values()) if cluster_sizes else 0
            MIN_CHUNKS_PER_SEGMENT = config.get("stepping_min_chunks_per_cluster", 3)

            if min_cluster_size >= MIN_CHUNKS_PER_SEGMENT:
                return "STEPPING", {
                    "clusters": len(unique_clusters),
                    "cluster_details": cluster_details,
                }
            else:
                return "UNIFORM", {}

    # --- Test 3: Check for General Linear Drift (Now Codec-Aware) ---
    slope, intercept = np.polyfit(times, delays, 1)

    # Use new settings from config
    codec_name_lower = (codec_id or "").lower()
    is_lossless = (
        "pcm" in codec_name_lower
        or "flac" in codec_name_lower
        or "truehd" in codec_name_lower
    )

    slope_threshold = (
        config.get("drift_detection_slope_threshold_lossless")
        if is_lossless
        else config.get("drift_detection_slope_threshold_lossy")
    )
    r2_threshold = (
        config.get("drift_detection_r2_threshold_lossless")
        if is_lossless
        else config.get("drift_detection_r2_threshold")
    )

    runner._log_message(
        f"[DriftDiagnosis] Codec: {codec_name_lower} (lossless={is_lossless}). Using R²>{r2_threshold:.2f}, slope>{slope_threshold:.1f} ms/s."
    )

    if abs(slope) > slope_threshold:
        y_predicted = slope * times + intercept
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", "invalid value encountered in divide")
            correlation_matrix = np.corrcoef(delays, y_predicted)
        r_squared = correlation_matrix[0, 1] ** 2

        if r_squared > r2_threshold:
            runner._log_message(
                f"[Linear Drift Detected] Delays fit a straight line with R-squared={r_squared:.3f} and slope={slope:.2f} ms/s."
            )
            return "LINEAR_DRIFT", {"rate": slope}

    # --- Default Case: Uniform Delay ---
    return "UNIFORM", {}
