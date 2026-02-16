# vsg_core/subtitles/sync_mode_plugins/video_verified/verification.py
"""
Final verification pass for video-verified sync.

After the search phase picks a winning frame offset, this module runs
an independent verification using NEW checkpoint times (different from
search) and multi-metric comparison to produce a confidence verdict.
"""

from __future__ import annotations

from typing import Any

from .quality import normalize_frame_pair


def run_final_verification(
    best_frame_offset: int,
    source_reader,
    target_reader,
    source_duration: float,
    source_frame_duration_ms: float,
    target_frame_duration_ms: float,
    hash_algorithm: str,
    hash_size: int,
    hash_threshold: int,
    ssim_threshold: int | None,
    use_global_ssim: bool,
    num_verification_points: int = 15,
    checkpoint_times_used: list[float] | None = None,
    metric_agreement: int = 3,
    log=None,
) -> dict[str, Any]:
    """
    Run a final verification pass on the winning frame offset.

    Uses independent checkpoint times (different from search phase) and
    multi-metric comparison to cross-validate the result.

    Args:
        best_frame_offset: The winning frame offset from search phase
        source_reader: VideoReader for source video
        target_reader: VideoReader for target video
        source_duration: Total source duration in ms
        source_frame_duration_ms: Source frame duration in ms
        target_frame_duration_ms: Target frame duration in ms
        hash_algorithm: Hash algorithm for phash
        hash_size: Hash size for phash
        hash_threshold: Max hamming distance for phash match
        ssim_threshold: Max SSIM distance for match
        use_global_ssim: Use global SSIM (for interlaced content)
        num_verification_points: Number of verification checkpoints (default 15)
        checkpoint_times_used: Checkpoint times from search phase (to avoid reuse)
        metric_agreement: Number of metrics that agree on winner (from search)
        log: Logging function

    Returns:
        Dict with verification results including confidence verdict
    """
    from ...frame_utils import compare_frames_multi

    def _log(msg: str):
        if log:
            log(msg)

    eff_ssim_thresh = ssim_threshold if ssim_threshold is not None else 10
    eff_mse_thresh = 5

    # Generate verification checkpoint times that differ from search checkpoints.
    # Use a different distribution: offset by half-interval from search positions.
    margin_pct = 5  # 5% to 95% (wider than search's 10%-90%)
    start_pct = margin_pct
    end_pct = 100 - margin_pct
    span_pct = end_pct - start_pct

    verify_times = []
    for i in range(num_verification_points):
        # Offset each point by 0.3 of the interval to avoid overlapping search CPs
        pos = start_pct + span_pct * (i + 0.3) / num_verification_points
        time_ms = source_duration * pos / 100
        verify_times.append(time_ms)

    # Track per-point results
    results = []
    phash_matched = 0
    ssim_matched = 0
    mse_matched = 0
    phash_exact = 0
    total_tested = 0

    for vt_ms in verify_times:
        # Source frame at verification time
        ts_frame = source_reader.get_frame_index_for_time(vt_ms)
        if ts_frame is not None:
            source_idx = ts_frame
        else:
            source_idx = int(vt_ms / source_frame_duration_ms)

        # Target frame with offset (TIME-based, same as search)
        offset_time_ms = best_frame_offset * source_frame_duration_ms
        target_time_ms = vt_ms + offset_time_ms

        ts_tgt = target_reader.get_frame_index_for_time(target_time_ms)
        if ts_tgt is not None:
            target_idx = ts_tgt
        else:
            target_idx = int(target_time_ms / target_frame_duration_ms)

        if target_idx < 0:
            continue

        try:
            source_frame = source_reader.get_frame_at_index(source_idx)
            target_frame = target_reader.get_frame_at_index(target_idx)

            if source_frame is None or target_frame is None:
                continue

            source_frame, target_frame = normalize_frame_pair(
                source_frame, target_frame
            )

            multi = compare_frames_multi(
                source_frame,
                target_frame,
                hash_algorithm=hash_algorithm,
                hash_size=hash_size,
                hash_threshold=hash_threshold,
                ssim_threshold=eff_ssim_thresh,
                mse_threshold=eff_mse_thresh,
                use_global_ssim=use_global_ssim,
            )

            total_tested += 1
            if multi.phash_match:
                phash_matched += 1
            if multi.phash_distance == 0:
                phash_exact += 1
            if multi.ssim_match:
                ssim_matched += 1
            if multi.mse_match:
                mse_matched += 1

            results.append(
                {
                    "time_ms": vt_ms,
                    "source_idx": source_idx,
                    "target_idx": target_idx,
                    "phash_distance": multi.phash_distance,
                    "ssim_distance": multi.ssim_distance,
                    "mse_value": multi.mse_value,
                    "phash_match": multi.phash_match,
                    "ssim_match": multi.ssim_match,
                    "mse_match": multi.mse_match,
                }
            )

        except Exception:
            continue

    # Compute match rates
    if total_tested == 0:
        return {
            "confidence": "LOW",
            "frames_matched": 0,
            "frames_tested": 0,
            "match_rate": 0.0,
            "phash_exact": 0,
            "phash_matched": 0,
            "ssim_matched": 0,
            "mse_matched": 0,
            "metric_agreement": metric_agreement,
            "results": [],
        }

    # "frames_matched" = matched on SSIM (the most informative single metric)
    frames_matched = ssim_matched
    match_rate = frames_matched / total_tested

    # Confidence verdict
    if match_rate >= 0.90 and metric_agreement == 3:
        confidence = "HIGH"
    elif match_rate >= 0.70 and metric_agreement >= 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "confidence": confidence,
        "frames_matched": frames_matched,
        "frames_tested": total_tested,
        "match_rate": match_rate,
        "phash_exact": phash_exact,
        "phash_matched": phash_matched,
        "ssim_matched": ssim_matched,
        "mse_matched": mse_matched,
        "metric_agreement": metric_agreement,
        "results": results,
    }
