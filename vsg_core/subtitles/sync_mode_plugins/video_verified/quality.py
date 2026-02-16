# vsg_core/subtitles/sync_mode_plugins/video_verified/quality.py
"""
Frame quality measurement and sequence verification for video-verified sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .offset import get_vfr_frame_for_time

if TYPE_CHECKING:
    from PIL import Image


@dataclass(slots=True)
class SequenceResult:
    """Result of verifying a sequence of consecutive frames."""

    matched: int  # Frames matching on primary metric
    avg_distance: float  # Average primary metric distance
    distances: list[int]  # Per-frame primary metric distances
    total_tested: int  # Frames actually compared
    phash_exact: int  # Frames with phash hamming distance = 0
    phash_distances: list[int]  # Per-frame phash distances
    ssim_distances: list[float]  # Per-frame SSIM distances
    mse_values: list[float]  # Per-frame raw MSE values


def normalize_frame_pair(
    source_frame: Image.Image, target_frame: Image.Image
) -> tuple[Image.Image, Image.Image]:
    """
    Normalize two frames to the same resolution for robust comparison.

    Only resizes when frames differ in size. When they do, resizes BOTH to a
    standard comparison resolution (320x240) to avoid aspect ratio distortion
    from resizing one to match the other's non-standard dimensions.

    For same-size frames, returns them unchanged (zero overhead for CFR
    same-source comparisons).
    """
    if source_frame.size == target_frame.size:
        return source_frame, target_frame

    from PIL import Image as PILImage

    # Standard comparison size — small enough to smooth artifacts,
    # large enough to preserve structural content for SSIM/hashing
    target_size = (320, 240)
    source_norm = source_frame.resize(target_size, PILImage.Resampling.LANCZOS)
    target_norm = target_frame.resize(target_size, PILImage.Resampling.LANCZOS)
    return source_norm, target_norm


def verify_frame_sequence(
    source_start_idx: int,
    target_start_idx: int,
    sequence_length: int,
    source_reader,
    target_reader,
    hash_algorithm: str,
    hash_size: int,
    hash_threshold: int,
    comparison_method: str = "hash",
    ssim_threshold: int | None = None,
    ivtc_tolerance: int = 0,
    use_global_ssim: bool = False,
) -> SequenceResult:
    """
    Verify that a sequence of consecutive frames match between source and target.

    Uses compare_frames_multi() to compute ALL metrics (phash, SSIM, MSE) for
    each frame pair. The primary metric (determined by comparison_method) is used
    for the matched count and threshold check, while all metrics are collected.

    This is the key to accurate offset detection - if the offset is correct,
    then source[N], source[N+1], source[N+2], ... should match
    target[N+offset], target[N+offset+1], target[N+offset+2], ...

    For IVTC content, ivtc_tolerance allows ±N frame tolerance per step to
    handle VDecimate drift (different encodes drop different frames).

    Args:
        source_start_idx: Starting frame index in source
        target_start_idx: Starting frame index in target (= source_start + offset)
        sequence_length: Number of consecutive frames to verify
        source_reader: VideoReader for source
        target_reader: VideoReader for target
        hash_algorithm: Hash algorithm to use
        hash_size: Hash size
        hash_threshold: Maximum distance for a hash match
        comparison_method: 'hash', 'ssim', or 'mse' — determines primary metric
        ssim_threshold: Maximum SSIM/MSE distance for a match. If None, uses
            defaults (ssim=10, mse=5).
        ivtc_tolerance: Frame tolerance for IVTC content (0=exact, 1=±1 frame)
        use_global_ssim: Use global SSIM (better for interlaced content)

    Returns:
        SequenceResult with per-frame data for all metrics
    """
    from ...frame_utils import compare_frames_multi

    # Determine effective thresholds
    eff_ssim_thresh = ssim_threshold if ssim_threshold is not None else 10
    eff_mse_thresh = 5  # default MSE distance threshold

    matched = 0
    distances: list[int] = []
    phash_exact = 0
    phash_distances: list[int] = []
    ssim_distances: list[float] = []
    mse_values: list[float] = []
    total_tested = 0

    for i in range(sequence_length):
        source_idx = source_start_idx + i

        # For IVTC content, try ±tolerance around the expected target frame
        target_candidates = [target_start_idx + i]
        if ivtc_tolerance > 0:
            for delta in range(1, ivtc_tolerance + 1):
                target_candidates.append(target_start_idx + i + delta)
                target_candidates.append(target_start_idx + i - delta)

        best_multi = None
        best_primary_dist = float("inf")
        best_match = False

        for target_idx in target_candidates:
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

                # Determine primary metric distance and match
                if comparison_method == "ssim":
                    primary_dist = multi.ssim_distance
                    is_match = multi.ssim_match
                elif comparison_method == "mse":
                    primary_dist = multi.mse_distance
                    is_match = multi.mse_match
                else:  # hash
                    primary_dist = multi.phash_distance
                    is_match = multi.phash_match

                if primary_dist < best_primary_dist:
                    best_primary_dist = primary_dist
                    best_match = is_match
                    best_multi = multi

            except Exception:
                continue

        if best_multi is not None:
            total_tested += 1
            distances.append(int(best_primary_dist))
            phash_distances.append(best_multi.phash_distance)
            ssim_distances.append(best_multi.ssim_distance)
            mse_values.append(best_multi.mse_value)

            if best_multi.phash_distance == 0:
                phash_exact += 1
            if best_match:
                matched += 1

    avg_dist = sum(distances) / len(distances) if distances else float("inf")
    return SequenceResult(
        matched=matched,
        avg_distance=avg_dist,
        distances=distances,
        total_tested=total_tested,
        phash_exact=phash_exact,
        phash_distances=phash_distances,
        ssim_distances=ssim_distances,
        mse_values=mse_values,
    )


def measure_frame_offset_quality(
    frame_offset: int,
    checkpoint_times: list[float],
    source_reader,
    target_reader,
    fps: float,
    source_frame_duration_ms: float,
    target_frame_duration_ms: float,
    window_radius: int,
    hash_algorithm: str,
    hash_size: int,
    hash_threshold: int,
    comparison_method: str,
    log,
    sequence_verify_length: int = 10,
    ssim_threshold: int | None = None,
    ivtc_tolerance: int = 0,
    use_global_ssim: bool = False,
) -> dict[str, Any]:
    """
    Measure quality of a candidate frame offset using multi-metric sequence verification.

    Algorithm:
    1. At each checkpoint, compare source frame N vs target frame N+offset using ALL
       metrics (phash, SSIM, MSE) via compare_frames_multi()
    2. Verify with SEQUENCE of consecutive frames (also multi-metric)
    3. Primary metric (from comparison_method) determines sequence_verified status
    4. All metrics are collected for cross-validation and logging

    Returns:
        Dict with score, matched count, avg_distance, sequence_verified count,
        match_details, per_checkpoint_summary, and frame counts for all metrics.
    """
    from ...frame_utils import compare_frames_multi

    # Determine effective thresholds
    eff_ssim_thresh = ssim_threshold if ssim_threshold is not None else 10
    eff_mse_thresh = 5  # default MSE distance threshold

    total_score = 0.0
    matched_count = 0
    sequence_verified_count = 0
    distances: list[float] = []
    mse_values: list[float] = []
    match_details = []
    per_checkpoint_summary = []

    # Aggregate frame counts across all checkpoints
    total_frames_tested = 0
    total_frames_matched = 0  # matched on primary metric
    total_phash_exact = 0

    # Debug: log frame mapping details for first candidate only
    if frame_offset == 0:
        src_fps_actual = getattr(source_reader, "fps", 0)
        tgt_fps_actual = getattr(target_reader, "fps", 0)
        src_soft_tc = getattr(source_reader, "is_soft_telecine", False)
        tgt_soft_tc = getattr(target_reader, "is_soft_telecine", False)
        src_di = getattr(source_reader, "deinterlace_applied", False)
        tgt_di = getattr(target_reader, "deinterlace_applied", False)
        src_frames = (
            len(source_reader.vs_clip)
            if getattr(source_reader, "vs_clip", None)
            else "?"
        )
        tgt_frames = (
            len(target_reader.vs_clip)
            if getattr(target_reader, "vs_clip", None)
            else "?"
        )
        log(
            f"[VideoVerified] DEBUG readers: "
            f"src(fps={src_fps_actual:.3f}, soft_tc={src_soft_tc}, di={src_di}, frames={src_frames}) "
            f"tgt(fps={tgt_fps_actual:.3f}, soft_tc={tgt_soft_tc}, di={tgt_di}, frames={tgt_frames})"
        )
        log(
            f"[VideoVerified] DEBUG frame_duration: "
            f"src={source_frame_duration_ms:.3f}ms, tgt={target_frame_duration_ms:.3f}ms"
        )

    for checkpoint_ms in checkpoint_times:
        # Source frame at checkpoint time
        ts_frame = source_reader.get_frame_index_for_time(checkpoint_ms)
        if ts_frame is not None:
            source_frame_idx = ts_frame
        else:
            is_source_vfr = getattr(source_reader, "is_soft_telecine", False)
            source_path = getattr(source_reader, "video_path", "")
            vfr_frame = get_vfr_frame_for_time(
                source_path, checkpoint_ms, is_source_vfr, log
            )
            if vfr_frame is not None:
                source_frame_idx = vfr_frame
            else:
                source_frame_idx = int(checkpoint_ms / source_frame_duration_ms)

        # Target frame with this offset (TIME-based)
        offset_time_ms = frame_offset * source_frame_duration_ms
        target_time_ms = checkpoint_ms + offset_time_ms

        ts_tgt = target_reader.get_frame_index_for_time(target_time_ms)
        if ts_tgt is not None:
            target_frame_idx = ts_tgt
        else:
            target_frame_idx = int(target_time_ms / target_frame_duration_ms)

        if target_frame_idx < 0:
            continue

        # Debug: log frame indices for first candidate
        if frame_offset == 0:
            log(
                f"[VideoVerified] DEBUG checkpoint {checkpoint_ms:.0f}ms: "
                f"src_frame={source_frame_idx}, tgt_frame={target_frame_idx}"
            )

        try:
            # Get the initial frame pair
            source_frame = source_reader.get_frame_at_index(source_frame_idx)

            # Debug: save first checkpoint frames at offset 0
            if frame_offset == 0 and checkpoint_ms == checkpoint_times[0]:
                try:
                    import tempfile

                    dbg_dir = Path(tempfile.gettempdir()) / "vsg_debug_frames"
                    dbg_dir.mkdir(exist_ok=True)
                    if source_frame is not None:
                        source_frame.save(dbg_dir / f"src_{source_frame_idx}.png")
                    tgt_dbg = target_reader.get_frame_at_index(target_frame_idx)
                    if tgt_dbg is not None:
                        tgt_dbg.save(dbg_dir / f"tgt_{target_frame_idx}.png")
                    log(f"[VideoVerified] DEBUG: saved frames to {dbg_dir}")
                except Exception as dbg_err:
                    log(f"[VideoVerified] DEBUG: frame save failed: {dbg_err}")
            if source_frame is None:
                continue

            target_frame = target_reader.get_frame_at_index(target_frame_idx)
            if target_frame is None:
                continue

            # Normalize resolution if frames differ in size
            source_frame, target_frame = normalize_frame_pair(
                source_frame, target_frame
            )

            # Multi-metric comparison for the initial frame
            initial_multi = compare_frames_multi(
                source_frame,
                target_frame,
                hash_algorithm=hash_algorithm,
                hash_size=hash_size,
                hash_threshold=hash_threshold,
                ssim_threshold=eff_ssim_thresh,
                mse_threshold=eff_mse_thresh,
                use_global_ssim=use_global_ssim,
            )

            # Primary metric for backward-compatible ranking
            if comparison_method == "ssim":
                initial_distance = initial_multi.ssim_distance
                initial_match = initial_multi.ssim_match
            elif comparison_method == "mse":
                initial_distance = initial_multi.mse_distance
                initial_match = initial_multi.mse_match
            else:  # hash
                initial_distance = initial_multi.phash_distance
                initial_match = initial_multi.phash_match

            distances.append(initial_distance)
            mse_values.append(initial_multi.mse_value)

            # Sequence verification (multi-metric)
            seq_result = verify_frame_sequence(
                source_frame_idx,
                target_frame_idx,
                sequence_verify_length,
                source_reader,
                target_reader,
                hash_algorithm,
                hash_size,
                hash_threshold,
                comparison_method=comparison_method,
                ssim_threshold=ssim_threshold,
                ivtc_tolerance=ivtc_tolerance,
                use_global_ssim=use_global_ssim,
            )

            # Sequence is verified if majority of frames match on primary metric
            min_sequence_matches = int(sequence_verify_length * 0.7)
            sequence_verified = seq_result.matched >= min_sequence_matches

            # Aggregate frame counts
            total_frames_tested += seq_result.total_tested
            total_frames_matched += seq_result.matched
            total_phash_exact += seq_result.phash_exact

            # Compute per-checkpoint averages
            cp_avg_ssim = (
                sum(seq_result.ssim_distances) / len(seq_result.ssim_distances)
                if seq_result.ssim_distances
                else float("inf")
            )
            cp_avg_mse = (
                sum(seq_result.mse_values) / len(seq_result.mse_values)
                if seq_result.mse_values
                else float("inf")
            )

            per_checkpoint_summary.append(
                {
                    "checkpoint_ms": checkpoint_ms,
                    "source_frame": source_frame_idx,
                    "target_frame": target_frame_idx,
                    "seq_matched": seq_result.matched,
                    "seq_total": seq_result.total_tested,
                    "phash_exact": seq_result.phash_exact,
                    "avg_ssim_dist": cp_avg_ssim,
                    "avg_mse": cp_avg_mse,
                    "verified": sequence_verified,
                }
            )

            # Record match details (backward-compatible)
            match_details.append(
                {
                    "source_frame": source_frame_idx,
                    "target_frame": target_frame_idx,
                    "distance": initial_distance,
                    "is_match": initial_match,
                    "sequence_matched": seq_result.matched,
                    "sequence_length": sequence_verify_length,
                    "sequence_verified": sequence_verified,
                    "sequence_avg_dist": seq_result.avg_distance,
                    # Multi-metric data
                    "phash_distance": initial_multi.phash_distance,
                    "ssim_distance": initial_multi.ssim_distance,
                    "mse_value": initial_multi.mse_value,
                }
            )

            if sequence_verified:
                sequence_verified_count += 1
                matched_count += 1
                seq_ratio = seq_result.matched / sequence_verify_length
                total_score += 2.0 * seq_ratio
            elif initial_match:
                matched_count += 1
                total_score += 0.3
            else:
                total_score += max(
                    0, 0.1 - (initial_distance / (hash_threshold * 4))
                )

        except Exception as e:
            log(f"[VideoVerified] Checkpoint error: {e}")
            continue

    avg_distance = sum(distances) / len(distances) if distances else float("inf")
    avg_mse = sum(mse_values) / len(mse_values) if mse_values else float("inf")

    return {
        "score": total_score,
        "matched": matched_count,
        "sequence_verified": sequence_verified_count,
        "avg_distance": avg_distance,
        "avg_mse": avg_mse,
        "match_details": match_details,
        # New multi-metric fields
        "total_frames_tested": total_frames_tested,
        "total_frames_matched": total_frames_matched,
        "phash_exact_matches": total_phash_exact,
        "per_checkpoint_summary": per_checkpoint_summary,
    }
