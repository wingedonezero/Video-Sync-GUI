# vsg_core/subtitles/frame_utils/validation.py
"""
Frame alignment validation for video sync verification.

Contains:
- Frame extraction from video
- Perceptual hash-based frame alignment validation
"""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def extract_frame_as_image(
    video_path: str, frame_number: int, runner, temp_dir: Path | None = None
) -> bytes | None:
    """
    Extract a single frame from video as PNG image data using VapourSynth.

    Args:
        video_path: Path to video file
        frame_number: Frame index to extract (0-based)
        runner: CommandRunner for logging
        temp_dir: Optional job temp directory for index storage

    Returns:
        PNG image data as bytes, or None on error
    """
    try:
        import io

        import numpy as np
        import vapoursynth as vs
        from PIL import Image

        from .video_reader import _get_ffms2_cache_path

        core = vs.core

        # Generate cache path for FFMS2 index
        index_path = _get_ffms2_cache_path(video_path, temp_dir)

        # Load video - try L-SMASH first, fall back to FFmpegSource2
        clip = None
        try:
            clip = core.lsmas.LWLibavSource(str(video_path))
        except (AttributeError, Exception):
            pass

        if clip is None:
            try:
                # Use FFMS2 with custom cache path
                clip = core.ffms2.Source(
                    source=str(video_path), cachefile=str(index_path)
                )
            except Exception as e:
                runner._log_message(f"[VapourSynth] ERROR: Failed to load video: {e}")
                del core
                gc.collect()
                return None

        # Validate frame number
        if frame_number < 0 or frame_number >= clip.num_frames:
            runner._log_message(
                f"[VapourSynth] ERROR: Frame {frame_number} out of range (0-{clip.num_frames - 1})"
            )
            del clip
            del core
            gc.collect()
            return None

        # Get frame
        frame = clip.get_frame(frame_number)

        # Convert frame to RGB for PIL
        # VapourSynth frame format is planar, need to convert to interleaved

        # Read planes (YUV or RGB depending on format)
        # Convert to RGB24 first if needed
        if frame.format.color_family == vs.YUV:
            clip_rgb = core.resize.Bicubic(clip, format=vs.RGB24, matrix_in_s="709")
            frame_rgb = clip_rgb.get_frame(frame_number)
        else:
            frame_rgb = frame

        # Extract RGB data
        # VapourSynth stores planes separately, PIL needs interleaved RGB
        r_plane = np.array(frame_rgb[0], copy=False)
        g_plane = np.array(frame_rgb[1], copy=False)
        b_plane = np.array(frame_rgb[2], copy=False)

        # Stack into RGB image
        rgb_array = np.stack([r_plane, g_plane, b_plane], axis=2)

        # Create PIL Image
        img = Image.fromarray(rgb_array, mode="RGB")

        # Convert to PNG bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_data = img_bytes.getvalue()

        # Free memory
        del frame
        del frame_rgb
        del clip
        try:
            del clip_rgb
        except:
            pass
        del core
        del img
        del rgb_array
        gc.collect()

        return img_data

    except Exception as e:
        runner._log_message(
            f"[VapourSynth] ERROR: Failed to extract frame {frame_number}: {e}"
        )
        # Cleanup on error (variables may not exist if import failed)
        try:
            del clip
        except NameError:
            pass
        try:
            del core
        except NameError:
            pass
        gc.collect()
        return None


def validate_frame_alignment(
    source_video: str,
    target_video: str,
    subtitle_events: list,
    duration_offset_ms: float,
    runner,
    config: dict | None = None,
    temp_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Validate that videos are frame-aligned by comparing perceptual hashes.

    Checks 3 points throughout the video:
    1. First subtitle event (~5 min in)
    2. Middle subtitle event (~45 min in)
    3. Last subtitle event (~85 min in)

    For each checkpoint:
    - Extracts 11 frames (center +/- 5 frames)
    - Computes perceptual hashes
    - Compares source vs target
    - Reports match confidence

    Args:
        source_video: Path to source video
        target_video: Path to target video
        subtitle_events: List of subtitle events
        duration_offset_ms: Calculated duration offset
        runner: CommandRunner for logging
        config: Optional config dict with:
            - 'duration_align_validate': bool (enable/disable)
            - 'duration_align_validate_points': int (1 or 3)
            - 'duration_align_hash_threshold': int (max hamming distance)
        temp_dir: Optional job temp directory for index storage

    Returns:
        Dict with validation results
    """
    from .frame_hashing import compute_perceptual_hash
    from .video_properties import detect_video_fps

    config = config or {}

    # Check if validation is enabled
    if not config.get("duration_align_validate", True):
        runner._log_message("[Frame Validation] Validation disabled in config")
        return {"enabled": False, "valid": True}

    runner._log_message("[Frame Validation] =========================================")
    runner._log_message("[Frame Validation] Validating frame alignment...")

    # Get number of checkpoints to validate
    # UI sends text like "1 point (fast)" or "3 points (thorough)", extract the number
    num_points_str = config.get("duration_align_validate_points", "3 points (thorough)")
    if "1 point" in str(num_points_str):
        num_points = 1
    elif "3 points" in str(num_points_str):
        num_points = 3
    else:
        # Fallback: try to extract number or default to 3
        try:
            num_points = int(num_points_str)
        except (ValueError, TypeError):
            num_points = 3

    hash_threshold = config.get("duration_align_hash_threshold", 5)
    hash_algorithm = config.get("duration_align_hash_algorithm", "dhash")
    # UI sends hash_size as string ("4", "8", "16"), convert to int
    hash_size_str = config.get("duration_align_hash_size", "8")
    hash_size = int(hash_size_str) if isinstance(hash_size_str, str) else hash_size_str
    strictness_pct = config.get("duration_align_strictness", 80)

    runner._log_message(f"[Frame Validation] Hash algorithm: {hash_algorithm}")
    runner._log_message(f"[Frame Validation] Hash size: {hash_size}x{hash_size}")
    runner._log_message(f"[Frame Validation] Hash threshold: {hash_threshold}")
    runner._log_message(f"[Frame Validation] Strictness: {strictness_pct}%")

    # Find non-empty subtitle events
    valid_events = [e for e in subtitle_events if e.end > e.start]
    if not valid_events:
        runner._log_message(
            "[Frame Validation] WARNING: No valid subtitle events to validate"
        )
        return {"enabled": True, "valid": False, "error": "No valid subtitle events"}

    # Select checkpoints
    checkpoints = []
    if num_points == 1:
        # Just check first event
        checkpoints = [valid_events[0]]
    else:  # 3 points
        # First, middle, last
        first_event = valid_events[0]
        middle_event = valid_events[len(valid_events) // 2]
        last_event = valid_events[-1]
        checkpoints = [first_event, middle_event, last_event]
        runner._log_message("[Frame Validation] Checking 3 points:")
        runner._log_message(
            f"[Frame Validation]   - First subtitle @ {first_event.start}ms"
        )
        runner._log_message(
            f"[Frame Validation]   - Middle subtitle @ {middle_event.start}ms"
        )
        runner._log_message(
            f"[Frame Validation]   - Last subtitle @ {last_event.start}ms"
        )

    # Detect FPS
    source_fps = detect_video_fps(source_video, runner)
    target_fps = detect_video_fps(target_video, runner)

    validation_results = {
        "enabled": True,
        "valid": True,
        "checkpoints": [],
        "total_frames_checked": 0,
        "matched_frames": 0,
        "mismatched_frames": 0,
    }

    # Validate each checkpoint
    for idx, event in enumerate(checkpoints, 1):
        checkpoint_name = (
            ["First", "Middle", "Last"][idx - 1] if num_points == 3 else "First"
        )

        runner._log_message(
            "[Frame Validation] -----------------------------------------"
        )
        runner._log_message(
            f"[Frame Validation] Checkpoint {idx}/{len(checkpoints)}: {checkpoint_name} subtitle"
        )

        # Get source frame for this subtitle
        source_time_ms = event.start
        # Use simple calculation instead of VFR function to avoid VideoTimestamps complexity
        source_frame = int(source_time_ms * source_fps / 1000.0)

        # Get target frame (source time + duration offset)
        target_time_ms = source_time_ms + duration_offset_ms
        target_frame = int(target_time_ms * target_fps / 1000.0)

        runner._log_message(
            f"[Frame Validation] Source: frame {source_frame} @ {source_time_ms}ms"
        )
        runner._log_message(
            f"[Frame Validation] Target: frame {target_frame} @ {target_time_ms:.1f}ms"
        )
        runner._log_message("[Frame Validation] Comparing 11 frames (center +/- 5)...")

        checkpoint_result = {
            "checkpoint": checkpoint_name,
            "source_frame": source_frame,
            "target_frame": target_frame,
            "frames_checked": 0,
            "frames_matched": 0,
            "frames_mismatched": 0,
            "match_percentage": 0.0,
        }

        # Compare frames: center +/- 5
        for offset in range(-5, 6):
            src_frame_num = source_frame + offset
            tgt_frame_num = target_frame + offset

            # Extract frames
            src_img = extract_frame_as_image(
                source_video, src_frame_num, runner, temp_dir
            )
            tgt_img = extract_frame_as_image(
                target_video, tgt_frame_num, runner, temp_dir
            )

            if src_img is None or tgt_img is None:
                runner._log_message(
                    f"[Frame Validation]   Frame {offset:+d}: SKIP (extraction failed)"
                )
                continue

            # Compute hashes
            src_hash = compute_perceptual_hash(
                src_img, runner, hash_algorithm, hash_size
            )
            tgt_hash = compute_perceptual_hash(
                tgt_img, runner, hash_algorithm, hash_size
            )

            if src_hash is None or tgt_hash is None:
                runner._log_message(
                    f"[Frame Validation]   Frame {offset:+d}: SKIP (hash failed)"
                )
                continue

            # Compare hashes (Hamming distance)
            try:
                import imagehash

                src_hash_obj = imagehash.hex_to_hash(src_hash)
                tgt_hash_obj = imagehash.hex_to_hash(tgt_hash)
                hamming_dist = src_hash_obj - tgt_hash_obj

                checkpoint_result["frames_checked"] += 1
                validation_results["total_frames_checked"] += 1

                if hamming_dist <= hash_threshold:
                    checkpoint_result["frames_matched"] += 1
                    validation_results["matched_frames"] += 1
                    runner._log_message(
                        f"[Frame Validation]   Frame {offset:+d}: MATCH (distance: {hamming_dist})"
                    )
                else:
                    checkpoint_result["frames_mismatched"] += 1
                    validation_results["mismatched_frames"] += 1
                    runner._log_message(
                        f"[Frame Validation]   Frame {offset:+d}: MISMATCH (distance: {hamming_dist})"
                    )

            except Exception as e:
                runner._log_message(
                    f"[Frame Validation]   Frame {offset:+d}: ERROR ({e})"
                )

        # Calculate match percentage for this checkpoint
        if checkpoint_result["frames_checked"] > 0:
            match_pct = (
                checkpoint_result["frames_matched"]
                / checkpoint_result["frames_checked"]
            ) * 100
            checkpoint_result["match_percentage"] = match_pct

            runner._log_message(
                f"[Frame Validation] Checkpoint result: {checkpoint_result['frames_matched']}/{checkpoint_result['frames_checked']} matched ({match_pct:.1f}%)"
            )

            # Consider checkpoint valid if >= strictness threshold
            if match_pct < strictness_pct:
                validation_results["valid"] = False
                runner._log_message(
                    f"[Frame Validation] WARNING: Low match rate for {checkpoint_name} subtitle ({match_pct:.1f}% < {strictness_pct}% required)!"
                )

        validation_results["checkpoints"].append(checkpoint_result)

    # Final verdict
    runner._log_message("[Frame Validation] =========================================")

    if validation_results["total_frames_checked"] > 0:
        overall_match_pct = (
            validation_results["matched_frames"]
            / validation_results["total_frames_checked"]
        ) * 100
        validation_results["overall_match_percentage"] = overall_match_pct

        runner._log_message(
            f"[Frame Validation] OVERALL: {validation_results['matched_frames']}/{validation_results['total_frames_checked']} frames matched ({overall_match_pct:.1f}%)"
        )

        if validation_results["valid"]:
            runner._log_message(
                "[Frame Validation] VALIDATION PASSED - Videos appear frame-aligned"
            )
        else:
            runner._log_message(
                "[Frame Validation] VALIDATION FAILED - Videos may NOT be frame-aligned!"
            )
            runner._log_message(
                "[Frame Validation] Consider using audio-correlation mode instead"
            )
    else:
        runner._log_message("[Frame Validation] ERROR: No frames could be validated")
        validation_results["valid"] = False

    runner._log_message("[Frame Validation] =========================================")

    return validation_results
