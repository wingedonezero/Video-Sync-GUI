# vsg_core/analysis/videodiff.py
"""
VideoDiff: Visual frame matching to find timing offset between two video files.

Extracts frames at a low sample rate (default 2fps), computes perceptual hashes
(dhash), matches frames between the two videos by hamming distance, then uses
RANSAC regression to find the optimal global offset while rejecting outlier
matches.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.models.settings import AppSettings

logger = logging.getLogger(__name__)


# =============================================================================
# Result types
# =============================================================================


@dataclass(frozen=True, slots=True)
class VideoDiffResult:
    """Result from native VideoDiff analysis."""

    offset_ms: int  # Rounded delay for mkvmerge
    raw_offset_ms: float  # Precise float offset
    matched_frames: int  # Total frame pairs found
    inlier_count: int  # Frames that agree on offset (RANSAC inliers)
    inlier_ratio: float  # inlier_count / matched_frames
    mean_residual_ms: float  # Average timing error of inliers
    confidence: str  # "HIGH", "MEDIUM", "LOW"
    ref_frames_extracted: int  # Total frames sampled from reference
    target_frames_extracted: int  # Total frames sampled from target
    speed_drift_detected: bool  # True if residuals correlate with time (PAL?)


# =============================================================================
# Frame extraction via ffmpeg pipe
# =============================================================================

# Raw video frame size for hashing (small = fast, sufficient for matching)
_FRAME_W = 32
_FRAME_H = 32


def _probe_fps(video_path: str) -> float:
    """Probe the native frame rate of a video using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "csv=p=0",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        # r_frame_rate is a fraction like "24000/1001" or "25/1"
        rate_str = result.stdout.strip()
        if "/" in rate_str:
            num, den = rate_str.split("/")
            return float(num) / float(den)
        return float(rate_str)
    except Exception:
        return 23.976  # Safe fallback


def _extract_frame_hashes(
    video_path: str,
    sample_fps: float,
    log: callable,
) -> tuple[list[np.ndarray], list[float]]:
    """
    Extract frames from video at sample_fps and compute dhash for each.

    Uses ffmpeg to pipe raw frames. When sample_fps > 0, resamples to that
    rate. When sample_fps == 0, uses the video's native frame rate for
    maximum precision.

    Args:
        video_path: Path to video file
        sample_fps: Frames per second to sample. 0 = native frame rate.
        log: Logging callback

    Returns:
        (hashes, timestamps) where hashes are uint64 dhash arrays
        and timestamps are in milliseconds
    """
    # Determine effective fps
    if sample_fps <= 0:
        effective_fps = _probe_fps(video_path)
        vf_filters = f"scale={_FRAME_W}:{_FRAME_H}:flags=area,format=gray"
        log(
            f"[VideoDiff] Extracting at native rate ({effective_fps:.3f}fps) "
            f"from: {Path(video_path).name}"
        )
    else:
        effective_fps = sample_fps
        vf_filters = f"fps={sample_fps},scale={_FRAME_W}:{_FRAME_H}:flags=area,format=gray"
        log(
            f"[VideoDiff] Extracting frames at {sample_fps}fps "
            f"from: {Path(video_path).name}"
        )

    cmd = [
        "ffmpeg",
        "-i",
        video_path,
        "-vf",
        vf_filters,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-v",
        "error",
        "-nostdin",
        "pipe:1",
    ]

    frame_size = _FRAME_W * _FRAME_H  # 1 byte per pixel (grayscale)
    hashes: list[np.ndarray] = []
    timestamps: list[float] = []
    ms_per_frame = 1000.0 / effective_fps

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=frame_size * 64,  # Buffer multiple frames
        )

        frame_idx = 0
        buf = b""
        while True:
            chunk = proc.stdout.read(frame_size * 32)
            if not chunk:
                break
            buf += chunk

            while len(buf) >= frame_size:
                raw_frame = buf[:frame_size]
                buf = buf[frame_size:]

                # Reshape to 2D grayscale image
                frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape(
                    _FRAME_H, _FRAME_W
                )

                # Compute dhash (difference hash)
                h = _compute_dhash(frame)
                hashes.append(h)
                timestamps.append(frame_idx * ms_per_frame)
                frame_idx += 1

        proc.wait()
        stderr_out = proc.stderr.read().decode("utf-8", errors="replace").strip()
        if proc.returncode != 0 and stderr_out:
            log(f"[VideoDiff] ffmpeg warning: {stderr_out[:200]}")

    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found. Required for VideoDiff frame extraction.")

    duration_s = len(hashes) / effective_fps if effective_fps > 0 else 0
    log(f"[VideoDiff] Extracted {len(hashes)} frames ({duration_s:.1f}s)")
    return hashes, timestamps


def _compute_dhash(gray_frame: np.ndarray, hash_size: int = 8) -> np.uint64:
    """
    Compute difference hash (dhash) from a grayscale frame.

    Resizes to (hash_size+1, hash_size) and compares adjacent horizontal pixels.
    Returns a 64-bit hash as uint64.

    Args:
        gray_frame: 2D grayscale numpy array
        hash_size: Hash grid size (8 = 64-bit hash)

    Returns:
        uint64 hash value
    """
    # Resize using simple averaging (frame is already small)
    # Use numpy-only resize: divide frame into hash_size blocks and average
    h, w = gray_frame.shape
    # Target: (hash_size, hash_size+1) for horizontal gradient
    target_h = hash_size
    target_w = hash_size + 1

    # Simple block-average resize
    resized = np.zeros((target_h, target_w), dtype=np.float32)
    block_h = h / target_h
    block_w = w / target_w
    for r in range(target_h):
        for c in range(target_w):
            r_start = int(r * block_h)
            r_end = int((r + 1) * block_h)
            c_start = int(c * block_w)
            c_end = int((c + 1) * block_w)
            resized[r, c] = gray_frame[r_start:r_end, c_start:c_end].mean()

    # Compute horizontal gradient: is left pixel brighter than right?
    diff = resized[:, 1:] > resized[:, :-1]  # shape: (hash_size, hash_size)

    # Pack into uint64
    flat = diff.flatten()
    hash_val = np.uint64(0)
    for i, bit in enumerate(flat[:64]):
        if bit:
            hash_val |= np.uint64(1) << np.uint64(i)

    return hash_val


# =============================================================================
# Frame matching
# =============================================================================


def _hamming_distance(a: np.uint64, b: np.uint64) -> int:
    """Count differing bits between two uint64 hashes."""
    xor = np.uint64(a) ^ np.uint64(b)
    # popcount via bit manipulation
    count = 0
    val = int(xor)
    while val:
        count += 1
        val &= val - 1
    return count


def _match_frames(
    ref_hashes: list[np.uint64],
    ref_timestamps: list[float],
    target_hashes: list[np.uint64],
    target_timestamps: list[float],
    max_hamming: int,
    log: callable,
) -> list[tuple[float, float]]:
    """
    Match target frames against reference frames by hash similarity.

    Uses a bucket-based approach: group reference hashes by their value,
    then for each target hash check exact match first, then scan neighbors.

    For speed with large frame counts, we use vectorized hamming distance.

    Args:
        ref_hashes: Reference video dhash values
        ref_timestamps: Reference timestamps in ms
        target_hashes: Target video dhash values
        target_timestamps: Target timestamps in ms
        max_hamming: Maximum hamming distance for a match (e.g. 5)
        log: Logging callback

    Returns:
        List of (ref_timestamp_ms, target_timestamp_ms) matched pairs
    """
    # Convert to numpy arrays for vectorized operations
    ref_arr = np.array(ref_hashes, dtype=np.uint64)
    ref_ts = np.array(ref_timestamps, dtype=np.float64)
    target_arr = np.array(target_hashes, dtype=np.uint64)
    target_ts = np.array(target_timestamps, dtype=np.float64)

    # Build exact-match lookup for fast path
    ref_lookup: dict[int, list[int]] = {}
    for i, h in enumerate(ref_hashes):
        key = int(h)
        if key not in ref_lookup:
            ref_lookup[key] = []
        ref_lookup[key].append(i)

    matches: list[tuple[float, float]] = []
    used_ref: set[int] = set()  # Prevent duplicate matches to same ref frame

    for t_idx in range(len(target_arr)):
        t_hash = target_arr[t_idx]
        t_key = int(t_hash)
        best_dist = max_hamming + 1
        best_ref_idx = -1

        # Fast path: exact match
        if t_key in ref_lookup:
            for r_idx in ref_lookup[t_key]:
                if r_idx not in used_ref:
                    best_dist = 0
                    best_ref_idx = r_idx
                    break

        # If no exact match, do vectorized hamming distance
        if best_ref_idx == -1:
            # XOR all ref hashes with this target hash
            xor_vals = ref_arr ^ t_hash

            # Vectorized popcount using the bit-counting trick
            # For uint64, count bits via lookup
            dists = np.zeros(len(ref_arr), dtype=np.int32)
            for bit in range(64):
                dists += ((xor_vals >> np.uint64(bit)) & np.uint64(1)).astype(np.int32)

            # Find best unused match within threshold
            sorted_indices = np.argsort(dists)
            for r_idx in sorted_indices:
                if dists[r_idx] > max_hamming:
                    break
                if int(r_idx) not in used_ref:
                    best_dist = int(dists[r_idx])
                    best_ref_idx = int(r_idx)
                    break

        if best_ref_idx >= 0 and best_dist <= max_hamming:
            matches.append((float(ref_ts[best_ref_idx]), float(target_ts[t_idx])))
            used_ref.add(best_ref_idx)

    log(
        f"[VideoDiff] Matched {len(matches)} frame pairs (threshold ≤{max_hamming} bits)"
    )
    return matches


# =============================================================================
# RANSAC offset estimation
# =============================================================================


def _ransac_offset(
    matches: list[tuple[float, float]],
    n_iterations: int = 1000,
    inlier_threshold_ms: float = 100.0,
    log: callable = lambda m: None,
) -> tuple[float, list[bool], float]:
    """
    RANSAC estimation of global offset from matched frame pairs.

    Model: target_timestamp = ref_timestamp + offset
    (No tempo/scale - just a constant offset)

    Each iteration picks one random match, computes offset, counts inliers.
    Best offset is refined by averaging all inlier offsets.

    Args:
        matches: List of (ref_ms, target_ms) pairs
        n_iterations: RANSAC iterations
        inlier_threshold_ms: Max residual to count as inlier
        log: Logging callback

    Returns:
        (offset_ms, inlier_mask, mean_residual_ms)
    """
    if not matches:
        return 0.0, [], 0.0

    ref_times = np.array([m[0] for m in matches], dtype=np.float64)
    target_times = np.array([m[1] for m in matches], dtype=np.float64)

    # All candidate offsets: ref - target for each match
    # Convention: positive offset means target is ahead (needs delay added)
    # This matches the audio correlation sign convention
    all_offsets = ref_times - target_times
    n = len(matches)

    best_inlier_count = 0
    best_offset = 0.0
    best_inliers = np.zeros(n, dtype=bool)

    rng = np.random.default_rng(seed=42)  # Deterministic for reproducibility

    for _ in range(n_iterations):
        # Pick a random match
        idx = rng.integers(0, n)
        candidate_offset = all_offsets[idx]

        # Count inliers: matches where |offset_i - candidate| < threshold
        residuals = np.abs(all_offsets - candidate_offset)
        inliers = residuals < inlier_threshold_ms
        inlier_count = int(np.sum(inliers))

        if inlier_count > best_inlier_count:
            best_inlier_count = inlier_count
            best_inliers = inliers
            # Refine offset from all inliers
            best_offset = float(np.mean(all_offsets[inliers]))

    # Final refinement with best inlier set
    if best_inlier_count > 0:
        inlier_offsets = all_offsets[best_inliers]
        best_offset = float(np.mean(inlier_offsets))
        residuals = np.abs(inlier_offsets - best_offset)
        mean_residual = float(np.mean(residuals))
    else:
        mean_residual = 0.0

    return best_offset, best_inliers.tolist(), mean_residual


def _detect_speed_drift(
    matches: list[tuple[float, float]],
    inlier_mask: list[bool],
    offset_ms: float,
) -> bool:
    """
    Check if residuals correlate with time, indicating a speed/tempo difference.

    If the correlation coefficient between timestamp and residual is significant,
    there's likely a PAL speedup or similar tempo mismatch.

    Returns:
        True if speed drift detected
    """
    if sum(inlier_mask) < 20:
        return False

    ref_times = np.array(
        [m[0] for m, inl in zip(matches, inlier_mask) if inl], dtype=np.float64
    )
    target_times = np.array(
        [m[1] for m, inl in zip(matches, inlier_mask) if inl], dtype=np.float64
    )

    # Residuals after removing constant offset (same sign convention as _ransac_offset)
    residuals = (ref_times - target_times) - offset_ms

    # Correlation between time position and residual
    if len(ref_times) < 2:
        return False

    # Guard against zero stddev (all residuals identical) which causes np.corrcoef
    # to produce NaN with a RuntimeWarning
    if np.std(residuals) == 0.0:
        return False

    corrcoef = np.corrcoef(ref_times, residuals)[0, 1]
    # Strong correlation (|r| > 0.7) suggests systematic drift
    return bool(abs(corrcoef) > 0.7)


# =============================================================================
# Confidence scoring
# =============================================================================


def _compute_confidence(
    matched_frames: int,
    inlier_count: int,
    inlier_ratio: float,
    mean_residual_ms: float,
) -> str:
    """
    Compute confidence level based on matching statistics.

    Returns:
        "HIGH", "MEDIUM", or "LOW"
    """
    if inlier_count >= 100 and inlier_ratio >= 0.85 and mean_residual_ms < 30.0:
        return "HIGH"
    if inlier_count >= 50 and inlier_ratio >= 0.70 and mean_residual_ms < 50.0:
        return "MEDIUM"
    return "LOW"


# =============================================================================
# Main native entry point
# =============================================================================


def run_native_videodiff(
    ref_file: str,
    target_file: str,
    settings: AppSettings,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> VideoDiffResult:
    """
    Run native VideoDiff analysis between two video files.

    Extracts frames at a low sample rate, computes perceptual hashes,
    matches frames, and finds the optimal global timing offset using RANSAC.

    Args:
        ref_file: Reference video path (Source 1)
        target_file: Target video path (Source 2/3)
        settings: Application settings
        runner: CommandRunner for logging
        tool_paths: Tool path dictionary (needs ffmpeg)

    Returns:
        VideoDiffResult with offset, confidence, and statistics
    """
    log = runner._log_message
    log("=" * 60)
    log("[VideoDiff] Starting native frame-based analysis")
    log("=" * 60)

    sample_fps = getattr(settings, "videodiff_sample_fps", 0)
    max_hamming = getattr(settings, "videodiff_match_threshold", 5)
    min_matches = getattr(settings, "videodiff_min_matches", 50)
    inlier_threshold = getattr(settings, "videodiff_inlier_threshold_ms", 100.0)

    # Step 1: Extract and hash frames from both videos
    fps_label = "native" if sample_fps <= 0 else f"{sample_fps}fps"
    log(f"\n[VideoDiff] Step 1: Frame extraction (sample rate: {fps_label})")

    ref_hashes, ref_timestamps = _extract_frame_hashes(ref_file, sample_fps, log)
    target_hashes, target_timestamps = _extract_frame_hashes(
        target_file, sample_fps, log
    )

    if not ref_hashes:
        raise RuntimeError(
            f"[VideoDiff] No frames extracted from reference: {ref_file}"
        )
    if not target_hashes:
        raise RuntimeError(
            f"[VideoDiff] No frames extracted from target: {target_file}"
        )

    # Step 2: Match frames between videos
    log(f"\n[VideoDiff] Step 2: Frame matching (max hamming distance: {max_hamming})")

    matches = _match_frames(
        ref_hashes,
        ref_timestamps,
        target_hashes,
        target_timestamps,
        max_hamming,
        log,
    )

    if len(matches) < min_matches:
        raise RuntimeError(
            f"[VideoDiff] Insufficient frame matches: {len(matches)} "
            f"(minimum: {min_matches})\n"
            f"  Reference frames: {len(ref_hashes)}\n"
            f"  Target frames: {len(target_hashes)}\n"
            f"  Match threshold: {max_hamming} bits\n\n"
            f"Possible causes:\n"
            f"  - Videos are not from the same source material\n"
            f"  - Heavy cropping or aspect ratio differences\n"
            f"  - Extreme color grading or processing differences\n\n"
            f"Solutions:\n"
            f"  - Increase 'VideoDiff Match Threshold' in settings\n"
            f"  - Try Audio Correlation mode instead\n"
            f"  - Verify the files are different versions of the same content"
        )

    # Step 3: RANSAC offset estimation
    log(
        f"\n[VideoDiff] Step 3: RANSAC offset estimation "
        f"(inlier threshold: {inlier_threshold:.0f}ms)"
    )

    raw_offset, inlier_mask, mean_residual = _ransac_offset(
        matches,
        n_iterations=2000,
        inlier_threshold_ms=inlier_threshold,
        log=log,
    )

    inlier_count = sum(inlier_mask)
    inlier_ratio = inlier_count / len(matches) if matches else 0.0
    rounded_offset = round(raw_offset)

    # Step 4: Check for speed drift
    speed_drift = _detect_speed_drift(matches, inlier_mask, raw_offset)

    # Step 5: Compute confidence
    confidence = _compute_confidence(
        len(matches), inlier_count, inlier_ratio, mean_residual
    )

    # Build result
    result = VideoDiffResult(
        offset_ms=rounded_offset,
        raw_offset_ms=raw_offset,
        matched_frames=len(matches),
        inlier_count=inlier_count,
        inlier_ratio=inlier_ratio,
        mean_residual_ms=mean_residual,
        confidence=confidence,
        ref_frames_extracted=len(ref_hashes),
        target_frames_extracted=len(target_hashes),
        speed_drift_detected=speed_drift,
    )

    # Log results
    log(f"\n{'=' * 60}")
    log("[VideoDiff] RESULTS")
    log(f"{'=' * 60}")
    log(f"  Offset: {rounded_offset}ms (raw: {raw_offset:.3f}ms)")
    log(
        f"  Matched frames: {len(matches)} / "
        f"{min(len(ref_hashes), len(target_hashes))} "
        f"({len(matches) / min(len(ref_hashes), len(target_hashes)) * 100:.1f}%)"
    )
    log(f"  Inliers: {inlier_count} / {len(matches)} ({inlier_ratio * 100:.1f}%)")
    log(f"  Mean residual: {mean_residual:.1f}ms")
    log(f"  Confidence: {confidence}")
    if speed_drift:
        log(
            "  WARNING: Speed drift detected - videos may have different "
            "frame rates (e.g. PAL vs NTSC). Offset is still valid but "
            "timing may drift over the duration of the video."
        )
    log(f"{'=' * 60}")

    return result


# =============================================================================
# Convenience alias
# =============================================================================

# run_videodiff is the single entry point - always uses native implementation
run_videodiff = run_native_videodiff
