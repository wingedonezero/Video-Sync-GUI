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
    from ...frame_utils.video_properties import analyze_content_type

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

    # Determine if we should use interlaced handling
    interlaced_handling_enabled = settings.interlaced_handling_enabled
    force_mode = settings.interlaced_force_mode

    # Run content analysis for DVD content (MPEG-2 codec gate)
    # This uses idet + mpdecimate on the whole file for precise detection
    source_analysis = analyze_content_type(source_video, runner, source_props)
    target_analysis = analyze_content_type(target_video, runner, target_props)

    # Use analyzed content_type (more precise than metadata-only)
    source_content_type = source_analysis.content_type
    target_content_type = target_analysis.content_type

    # Check if either video needs interlaced handling
    _interlaced_types = (
        "interlaced",
        "telecine",
        "telecine_hard",
        "telecine_soft",
        "mixed",
    )
    source_needs_interlaced = source_content_type in _interlaced_types
    target_needs_interlaced = target_content_type in _interlaced_types
    either_interlaced = source_needs_interlaced or target_needs_interlaced

    # Determine if we should use interlaced settings
    use_interlaced_settings = False
    if force_mode == "progressive":
        use_interlaced_settings = False
    elif force_mode in ("interlaced", "telecine") or (
        force_mode == "auto" and interlaced_handling_enabled and either_interlaced
    ):
        use_interlaced_settings = True

    if use_interlaced_settings:
        log("[VideoVerified] Using INTERLACED settings")
        if source_needs_interlaced:
            log(
                f"[VideoVerified]   Source: {source_content_type} "
                f"({source_props.get('width')}x{source_props.get('height')}, "
                f"confidence={source_analysis.confidence:.0%})"
            )
        if target_needs_interlaced:
            log(
                f"[VideoVerified]   Target: {target_content_type} "
                f"({target_props.get('width')}x{target_props.get('height')}, "
                f"confidence={target_analysis.confidence:.0%})"
            )

    # Detect FPS (initial - may be updated after IVTC)
    initial_fps = source_props.get("fps", 23.976)
    if not initial_fps:
        initial_fps = 23.976
        log(f"[VideoVerified] FPS detection failed, using default: {initial_fps}")

    log(f"[VideoVerified] Initial FPS: {initial_fps:.3f}")

    # Get settings parameters - use interlaced settings if appropriate
    if use_interlaced_settings:
        num_checkpoints = settings.interlaced_num_checkpoints
        search_range_frames = settings.interlaced_search_range_frames
        hash_algorithm = settings.interlaced_hash_algorithm
        hash_size = settings.interlaced_hash_size
        hash_threshold = settings.interlaced_hash_threshold
        window_radius = settings.frame_window_radius
        comparison_method = settings.interlaced_comparison_method
        # interlaced_fallback_to_audio is accessed later if needed
    else:
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

    # Open video readers with per-video processing based on content type
    # NOTE: We do this BEFORE calculating frame offsets because processing may change FPS
    try:
        # Determine processing for each video independently based on analysis.
        # For cross-encode comparison, VFM (IVTC field matching) is NOT used:
        # VFM makes non-deterministic field-matching decisions that differ between
        # encodes, producing incomparable progressive frames.  Instead, all
        # Processing strategy for different content types:
        #
        # telecine_hard/telecine → Full IVTC (VFM + VDecimate → ~24fps film)
        #   Bwdif/yadif CANNOT fix telecine: different encodes have different
        #   telecine phase, so frame N deinterlaced from encode A ≠ frame N
        #   from encode B (avg_dist 35+). VFM-only (no VDecimate) also fails
        #   because VFM makes encode-dependent field-match decisions.
        #   Full IVTC recovers real progressive film frames at ~24fps.
        #   After VDecimate + AssumeFPS(24000/1001), time-based frame lookup
        #   gives the correct film frame regardless of which telecine frames
        #   VDecimate dropped — exactly like the soft-telecine case.
        #
        # telecine_soft → passthrough (pulldown already removed by container)
        # interlaced/mixed → deinterlace (bwdif/yadif)
        # progressive → passthrough
        _interlaced_types = ("telecine", "telecine_hard", "mixed", "interlaced")
        _telecine_types = ("telecine", "telecine_hard")

        # Determine per-video processing strategy
        source_use_ivtc = (
            use_interlaced_settings and source_content_type in _telecine_types
        )
        target_use_ivtc = (
            use_interlaced_settings and target_content_type in _telecine_types
        )

        source_apply_decimate = (
            use_interlaced_settings
            and settings.interlaced_use_ivtc
            and source_content_type == "telecine_soft"
        )
        # For telecine: full IVTC handles everything, no bwdif needed.
        # For pure interlaced/mixed: use explicit deinterlace method.
        # "auto" checks ffprobe's scan_type which can be wrong (e.g.
        # container says progressive for actually-interlaced MPEG-2).
        if source_use_ivtc:
            source_deinterlace = "none"  # IVTC handles it
        elif use_interlaced_settings and source_content_type in _interlaced_types:
            source_deinterlace = settings.interlaced_deinterlace_method
        else:
            source_deinterlace = "auto"

        target_apply_decimate = (
            use_interlaced_settings
            and settings.interlaced_use_ivtc
            and target_content_type == "telecine_soft"
        )
        if target_use_ivtc:
            target_deinterlace = "none"  # IVTC handles it
        elif use_interlaced_settings and target_content_type in _interlaced_types:
            target_deinterlace = settings.interlaced_deinterlace_method
        else:
            target_deinterlace = "auto"

        log(f"[VideoVerified] Source: {source_content_type}")
        if source_use_ivtc:
            log(
                "[VideoVerified]   Processing: Full IVTC (VFM+VDecimate → ~24fps film frames)"
            )
        elif source_content_type in _interlaced_types and use_interlaced_settings:
            log(f"[VideoVerified]   Processing: deinterlace ({source_deinterlace})")
        elif source_apply_decimate:
            log("[VideoVerified]   Processing: VDecimate (telecine_soft -> ~24fps)")
        else:
            log("[VideoVerified]   Processing: none (progressive)")

        log(f"[VideoVerified] Target: {target_content_type}")
        if target_use_ivtc:
            log(
                "[VideoVerified]   Processing: Full IVTC (VFM+VDecimate → ~24fps film frames)"
            )
        elif target_content_type in _interlaced_types and use_interlaced_settings:
            log(f"[VideoVerified]   Processing: deinterlace ({target_deinterlace})")
        elif target_apply_decimate:
            log("[VideoVerified]   Processing: VDecimate (telecine_soft -> ~24fps)")
        else:
            log("[VideoVerified]   Processing: none (progressive)")

        # Create readers with per-video settings
        # For telecine: apply_ivtc=True runs full IVTC (VFM + VDecimate)
        # to recover real ~24fps progressive film frames. After VDecimate +
        # AssumeFPS(24000/1001), time-based frame lookup aligns correctly
        # across encodes — same as the proven soft-telecine path.
        # skip_decimate_in_ivtc=False: we WANT VDecimate to produce real 24fps.
        source_reader = VideoReader(
            source_video,
            runner,
            temp_dir=temp_dir,
            deinterlace=source_deinterlace,
            content_type=source_content_type,
            ivtc_field_order=source_analysis.field_order,
            apply_ivtc=source_use_ivtc,
            skip_decimate_in_ivtc=False,
            apply_decimate=source_apply_decimate,
            settings=settings,
        )
        target_reader = VideoReader(
            target_video,
            runner,
            temp_dir=temp_dir,
            deinterlace=target_deinterlace,
            content_type=target_content_type,
            ivtc_field_order=target_analysis.field_order,
            apply_ivtc=target_use_ivtc,
            skip_decimate_in_ivtc=False,
            apply_decimate=target_apply_decimate,
            settings=settings,
        )

        # Get processed FPS from readers (after IVTC/deinterlace/decimate)
        # Use source reader's FPS for logging and legacy calculations.
        fps = source_reader.fps if source_reader.fps else initial_fps
        target_fps = target_reader.fps if target_reader.fps else initial_fps

        # Log FPS info, especially if processing changed it
        any_fps_changed = (
            source_reader.ivtc_applied
            or target_reader.ivtc_applied
            or source_reader.decimate_applied
            or target_reader.decimate_applied
            or source_reader.deinterlace_applied
            or target_reader.deinterlace_applied
        )
        if any_fps_changed:
            log(
                f"[VideoVerified] Processed FPS: source={fps:.3f}, target={target_fps:.3f}"
            )
            if abs(fps - target_fps) > 0.1:
                log(
                    f"[VideoVerified] WARNING: FPS mismatch after processing "
                    f"({fps:.3f} vs {target_fps:.3f})"
                )
        else:
            log(f"[VideoVerified] FPS: {fps:.3f} (frame: {1000.0 / fps:.3f}ms)")

        # Timebase for frame index calculation.
        # Two cases:
        # 1. IVTC/VDecimate applied: VDecimate actually removes frames, so
        #    the post-IVTC fps (23.976) IS the real frame rate. Use reader.fps.
        # 2. AssumeFPS-only (no frame removal): AssumeFPS only relabels fps,
        #    frame count unchanged. Must use real_fps (pre-AssumeFPS) so that
        #    time→index math matches the actual frame count. E.g. FFMS2
        #    reports 29.778fps (42195 frames), AssumeFPS says 29.970 but
        #    get_frame(N) still returns the Nth of 42195 frames.
        def _get_indexing_fps(reader, processed_fps):
            """Get the correct FPS for time→frame index conversion."""
            if getattr(reader, "ivtc_applied", False):
                # VDecimate changed the frame count — post-IVTC fps is correct
                return processed_fps
            if getattr(reader, "decimate_applied", False):
                # Same: VDecimate changed the frame count
                return processed_fps
            # No decimation — use real FFMS2 fps (before AssumeFPS relabeling)
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

    # Get sequence length based on content type
    if use_interlaced_settings:
        sequence_length = settings.interlaced_sequence_length
    else:
        sequence_length = settings.video_verified_sequence_length

    # Get SSIM/MSE threshold (separate from hash threshold, different scale)
    # Only used when comparison_method is 'ssim' or 'mse'; None = defaults
    if comparison_method in ("ssim", "mse"):
        if use_interlaced_settings:
            ssim_threshold: int | None = settings.interlaced_ssim_threshold
        else:
            ssim_threshold = settings.frame_ssim_threshold
        log(
            f"[VideoVerified] SSIM/MSE distance threshold: {ssim_threshold} "
            f"(SSIM > {1.0 - ssim_threshold / 100:.2f})"
        )
    else:
        ssim_threshold = None

    # Determine IVTC/VFM tolerance for sequence verification.
    # VFM field-matching is content-dependent: different encodes of the same
    # content produce different field-match decisions for some frames (near
    # scene changes, high motion). This means frame N after VFM on encode A
    # may correspond to frame N±1 after VFM on encode B. Allow ±1 frame
    # tolerance so sequence verification can handle this.
    source_ivtc = getattr(source_reader, "ivtc_applied", False)
    target_ivtc = getattr(target_reader, "ivtc_applied", False)
    source_vfm = getattr(source_reader, "vfm_applied", False)
    target_vfm = getattr(target_reader, "vfm_applied", False)
    any_field_processing = source_ivtc or target_ivtc or source_vfm or target_vfm
    ivtc_tolerance = 1 if any_field_processing else 0
    if ivtc_tolerance > 0:
        reason = "VFM" if (source_vfm or target_vfm) else "IVTC"
        log(
            f"[VideoVerified] {reason} detected — using ±1 frame tolerance in sequence verification"
        )

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
            ivtc_tolerance=ivtc_tolerance,
            use_global_ssim=use_interlaced_settings,
        )
        # Convert frame offset to approximate ms for logging
        approx_ms = frame_offset * source_frame_duration_ms
        seq_verified = quality.get("sequence_verified", 0)
        candidate_results.append(
            {
                "frame_offset": frame_offset,
                "approx_ms": approx_ms,
                "quality": quality["score"],
                "matched_checkpoints": quality["matched"],
                "sequence_verified": seq_verified,
                "avg_distance": quality["avg_distance"],
                "match_details": quality.get("match_details", []),
            }
        )
        log(
            f"[VideoVerified]   Frame {frame_offset:+d} (~{approx_ms:+.1f}ms): "
            f"score={quality['score']:.2f}, seq_verified={seq_verified}/{len(checkpoint_times)}, "
            f"avg_dist={quality['avg_distance']:.1f}"
        )

    # Select best candidate - prefer sequence_verified count, then score, then lowest avg_distance
    best_result = max(
        candidate_results,
        key=lambda r: (r["sequence_verified"], r["quality"], -r["avg_distance"]),
    )
    best_frame_offset = best_result["frame_offset"]

    log("[VideoVerified] ───────────────────────────────────────")
    log(
        f"[VideoVerified] Best frame offset: {best_frame_offset:+d} frames "
        f"(seq_verified={best_result['sequence_verified']}/{len(checkpoint_times)}, score={best_result['quality']:.2f})"
    )

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
        log("[VideoVerified]   - Different telecine/pulldown patterns (common for DVD)")
        log("[VideoVerified]   - One video has hardcoded subs/watermarks")
        log("[VideoVerified]   - Deinterlacing producing different results")
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
        "use_interlaced_settings": use_interlaced_settings,
        "source_content_type": source_props.get("content_type", "unknown"),
        "target_content_type": target_props.get("content_type", "unknown"),
        "source_fps": fps,
        "target_fps": target_fps,
    }
