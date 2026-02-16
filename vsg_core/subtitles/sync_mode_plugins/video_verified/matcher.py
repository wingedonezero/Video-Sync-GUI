# vsg_core/subtitles/sync_mode_plugins/video_verified/matcher.py
"""
Core frame matching algorithm for video-verified sync.

This module contains the main `calculate_video_verified_offset()` function
which performs frame matching to find the TRUE video-to-video offset.
It can be used independently for any subtitle format, including bitmap
subtitles (VobSub, PGS) that can't be loaded into SubtitleData.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .candidates import generate_frame_candidates, select_checkpoint_times
from .offset import calculate_subframe_offset
from .quality import measure_frame_offset_quality

if TYPE_CHECKING:
    from ....models.settings import AppSettings


def calculate_video_verified_offset(
    source_video: str,
    target_video: str,
    total_delay_ms: float,
    global_shift_ms: float,
    settings: AppSettings | None = None,
    runner=None,
    temp_dir: Path | None = None,
    video_duration_ms: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """
    Calculate the video-verified offset using frame matching with sub-frame precision.

    This function performs the core frame matching logic to find the TRUE
    video-to-video offset, independent of any subtitle format. It can be
    used for both text-based and bitmap subtitles (VobSub, PGS).

    The algorithm:
    1. Uses audio correlation as starting point (any offset size)
    2. Generates candidate frame offsets around the correlation value
    3. Tests each candidate at multiple checkpoints across the video
    4. Selects the best matching frame offset
    5. Uses actual PTS timestamps for sub-frame precision

    Args:
        source_video: Path to source video file
        target_video: Path to target video file (Source 1)
        total_delay_ms: Total delay from audio correlation (with global shift)
        global_shift_ms: Global shift component of the delay
        settings: AppSettings with video-verified parameters
        runner: CommandRunner for logging
        temp_dir: Temp directory for frame cache
        video_duration_ms: Optional video duration (auto-detected if not provided)

    Returns:
        Tuple of (final_offset_ms, details_dict)
        - final_offset_ms: The frame-corrected offset including global shift,
          or None if frame matching failed/wasn't needed
        - details_dict: Contains 'reason', 'audio_correlation_ms', 'video_offset_ms',
          'candidates', etc.
    """
    from ....models.settings import AppSettings
    from ...frame_utils import detect_video_properties

    if settings is None:
        settings = AppSettings()

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    log("[VideoVerified] === Frame Matching for Delay Correction ===")

    if not source_video or not target_video:
        return None, {
            "reason": "missing-videos",
            "error": "Both source and target videos required",
        }

    # Calculate pure correlation (correlation only, without global shift)
    pure_correlation_ms = total_delay_ms - global_shift_ms

    log(f"[VideoVerified] Source: {Path(source_video).name}")
    log(f"[VideoVerified] Target: {Path(target_video).name}")
    log(f"[VideoVerified] Total delay (with global): {total_delay_ms:+.3f}ms")
    log(f"[VideoVerified] Global shift: {global_shift_ms:+.3f}ms")
    log(f"[VideoVerified] Pure correlation (audio): {pure_correlation_ms:+.3f}ms")

    # Detect video properties for both videos
    source_props = detect_video_properties(source_video, runner)
    target_props = detect_video_properties(target_video, runner)

    # Detect FPS
    initial_fps = source_props.get("fps", 23.976)
    if not initial_fps:
        initial_fps = 23.976
        log(f"[VideoVerified] FPS detection failed, using default: {initial_fps}")

    log(f"[VideoVerified] Initial FPS: {initial_fps:.3f}")

    # Get settings parameters
    num_checkpoints = settings.video_verified_num_checkpoints
    search_range_frames = settings.video_verified_search_range_frames
    hash_algorithm = settings.frame_hash_algorithm
    hash_size = settings.frame_hash_size
    hash_threshold = settings.frame_hash_threshold
    window_radius = settings.frame_window_radius
    comparison_method = settings.frame_comparison_method

    log(
        f"[VideoVerified] Checkpoints: {num_checkpoints}, Search: ±{search_range_frames} frames"
    )
    log(
        f"[VideoVerified] Hash: {hash_algorithm} size={hash_size} threshold={hash_threshold}"
    )
    log(f"[VideoVerified] Comparison method: {comparison_method}")

    # Try to import frame utilities
    try:
        from ...frame_utils import VideoReader
    except ImportError as e:
        log(f"[VideoVerified] Frame utilities unavailable: {e}")
        log("[VideoVerified] Falling back to correlation")
        return total_delay_ms, {
            "reason": "fallback-no-frame-utils",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
        }

    # Get video duration for checkpoint selection
    source_duration = video_duration_ms
    if not source_duration or source_duration <= 0:
        try:
            props = detect_video_properties(source_video, runner)
            source_duration = props.get("duration_ms", 0)
            if source_duration <= 0:
                raise ValueError("Could not detect video duration")
        except Exception:
            source_duration = 1200000  # Default 20 minutes
            log(
                f"[VideoVerified] Could not detect duration, using default: {source_duration / 1000:.1f}s"
            )

    log(f"[VideoVerified] Source duration: ~{source_duration / 1000:.1f}s")

    # Open video readers
    try:
        source_reader = VideoReader(
            source_video,
            runner,
            temp_dir=temp_dir,
            settings=settings,
        )
        target_reader = VideoReader(
            target_video,
            runner,
            temp_dir=temp_dir,
            settings=settings,
        )

        # Get FPS from readers
        fps = source_reader.fps if source_reader.fps else initial_fps
        target_fps = target_reader.fps if target_reader.fps else initial_fps

        log(f"[VideoVerified] FPS: source={fps:.3f}, target={target_fps:.3f}")

        # Timebase for frame index calculation.
        # Use real_fps (pre-AssumeFPS) when available so that
        # time→index math matches the actual frame count.
        def _get_indexing_fps(reader, processed_fps):
            """Get the correct FPS for time→frame index conversion."""
            real = getattr(reader, "real_fps", None)
            return real if real else processed_fps

        source_index_fps = _get_indexing_fps(source_reader, fps)
        target_index_fps = _get_indexing_fps(target_reader, target_fps)
        source_frame_duration_ms = 1000.0 / source_index_fps
        target_frame_duration_ms = 1000.0 / target_index_fps

        if (
            abs(source_index_fps - fps) > 0.01
            or abs(target_index_fps - target_fps) > 0.01
        ):
            log(
                f"[VideoVerified] Indexing FPS: source={source_index_fps:.3f}, target={target_index_fps:.3f}"
            )

    except Exception as e:
        log(f"[VideoVerified] Failed to open videos: {e}")
        log("[VideoVerified] Falling back to correlation")
        return total_delay_ms, {
            "reason": "fallback-video-open-failed",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "error": str(e),
        }

    # Generate candidate frame offsets using processed FPS
    correlation_frames = pure_correlation_ms / source_frame_duration_ms
    candidates_frames = generate_frame_candidates(
        correlation_frames, search_range_frames
    )
    log(
        f"[VideoVerified] Testing frame offsets: {candidates_frames} (around {correlation_frames:+.1f} frames)"
    )

    # Select checkpoint times (distributed across video)
    checkpoint_times = select_checkpoint_times(source_duration, num_checkpoints)
    log(
        f"[VideoVerified] Checkpoint times: {[f'{t / 1000:.1f}s' for t in checkpoint_times]}"
    )

    # Test each candidate frame offset
    candidate_results = []

    sequence_length = settings.video_verified_sequence_length

    # Get SSIM/MSE threshold (separate from hash threshold, different scale)
    # Only used when comparison_method is 'ssim' or 'mse'; None = defaults
    if comparison_method in ("ssim", "mse"):
        ssim_threshold: int | None = settings.frame_ssim_threshold
        log(
            f"[VideoVerified] SSIM/MSE distance threshold: {ssim_threshold} "
            f"(SSIM > {1.0 - ssim_threshold / 100:.2f})"
        )
    else:
        ssim_threshold = None

    log(
        f"[VideoVerified] Sequence verification: {sequence_length} consecutive frames must match"
    )

    for frame_offset in candidates_frames:
        quality = measure_frame_offset_quality(
            frame_offset,
            checkpoint_times,
            source_reader,
            target_reader,
            fps,
            source_frame_duration_ms,
            target_frame_duration_ms,
            window_radius,
            hash_algorithm,
            hash_size,
            hash_threshold,
            comparison_method,
            log,
            sequence_verify_length=sequence_length,
            ssim_threshold=ssim_threshold,
            ivtc_tolerance=0,
            use_global_ssim=False,
        )
        # Convert frame offset to approximate ms for logging
        approx_ms = frame_offset * source_frame_duration_ms
        seq_verified = quality.get("sequence_verified", 0)
        avg_mse = quality.get("avg_mse", float("inf"))
        total_tested = quality.get("total_frames_tested", 0)
        total_matched = quality.get("total_frames_matched", 0)
        phash_exact = quality.get("phash_exact_matches", 0)
        candidate_results.append(
            {
                "frame_offset": frame_offset,
                "approx_ms": approx_ms,
                "quality": quality["score"],
                "matched_checkpoints": quality["matched"],
                "sequence_verified": seq_verified,
                "avg_distance": quality["avg_distance"],
                "avg_mse": avg_mse,
                "match_details": quality.get("match_details", []),
                # Multi-metric fields
                "total_frames_tested": total_tested,
                "total_frames_matched": total_matched,
                "phash_exact_matches": phash_exact,
                "avg_ssim_distance": quality.get("avg_distance", float("inf")),
                "per_checkpoint_summary": quality.get(
                    "per_checkpoint_summary", []
                ),
            }
        )
        # Improved per-candidate logging with frame counts
        log(
            f"[VideoVerified]   Frame {frame_offset:+d} (~{approx_ms:+.1f}ms): "
            f"{total_matched}/{total_tested} frames matched, "
            f"seq={seq_verified}/{len(checkpoint_times)}, "
            f"phash_exact={phash_exact}/{total_tested}"
        )
        # Per-checkpoint breakdown
        for cp in quality.get("per_checkpoint_summary", []):
            status = "PASS" if cp["verified"] else "FAIL"
            log(
                f"[VideoVerified]     CP {cp['checkpoint_ms']/1000:.0f}s: "
                f"{cp['seq_matched']}/{cp['seq_total']} matched, "
                f"phash={cp['phash_exact']}/{cp['seq_total']}, "
                f"ssim={cp['avg_ssim_dist']:.1f}, mse={cp['avg_mse']:.0f} [{status}]"
            )

    # Select best candidate:
    # Ranking key (most important → least important):
    # 1. sequence_verified — how many checkpoints passed sequence verification
    # 2. total_frames_matched — of all N×seq_len frames, how many matched on
    #    the primary metric (SSIM). Finer than seq count since it captures
    #    partial checkpoint success (e.g. 86/90 vs 82/90).
    # 3. phash_exact_matches — hamming distance 0 count. Binary "same frame"
    #    signal immune to threshold tuning; strongest discriminator between
    #    correct offset and ±1 neighbors (typically 85/90 vs 58-66/90).
    # 4. -avg_mse — MSE tiebreaker for when everything else ties.
    def _rank_key(r):
        return (
            r["sequence_verified"],
            r.get("total_frames_matched", 0),
            r.get("phash_exact_matches", 0),
            -r["avg_mse"],
        )

    best_result = max(candidate_results, key=_rank_key)
    best_frame_offset = best_result["frame_offset"]

    # ─── RESULTS SUMMARY ─────────────────────────────────────────────
    log("[VideoVerified] ═══════════════════════════════════════")
    log("[VideoVerified] RESULTS SUMMARY")
    log("[VideoVerified] ═══════════════════════════════════════")

    best_tested = best_result.get("total_frames_tested", 0)
    best_matched = best_result.get("total_frames_matched", 0)
    best_phash = best_result.get("phash_exact_matches", 0)

    log(
        f"[VideoVerified] Winner: frame {best_frame_offset:+d} "
        f"({best_matched}/{best_tested} frames matched, "
        f"seq={best_result['sequence_verified']}/{len(checkpoint_times)}, "
        f"phash_exact={best_phash}/{best_tested})"
    )

    # Runner-up comparison
    sorted_candidates = sorted(candidate_results, key=_rank_key, reverse=True)
    if len(sorted_candidates) > 1:
        runner_up = sorted_candidates[1]
        runner_tested = runner_up.get("total_frames_tested", 0)
        runner_matched = runner_up.get("total_frames_matched", 0)
        log(
            f"[VideoVerified] Runner-up: frame {runner_up['frame_offset']:+d} "
            f"({runner_matched}/{runner_tested} frames matched, "
            f"seq={runner_up['sequence_verified']}/{len(checkpoint_times)})"
        )

    # Metric agreement: which offset does each metric independently pick?
    phash_winner = max(
        candidate_results,
        key=lambda r: r.get("phash_exact_matches", 0),
    )
    ssim_winner = min(
        candidate_results,
        key=lambda r: r.get("avg_ssim_distance", float("inf")),
    )
    mse_winner = min(
        candidate_results,
        key=lambda r: r["avg_mse"],
    )

    agree_count = sum(
        [
            phash_winner["frame_offset"] == best_frame_offset,
            ssim_winner["frame_offset"] == best_frame_offset,
            mse_winner["frame_offset"] == best_frame_offset,
        ]
    )
    log(
        f"[VideoVerified] Metric agreement: {agree_count}/3 "
        f"(phash={phash_winner['frame_offset']:+d}, "
        f"ssim={ssim_winner['frame_offset']:+d}, "
        f"mse={mse_winner['frame_offset']:+d})"
    )
    log("[VideoVerified] ───────────────────────────────────────")

    # Check if frame matching actually worked
    # Require at least one sequence-verified checkpoint for reliable results
    if best_result["sequence_verified"] == 0:
        log(
            "[VideoVerified] ⚠ Sequence verification failed - no consecutive frame sequences matched"
        )
        log(
            f"[VideoVerified] Required: {sequence_length} consecutive frames to match at 70%+ threshold"
        )
        log(
            f"[VideoVerified] Avg distance was {best_result['avg_distance']:.1f}, threshold is {hash_threshold}"
        )

        # Check if this might be fixable with higher threshold
        if best_result["avg_distance"] < 40:
            log(
                f"[VideoVerified] TIP: Try increasing 'frame_hash_threshold' to {int(best_result['avg_distance']) + 5}"
            )
            log("[VideoVerified]      (Settings → Video-Verified → Hash Threshold)")

        log("[VideoVerified] This could mean:")
        log("[VideoVerified]   - Videos have different encodes/color grading")
        log("[VideoVerified]   - One video has hardcoded subs/watermarks")
        log(
            f"[VideoVerified] Falling back to audio correlation: {pure_correlation_ms:+.3f}ms"
        )

        # Close readers before returning
        try:
            source_reader.close()
            target_reader.close()
        except Exception:
            pass

        # Return audio correlation as the offset
        return total_delay_ms, {
            "reason": "fallback-no-frame-matches",
            "audio_correlation_ms": pure_correlation_ms,
            "video_offset_ms": pure_correlation_ms,
            "final_offset_ms": total_delay_ms,
            "candidates": candidate_results,
            "checkpoints": len(checkpoint_times),
            "sub_frame_precision": False,
        }

    # ─── FINAL VERIFICATION PASS ────────────────────────────────────
    from .verification import run_final_verification

    verification = run_final_verification(
        best_frame_offset=best_frame_offset,
        source_reader=source_reader,
        target_reader=target_reader,
        source_duration=source_duration,
        source_frame_duration_ms=source_frame_duration_ms,
        target_frame_duration_ms=target_frame_duration_ms,
        hash_algorithm=hash_algorithm,
        hash_size=hash_size,
        hash_threshold=hash_threshold,
        ssim_threshold=ssim_threshold,
        use_global_ssim=False,
        num_verification_points=15,
        checkpoint_times_used=checkpoint_times,
        metric_agreement=agree_count,
        log=log,
    )

    v_matched = verification["frames_matched"]
    v_total = verification["frames_tested"]
    confidence = verification["confidence"]
    v_pct = (100 * v_matched / v_total) if v_total > 0 else 0

    log(
        f"[VideoVerified] Final verification: {v_matched}/{v_total} matched ({v_pct:.0f}%)"
    )
    log(f"[VideoVerified] Confidence: {confidence}")
    if confidence == "LOW":
        log(
            "[VideoVerified] ⚠ Low confidence — result may be unreliable"
        )
    log("[VideoVerified] ───────────────────────────────────────")

    # Calculate offset in milliseconds
    # By default uses frame-based (frame_offset * frame_duration)
    # Optionally can use PTS for VFR content (enable via settings)
    use_pts = settings.video_verified_use_pts_precision
    sub_frame_offset_ms = calculate_subframe_offset(
        best_frame_offset,
        best_result.get("match_details", []),
        checkpoint_times,
        source_reader,
        target_reader,
        fps,
        source_frame_duration_ms,
        log,
        use_pts_precision=use_pts,
    )

    # Close readers
    try:
        source_reader.close()
        target_reader.close()
    except Exception:
        pass

    # Calculate final offset with global shift
    final_offset_ms = sub_frame_offset_ms + global_shift_ms

    log("[VideoVerified] ───────────────────────────────────────")
    log(f"[VideoVerified] Audio correlation: {pure_correlation_ms:+.3f}ms")
    precision_mode = "PTS-based" if use_pts else "frame-based"
    log(
        f"[VideoVerified] Video-verified offset: {sub_frame_offset_ms:+.3f}ms ({precision_mode})"
    )
    log(f"[VideoVerified] + Global shift: {global_shift_ms:+.3f}ms")
    log(f"[VideoVerified] = Final offset: {final_offset_ms:+.3f}ms")

    if abs(sub_frame_offset_ms - pure_correlation_ms) > source_frame_duration_ms / 2:
        log("[VideoVerified] ⚠ VIDEO OFFSET DIFFERS FROM AUDIO CORRELATION")
        log(
            f"[VideoVerified] Audio said {pure_correlation_ms:+.1f}ms, "
            f"video shows {sub_frame_offset_ms:+.1f}ms"
        )

    log("[VideoVerified] ───────────────────────────────────────")

    return final_offset_ms, {
        "reason": "frame-matched",
        "audio_correlation_ms": pure_correlation_ms,
        "video_offset_ms": sub_frame_offset_ms,
        "frame_offset": best_frame_offset,
        "final_offset_ms": final_offset_ms,
        "candidates": candidate_results,
        "checkpoints": len(checkpoint_times),
        "use_pts_precision": use_pts,
        "source_content_type": source_props.get("content_type", "unknown"),
        "target_content_type": target_props.get("content_type", "unknown"),
        "source_fps": fps,
        "target_fps": target_fps,
        # Multi-metric verification
        "verification": verification,
        "confidence": confidence,
        "metric_agreement": agree_count,
    }
