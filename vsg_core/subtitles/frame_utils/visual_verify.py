# vsg_core/subtitles/frame_utils/visual_verify.py
"""
Visual frame verification for video-verified sync.

Samples frames at regular intervals across the entire video and compares
raw Y-plane content between source and target using global SSIM. This
verifies that the calculated frame offset actually aligns corresponding
frames correctly.

Key design decisions:
- Self-contained: opens videos with VapourSynth/FFMS2 directly, no
  dependency on VideoReader or video_verified.py internals.
- Raw frames only: no deinterlacing, no IVTC. Compares what the
  user actually sees when playing interlaced content.
- Global SSIM: works well for interlaced content. Distance thresholds:
  < 2.0 = visually identical, < 25.0 = same content, > 50.0 = different.
- VFR-aware: detects variable frame rate MKVs and builds a sparse
  timestamp table for accurate time→frame lookup.

This is a diagnostic tool — it does not modify any timing or subtitles.
"""

from __future__ import annotations

import bisect
import gc
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable


# ============================================================================
# Data Model
# ============================================================================


@dataclass(slots=True)
class SampleResult:
    """Result of comparing one sample point across source and target."""

    sample_index: int  # 0-based sample number
    time_s: float  # Sample time in source video (seconds)
    source_frame: int  # Source frame index
    target_frame: int  # Target frame index (offset-adjusted)

    base_dist: float  # SSIM distance at expected offset (0=identical, 100=different)
    best_delta: int  # Best matching delta within search window (0=exact)
    best_dist: float  # SSIM distance at best delta

    classification: str  # "exact", "off_by_1", ..., "unmatchable"
    is_static: bool  # True if frame is static/held (base ≈ best, both low)
    region: str = ""  # Assigned later: "early", "main", "late", "credits"


@dataclass(slots=True)
class RegionStats:
    """Aggregated statistics for one region of the video."""

    name: str  # "early", "main", "late", "credits"
    total: int = 0
    exact: int = 0  # delta=0, dist<2
    within_1: int = 0  # |delta| <= 1
    within_2: int = 0  # |delta| <= 2
    unmatchable: int = 0  # All deltas > 50
    static_frames: int = 0  # Low-info static frames
    mean_base_dist: float = 0.0
    mean_best_dist: float = 0.0


@dataclass(slots=True)
class CreditsInfo:
    """Credits region detection result."""

    detected: bool = False
    boundary_time_s: float | None = None  # Time where credits begin
    boundary_sample: int | None = None  # Sample index where credits begin
    num_credits_samples: int = 0


@dataclass(slots=True)
class VisualVerifyResult:
    """Complete visual verification result for a sync job."""

    job_name: str
    source_path: str
    target_path: str
    offset_ms: float
    frame_offset: int
    source_fps: float
    target_fps: float
    sample_interval_s: float
    search_range: int
    total_samples: int
    total_duration_s: float
    verify_timestamp: datetime

    source_content_type: str
    target_content_type: str

    # Global stats (main content only, excluding credits)
    main_exact: int = 0
    main_within_1: int = 0
    main_within_2: int = 0
    main_unmatchable: int = 0
    main_total: int = 0
    main_static: int = 0

    # Per-sample detail
    samples: list[SampleResult] = field(default_factory=list)

    # Region breakdown
    regions: list[RegionStats] = field(default_factory=list)

    # Credits detection
    credits: CreditsInfo = field(default_factory=CreditsInfo)

    @property
    def accuracy_pct(self) -> float:
        """Percentage of main-content samples within ±2 frames."""
        if self.main_total == 0:
            return 0.0
        return 100.0 * self.main_within_2 / self.main_total

    @property
    def has_real_drift(self) -> bool:
        """True if any main-content samples are unmatchable."""
        return self.main_unmatchable > 0


# ============================================================================
# Internal Helpers — VapourSynth / FFMS2
# ============================================================================


def _open_raw_clip(
    path: str, cache_dir: Path | None = None
) -> tuple[object, float, int]:
    """
    Open a video with FFMS2 (raw — no deinterlace, no IVTC).

    Args:
        path: Path to video file.
        cache_dir: Optional directory for FFMS2 index cache.

    Returns:
        Tuple of (clip, fps, num_frames).

    Raises:
        ImportError: If VapourSynth is not available.
        RuntimeError: If FFMS2 cannot open the file.
    """
    import vapoursynth as vs

    core = vs.core

    # Build FFMS2 cache path if cache_dir is provided
    cachefile = None
    if cache_dir is not None:
        from .video_reader import _get_ffms2_cache_path

        cachefile = str(_get_ffms2_cache_path(path, cache_dir))

    kwargs = {"source": path}
    if cachefile:
        kwargs["cachefile"] = cachefile

    clip = core.ffms2.Source(**kwargs)

    fps = clip.fps_num / clip.fps_den if clip.fps_den else 29.970
    num_frames = clip.num_frames

    return clip, fps, num_frames


def _detect_vfr(clip: object, fps: float, num_frames: int) -> bool:
    """
    Detect if a clip has variable frame rate (VFR) timestamps.

    Samples 4 evenly-spaced points and checks if _AbsoluteTime drifts
    more than 500ms from the expected CFR position.

    Args:
        clip: VapourSynth clip.
        fps: Nominal FPS from container.
        num_frames: Total frame count.

    Returns:
        True if VFR is detected.
    """
    test_indices = [0, num_frames // 4, num_frames // 2, 3 * num_frames // 4]
    for idx in test_indices:
        if idx >= num_frames:
            continue
        try:
            props = clip.get_frame(idx).props
            actual_t = props.get("_AbsoluteTime", None)
            if actual_t is None:
                # No _AbsoluteTime — assume CFR
                return False
            expected_t = idx / fps
            if abs(actual_t - expected_t) > 0.5:
                return True
        except Exception:
            pass
    return False


def _build_vfr_table(
    clip: object, num_frames: int, step: int = 50
) -> tuple[list[float], list[int]]:
    """
    Build a sparse time→frame lookup table for VFR content.

    Samples every `step` frames and records their _AbsoluteTime.
    Always includes the last frame.

    Args:
        clip: VapourSynth clip with _AbsoluteTime frame props.
        num_frames: Total frame count.
        step: Sampling step (default 50).

    Returns:
        Tuple of (times_seconds, frame_indices) — parallel lists,
        sorted by time. Empty lists if table cannot be built.
    """
    times: list[float] = []
    indices: list[int] = []

    for i in range(0, num_frames, step):
        try:
            props = clip.get_frame(i).props
            t = props.get("_AbsoluteTime", None)
            if t is not None:
                times.append(float(t))
                indices.append(i)
        except Exception:
            pass

    # Always include last frame
    last = num_frames - 1
    if last not in indices:
        try:
            props = clip.get_frame(last).props
            t = props.get("_AbsoluteTime", None)
            if t is not None:
                times.append(float(t))
                indices.append(last)
        except Exception:
            pass

    return times, indices


def _time_to_frame_idx(
    time_s: float,
    fps: float,
    num_frames: int,
    vfr_times: list[float] | None = None,
    vfr_indices: list[int] | None = None,
    clip: object | None = None,
    vfr_step: int = 50,
) -> int:
    """
    Convert a time (seconds) to a frame index.

    For CFR: simple ``int(time_s * fps)``.
    For VFR: binary search in sparse table, then local refinement by
    scanning actual frame timestamps.

    Args:
        time_s: Time in seconds.
        fps: Frame rate.
        num_frames: Total frames (for clamping).
        vfr_times: Sparse VFR time table (seconds). None for CFR.
        vfr_indices: Sparse VFR frame index table. None for CFR.
        clip: VapourSynth clip (needed for VFR local refinement).
        vfr_step: Step size used when building VFR table.

    Returns:
        Frame index (0-based), clamped to [0, num_frames-1].
    """
    if not vfr_times or not vfr_indices:
        # CFR path
        idx = int(time_s * fps)
        return max(0, min(idx, num_frames - 1))

    # VFR path: binary search in sparse table
    pos = bisect.bisect_left(vfr_times, time_s)

    if pos >= len(vfr_times):
        start_frame = vfr_indices[-1]
    elif pos == 0:
        start_frame = vfr_indices[0]
    else:
        # Pick closer bracket
        if abs(vfr_times[pos] - time_s) < abs(vfr_times[pos - 1] - time_s):
            start_frame = vfr_indices[pos]
        else:
            start_frame = vfr_indices[pos - 1]

    # Local refinement: scan ±step frames around the sparse match
    if clip is not None:
        lo = max(0, start_frame - vfr_step)
        hi = min(num_frames - 1, start_frame + vfr_step)

        best_frame = start_frame
        best_diff = float("inf")

        for i in range(lo, hi + 1):
            try:
                props = clip.get_frame(i).props
                t = props.get("_AbsoluteTime", None)
                if t is None:
                    continue
                diff = abs(t - time_s)
                if diff < best_diff:
                    best_diff = diff
                    best_frame = i
                    if diff < 0.001:  # Within 1ms — good enough
                        break
                elif t > time_s + 0.1:
                    break
            except Exception:
                continue

        return max(0, min(best_frame, num_frames - 1))

    return max(0, min(start_frame, num_frames - 1))


# ============================================================================
# Internal Helpers — Frame Extraction & Comparison
# ============================================================================


def _get_y_plane(clip: object, idx: int, num_frames: int) -> np.ndarray:
    """
    Extract the raw Y (luma) plane from a frame as a uint8 numpy array.

    Handles 8-bit and 10/16-bit content. No deinterlacing applied.

    Args:
        clip: VapourSynth clip.
        idx: Frame index.
        num_frames: Total frames (for clamping).

    Returns:
        2D uint8 numpy array (height × width).
    """
    idx = max(0, min(idx, num_frames - 1))
    frame = clip.get_frame(idx)
    y = np.asarray(frame[0])

    if y.dtype == np.uint16:
        # 10-bit content stored in uint16
        if y.max() <= 1023:
            y = (y >> 2).astype(np.uint8)
        else:
            y = (y >> 8).astype(np.uint8)

    return y


def _global_ssim_dist(y1: np.ndarray, y2: np.ndarray) -> float:
    """
    Compute global SSIM distance between two grayscale images.

    Returns distance in range [0, 100]:
    - 0.0 = identical
    - < 2.0 = visually identical (noise-level differences)
    - < 25.0 = same content (minor differences)
    - > 50.0 = different content (scene change / different source)

    If shapes differ, y2 is resized to match y1.

    Args:
        y1: First image (uint8, 2D).
        y2: Second image (uint8, 2D).

    Returns:
        SSIM distance = (1.0 - ssim) * 100.
    """
    if y1.shape != y2.shape:
        from PIL import Image

        y2_pil = Image.fromarray(y2, "L").resize(
            (y1.shape[1], y1.shape[0]), Image.Resampling.LANCZOS
        )
        y2 = np.array(y2_pil)

    img1 = y1.astype(np.float64)
    img2 = y2.astype(np.float64)

    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    mu1 = img1.mean()
    mu2 = img2.mean()
    s1 = img1.var()
    s2 = img2.var()
    s12 = ((img1 - mu1) * (img2 - mu2)).mean()

    ssim = ((2 * mu1 * mu2 + C1) * (2 * s12 + C2)) / (
        (mu1**2 + mu2**2 + C1) * (s1 + s2 + C2)
    )
    return (1.0 - ssim) * 100.0


# ============================================================================
# Per-Sample Verification
# ============================================================================


def _verify_sample(
    src_clip: object,
    tgt_clip: object,
    time_s: float,
    offset_ms: float,
    src_fps: float,
    tgt_fps: float,
    src_num_frames: int,
    tgt_num_frames: int,
    src_vfr_times: list[float] | None,
    src_vfr_indices: list[int] | None,
    tgt_vfr_times: list[float] | None,
    tgt_vfr_indices: list[int] | None,
    search_range: int,
    sample_index: int,
    vfr_step: int = 50,
) -> SampleResult:
    """
    Verify a single sample point.

    Compares source frame at time T with target frame at time T - offset,
    then searches ±search_range frames for the best match.

    Args:
        src_clip: Source VapourSynth clip.
        tgt_clip: Target VapourSynth clip.
        time_s: Sample time in source video (seconds).
        offset_ms: Video-verified offset in milliseconds.
        src_fps: Source FPS.
        tgt_fps: Target FPS.
        src_num_frames: Source total frames.
        tgt_num_frames: Target total frames.
        src_vfr_times: Source VFR time table (None for CFR).
        src_vfr_indices: Source VFR index table (None for CFR).
        tgt_vfr_times: Target VFR time table (None for CFR).
        tgt_vfr_indices: Target VFR index table (None for CFR).
        search_range: How many frames to search (±N).
        sample_index: Index of this sample (for reporting).
        vfr_step: Step size used for VFR tables.

    Returns:
        SampleResult with classification.
    """
    # Source frame at time T
    src_frame = _time_to_frame_idx(
        time_s, src_fps, src_num_frames,
        src_vfr_times, src_vfr_indices, src_clip, vfr_step,
    )

    # Target frame at time T - offset_ms
    # offset_ms is the adjustment applied to subtitles:
    #   If offset_ms = -1034, subs shift earlier by 1034ms.
    #   Source content at T corresponds to target content at T - offset/1000.
    #   T - (-1034/1000) = T + 1.034 → target content is ahead.
    target_time_s = time_s - (offset_ms / 1000.0)
    tgt_frame = _time_to_frame_idx(
        target_time_s, tgt_fps, tgt_num_frames,
        tgt_vfr_times, tgt_vfr_indices, tgt_clip, vfr_step,
    )

    # Extract raw Y planes
    src_y = _get_y_plane(src_clip, src_frame, src_num_frames)
    tgt_y = _get_y_plane(tgt_clip, tgt_frame, tgt_num_frames)

    # Base comparison at expected offset
    base_dist = _global_ssim_dist(src_y, tgt_y)

    # Search ±N frames for best match
    best_delta = 0
    best_dist = base_dist

    for delta in range(-search_range, search_range + 1):
        if delta == 0:
            continue  # Already computed as base_dist
        test_frame = tgt_frame + delta
        if test_frame < 0 or test_frame >= tgt_num_frames:
            continue
        try:
            tgt_y_delta = _get_y_plane(tgt_clip, test_frame, tgt_num_frames)
            dist = _global_ssim_dist(src_y, tgt_y_delta)
            if dist < best_dist:
                best_dist = dist
                best_delta = delta
        except Exception:
            continue

    # Classify
    if best_dist >= 50.0:
        classification = "unmatchable"
    elif best_delta == 0 and base_dist < 2.0:
        classification = "exact"
    elif best_dist < 50.0:
        classification = f"off_by_{abs(best_delta)}" if best_delta != 0 else "exact"
    else:
        classification = "unmatchable"

    # Static frame detection: all nearby frames look similar (static/held scene)
    is_static = abs(base_dist - best_dist) < 1.0 and base_dist < 5.0

    return SampleResult(
        sample_index=sample_index,
        time_s=time_s,
        source_frame=src_frame,
        target_frame=tgt_frame,
        base_dist=base_dist,
        best_delta=best_delta,
        best_dist=best_dist,
        classification=classification,
        is_static=is_static,
    )


# ============================================================================
# Credits Detection & Region Assignment
# ============================================================================


def _detect_credits_region(samples: list[SampleResult]) -> CreditsInfo:
    """
    Detect credits by scanning backward from the end of the video.

    Credits are identified when 3+ consecutive samples from the end
    have best_dist > 50 (completely different content — typically
    Japanese vs English credit text).

    Args:
        samples: List of SampleResult in time order.

    Returns:
        CreditsInfo with detection results.
    """
    if len(samples) < 5:
        return CreditsInfo()

    # Scan backward: count consecutive unmatchable samples
    consecutive_unmatchable = 0
    boundary_idx = None

    for i in range(len(samples) - 1, -1, -1):
        if samples[i].best_dist > 50.0:
            consecutive_unmatchable += 1
            boundary_idx = i
        else:
            break

    if consecutive_unmatchable >= 3:
        return CreditsInfo(
            detected=True,
            boundary_time_s=samples[boundary_idx].time_s,
            boundary_sample=boundary_idx,
            num_credits_samples=consecutive_unmatchable,
        )

    return CreditsInfo()


def _assign_regions(
    samples: list[SampleResult],
    duration_s: float,
    credits: CreditsInfo,
) -> None:
    """
    Assign region labels to each sample point.

    Regions:
    - "early": First 5 minutes (0-300s)
    - "credits": From credits boundary to end (if detected)
    - "late": Last 10% of non-credits content
    - "main": Everything else

    Mutates sample.region in place.

    Args:
        samples: List of SampleResult in time order.
        duration_s: Total video duration in seconds.
        credits: Credits detection info.
    """
    early_boundary = 300.0  # 5 minutes

    # Determine where non-credits content ends
    if credits.detected and credits.boundary_time_s is not None:
        content_end = credits.boundary_time_s
    else:
        content_end = duration_s

    # Late region: last 10% of content (before credits)
    late_boundary = content_end * 0.9

    for s in samples:
        if credits.detected and credits.boundary_sample is not None:
            if s.sample_index >= credits.boundary_sample:
                s.region = "credits"
                continue

        if s.time_s <= early_boundary:
            s.region = "early"
        elif s.time_s >= late_boundary:
            s.region = "late"
        else:
            s.region = "main"


def _compute_region_stats(samples: list[SampleResult]) -> list[RegionStats]:
    """
    Compute per-region aggregate statistics.

    Args:
        samples: List of SampleResult with region labels assigned.

    Returns:
        List of RegionStats, one per region present (in order).
    """
    region_order = ["early", "main", "late", "credits"]
    region_samples: dict[str, list[SampleResult]] = {r: [] for r in region_order}

    for s in samples:
        if s.region in region_samples:
            region_samples[s.region].append(s)

    stats = []
    for name in region_order:
        region_list = region_samples[name]
        if not region_list:
            continue

        total = len(region_list)
        exact = sum(1 for s in region_list if s.classification == "exact")
        within_1 = sum(
            1 for s in region_list if abs(s.best_delta) <= 1 and s.best_dist < 50.0
        )
        within_2 = sum(
            1 for s in region_list if abs(s.best_delta) <= 2 and s.best_dist < 50.0
        )
        unmatchable = sum(1 for s in region_list if s.classification == "unmatchable")
        static = sum(1 for s in region_list if s.is_static)

        base_dists = [s.base_dist for s in region_list]
        best_dists = [s.best_dist for s in region_list]

        stats.append(
            RegionStats(
                name=name,
                total=total,
                exact=exact,
                within_1=within_1,
                within_2=within_2,
                unmatchable=unmatchable,
                static_frames=static,
                mean_base_dist=sum(base_dists) / total if total else 0.0,
                mean_best_dist=sum(best_dists) / total if total else 0.0,
            )
        )

    return stats


# ============================================================================
# Main Entry Point
# ============================================================================


def run_visual_verify(
    source_video: str,
    target_video: str,
    offset_ms: float,
    frame_offset: int,
    source_fps: float,
    target_fps: float,
    job_name: str = "unknown",
    sample_interval_s: float = 5.0,
    search_range: int = 5,
    temp_dir: Path | None = None,
    source_content_type: str = "unknown",
    target_content_type: str = "unknown",
    log: Callable[[str], None] | None = None,
) -> VisualVerifyResult:
    """
    Run visual frame verification across the entire video.

    Opens both source and target videos with FFMS2 (raw, no processing),
    samples frames at regular intervals, and compares them using global
    SSIM to verify the calculated offset.

    Args:
        source_video: Path to source video file.
        target_video: Path to target video file.
        offset_ms: Video-verified offset in milliseconds (before global shift).
        frame_offset: Integer frame offset.
        source_fps: Source video FPS (from video-verified calculation).
        target_fps: Target video FPS.
        job_name: Job identifier for the report filename.
        sample_interval_s: Seconds between sample points (default 5.0).
        search_range: Frames to search around expected position (default ±5).
        temp_dir: Optional temp directory for FFMS2 index cache.
        source_content_type: Source content type string (for reporting).
        target_content_type: Target content type string (for reporting).
        log: Optional logging function.

    Returns:
        VisualVerifyResult with complete verification data.
    """

    def _log(msg: str) -> None:
        if log:
            log(msg)

    _log("[VisualVerify] Starting visual frame verification...")
    _log(f"[VisualVerify] Source: {Path(source_video).name}")
    _log(f"[VisualVerify] Target: {Path(target_video).name}")
    _log(f"[VisualVerify] Offset: {offset_ms:+.3f}ms (frame_offset: {frame_offset})")
    _log(f"[VisualVerify] Sample interval: {sample_interval_s}s, Search: ±{search_range}")

    # Open both clips raw (no deinterlace, no IVTC)
    try:
        src_clip, src_fps_detected, src_num_frames = _open_raw_clip(
            source_video, temp_dir
        )
        tgt_clip, tgt_fps_detected, tgt_num_frames = _open_raw_clip(
            target_video, temp_dir
        )
    except Exception as e:
        _log(f"[VisualVerify] ERROR: Failed to open clips: {e}")
        return VisualVerifyResult(
            job_name=job_name,
            source_path=source_video,
            target_path=target_video,
            offset_ms=offset_ms,
            frame_offset=frame_offset,
            source_fps=source_fps,
            target_fps=target_fps,
            sample_interval_s=sample_interval_s,
            search_range=search_range,
            total_samples=0,
            total_duration_s=0.0,
            verify_timestamp=datetime.now(),
            source_content_type=source_content_type,
            target_content_type=target_content_type,
        )

    # Use the FPS from FFMS2 (raw, before any processing)
    # These may differ from source_fps/target_fps which are post-IVTC.
    # For visual verification we use the raw clip FPS since we opened raw clips.
    src_raw_fps = src_fps_detected
    tgt_raw_fps = tgt_fps_detected

    _log(
        f"[VisualVerify] Raw FPS: source={src_raw_fps:.3f} ({src_num_frames} frames), "
        f"target={tgt_raw_fps:.3f} ({tgt_num_frames} frames)"
    )

    # Detect VFR for each clip
    src_is_vfr = _detect_vfr(src_clip, src_raw_fps, src_num_frames)
    tgt_is_vfr = _detect_vfr(tgt_clip, tgt_raw_fps, tgt_num_frames)

    if src_is_vfr:
        _log("[VisualVerify] Source is VFR — building timestamp table...")
    if tgt_is_vfr:
        _log("[VisualVerify] Target is VFR — building timestamp table...")

    # Build VFR tables if needed
    vfr_step = 50
    src_vfr_times, src_vfr_indices = (
        _build_vfr_table(src_clip, src_num_frames, vfr_step)
        if src_is_vfr
        else (None, None)
    )
    tgt_vfr_times, tgt_vfr_indices = (
        _build_vfr_table(tgt_clip, tgt_num_frames, vfr_step)
        if tgt_is_vfr
        else (None, None)
    )

    if src_is_vfr and src_vfr_times:
        _log(f"[VisualVerify] Source VFR table: {len(src_vfr_times)} entries")
    if tgt_is_vfr and tgt_vfr_times:
        _log(f"[VisualVerify] Target VFR table: {len(tgt_vfr_times)} entries")

    # Determine video duration from shorter clip
    src_duration_s = src_num_frames / src_raw_fps
    tgt_duration_s = tgt_num_frames / tgt_raw_fps
    duration_s = min(src_duration_s, tgt_duration_s)

    _log(f"[VisualVerify] Duration: {duration_s:.1f}s ({duration_s / 60:.1f} min)")

    # Generate sample times (skip first 2 seconds of potential black frames)
    start_time = 2.0
    sample_times: list[float] = []
    t = start_time
    while t < duration_s:
        # Ensure the offset-adjusted target time is also within bounds
        target_time = t - (offset_ms / 1000.0)
        if target_time >= 0 and target_time < tgt_duration_s:
            sample_times.append(t)
        t += sample_interval_s

    _log(f"[VisualVerify] Samples to check: {len(sample_times)}")

    # Verify each sample
    samples: list[SampleResult] = []
    for i, time_s in enumerate(sample_times):
        try:
            result = _verify_sample(
                src_clip=src_clip,
                tgt_clip=tgt_clip,
                time_s=time_s,
                offset_ms=offset_ms,
                src_fps=src_raw_fps,
                tgt_fps=tgt_raw_fps,
                src_num_frames=src_num_frames,
                tgt_num_frames=tgt_num_frames,
                src_vfr_times=src_vfr_times,
                src_vfr_indices=src_vfr_indices,
                tgt_vfr_times=tgt_vfr_times,
                tgt_vfr_indices=tgt_vfr_indices,
                search_range=search_range,
                sample_index=i,
                vfr_step=vfr_step,
            )
            samples.append(result)
        except Exception as e:
            _log(f"[VisualVerify] Sample {i} at {time_s:.1f}s failed: {e}")

        # Progress logging every 50 samples
        if (i + 1) % 50 == 0:
            _log(f"[VisualVerify] Progress: {i + 1}/{len(sample_times)} samples...")

    _log(f"[VisualVerify] Completed: {len(samples)} samples verified")

    # Close clips to free resources
    try:
        del src_clip, tgt_clip
        gc.collect()
    except Exception:
        pass

    # Detect credits region
    credits = _detect_credits_region(samples)

    # Assign region labels
    _assign_regions(samples, duration_s, credits)

    # Compute per-region stats
    regions = _compute_region_stats(samples)

    # Compute main-content stats (everything except credits)
    main_samples = [s for s in samples if s.region != "credits"]
    main_total = len(main_samples)
    main_exact = sum(1 for s in main_samples if s.classification == "exact")
    main_within_1 = sum(
        1 for s in main_samples if abs(s.best_delta) <= 1 and s.best_dist < 50.0
    )
    main_within_2 = sum(
        1 for s in main_samples if abs(s.best_delta) <= 2 and s.best_dist < 50.0
    )
    main_unmatchable = sum(
        1 for s in main_samples if s.classification == "unmatchable"
    )
    main_static = sum(1 for s in main_samples if s.is_static)

    result = VisualVerifyResult(
        job_name=job_name,
        source_path=source_video,
        target_path=target_video,
        offset_ms=offset_ms,
        frame_offset=frame_offset,
        source_fps=source_fps,
        target_fps=target_fps,
        sample_interval_s=sample_interval_s,
        search_range=search_range,
        total_samples=len(samples),
        total_duration_s=duration_s,
        verify_timestamp=datetime.now(),
        source_content_type=source_content_type,
        target_content_type=target_content_type,
        main_exact=main_exact,
        main_within_1=main_within_1,
        main_within_2=main_within_2,
        main_unmatchable=main_unmatchable,
        main_total=main_total,
        main_static=main_static,
        samples=samples,
        regions=regions,
        credits=credits,
    )

    _log(
        f"[VisualVerify] Main content accuracy (±2): "
        f"{result.accuracy_pct:.1f}% ({main_within_2}/{main_total})"
    )
    if credits.detected:
        _log(
            f"[VisualVerify] Credits detected at {credits.boundary_time_s:.0f}s "
            f"({credits.num_credits_samples} samples)"
        )

    return result


# ============================================================================
# Report Writing
# ============================================================================


def _format_time(seconds: float) -> str:
    """Format seconds as M:SS.S or H:MM:SS.S."""
    if seconds < 0:
        return f"-{_format_time(-seconds)}"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:04.1f}"
    return f"{m}:{s:04.1f}"


def write_visual_verify_report(
    result: VisualVerifyResult,
    output_dir: Path,
    log: Callable[[str], None] | None = None,
) -> Path:
    """
    Write a visual verification report to a text file.

    Args:
        result: VisualVerifyResult from run_visual_verify.
        output_dir: Directory for the report (created if needed).
        log: Optional logging function.

    Returns:
        Path to the written report file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    timestamp_str = result.verify_timestamp.strftime("%Y%m%d_%H%M%S")
    safe_job = "".join(
        c if c.isalnum() or c in "._-" else "_" for c in result.job_name
    )
    filename = f"{safe_job}_{timestamp_str}_visual_verify.txt"
    output_path = output_dir / filename

    lines: list[str] = []

    # Header
    lines.append("=" * 70)
    lines.append("VISUAL FRAME VERIFICATION REPORT")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Job: {result.job_name}")
    lines.append(
        f"Timestamp: {result.verify_timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    lines.append(f"Source: {result.source_path}")
    lines.append(f"Target: {result.target_path}")
    lines.append(
        f"Offset applied: {result.offset_ms:+.3f}ms (frame_offset: {result.frame_offset})"
    )
    lines.append(
        f"Source FPS: {result.source_fps:.3f} | Target FPS: {result.target_fps:.3f}"
    )
    lines.append(
        f"Content: source={result.source_content_type}, "
        f"target={result.target_content_type}"
    )
    lines.append(
        f"Sample interval: {result.sample_interval_s}s | "
        f"Search range: ±{result.search_range} frames"
    )
    lines.append(
        f"Duration: {result.total_duration_s:.1f}s | "
        f"Samples: {result.total_samples}"
    )
    lines.append("")

    # Overall accuracy (excluding credits)
    lines.append("=" * 70)
    lines.append("OVERALL ACCURACY (excluding credits)")
    lines.append("=" * 70)
    lines.append("")

    mt = result.main_total
    if mt > 0:
        lines.append(
            f"  Exact match (delta=0): {result.main_exact:4d}/{mt} "
            f"({100.0 * result.main_exact / mt:.1f}%)"
        )
        lines.append(
            f"  Within ±1 frame:       {result.main_within_1:4d}/{mt} "
            f"({100.0 * result.main_within_1 / mt:.1f}%)"
        )
        lines.append(
            f"  Within ±2 frames:      {result.main_within_2:4d}/{mt} "
            f"({100.0 * result.main_within_2 / mt:.1f}%)"
        )
        lines.append(
            f"  Unmatchable:           {result.main_unmatchable:4d}/{mt} "
            f"({100.0 * result.main_unmatchable / mt:.1f}%)"
        )
        lines.append(
            f"  Static/low-info:       {result.main_static:4d}/{mt} "
            f"({100.0 * result.main_static / mt:.1f}%)"
        )
    else:
        lines.append("  No main-content samples.")
    lines.append("")

    # Per-region breakdown
    lines.append("=" * 70)
    lines.append("PER-REGION BREAKDOWN")
    lines.append("=" * 70)
    lines.append("")

    for rs in result.regions:
        if rs.name == "credits":
            lines.append(
                f"  Region: {rs.name} — {rs.total} samples "
                f"[different content expected]"
            )
            lines.append(
                f"    Unmatchable: {rs.unmatchable} ({100.0 * rs.unmatchable / rs.total:.1f}%)"
                if rs.total > 0
                else "    No samples"
            )
        else:
            lines.append(f"  Region: {rs.name} — {rs.total} samples")
            if rs.total > 0:
                lines.append(
                    f"    Exact: {rs.exact} ({100.0 * rs.exact / rs.total:.1f}%)  "
                    f"±1: {rs.within_1} ({100.0 * rs.within_1 / rs.total:.1f}%)  "
                    f"±2: {rs.within_2} ({100.0 * rs.within_2 / rs.total:.1f}%)  "
                    f"Unmatch: {rs.unmatchable}"
                )
                lines.append(
                    f"    Mean dist: base={rs.mean_base_dist:.1f}, "
                    f"best={rs.mean_best_dist:.1f}"
                )
        lines.append("")

    # Credits detection
    lines.append("=" * 70)
    lines.append("CREDITS DETECTION")
    lines.append("=" * 70)
    lines.append("")

    if result.credits.detected:
        lines.append(f"  Credits detected: YES")
        lines.append(
            f"  Boundary: {_format_time(result.credits.boundary_time_s or 0)} "
            f"(sample #{result.credits.boundary_sample})"
        )
        lines.append(f"  Credits samples: {result.credits.num_credits_samples}")
    else:
        lines.append("  Credits detected: NO")
    lines.append("")

    # Drift map (non-exact, non-credits)
    drift_samples = [
        s
        for s in result.samples
        if s.classification != "exact" and s.region != "credits"
    ]

    lines.append("=" * 70)
    if drift_samples:
        lines.append(
            f"DRIFT MAP ({len(drift_samples)} non-exact samples, excluding credits)"
        )
    else:
        lines.append("DRIFT MAP (no drift detected in main content)")
    lines.append("=" * 70)
    lines.append("")

    if drift_samples:
        lines.append(
            f"  {'Time':>8s}  {'Delta':>6s}  {'BaseDist':>8s}  "
            f"{'BestDist':>8s}  {'Classification'}"
        )
        lines.append(f"  {'─' * 8}  {'─' * 6}  {'─' * 8}  {'─' * 8}  {'─' * 16}")

        for s in drift_samples:
            delta_str = f"{s.best_delta:+d}" if s.best_delta != 0 else "0"
            static_tag = " [static]" if s.is_static else ""
            lines.append(
                f"  {_format_time(s.time_s):>8s}  {delta_str:>6s}  "
                f"{s.base_dist:>8.1f}  {s.best_dist:>8.1f}  "
                f"{s.classification}{static_tag}"
            )
        lines.append("")

    # Verdict
    lines.append("=" * 70)
    lines.append("VERDICT")
    lines.append("=" * 70)
    lines.append("")

    accuracy = result.accuracy_pct
    if accuracy >= 95.0:
        verdict = "GOOD"
    elif accuracy >= 85.0:
        verdict = "FAIR"
    elif accuracy >= 70.0:
        verdict = "MARGINAL"
    else:
        verdict = "POOR"

    lines.append(f"  Offset verification: {verdict}")
    lines.append(f"  Main content accuracy (within ±2): {accuracy:.1f}%")

    if result.main_unmatchable > 0:
        lines.append(
            f"  ⚠ {result.main_unmatchable} unmatchable samples in main content"
        )

    lines.append("")
    lines.append("=" * 70)
    lines.append("END OF REPORT")
    lines.append("=" * 70)

    # Write file
    output_path.write_text("\n".join(lines), encoding="utf-8")

    if log:
        log(f"[VisualVerify] Report written to: {output_path}")

    return output_path
