# vsg_core/subtitles/sync_mode_plugins/video_verified/neural_matcher.py
"""
Neural feature sequence sliding for video-verified sync.

Uses ISC (Image Similarity Challenge) features to find the correct
frame offset between two video sources by sliding a sequence of
feature vectors from one source across the other and finding the
position with highest cumulative cosine similarity.

This is fundamentally different from the classic per-frame matching:
- Classic: compare individual frames at fixed checkpoints
- Neural: compare SEQUENCES of frames, slide across a window

The sequence approach works because even though individual frames
in static scenes are nearly identical at any offset, the *sequence
of transitions* between frames is unique and provides a strong signal.

Tested accuracy:
- Outbreak Company EP3: 9/9 exact (same-master, same fps)
- Black Summoner EP1: 9/9 exact (BDMV vs web encode)
- 009-1 EP1: 9/9 exact (interlaced DVD, with bwdif deinterlace)
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np


def calculate_neural_verified_offset(
    source_video: str,
    target_video: str,
    total_delay_ms: float,
    global_shift_ms: float,
    settings=None,
    runner=None,
    temp_dir: Path | None = None,
    video_duration_ms: float | None = None,
    debug_output_dir: Path | None = None,
    source_key: str = "",
) -> tuple[float | None, dict[str, Any]]:
    """
    Calculate video-verified offset using ISC neural feature sequence sliding.

    Same interface as calculate_video_verified_offset() so they can be
    swapped in preprocessing.py.

    Args:
        source_video: Path to source video file
        target_video: Path to target video file (Source 1)
        total_delay_ms: Total delay from audio correlation (with global shift)
        global_shift_ms: Global shift component of the delay
        settings: AppSettings with neural-specific parameters
        runner: CommandRunner for logging
        temp_dir: Temp directory for frame cache / ffms2 index
        video_duration_ms: Optional video duration
        debug_output_dir: Directory for debug reports (None = disabled)

    Returns:
        Tuple of (final_offset_ms, details_dict)
    """
    from ....models.settings import AppSettings

    if settings is None:
        settings = AppSettings()

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    pure_correlation_ms = total_delay_ms - global_shift_ms

    log("[NeuralVerified] === Neural Feature Matching ===")
    log(f"[NeuralVerified] Source: {Path(source_video).name}")
    log(f"[NeuralVerified] Target: {Path(target_video).name}")
    log(f"[NeuralVerified] Total delay (with global): {total_delay_ms:+.3f}ms")
    log(f"[NeuralVerified] Global shift: {global_shift_ms:+.3f}ms")
    log(f"[NeuralVerified] Pure correlation (audio): {pure_correlation_ms:+.3f}ms")

    # Get neural-specific settings
    window_sec = getattr(settings, "neural_window_seconds", 10)
    slide_range_sec = getattr(settings, "neural_slide_range_seconds", 5)
    num_positions = getattr(settings, "neural_num_positions", 9)
    batch_size = getattr(settings, "neural_batch_size", 32)

    log(f"[NeuralVerified] Model: ISC ft_v107 (256-dim)")
    log(
        f"[NeuralVerified] Window: {window_sec}s, Slide: ±{slide_range_sec}s, "
        f"Positions: {num_positions}, Batch: {batch_size}"
    )

    # Open video clips with VapourSynth
    try:
        import vapoursynth as vs
    except ImportError as e:
        log(f"[NeuralVerified] VapourSynth not available: {e}")
        return total_delay_ms, {
            "reason": "fallback-no-vapoursynth",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
        }

    try:
        import torch
    except ImportError as e:
        log(f"[NeuralVerified] PyTorch not available: {e}")
        return total_delay_ms, {
            "reason": "fallback-no-torch",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
        }

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Open clips
    try:
        src_yuv, src_rgb = _open_clip(source_video, vs, temp_dir)
        tgt_yuv, tgt_rgb = _open_clip(target_video, vs, temp_dir)
    except Exception as e:
        log(f"[NeuralVerified] Failed to open videos: {e}")
        return total_delay_ms, {
            "reason": "fallback-video-open-failed",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
        }

    src_fps = src_yuv.fps.numerator / src_yuv.fps.denominator
    tgt_fps = tgt_yuv.fps.numerator / tgt_yuv.fps.denominator
    src_frame_dur_ms = 1000.0 / src_fps

    log(
        f"[NeuralVerified] Source: {src_yuv.num_frames}f @ {src_fps:.3f}fps, "
        f"{src_yuv.width}x{src_yuv.height}"
    )
    log(
        f"[NeuralVerified] Target: {tgt_yuv.num_frames}f @ {tgt_fps:.3f}fps, "
        f"{tgt_yuv.width}x{tgt_yuv.height}"
    )

    # Check FPS compatibility — for now we only handle same-fps content
    fps_ratio = max(src_fps, tgt_fps) / min(src_fps, tgt_fps)
    if fps_ratio > 1.01:
        log(
            f"[NeuralVerified] WARNING: FPS mismatch ({src_fps:.3f} vs {tgt_fps:.3f}), "
            f"ratio={fps_ratio:.4f}"
        )
        log("[NeuralVerified] Cross-fps matching not yet supported in production")
        log("[NeuralVerified] Falling back to audio correlation")
        return total_delay_ms, {
            "reason": "fallback-cross-fps",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "source_fps": src_fps,
            "target_fps": tgt_fps,
        }

    # Determine duration
    src_dur_ms = video_duration_ms
    if not src_dur_ms or src_dur_ms <= 0:
        src_dur_ms = src_yuv.num_frames / src_fps * 1000.0

    # Load ISC model
    t_model_start = time.time()
    try:
        from .isc_model import create_isc_model

        model, preprocessor = create_isc_model(device=str(device), log=log)
    except Exception as e:
        log(f"[NeuralVerified] Failed to load ISC model: {e}")
        return total_delay_ms, {
            "reason": "fallback-model-failed",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
        }
    t_model = time.time() - t_model_start

    # Calculate frame counts for window and slide
    src_n_frames = int(window_sec * src_fps)
    slide_pad = int(slide_range_sec * tgt_fps)

    log(f"[NeuralVerified] Source window: {src_n_frames} frames ({window_sec}s)")
    log(f"[NeuralVerified] Slide range: ±{slide_pad} frames (±{slide_range_sec}s)")
    log(f"[NeuralVerified] Model load time: {t_model:.1f}s")

    # Select test positions (evenly across 10%–90%)
    positions_pct = [10 + 80 * (i + 0.5) / num_positions for i in range(num_positions)]

    log(f"[NeuralVerified] ─────────────────────────────────────")
    log(f"[NeuralVerified] Testing {num_positions} positions")
    log(f"[NeuralVerified] ─────────────────────────────────────")

    # Run sliding at each position
    results = []
    landscapes = []
    t_total_start = time.time()

    for i, pct in enumerate(positions_pct):
        t_pos_start = time.time()

        # Source frame range
        src_start = int(src_rgb.num_frames * pct / 100.0)
        src_end = min(src_start + src_n_frames, src_rgb.num_frames)
        src_frames = list(range(src_start, src_end))

        # Target frame range (padded for sliding)
        tgt_center = src_start  # Start from same position
        tgt_window_start = max(0, tgt_center - slide_pad)
        tgt_window_end = min(tgt_rgb.num_frames, tgt_center + src_n_frames + slide_pad)
        tgt_frames = list(range(tgt_window_start, tgt_window_end))

        if len(tgt_frames) <= len(src_frames):
            log(
                f"[NeuralVerified]   [{i + 1}/{num_positions}] {pct:.0f}% — SKIPPED (edge)"
            )
            continue

        # Extract features
        src_feats = _extract_features_batch(
            src_rgb, src_frames, model, device, batch_size, torch
        )
        tgt_feats = _extract_features_batch(
            tgt_rgb, tgt_frames, model, device, batch_size, torch
        )

        # Slide and score
        scores, match_counts = _slide_and_score(src_feats, tgt_feats)

        if len(scores) == 0:
            log(
                f"[NeuralVerified]   [{i + 1}/{num_positions}] {pct:.0f}% — SKIPPED (no slides)"
            )
            continue

        best_pos = int(np.argmax(scores))
        # Sign convention: source_video=Source2, target_video=Source1
        # Positive = Source 2 subs shift forward, Negative = shift backward
        # (tgt_pos - src_pos): if Source 2 content is at frame 4917 but matches
        # Source 1 at frame 4941, offset = +24 = "shift Source 2 forward by 24f"
        offset_frames = (tgt_window_start + best_pos) - src_start
        offset_ms = offset_frames * src_frame_dur_ms

        # Score gradient (how sharp is the peak)
        gradient = _compute_gradient(scores, best_pos)

        dt = time.time() - t_pos_start

        result = {
            "position_pct": pct,
            "src_start": src_start,
            "offset_frames": offset_frames,
            "offset_ms": offset_ms,
            "score": float(scores[best_pos]),
            "matches": int(match_counts[best_pos]),
            "total": len(src_frames),
            "gradient": gradient,
            "time_s": dt,
        }
        results.append(result)

        landscape = {
            "position_pct": pct,
            "scores": scores.tolist(),
            "match_counts": match_counts.tolist(),
            "best_pos": best_pos,
            "tgt_window_start": tgt_window_start,
            "src_start": src_start,
        }
        landscapes.append(landscape)

        log(
            f"[NeuralVerified]   [{i + 1}/{num_positions}] {pct:.0f}% @{src_start}f → "
            f"offset={offset_frames:+d}f ({offset_ms:+.1f}ms) "
            f"score={scores[best_pos]:.4f} "
            f"match={int(match_counts[best_pos])}/{len(src_frames)} "
            f"grad={gradient:.4f}/f ({dt:.1f}s)"
        )

    dt_total = time.time() - t_total_start

    if not results:
        log("[NeuralVerified] No valid positions — falling back to audio correlation")
        return total_delay_ms, {
            "reason": "fallback-no-valid-positions",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
        }

    # ─── CONSENSUS ───────────────────────────────────────────────
    offsets_f = [r["offset_frames"] for r in results]
    offsets_ms = [r["offset_ms"] for r in results]
    scores_list = [r["score"] for r in results]
    consensus = Counter(offsets_f).most_common(1)[0]
    consensus_frames = consensus[0]
    consensus_count = consensus[1]
    consensus_ms = consensus_frames * src_frame_dur_ms

    # Confidence assessment
    consensus_ratio = consensus_count / len(results)
    mean_score = float(np.mean(scores_list))
    min_score = float(min(scores_list))
    mean_gradient = float(np.mean([r["gradient"] for r in results]))

    if consensus_ratio >= 0.9 and mean_score >= 0.98:
        confidence = "HIGH"
    elif consensus_ratio >= 0.7 and mean_score >= 0.95:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # ─── RESULTS SUMMARY ─────────────────────────────────────────
    log(f"[NeuralVerified] ═══════════════════════════════════════")
    log(f"[NeuralVerified] RESULTS SUMMARY")
    log(f"[NeuralVerified] ═══════════════════════════════════════")
    log(
        f"[NeuralVerified] Consensus: {consensus_frames:+d}f = {consensus_ms:+.1f}ms "
        f"({consensus_count}/{len(results)} positions)"
    )
    log(
        f"[NeuralVerified] Mean score: {mean_score:.4f}, "
        f"Range: [{min_score:.4f}, {max(scores_list):.4f}]"
    )
    log(f"[NeuralVerified] Mean gradient: {mean_gradient:.4f}/frame")
    log(f"[NeuralVerified] Confidence: {confidence}")
    log(f"[NeuralVerified] Audio correlation: {pure_correlation_ms:+.3f}ms")

    diff_ms = consensus_ms - pure_correlation_ms
    diff_frames = diff_ms / src_frame_dur_ms
    log(
        f"[NeuralVerified] Difference from audio: {diff_ms:+.1f}ms ({diff_frames:+.1f} frames)"
    )

    if abs(diff_ms) > src_frame_dur_ms / 2:
        log(f"[NeuralVerified] VIDEO OFFSET DIFFERS FROM AUDIO CORRELATION")

    log(
        f"[NeuralVerified] Total time: {dt_total:.1f}s "
        f"({dt_total / len(results):.1f}s/position)"
    )
    log(f"[NeuralVerified] ─────────────────────────────────────")

    # Score landscape summary for top 3 positions
    for land in landscapes[:3]:
        sc = np.array(land["scores"])
        bp = land["best_pos"]
        src_start = land["src_start"]
        tgt_ws = land["tgt_window_start"]
        best_off_f = (tgt_ws + bp) - src_start
        best_off_ms = best_off_f * src_frame_dur_ms

        log(
            f"[NeuralVerified]   Landscape {land['position_pct']:.0f}%: "
            f"peak {best_off_f:+d}f ({best_off_ms:+.1f}ms) score={sc[bp]:.4f}"
        )

        # Show ±5 frames around peak
        for delta in range(-5, 6):
            pos = bp + delta
            if 0 <= pos < len(sc):
                off_f = (tgt_ws + pos) - src_start
                off_ms = off_f * src_frame_dur_ms
                marker = " ★" if delta == 0 else ""
                log(
                    f"[NeuralVerified]     {off_f:+4d}f ({off_ms:+7.1f}ms): "
                    f"{sc[pos]:.4f}{marker}"
                )

    log(f"[NeuralVerified] ─────────────────────────────────────")

    # ─── DEBUG REPORT ─────────────────────────────────────────────
    if debug_output_dir:
        _write_debug_report(
            debug_output_dir=debug_output_dir,
            source_video=source_video,
            target_video=target_video,
            source_key=source_key,
            pure_correlation_ms=pure_correlation_ms,
            consensus_frames=consensus_frames,
            consensus_ms=consensus_ms,
            consensus_count=consensus_count,
            confidence=confidence,
            mean_score=mean_score,
            results=results,
            landscapes=landscapes,
            src_fps=src_fps,
            tgt_fps=tgt_fps,
            src_frame_dur_ms=src_frame_dur_ms,
            dt_total=dt_total,
            log=log,
        )

    # ─── CALCULATE FINAL OFFSET ──────────────────────────────────
    # Neural offset is the consensus in ms
    video_offset_ms = consensus_ms
    final_offset_ms = video_offset_ms + global_shift_ms

    log(f"[NeuralVerified] Video-verified offset: {video_offset_ms:+.3f}ms (neural)")
    log(f"[NeuralVerified] + Global shift: {global_shift_ms:+.3f}ms")
    log(f"[NeuralVerified] = Final offset: {final_offset_ms:+.3f}ms")
    log(f"[NeuralVerified] ═══════════════════════════════════════")

    return final_offset_ms, {
        "reason": "neural-matched",
        "audio_correlation_ms": pure_correlation_ms,
        "video_offset_ms": video_offset_ms,
        "frame_offset": consensus_frames,
        "final_offset_ms": final_offset_ms,
        "confidence": confidence,
        "consensus_count": consensus_count,
        "num_positions": len(results),
        "mean_score": mean_score,
        "min_score": min_score,
        "mean_gradient": mean_gradient,
        "source_fps": src_fps,
        "target_fps": tgt_fps,
        "total_time_s": dt_total,
        "per_position_results": results,
    }


# ─── Internal helpers ─────────────────────────────────────────────────


def _open_clip(video_path: str, vs, temp_dir: Path | None = None):
    """Open a video with VapourSynth/FFMS2 and return (yuv_clip, rgb_clip)."""
    from ...frame_utils.video_reader import _get_ffms2_cache_path

    core = vs.core

    # Use the same cache-path logic as the classic matcher so indexes
    # always land in job_temp/ffindex/ (never next to the source file).
    cache_path = str(_get_ffms2_cache_path(video_path, temp_dir))

    try:
        clip = core.ffms2.Source(source=video_path, cachefile=cache_path)
    except Exception:
        # Delete stale index and retry — still specify cachefile so the
        # index never lands next to the original source file.
        stale = Path(cache_path)
        if stale.exists():
            stale.unlink(missing_ok=True)
        clip = core.ffms2.Source(source=video_path, cachefile=cache_path)

    rgb_clip = core.resize.Bicubic(clip, format=vs.RGB24, matrix_in_s="170m")
    return clip, rgb_clip


def _frame_to_tensor(frame, device, F):
    """Convert a VapourSynth frame to a normalized GPU tensor for ISC."""
    import torch

    r = np.asarray(frame[0])
    g = np.asarray(frame[1])
    b = np.asarray(frame[2])
    rgb_np = np.stack([r, g, b], axis=0).astype(np.float32) / 255.0
    tensor = torch.from_numpy(rgb_np).unsqueeze(0).to(device)
    resized = F.interpolate(
        tensor, size=(512, 512), mode="bilinear", align_corners=False
    )
    mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)
    normalized = (resized - mean) / std
    return normalized.squeeze(0)


def _extract_features_batch(rgb_clip, frame_nums, model, device, batch_size, torch):
    """Extract ISC features for a list of frame numbers using GPU batch processing.

    Uses clip.frames() for contiguous frame ranges (faster I/O) with GPU resize
    and normalization (skips PIL).
    """
    import torch.nn.functional as F

    all_feats = []
    batch_tensors = []

    first_frame = frame_nums[0]
    last_frame = frame_nums[-1]
    is_contiguous = frame_nums == list(range(first_frame, last_frame + 1))

    with torch.no_grad():
        if is_contiguous:
            # Fast path: use clip.frames() for contiguous ranges
            trimmed = rgb_clip[first_frame : last_frame + 1]
            for i, frame in enumerate(trimmed.frames()):
                tensor = _frame_to_tensor(frame, device, F)
                batch_tensors.append(tensor)

                if len(batch_tensors) == batch_size or i == len(frame_nums) - 1:
                    batch = torch.stack(batch_tensors).to(device)
                    feats = model(batch)
                    all_feats.append(feats.cpu())
                    batch_tensors = []
        else:
            # Slow path: random access
            for fn in frame_nums:
                fn_clamped = max(0, min(fn, rgb_clip.num_frames - 1))
                frame = rgb_clip.get_frame(fn_clamped)
                tensor = _frame_to_tensor(frame, device, F)
                batch_tensors.append(tensor)

                if len(batch_tensors) == batch_size or fn == frame_nums[-1]:
                    batch = torch.stack(batch_tensors).to(device)
                    feats = model(batch)
                    all_feats.append(feats.cpu())
                    batch_tensors = []

    return torch.cat(all_feats, dim=0).numpy()


def _slide_and_score(src_feats: np.ndarray, tgt_feats: np.ndarray):
    """Slide source features across target and compute cosine similarity at each position.

    Returns:
        scores: mean cosine similarity at each slide position
        match_counts: number of frame pairs with similarity > 0.5
    """
    S = len(src_feats)
    T = len(tgt_feats)
    max_slides = T - S + 1
    if max_slides <= 0:
        return np.array([]), np.array([])

    # L2 normalize
    src_norm = src_feats / (np.linalg.norm(src_feats, axis=1, keepdims=True) + 1e-8)
    tgt_norm = tgt_feats / (np.linalg.norm(tgt_feats, axis=1, keepdims=True) + 1e-8)

    scores = np.zeros(max_slides)
    match_counts = np.zeros(max_slides, dtype=int)
    for p in range(max_slides):
        pair_sims = np.sum(src_norm * tgt_norm[p : p + S], axis=1)
        scores[p] = pair_sims.mean()
        match_counts[p] = np.sum(pair_sims > 0.5)

    return scores, match_counts


def _compute_gradient(scores: np.ndarray, best_pos: int) -> float:
    """Compute average score drop-off per frame from peak.

    Higher gradient = sharper peak = more confident result.
    """
    if len(scores) < 3:
        return 0.0

    peak_score = scores[best_pos]
    gradients = []

    # Check ±5 frames
    for delta in range(1, 6):
        for sign in [-1, 1]:
            pos = best_pos + sign * delta
            if 0 <= pos < len(scores):
                drop = peak_score - scores[pos]
                gradients.append(drop / delta)

    return float(np.mean(gradients)) if gradients else 0.0


def _write_debug_report(
    debug_output_dir: Path,
    source_video: str,
    target_video: str,
    source_key: str,
    pure_correlation_ms: float,
    consensus_frames: int,
    consensus_ms: float,
    consensus_count: int,
    confidence: str,
    mean_score: float,
    results: list[dict],
    landscapes: list[dict],
    src_fps: float,
    tgt_fps: float,
    src_frame_dur_ms: float,
    dt_total: float,
    log: Callable,
) -> None:
    """Write detailed debug report to neural_verify directory."""
    try:
        debug_output_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename: {job}_{sourceKey}_neural_verify.txt
        # Matches frame audit convention: 1_Source3_t2_frame_audit.txt
        tgt_stem = Path(target_video).stem
        key_sanitized = source_key.replace(" ", "") if source_key else "unknown"
        report_name = f"{tgt_stem}_{key_sanitized}_neural_verify.txt"
        report_path = debug_output_dir / report_name

        lines = []
        lines.append("=" * 80)
        lines.append("NEURAL FEATURE MATCHING DEBUG REPORT")
        lines.append("=" * 80)
        lines.append(f"Source: {source_video}")
        lines.append(f"Target: {target_video}")
        lines.append(f"Source FPS: {src_fps:.3f}")
        lines.append(f"Target FPS: {tgt_fps:.3f}")
        lines.append(f"Frame duration: {src_frame_dur_ms:.2f}ms")
        lines.append(f"Audio correlation: {pure_correlation_ms:+.3f}ms")
        lines.append(f"")
        lines.append(
            f"RESULT: {consensus_frames:+d}f = {consensus_ms:+.1f}ms "
            f"({consensus_count}/{len(results)} consensus)"
        )
        lines.append(f"Confidence: {confidence}")
        lines.append(f"Mean score: {mean_score:.4f}")
        lines.append(f"Total time: {dt_total:.1f}s")
        lines.append("")

        # Per-position results
        lines.append("-" * 80)
        lines.append("PER-POSITION RESULTS")
        lines.append("-" * 80)
        for r in results:
            lines.append(
                f"  {r['position_pct']:5.1f}% @{r['src_start']:6d}f: "
                f"offset={r['offset_frames']:+4d}f ({r['offset_ms']:+8.1f}ms) "
                f"score={r['score']:.4f} match={r['matches']}/{r['total']} "
                f"grad={r['gradient']:.4f}/f ({r['time_s']:.1f}s)"
            )
        lines.append("")

        # Full score landscapes
        lines.append("-" * 80)
        lines.append("SCORE LANDSCAPES (all positions)")
        lines.append("-" * 80)
        for land in landscapes:
            sc = np.array(land["scores"])
            bp = land["best_pos"]
            src_start = land["src_start"]
            tgt_ws = land["tgt_window_start"]
            best_off_f = (tgt_ws + bp) - src_start
            best_off_ms = best_off_f * src_frame_dur_ms

            lines.append(f"")
            lines.append(
                f"  Position {land['position_pct']:.0f}% (src={src_start}) — "
                f"peak: {best_off_f:+d}f ({best_off_ms:+.1f}ms) "
                f"score={sc[bp]:.4f}"
            )

            for delta in range(-15, 16):
                pos = bp + delta
                if 0 <= pos < len(sc):
                    off_f = (tgt_ws + pos) - src_start
                    off_ms = off_f * src_frame_dur_ms
                    marker = " ★" if delta == 0 else ""
                    bar_val = max(0, (sc[pos] - 0.3) * 60)
                    bar = "█" * int(bar_val)
                    lines.append(
                        f"    {off_f:+4d}f ({off_ms:+7.1f}ms): "
                        f"{sc[pos]:.4f} {bar}{marker}"
                    )

        report_path.write_text("\n".join(lines), encoding="utf-8")
        log(f"[NeuralVerified] Debug report saved: {report_path}")

    except Exception as e:
        log(f"[NeuralVerified] WARNING: Failed to write debug report: {e}")
