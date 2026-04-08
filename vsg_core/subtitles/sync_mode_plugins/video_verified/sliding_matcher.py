# vsg_core/subtitles/sync_mode_plugins/video_verified/sliding_matcher.py
"""
Sliding-window feature matching for video-verified subtitle sync.

Unified orchestrator for all video-verified matching. Pluggable backends
(ISC, SSCD mixup, SSCD large, pHash GPU, dHash GPU, SSIM GPU) share the
same sliding-window protocol — walk the source video at N positions,
extract a feature sequence per position, slide it across the target
to find the best-matching offset, then vote across positions for a
consensus answer. Each backend provides its own ``score()`` method via
the ``SlidingBackend`` protocol; everything else is backend-agnostic.

This replaces the former ``neural_matcher.py`` (ISC-only) with a design
that scales to any feature extractor. The back-compat wrapper
``calculate_neural_verified_offset()`` is preserved at the bottom of the
file so legacy callers still work during the refactor transition.

Critical invariants preserved verbatim from neural_matcher.py:
- PTS correction (source and target ``_AbsoluteTime`` delta) is applied
  in the orchestrator so the backend always receives wall-clock-aligned
  frame indices and never has to think about container timing.
- Consensus, confidence thresholds, and debug-report structure are
  unchanged — the matcher returns the same ``details`` dict shape as
  before, with only two new fields: ``backend`` and ``reason`` switched
  from ``"neural-matched"`` to ``"sliding-matched"``.

Tested accuracy baselines (neural_matcher.py heritage, should remain
intact for the ISC backend):
- Outbreak Company EP3: 9/9 exact (same-master, same fps)
- Black Summoner EP1:   9/9 exact (BDMV vs web encode)
- 009-1 EP1:            9/9 exact (interlaced DVD, with bwdif deinterlace)
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .backends import BackendResult, SlidingBackend, get_backend
from .sliding_core import compute_gradient, open_clip


# ── Main entrypoint ───────────────────────────────────────────────────────────


def calculate_sliding_offset(
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
    backend_name: str = "isc",
) -> tuple[float | None, dict[str, Any]]:
    """Calculate video-verified offset via sliding-window matching.

    Parameters
    ----------
    source_video, target_video
        Absolute paths to the source (needs sub correction) and target
        (reference) video files.
    total_delay_ms
        Total delay from audio correlation (includes global_shift_ms).
    global_shift_ms
        Global shift component already baked into total_delay_ms.
    settings
        ``AppSettings`` instance. Read for backend-specific settings
        (``video_verified_window_seconds``, ``video_verified_hash_size``,
        etc.). If ``None``, defaults are used.
    runner
        Optional ``CommandRunner`` with ``_log_message(str)`` method.
    temp_dir
        Directory for ffms2 index cache. Defaults to the system temp dir.
    video_duration_ms
        Optional source video duration in ms; auto-detected from
        ``src_rgb.num_frames / src_fps`` if not provided.
    debug_output_dir
        Directory for the per-source debug report. ``None`` = disabled.
    source_key
        Source identifier (e.g. ``"Source 2"``) used in debug report
        filenames and log prefixes.
    backend_name
        Which sliding backend to use. Must be a valid
        ``VideoVerifiedBackendStr`` value. Defaults to ``"isc"`` so
        legacy callers get the same behavior they had before.

    Returns
    -------
    (final_offset_ms, details_dict)
        ``final_offset_ms`` is the corrected sub timing (``video_offset_ms
        + global_shift_ms``). ``details_dict`` carries the full matcher
        output including per-position results, PTS correction metadata,
        confidence, and backend identification — see the return block
        for the exact shape.
    """
    from ....models.settings import AppSettings  # noqa: PLC0415

    if settings is None:
        settings = AppSettings()

    def log(msg: str) -> None:
        if runner:
            runner._log_message(msg)

    pure_correlation_ms = total_delay_ms - global_shift_ms

    # ─── BACKEND DESCRIPTOR (pre-load, for logging) ───────────────
    try:
        backend: SlidingBackend = get_backend(backend_name)
    except ValueError as e:
        log(f"[SlidingVerified] Unknown backend {backend_name!r}: {e}")
        return total_delay_ms, {
            "reason": "fallback-unknown-backend",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
            "backend": backend_name,
        }

    log("[SlidingVerified] === Sliding-Window Feature Matching ===")
    log(f"[SlidingVerified] Backend: {backend.display_name} ({backend_name})")
    log(f"[SlidingVerified] Source: {Path(source_video).name}")
    log(f"[SlidingVerified] Target: {Path(target_video).name}")
    log(f"[SlidingVerified] Total delay (with global): {total_delay_ms:+.3f}ms")
    log(f"[SlidingVerified] Global shift: {global_shift_ms:+.3f}ms")
    log(f"[SlidingVerified] Pure correlation (audio): {pure_correlation_ms:+.3f}ms")

    # ─── SLIDING GEOMETRY SETTINGS ──────────────────────────────
    window_sec = getattr(settings, "video_verified_window_seconds", 10)
    slide_range_sec = getattr(settings, "video_verified_slide_range_seconds", 5)
    num_positions = getattr(settings, "video_verified_num_positions", 9)
    batch_size = getattr(settings, "video_verified_batch_size", 32)

    log(
        f"[SlidingVerified] Window: {window_sec}s, Slide: ±{slide_range_sec}s, "
        f"Positions: {num_positions}, Batch: {batch_size}"
    )

    # ─── VAPOURSYNTH / TORCH AVAILABILITY ───────────────────────
    try:
        import vapoursynth as vs  # noqa: PLC0415
    except ImportError as e:
        log(f"[SlidingVerified] VapourSynth not available: {e}")
        return total_delay_ms, {
            "reason": "fallback-no-vapoursynth",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
            "backend": backend_name,
        }

    try:
        import torch  # noqa: PLC0415
    except ImportError as e:
        log(f"[SlidingVerified] PyTorch not available: {e}")
        return total_delay_ms, {
            "reason": "fallback-no-torch",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
            "backend": backend_name,
        }

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # ─── OPEN CLIPS (with PTS metadata) ──────────────────────────
    try:
        src_yuv, src_rgb, src_start_pts_s = open_clip(source_video, vs, temp_dir)
        tgt_yuv, tgt_rgb, tgt_start_pts_s = open_clip(target_video, vs, temp_dir)
    except Exception as e:
        log(f"[SlidingVerified] Failed to open videos: {e}")
        return total_delay_ms, {
            "reason": "fallback-video-open-failed",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
            "backend": backend_name,
        }

    src_fps = src_yuv.fps.numerator / src_yuv.fps.denominator
    tgt_fps = tgt_yuv.fps.numerator / tgt_yuv.fps.denominator
    src_frame_dur_ms = 1000.0 / src_fps

    log(
        f"[SlidingVerified] Source: {src_yuv.num_frames}f @ {src_fps:.3f}fps, "
        f"{src_yuv.width}x{src_yuv.height}  start_pts={src_start_pts_s:+.6f}s"
    )
    log(
        f"[SlidingVerified] Target: {tgt_yuv.num_frames}f @ {tgt_fps:.3f}fps, "
        f"{tgt_yuv.width}x{tgt_yuv.height}  start_pts={tgt_start_pts_s:+.6f}s"
    )

    # ─── PTS OFFSET CORRECTION ───────────────────────────────────
    # If source and target have different container PTS start times,
    # their frame-index spaces are shifted by a constant whole-frame
    # amount relative to each other. The matcher compares frames by
    # index, so an N-frame PTS label mismatch looks identical to an
    # N-frame content shift — even though the wall-clock-aligned subs
    # need no shift at all.
    #
    # We pre-compute the delta in frames (rounded to nearest whole
    # frame), shift the target window center so the sliding search is
    # centered on wall-clock equality, and subtract the same amount
    # from the final reported offset. The sub shifter therefore always
    # receives a WALL-CLOCK shift, regardless of either file's PTS
    # origin.
    #
    # For the common case (both files start_pts=0) the delta is zero
    # and every subsequent line executes identically to a PTS-unaware
    # matcher. No regression is possible when delta==0.
    pts_delta_s = src_start_pts_s - tgt_start_pts_s
    pts_delta_frames = int(round(pts_delta_s * src_fps))
    pts_correction_applied = pts_delta_frames != 0

    if pts_correction_applied:
        log("[SlidingVerified] ─────────────────────────────────────")
        log("[SlidingVerified] ⚠ PTS DELTA DETECTED — applying correction")
        log(f"[SlidingVerified]   Source start_pts: {src_start_pts_s:+.6f}s")
        log(f"[SlidingVerified]   Target start_pts: {tgt_start_pts_s:+.6f}s")
        log(
            f"[SlidingVerified]   Delta:            {pts_delta_s:+.6f}s "
            f"= {pts_delta_frames:+d} frames"
        )
        log(
            f"[SlidingVerified]   Action: target window center shifted by "
            f"{pts_delta_frames:+d} frames so search is centered on wall-clock equality"
        )
        log(
            "[SlidingVerified]   Cause:  source has non-zero PTS origin "
            "(container metadata preserves a wall-clock offset)"
        )
        log(
            "[SlidingVerified]   Output: matcher will return a WALL-CLOCK offset, "
            "which is what sub timing uses"
        )
        log(
            "[SlidingVerified]   REVIEW: this source will be flagged in the final "
            "audit — please verify subs manually in the output"
        )
        log("[SlidingVerified] ─────────────────────────────────────")

    # ─── FPS COMPATIBILITY CHECK ────────────────────────────────
    fps_ratio = max(src_fps, tgt_fps) / min(src_fps, tgt_fps)
    if fps_ratio > 1.01:
        log(
            f"[SlidingVerified] WARNING: FPS mismatch ({src_fps:.3f} vs {tgt_fps:.3f}), "
            f"ratio={fps_ratio:.4f}"
        )
        log("[SlidingVerified] Cross-fps matching not yet supported in production")
        log("[SlidingVerified] Falling back to audio correlation")
        return total_delay_ms, {
            "reason": "fallback-cross-fps",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "source_fps": src_fps,
            "target_fps": tgt_fps,
            "backend": backend_name,
        }

    # Determine duration
    src_dur_ms = video_duration_ms
    if not src_dur_ms or src_dur_ms <= 0:
        src_dur_ms = src_yuv.num_frames / src_fps * 1000.0

    # ─── LOAD BACKEND ───────────────────────────────────────────
    t_model_start = time.time()
    try:
        backend.load(device, settings)
    except FileNotFoundError as e:
        log(f"[SlidingVerified] Backend weights missing: {e}")
        return total_delay_ms, {
            "reason": "fallback-backend-weights-missing",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
            "backend": backend_name,
        }
    except Exception as e:
        log(f"[SlidingVerified] Failed to load backend: {e}")
        return total_delay_ms, {
            "reason": "fallback-backend-load-failed",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
            "backend": backend_name,
        }
    t_model = time.time() - t_model_start

    # ─── SLIDING GEOMETRY ───────────────────────────────────────
    src_n_frames = int(window_sec * src_fps)
    slide_pad = int(slide_range_sec * tgt_fps)

    log(f"[SlidingVerified] Source window: {src_n_frames} frames ({window_sec}s)")
    log(f"[SlidingVerified] Slide range: ±{slide_pad} frames (±{slide_range_sec}s)")
    log(f"[SlidingVerified] Backend load time: {t_model:.1f}s")

    # Select test positions (evenly across 10%–90%)
    positions_pct = [10 + 80 * (i + 0.5) / num_positions for i in range(num_positions)]

    log("[SlidingVerified] ─────────────────────────────────────")
    log(f"[SlidingVerified] Testing {num_positions} positions")
    log("[SlidingVerified] ─────────────────────────────────────")

    # ─── PER-POSITION SLIDING ───────────────────────────────────
    results: list[dict[str, Any]] = []
    landscapes: list[dict[str, Any]] = []
    t_total_start = time.time()

    for i, pct in enumerate(positions_pct):
        t_pos_start = time.time()

        # Source frame range
        src_start = int(src_rgb.num_frames * pct / 100.0)
        src_end = min(src_start + src_n_frames, src_rgb.num_frames)
        src_frames = list(range(src_start, src_end))

        # Target frame range (padded for sliding).
        # tgt_center is shifted by pts_delta_frames so that slide_pos == slide_pad
        # corresponds to WALL-CLOCK equality (not frame-index equality) between
        # src_frames[0] and tgt_frames[slide_pad]. For files where both
        # start_pts values are 0 this adds 0 and is identical to the
        # pre-patch version.
        tgt_center = src_start + pts_delta_frames
        tgt_window_start = max(0, tgt_center - slide_pad)
        tgt_window_end = min(tgt_rgb.num_frames, tgt_center + src_n_frames + slide_pad)
        tgt_frames = list(range(tgt_window_start, tgt_window_end))

        if len(tgt_frames) <= len(src_frames):
            log(
                f"[SlidingVerified]   [{i + 1}/{num_positions}] {pct:.0f}% — SKIPPED (edge)"
            )
            continue

        # ─── Backend scoring ───────────────────────────────────
        try:
            bresult: BackendResult = backend.score(
                src_rgb,
                src_frames,
                tgt_rgb,
                tgt_frames,
                device,
                batch_size,
                settings,
            )
        except Exception as e:
            log(
                f"[SlidingVerified]   [{i + 1}/{num_positions}] {pct:.0f}% — "
                f"BACKEND ERROR: {e}"
            )
            continue

        scores = bresult.scores
        match_counts = bresult.match_counts

        if len(scores) == 0:
            log(
                f"[SlidingVerified]   [{i + 1}/{num_positions}] {pct:.0f}% — SKIPPED (no slides)"
            )
            continue

        best_pos = int(np.argmax(scores))
        # Sign convention: source_video=Source2, target_video=Source1.
        # Positive offset = Source 2 subs shift forward, Negative = shift backward.
        #
        # raw_offset_frames is the frame-index offset the matcher found. Some
        # (or all) of this may be due to the PTS label mismatch already
        # absorbed into tgt_center above. We subtract pts_delta_frames so
        # that offset_frames represents only the *additional* wall-clock
        # shift (= what the sub shifter should actually apply).
        raw_offset_frames = (tgt_window_start + best_pos) - src_start
        offset_frames = raw_offset_frames - pts_delta_frames
        offset_ms = offset_frames * src_frame_dur_ms

        # Score gradient (how sharp is the peak)
        gradient = compute_gradient(scores, best_pos)

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
            f"[SlidingVerified]   [{i + 1}/{num_positions}] {pct:.0f}% @{src_start}f → "
            f"offset={offset_frames:+d}f ({offset_ms:+.1f}ms) "
            f"score={scores[best_pos]:.4f} "
            f"match={int(match_counts[best_pos])}/{len(src_frames)} "
            f"grad={gradient:.4f}/f ({dt:.1f}s)"
        )

    dt_total = time.time() - t_total_start

    # Release backend resources before returning
    backend.cleanup()

    if not results:
        log("[SlidingVerified] No valid positions — falling back to audio correlation")
        return total_delay_ms, {
            "reason": "fallback-no-valid-positions",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "backend": backend_name,
        }

    # ─── CONSENSUS ───────────────────────────────────────────────
    offsets_f = [r["offset_frames"] for r in results]
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
    log("[SlidingVerified] ═══════════════════════════════════════")
    log("[SlidingVerified] RESULTS SUMMARY")
    log("[SlidingVerified] ═══════════════════════════════════════")
    log(
        f"[SlidingVerified] Consensus: {consensus_frames:+d}f = {consensus_ms:+.1f}ms "
        f"({consensus_count}/{len(results)} positions)"
    )
    log(
        f"[SlidingVerified] Mean score: {mean_score:.4f}, "
        f"Range: [{min_score:.4f}, {max(scores_list):.4f}]"
    )
    log(f"[SlidingVerified] Mean gradient: {mean_gradient:.4f}/frame")
    log(f"[SlidingVerified] Confidence: {confidence}")
    log(f"[SlidingVerified] Audio correlation: {pure_correlation_ms:+.3f}ms")

    diff_ms = consensus_ms - pure_correlation_ms
    diff_frames = diff_ms / src_frame_dur_ms
    log(
        f"[SlidingVerified] Difference from audio: {diff_ms:+.1f}ms ({diff_frames:+.1f} frames)"
    )

    if abs(diff_ms) > src_frame_dur_ms / 2:
        log("[SlidingVerified] VIDEO OFFSET DIFFERS FROM AUDIO CORRELATION")

    log(
        f"[SlidingVerified] Total time: {dt_total:.1f}s "
        f"({dt_total / len(results):.1f}s/position)"
    )
    log("[SlidingVerified] ─────────────────────────────────────")

    # Score landscape summary for top 3 positions
    for land in landscapes[:3]:
        sc = np.array(land["scores"])
        bp = land["best_pos"]
        lsrc_start = land["src_start"]
        ltgt_ws = land["tgt_window_start"]
        best_off_f = (ltgt_ws + bp) - lsrc_start - pts_delta_frames
        best_off_ms = best_off_f * src_frame_dur_ms

        log(
            f"[SlidingVerified]   Landscape {land['position_pct']:.0f}%: "
            f"peak {best_off_f:+d}f ({best_off_ms:+.1f}ms) score={sc[bp]:.4f}"
        )

        # Show ±5 frames around peak
        for delta in range(-5, 6):
            pos = bp + delta
            if 0 <= pos < len(sc):
                off_f = (ltgt_ws + pos) - lsrc_start - pts_delta_frames
                off_ms = off_f * src_frame_dur_ms
                marker = " ★" if delta == 0 else ""
                log(
                    f"[SlidingVerified]     {off_f:+4d}f ({off_ms:+7.1f}ms): "
                    f"{sc[pos]:.4f}{marker}"
                )

    log("[SlidingVerified] ─────────────────────────────────────")

    # ─── DEBUG REPORT ─────────────────────────────────────────────
    if debug_output_dir:
        _write_debug_report(
            debug_output_dir=debug_output_dir,
            source_video=source_video,
            target_video=target_video,
            source_key=source_key,
            backend_name=backend_name,
            backend_display_name=backend.display_name,
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
            pts_delta_frames=pts_delta_frames,
            dt_total=dt_total,
            log=log,
        )

    # ─── CALCULATE FINAL OFFSET ──────────────────────────────────
    video_offset_ms = consensus_ms
    final_offset_ms = video_offset_ms + global_shift_ms

    log(
        f"[SlidingVerified] Video-verified offset: {video_offset_ms:+.3f}ms "
        f"({backend_name})"
    )
    if pts_correction_applied:
        log(
            f"[SlidingVerified]   (wall-clock; raw frame-index match included "
            f"{pts_delta_frames:+d}f / {pts_delta_s * 1000:+.1f}ms of PTS label "
            f"offset which has been removed)"
        )
    log(f"[SlidingVerified] + Global shift: {global_shift_ms:+.3f}ms")
    log(f"[SlidingVerified] = Final offset: {final_offset_ms:+.3f}ms")
    log("[SlidingVerified] ═══════════════════════════════════════")

    return final_offset_ms, {
        "reason": "sliding-matched",
        "backend": backend_name,
        "backend_display_name": backend.display_name,
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
        # PTS correction metadata — consumed by SlidingConfidenceAuditor
        "pts_correction_applied": pts_correction_applied,
        "src_start_pts_s": src_start_pts_s,
        "tgt_start_pts_s": tgt_start_pts_s,
        "pts_delta_s": pts_delta_s,
        "pts_delta_frames": pts_delta_frames,
    }


# ── Backward-compat wrapper ──────────────────────────────────────────────────


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
    """Backward-compat shim — forwards to ``calculate_sliding_offset(backend="isc")``.

    Kept so any caller that hasn't been updated to pass ``backend_name``
    explicitly continues to work exactly as before. Callers should switch
    to ``calculate_sliding_offset`` and pass ``backend_name`` derived from
    ``settings.video_verified_backend``. Scheduled for removal in Phase 5
    of the refactor.
    """
    return calculate_sliding_offset(
        source_video=source_video,
        target_video=target_video,
        total_delay_ms=total_delay_ms,
        global_shift_ms=global_shift_ms,
        settings=settings,
        runner=runner,
        temp_dir=temp_dir,
        video_duration_ms=video_duration_ms,
        debug_output_dir=debug_output_dir,
        source_key=source_key,
        backend_name="isc",
    )


# ── Debug report writer ──────────────────────────────────────────────────────


def _write_debug_report(
    debug_output_dir: Path,
    source_video: str,
    target_video: str,
    source_key: str,
    backend_name: str,
    backend_display_name: str,
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
    pts_delta_frames: int,
    dt_total: float,
    log: Callable,
) -> None:
    """Write detailed debug report to the sliding_verify directory.

    Filename convention: ``{tgt_stem}_{source_key}_{backend}_sliding.txt``
    so multiple backends can coexist in the same debug directory without
    overwriting each other (useful when cross-check is enabled).
    """
    try:
        debug_output_dir.mkdir(parents=True, exist_ok=True)

        tgt_stem = Path(target_video).stem
        key_sanitized = source_key.replace(" ", "") if source_key else "unknown"
        report_name = f"{tgt_stem}_{key_sanitized}_{backend_name}_sliding.txt"
        report_path = debug_output_dir / report_name

        lines: list[str] = []
        lines.append("=" * 80)
        lines.append("SLIDING-WINDOW FEATURE MATCHING DEBUG REPORT")
        lines.append("=" * 80)
        lines.append(f"Backend: {backend_display_name} ({backend_name})")
        lines.append(f"Source: {source_video}")
        lines.append(f"Target: {target_video}")
        lines.append(f"Source FPS: {src_fps:.3f}")
        lines.append(f"Target FPS: {tgt_fps:.3f}")
        lines.append(f"Frame duration: {src_frame_dur_ms:.2f}ms")
        lines.append(f"Audio correlation: {pure_correlation_ms:+.3f}ms")
        if pts_delta_frames != 0:
            lines.append(
                f"PTS delta correction applied: {pts_delta_frames:+d} frames"
            )
        lines.append("")
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
            best_off_f = (tgt_ws + bp) - src_start - pts_delta_frames
            best_off_ms = best_off_f * src_frame_dur_ms

            lines.append("")
            lines.append(
                f"  Position {land['position_pct']:.0f}% (src={src_start}) — "
                f"peak: {best_off_f:+d}f ({best_off_ms:+.1f}ms) "
                f"score={sc[bp]:.4f}"
            )

            for delta in range(-15, 16):
                pos = bp + delta
                if 0 <= pos < len(sc):
                    off_f = (tgt_ws + pos) - src_start - pts_delta_frames
                    off_ms = off_f * src_frame_dur_ms
                    marker = " ★" if delta == 0 else ""
                    bar_val = max(0, (sc[pos] - 0.3) * 60)
                    bar = "█" * int(bar_val)
                    lines.append(
                        f"    {off_f:+4d}f ({off_ms:+7.1f}ms): "
                        f"{sc[pos]:.4f} {bar}{marker}"
                    )

        report_path.write_text("\n".join(lines), encoding="utf-8")
        log(f"[SlidingVerified] Debug report saved: {report_path}")
    except Exception as e:
        log(f"[SlidingVerified] WARNING: Failed to write debug report: {e}")
