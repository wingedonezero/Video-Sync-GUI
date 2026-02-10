# vsg_core/analysis/drift_detection.py
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import numpy as np
from sklearn.cluster import DBSCAN

from .types import (
    ClusterDiagnostic,
    ClusterValidation,
    DriftDiagnosis,
    QualityThresholds,
    SteppingDiagnosis,
    UniformDiagnosis,
    ValidationCheck,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..io.runner import CommandRunner
    from ..models.settings import AppSettings
    from .types import ChunkResult, DiagnosisResult


def _build_cluster_diagnostics(
    accepted_chunks: list[ChunkResult],
    labels: np.ndarray,
    cluster_members: dict[int, list[int]],
    delays: np.ndarray,
    log: Callable[[str], None],
    settings: AppSettings,
) -> list[ClusterDiagnostic]:
    """
    Builds detailed cluster composition and transition analysis.
    Returns a list of ClusterDiagnostic objects.
    """
    verbose = settings.stepping_diagnostics_verbose

    # Sort clusters by their mean delay
    cluster_info: list[ClusterDiagnostic] = []
    for label in sorted(cluster_members.keys()):
        member_indices = cluster_members[label]
        member_delays = [delays[i] for i in member_indices]
        member_chunks = [accepted_chunks[i] for i in member_indices]

        # Calculate cluster statistics
        mean_delay = float(np.mean(member_delays))
        std_delay = float(np.std(member_delays))
        chunk_count = len(member_indices)

        # Get time range for this cluster
        start_times = [chunk.start_s for chunk in member_chunks]
        min_time = min(start_times)
        max_time = max(start_times)

        # Get chunk numbers (1-indexed for display)
        chunk_numbers = sorted(i + 1 for i in member_indices)

        # Get match scores for quality analysis
        match_scores = [chunk.match_pct for chunk in member_chunks]
        mean_match = float(np.mean(match_scores))
        min_match = float(min(match_scores))

        cluster_info.append(
            ClusterDiagnostic(
                cluster_id=label,
                mean_delay_ms=mean_delay,
                std_delay_ms=std_delay,
                chunk_count=chunk_count,
                chunk_numbers=chunk_numbers,
                time_range=(min_time, max_time),
                mean_match_pct=mean_match,
                min_match_pct=min_match,
            )
        )

    # Sort by mean delay to show progression
    cluster_info.sort(key=lambda x: x.mean_delay_ms)

    if verbose and cluster_info:
        log("[Cluster Diagnostics] Detailed composition:")

        for i, cluster in enumerate(cluster_info):
            chunk_range = _format_chunk_range(cluster.chunk_numbers)
            delay_jump = ""

            if i > 0:
                prev_delay = cluster_info[i - 1].mean_delay_ms
                curr_delay = cluster.mean_delay_ms
                jump = curr_delay - prev_delay
                direction = "↑" if jump > 0 else "↓"
                delay_jump = f" [{direction}{abs(jump):+.0f}ms jump]"

            log(
                f"  Cluster {i + 1}: delay={cluster.mean_delay_ms:+.0f}±{cluster.std_delay_ms:.1f}ms, "
                f"chunks {chunk_range} (@{cluster.time_range[0]:.1f}s - @{cluster.time_range[1]:.1f}s), "
                f"match={cluster.mean_match_pct:.1f}% (min={cluster.min_match_pct:.1f}%)"
                f"{delay_jump}"
            )

        # Analyze transition patterns
        _analyze_transition_patterns(cluster_info, log)

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
    cluster_info: list[ClusterDiagnostic], log: Callable[[str], None]
) -> None:
    """Analyzes and reports patterns in delay transitions"""
    if len(cluster_info) < 2:
        return

    # Calculate all jumps
    jumps = []
    for i in range(1, len(cluster_info)):
        prev_delay = cluster_info[i - 1].mean_delay_ms
        curr_delay = cluster_info[i].mean_delay_ms
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

    log("[Transition Analysis]:")

    if all_positive:
        log("  → All delays INCREASE (accumulating lag = missing content)")
    elif all_negative:
        log("  → All delays DECREASE (accumulating lead = extra content)")
    else:
        log("  → Mixed pattern (some increases, some decreases)")

    if consistent_jumps and len(jumps) > 1:
        log(f"  → Consistent jump size: ~{mean_jump:.0f}ms per transition")
        log("  → Likely cause: Regular reel changes or commercial breaks")
    else:
        log(f"  → Variable jump sizes: {', '.join(f'{j:+.0f}ms' for j in jumps)}")
        log("  → Likely cause: Scene-specific edits or variable content changes")

    # Check for low match scores that might indicate content mismatches
    # 70% threshold: Match scores below this suggest silence or mismatched content
    # This is diagnostic only - doesn't affect processing
    low_match_clusters = [c for c in cluster_info if c.min_match_pct < 70]
    if low_match_clusters:
        log(f"  ⚠ {len(low_match_clusters)} clusters have chunks with match < 70%")
        log("  → Possible silence sections or content mismatches at transitions")


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
    raw_out = runner.run(cmd, tool_paths)
    if not raw_out or not isinstance(raw_out, str) or "/" not in raw_out:
        return 0.0
    try:
        num, den = map(float, raw_out.strip().split("/"))
        return num / den if den != 0 else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def _get_quality_thresholds(settings: AppSettings) -> QualityThresholds:
    """
    Returns quality validation thresholds based on the selected quality mode.
    Modes: 'strict', 'normal', 'lenient', 'custom'
    """
    quality_mode = settings.stepping_quality_mode

    # Preset modes
    presets: dict[str, QualityThresholds] = {
        "strict": QualityThresholds(
            min_chunks_per_cluster=3,
            min_cluster_percentage=10.0,
            min_cluster_duration_s=30.0,
            min_match_quality_pct=90.0,
            min_total_clusters=3,
        ),
        "normal": QualityThresholds(
            min_chunks_per_cluster=3,
            min_cluster_percentage=5.0,
            min_cluster_duration_s=20.0,
            min_match_quality_pct=85.0,
            min_total_clusters=2,
        ),
        "lenient": QualityThresholds(
            min_chunks_per_cluster=2,
            min_cluster_percentage=3.0,
            min_cluster_duration_s=10.0,
            min_match_quality_pct=75.0,
            min_total_clusters=2,
        ),
    }

    # If custom mode, use user-configured values
    if quality_mode == "custom":
        return QualityThresholds(
            min_chunks_per_cluster=settings.stepping_min_chunks_per_cluster,
            min_cluster_percentage=settings.stepping_min_cluster_percentage,
            min_cluster_duration_s=settings.stepping_min_cluster_duration_s,
            min_match_quality_pct=settings.stepping_min_match_quality_pct,
            min_total_clusters=settings.stepping_min_total_clusters,
        )

    # Return preset or default to normal
    return presets.get(quality_mode, presets["normal"])


def _validate_cluster(
    cluster_label: int,
    cluster_members: list[int],
    accepted_chunks: list[ChunkResult],
    total_chunks: int,
    thresholds: QualityThresholds,
    chunk_duration: float = 15.0,
) -> ClusterValidation:
    """
    Validates a single cluster against quality thresholds.

    Args:
        chunk_duration: Duration of each chunk in seconds (from config 'scan_chunk_duration')
    """
    # Get cluster data
    cluster_size = len(cluster_members)
    cluster_percentage = (
        (cluster_size / total_chunks * 100.0) if total_chunks > 0 else 0.0
    )

    # Calculate duration
    chunk_times = [accepted_chunks[i].start_s for i in cluster_members]
    min_time = min(chunk_times)
    max_time = max(chunk_times)
    # chunk_duration comes from config, not from chunk data
    cluster_duration_s = (max_time - min_time) + chunk_duration

    # Calculate match quality
    match_qualities = [accepted_chunks[i].match_pct for i in cluster_members]
    avg_match_quality = float(np.mean(match_qualities)) if match_qualities else 0.0
    min_match_quality = float(min(match_qualities)) if match_qualities else 0.0

    # Perform validation checks
    checks = {
        "chunks": ValidationCheck(
            passed=cluster_size >= thresholds.min_chunks_per_cluster,
            value=float(cluster_size),
            threshold=float(thresholds.min_chunks_per_cluster),
            label="Chunks",
        ),
        "percentage": ValidationCheck(
            passed=cluster_percentage >= thresholds.min_cluster_percentage,
            value=cluster_percentage,
            threshold=thresholds.min_cluster_percentage,
            label="Percentage",
        ),
        "duration": ValidationCheck(
            passed=cluster_duration_s >= thresholds.min_cluster_duration_s,
            value=cluster_duration_s,
            threshold=thresholds.min_cluster_duration_s,
            label="Duration",
        ),
        "match_quality": ValidationCheck(
            passed=avg_match_quality >= thresholds.min_match_quality_pct,
            value=avg_match_quality,
            threshold=thresholds.min_match_quality_pct,
            label="Match quality",
        ),
    }

    # Overall validation
    all_passed = all(check.passed for check in checks.values())
    passed_count = sum(1 for check in checks.values() if check.passed)
    total_checks = len(checks)

    return ClusterValidation(
        valid=all_passed,
        checks=checks,
        passed_count=passed_count,
        total_checks=total_checks,
        cluster_size=cluster_size,
        cluster_percentage=cluster_percentage,
        cluster_duration_s=cluster_duration_s,
        avg_match_quality=avg_match_quality,
        min_match_quality=min_match_quality,
        time_range=(min_time, max_time + chunk_duration),
    )


def _filter_clusters(
    cluster_members: dict[int, list[int]],
    accepted_chunks: list[ChunkResult],
    delays: np.ndarray,
    thresholds: QualityThresholds,
    settings: AppSettings,
) -> tuple[dict[int, list[int]], dict[int, list[int]], dict[int, ClusterValidation]]:
    """
    Filters clusters based on quality validation.
    Returns (valid_clusters, invalid_clusters, validation_results)
    """
    total_chunks = len(accepted_chunks)
    valid_clusters: dict[int, list[int]] = {}
    invalid_clusters: dict[int, list[int]] = {}
    validation_results: dict[int, ClusterValidation] = {}

    # Get chunk duration from settings (used for cluster duration calculation)
    chunk_duration = float(settings.scan_chunk_duration)

    for label, members in cluster_members.items():
        validation = _validate_cluster(
            label, members, accepted_chunks, total_chunks, thresholds, chunk_duration
        )
        validation_results[label] = validation

        if validation.valid:
            valid_clusters[label] = members
        else:
            invalid_clusters[label] = members

    return valid_clusters, invalid_clusters, validation_results


def diagnose_audio_issue(
    video_path: str,
    chunks: list[ChunkResult],
    settings: AppSettings,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
    codec_id: str,
) -> DiagnosisResult:
    """
    Analyze correlation chunks to diagnose the type of sync issue.

    Returns:
        A DiagnosisResult (UniformDiagnosis, DriftDiagnosis, or SteppingDiagnosis).
    """
    log = runner._log_message

    accepted_chunks = [c for c in chunks if c.accepted]
    if len(accepted_chunks) < 6:
        return UniformDiagnosis()

    times = np.array([c.start_s for c in accepted_chunks])
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
            log(
                f"[PAL Drift Detected] Framerate is ~25fps and audio drift rate is {slope:.2f} ms/s."
            )
            return DriftDiagnosis(diagnosis="PAL_DRIFT", rate=float(slope))

    # --- Test 2: Check for Stepping (Clustered) ---
    # Use DBSCAN (Density-Based Spatial Clustering) to detect delay clustering
    # eps: Maximum distance (ms) between delays to be in same cluster
    # min_samples: Minimum delays required to form a cluster (reject noise)
    epsilon_ms = settings.detection_dbscan_epsilon_ms
    min_samples = settings.detection_dbscan_min_samples
    delays_reshaped = delays.reshape(-1, 1)
    db = DBSCAN(eps=epsilon_ms, min_samples=min_samples).fit(delays_reshaped)
    unique_clusters = {label for label in db.labels_ if label != -1}

    if len(unique_clusters) > 1:
        # Build cluster membership data
        cluster_sizes: dict[int, int] = {}
        cluster_members: dict[int, list[int]] = {}
        for i, label in enumerate(db.labels_):
            if label != -1:  # Ignore noise points
                cluster_sizes[label] = cluster_sizes.get(label, 0) + 1
                if label not in cluster_members:
                    cluster_members[label] = []
                cluster_members[label].append(i)

        # Get correction mode and quality thresholds
        correction_mode = settings.stepping_correction_mode
        quality_mode = settings.stepping_quality_mode

        # Check if stepping correction is disabled
        if correction_mode == "disabled":
            log(
                f"[Stepping] Found {len(unique_clusters)} timing clusters, but stepping correction is disabled."
            )
            return UniformDiagnosis()

        # Get quality thresholds based on mode
        thresholds = _get_quality_thresholds(settings)

        # Log detection
        log(f"[Stepping Detection] Found {len(unique_clusters)} timing clusters")
        log(
            f"[Stepping] Correction mode: {correction_mode}, Quality mode: {quality_mode}"
        )

        # Perform cluster filtering/validation
        valid_clusters, invalid_clusters, validation_results = _filter_clusters(
            cluster_members, accepted_chunks, delays, thresholds, settings
        )

        # Log validation results with enhanced diagnostics
        log(f"[Quality Validation - Mode: {quality_mode}]")
        for label in sorted(cluster_members.keys()):
            validation = validation_results[label]
            members = cluster_members[label]

            # Get cluster delay info
            cluster_delays = [delays[i] for i in members]
            mean_delay = np.mean(cluster_delays)

            # Get time range
            time_start, time_end = validation.time_range

            # Log cluster info
            status = "ACCEPTED" if validation.valid else "FILTERED OUT"

            log(
                f"  Cluster {label + 1} (@{time_start:.1f}s - {time_end:.1f}s): {mean_delay:+.0f}ms"
            )

            # Log each validation check
            for check_name, check_data in validation.checks.items():
                check_symbol = "✓" if check_data.passed else "✗"
                value = check_data.value
                threshold = check_data.threshold
                label_text = check_data.label

                if check_name == "percentage":
                    log(
                        f"    {check_symbol} {label_text}: {value:.1f}% (need {threshold:.1f}%+)"
                    )
                elif check_name == "duration":
                    log(
                        f"    {check_symbol} {label_text}: {value:.1f}s (need {threshold:.1f}s+)"
                    )
                elif check_name == "match_quality":
                    log(
                        f"    {check_symbol} {label_text}: {value:.1f}% (need {threshold:.1f}%+)"
                    )
                else:  # chunks
                    log(
                        f"    {check_symbol} {label_text}: {int(value)} (need {int(threshold)}+)"
                    )

            log(
                f"    → STATUS: {status} ({validation.passed_count}/{validation.total_checks} checks passed)"
            )

        # Build detailed cluster composition for diagnostics (for all clusters)
        cluster_details = _build_cluster_diagnostics(
            accepted_chunks, db.labels_, cluster_members, delays, log, settings
        )

        # Decide whether to accept stepping based on correction mode
        if correction_mode in {"full", "strict"}:
            # Full/Strict mode: Reject if ANY cluster is invalid
            if len(invalid_clusters) > 0:
                log(
                    f"[Stepping Rejected] {len(invalid_clusters)}/{len(cluster_members)} clusters failed validation in '{correction_mode}' mode."
                )
                log(
                    "  → Treating as uniform delay. Switch to 'filtered' mode to use valid clusters only."
                )
                return UniformDiagnosis()

            # Also check minimum total clusters requirement
            if len(valid_clusters) < thresholds.min_total_clusters:
                log(
                    f"[Stepping Rejected] Only {len(valid_clusters)} clusters (need {thresholds.min_total_clusters}+)."
                )
                return UniformDiagnosis()

            # All clusters passed - accept stepping
            log(
                f"[Stepping Accepted] All {len(valid_clusters)} clusters passed validation."
            )
            return SteppingDiagnosis(
                cluster_count=len(valid_clusters),
                cluster_details=cluster_details,
                valid_clusters=valid_clusters,
                invalid_clusters=invalid_clusters,
                validation_results=validation_results,
                correction_mode=correction_mode,
            )

        elif correction_mode == "filtered":
            # Filtered mode: Use only valid clusters, filter out invalid ones
            if len(valid_clusters) < thresholds.min_total_clusters:
                log(
                    f"[Filtered Stepping Rejected] Only {len(valid_clusters)} valid clusters (need {thresholds.min_total_clusters}+)."
                )
                return UniformDiagnosis()

            # Check fallback mode
            fallback_mode = settings.stepping_filtered_fallback
            if fallback_mode == "reject" and len(invalid_clusters) > 0:
                log(
                    f"[Filtered Stepping Rejected] Fallback mode is 'reject' and {len(invalid_clusters)} clusters were filtered."
                )
                return UniformDiagnosis()

            # Accept filtered stepping
            log(
                f"[Filtered Stepping Accepted] Using {len(valid_clusters)}/{len(cluster_members)} valid clusters (filtered {len(invalid_clusters)})."
            )
            if len(invalid_clusters) > 0:
                log(f"  → Filtered regions will use fallback mode: '{fallback_mode}'")

            return SteppingDiagnosis(
                cluster_count=len(valid_clusters),
                cluster_details=cluster_details,
                valid_clusters=valid_clusters,
                invalid_clusters=invalid_clusters,
                validation_results=validation_results,
                correction_mode=correction_mode,
                fallback_mode=fallback_mode,
            )

        else:
            # Unknown mode - fall back to legacy behavior
            min_cluster_size = min(cluster_sizes.values()) if cluster_sizes else 0
            MIN_CHUNKS_PER_SEGMENT = settings.stepping_min_chunks_per_cluster

            if min_cluster_size >= MIN_CHUNKS_PER_SEGMENT:
                return SteppingDiagnosis(
                    cluster_count=len(unique_clusters),
                    cluster_details=cluster_details,
                )
            else:
                return UniformDiagnosis()

    # --- Test 3: Check for General Linear Drift (Now Codec-Aware) ---
    slope, intercept = np.polyfit(times, delays, 1)

    # Use new settings
    codec_name_lower = (codec_id or "").lower()
    is_lossless = (
        "pcm" in codec_name_lower
        or "flac" in codec_name_lower
        or "truehd" in codec_name_lower
    )

    slope_threshold = (
        settings.drift_detection_slope_threshold_lossless
        if is_lossless
        else settings.drift_detection_slope_threshold_lossy
    )
    r2_threshold = (
        settings.drift_detection_r2_threshold_lossless
        if is_lossless
        else settings.drift_detection_r2_threshold
    )

    log(
        f"[DriftDiagnosis] Codec: {codec_name_lower} (lossless={is_lossless}). Using R²>{r2_threshold:.2f}, slope>{slope_threshold:.1f} ms/s."
    )

    if abs(slope) > slope_threshold:
        y_predicted = slope * times + intercept
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", "invalid value encountered in divide")
            correlation_matrix = np.corrcoef(delays, y_predicted)
        r_squared = correlation_matrix[0, 1] ** 2

        if r_squared > r2_threshold:
            log(
                f"[Linear Drift Detected] Delays fit a straight line with R-squared={r_squared:.3f} and slope={slope:.2f} ms/s."
            )
            return DriftDiagnosis(diagnosis="LINEAR_DRIFT", rate=float(slope))

    # --- Default Case: Uniform Delay ---
    return UniformDiagnosis()
