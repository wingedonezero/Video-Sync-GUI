# vsg_core/subtitles/sync_mode_plugins/video_verified/quality.py
"""
Frame quality measurement and sequence verification for video-verified sync.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .offset import get_vfr_frame_for_time

if TYPE_CHECKING:
    from PIL import Image


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
) -> tuple[int, float, list[int]]:
    """
    Verify that a sequence of consecutive frames match between source and target.

    This is the key to accurate offset detection - if the offset is correct,
    then source[N], source[N+1], source[N+2], ... should match
    target[N+offset], target[N+offset+1], target[N+offset+2], ...

    For hash comparison, NO window search is used - frames must match at exact
    positions. This prevents false positives from window compensation.

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
        comparison_method: 'hash', 'ssim', or 'mse'
        ssim_threshold: Maximum SSIM/MSE distance for a match. If None, uses
            hash_threshold for all methods (backwards compat).
        ivtc_tolerance: Frame tolerance for IVTC content (0=exact, 1=±1 frame)

    Returns:
        Tuple of (matched_count, avg_distance, distances_list)
    """
    from ...frame_utils import (
        compare_frames,
        compute_frame_hash,
        compute_hamming_distance,
    )

    # Determine the effective threshold for SSIM/MSE methods
    effective_ssim_threshold = ssim_threshold if ssim_threshold is not None else None

    matched = 0
    distances: list[int] = []

    for i in range(sequence_length):
        source_idx = source_start_idx + i

        # For IVTC content, try ±tolerance around the expected target frame
        # to handle VDecimate drift (different encodes drop different frames)
        target_candidates = [target_start_idx + i]
        if ivtc_tolerance > 0:
            for delta in range(1, ivtc_tolerance + 1):
                target_candidates.append(target_start_idx + i + delta)
                target_candidates.append(target_start_idx + i - delta)

        best_distance = float("inf")
        best_match = False

        for target_idx in target_candidates:
            if target_idx < 0:
                continue

            try:
                source_frame = source_reader.get_frame_at_index(source_idx)
                target_frame = target_reader.get_frame_at_index(target_idx)

                if source_frame is None or target_frame is None:
                    continue

                # Normalize resolution if frames differ in size
                source_frame, target_frame = normalize_frame_pair(
                    source_frame, target_frame
                )

                if comparison_method in ("ssim", "mse"):
                    distance, is_match = compare_frames(
                        source_frame,
                        target_frame,
                        method=comparison_method,
                        hash_algorithm=hash_algorithm,
                        hash_size=hash_size,
                        threshold=effective_ssim_threshold,
                        use_global_ssim=use_global_ssim,
                    )
                else:
                    source_hash = compute_frame_hash(
                        source_frame, hash_size, hash_algorithm
                    )
                    target_hash = compute_frame_hash(
                        target_frame, hash_size, hash_algorithm
                    )

                    if source_hash is None or target_hash is None:
                        continue

                    distance = compute_hamming_distance(source_hash, target_hash)
                    is_match = distance <= hash_threshold

                if distance < best_distance:
                    best_distance = distance
                    best_match = is_match

            except Exception:
                continue

        if best_distance < float("inf"):
            distances.append(int(best_distance))
            if best_match:
                matched += 1

    avg_dist = sum(distances) / len(distances) if distances else float("inf")
    return matched, avg_dist, distances


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
    Measure quality of a candidate frame offset using sequence verification.

    Algorithm:
    1. At each checkpoint, test if source frame N matches target frame N+offset
    2. If initial frame matches, verify with SEQUENCE of consecutive frames
    3. Sequence verification uses NO window - frames must match at exact positions
    4. This prevents false positives where window search compensates for wrong offset

    The sequence verification is key: if offset is correct, then frames
    N, N+1, N+2, ... in source should match N+offset, N+offset+1, N+offset+2, ...
    in target. If offset is wrong, the sequence will fail even if single frames
    happen to match due to similar content.

    Args:
        frame_offset: Integer frame offset to test (target_frame = source_frame + offset)
        checkpoint_times: List of times in the source video to check
        sequence_verify_length: Number of consecutive frames to verify (default 10)
        ssim_threshold: SSIM/MSE distance threshold (None = use compare_frames defaults)
        ivtc_tolerance: Frame tolerance for IVTC content (0=exact, 1=±1 frame)
        ... (other args same as before)

    Returns:
        Dict with score, matched count, avg_distance, sequence_verified count, and match_details
    """
    from ...frame_utils import (
        compare_frames,
        compute_frame_hash,
        compute_hamming_distance,
    )

    total_score = 0.0
    matched_count = 0
    sequence_verified_count = 0
    distances: list[float] = []
    match_details = []

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
        # Use timestamp-based lookup (handles VFR/non-linear timestamps correctly)
        # Falls back to CFR math when timestamps are linear
        ts_frame = source_reader.get_frame_index_for_time(checkpoint_ms)
        if ts_frame is not None:
            source_frame_idx = ts_frame
        else:
            # Fallback: try VFR VideoTimestamps, then CFR
            is_source_vfr = getattr(source_reader, "is_soft_telecine", False)
            source_path = getattr(source_reader, "video_path", "")
            vfr_frame = get_vfr_frame_for_time(
                source_path, checkpoint_ms, is_source_vfr, log
            )
            if vfr_frame is not None:
                source_frame_idx = vfr_frame
            else:
                source_frame_idx = int(checkpoint_ms / source_frame_duration_ms)

        # Target frame with this offset (STRICT - no window for initial test)
        # Convert frame_offset to a TIME offset using source frame duration,
        # then find the target frame at (checkpoint_time + offset_time).
        # This correctly handles VFR targets where frame indices don't map
        # linearly to time (e.g., MPEG-2 DVDs with non-constant frame durations).
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
            # First, check if the single frame matches (strict, no window)
            source_frame = source_reader.get_frame_at_index(source_frame_idx)

            # Debug: save first checkpoint frames at offset 0 for visual inspection
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

            if comparison_method in ("ssim", "mse"):
                # Use compare_frames with configurable SSIM/MSE threshold
                initial_distance, initial_match = compare_frames(
                    source_frame,
                    target_frame,
                    method=comparison_method,
                    hash_algorithm=hash_algorithm,
                    hash_size=hash_size,
                    threshold=ssim_threshold,
                    use_global_ssim=use_global_ssim,
                )
            else:
                # Default: use perceptual hash comparison
                source_hash = compute_frame_hash(
                    source_frame, hash_size, hash_algorithm
                )
                if source_hash is None:
                    continue

                target_hash = compute_frame_hash(
                    target_frame, hash_size, hash_algorithm
                )
                if target_hash is None:
                    continue

                initial_distance = compute_hamming_distance(source_hash, target_hash)
                initial_match = initial_distance <= hash_threshold

            distances.append(initial_distance)

            # Now verify with sequence of consecutive frames
            seq_matched, seq_avg_dist, _seq_distances = verify_frame_sequence(
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

            # Sequence is verified if majority of frames match
            # Require at least 70% of sequence to match
            min_sequence_matches = int(sequence_verify_length * 0.7)
            sequence_verified = seq_matched >= min_sequence_matches

            # Record match details
            match_details.append(
                {
                    "source_frame": source_frame_idx,
                    "target_frame": target_frame_idx,
                    "distance": initial_distance,
                    "is_match": initial_match,
                    "sequence_matched": seq_matched,
                    "sequence_length": sequence_verify_length,
                    "sequence_verified": sequence_verified,
                    "sequence_avg_dist": seq_avg_dist,
                }
            )

            if sequence_verified:
                sequence_verified_count += 1
                matched_count += 1
                # High score for sequence-verified matches
                # Score based on how many frames in sequence matched
                seq_ratio = seq_matched / sequence_verify_length
                total_score += 2.0 * seq_ratio  # Up to 2.0 for perfect sequence
            elif initial_match:
                # Initial frame matched but sequence didn't verify
                # Give partial score but much lower than verified
                matched_count += 1
                total_score += 0.3
            else:
                # No match at all
                total_score += max(0, 0.1 - (initial_distance / (hash_threshold * 4)))

        except Exception as e:
            log(f"[VideoVerified] Checkpoint error: {e}")
            continue

    avg_distance = sum(distances) / len(distances) if distances else float("inf")

    return {
        "score": total_score,
        "matched": matched_count,
        "sequence_verified": sequence_verified_count,
        "avg_distance": avg_distance,
        "match_details": match_details,
    }
