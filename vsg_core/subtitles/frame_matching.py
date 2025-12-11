# vsg_core/subtitles/frame_matching.py
# -*- coding: utf-8 -*-
"""
Frame-accurate subtitle synchronization using visual frame matching.

This module addresses the problem where two videos have different frame counts
or frame positions (due to duplicates, drops, or different encoding), making
mathematical frame-based sync impossible.

Instead, we:
1. Extract the frame at each subtitle's start time from the SOURCE video
2. Search for the visually matching frame in the TARGET video
3. Adjust subtitle timing to match the target video's frame positions
4. Preserve original duration (don't adjust end independently)

This handles cases like:
- Encode vs Remux with different frame counts
- Duplicate frames placed differently
- Dropped/added frames throughout the video
- Different IVTC/decimation processing
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import subprocess
import tempfile
import os
import pysubs2
from PIL import Image


def extract_frame_at_time(video_path: str, time_ms: int, runner) -> Optional[Image.Image]:
    """
    Extract a single frame at the specified timestamp using ffmpeg.

    Args:
        video_path: Path to video file
        time_ms: Timestamp in milliseconds
        runner: CommandRunner for logging

    Returns:
        PIL Image object, or None on failure
    """
    try:
        # Convert ms to seconds for ffmpeg
        time_sec = time_ms / 1000.0

        # Create temporary file for frame
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp_path = tmp.name

        # Extract frame using ffmpeg
        # -ss before -i for fast seek
        # -vframes 1 to extract only one frame
        cmd = [
            'ffmpeg',
            '-ss', f'{time_sec:.3f}',
            '-i', str(video_path),
            '-vframes', '1',
            '-q:v', '2',  # High quality
            '-y',
            tmp_path
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            runner._log_message(f"[FrameMatch] WARNING: ffmpeg failed to extract frame at {time_ms}ms")
            runner._log_message(f"[FrameMatch] Error: {result.stderr[:200]}")
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return None

        # Load the extracted frame
        frame = Image.open(tmp_path)
        frame.load()  # Load image data before closing file

        # Clean up temp file
        os.unlink(tmp_path)

        return frame

    except Exception as e:
        runner._log_message(f"[FrameMatch] ERROR: Failed to extract frame: {e}")
        return None


def compute_frame_hash(frame: Image.Image, hash_size: int = 8, method: str = 'phash') -> Optional[Any]:
    """
    Compute perceptual hash of a frame.

    Args:
        frame: PIL Image object
        hash_size: Hash size (8x8 = 64 bits, 16x16 = 256 bits)
        method: Hash method ('phash', 'dhash', 'average_hash')

    Returns:
        ImageHash object, or None on failure
    """
    try:
        import imagehash

        if method == 'dhash':
            return imagehash.dhash(frame, hash_size=hash_size)
        elif method == 'average_hash':
            return imagehash.average_hash(frame, hash_size=hash_size)
        else:  # 'phash' or default
            return imagehash.phash(frame, hash_size=hash_size)

    except ImportError:
        return None
    except Exception:
        return None


def find_matching_frame(
    source_hash,
    target_video: str,
    expected_time_ms: int,
    search_window_ms: int,
    threshold: int,
    fps: float,
    runner,
    config: dict
) -> Optional[int]:
    """
    Find the frame in target video that best matches the source hash.

    Searches within a window around the expected time for efficiency.

    Args:
        source_hash: ImageHash of the source frame
        target_video: Path to target video file
        expected_time_ms: Expected timestamp (starting point for search)
        search_window_ms: Search window in milliseconds (±window)
        threshold: Maximum hamming distance for match (0-64 for 8x8 hash)
        fps: Target video frame rate
        runner: CommandRunner for logging
        config: Config dict with hash settings

    Returns:
        Matched timestamp in milliseconds, or None if no match found
    """
    # Calculate search range
    start_time_ms = max(0, expected_time_ms - search_window_ms)
    end_time_ms = expected_time_ms + search_window_ms

    # Frame duration in ms
    frame_duration_ms = 1000.0 / fps

    # Search every frame in the window
    best_match_time = None
    best_match_distance = threshold + 1  # Start above threshold

    hash_size = config.get('frame_match_hash_size', 8)
    hash_method = config.get('frame_match_method', 'phash')

    # Calculate number of frames to search
    num_frames = int((end_time_ms - start_time_ms) / frame_duration_ms)

    # Limit search to reasonable number (e.g., max 300 frames = ~12 sec at 24fps)
    max_search_frames = config.get('frame_match_max_search_frames', 300)
    if num_frames > max_search_frames:
        runner._log_message(f"[FrameMatch] WARNING: Search window too large ({num_frames} frames), capping at {max_search_frames}")
        num_frames = max_search_frames
        end_time_ms = start_time_ms + (num_frames * frame_duration_ms)

    runner._log_message(f"[FrameMatch] Searching {num_frames} frames from {start_time_ms}ms to {end_time_ms}ms")

    # Search through frames
    current_time_ms = start_time_ms
    frames_checked = 0

    while current_time_ms <= end_time_ms:
        # Extract frame from target
        target_frame = extract_frame_at_time(target_video, int(current_time_ms), runner)

        if target_frame is None:
            current_time_ms += frame_duration_ms
            continue

        # Compute hash
        target_hash = compute_frame_hash(target_frame, hash_size=hash_size, method=hash_method)

        if target_hash is None:
            current_time_ms += frame_duration_ms
            continue

        # Compare hashes
        distance = source_hash - target_hash  # Hamming distance

        frames_checked += 1

        # Update best match if better
        if distance < best_match_distance:
            best_match_distance = distance
            best_match_time = int(current_time_ms)

            # If perfect or very close match, stop searching
            if distance <= 2:
                runner._log_message(f"[FrameMatch] Found excellent match at {best_match_time}ms (distance={distance})")
                break

        current_time_ms += frame_duration_ms

    runner._log_message(f"[FrameMatch] Checked {frames_checked} frames, best distance: {best_match_distance}")

    # Return best match if within threshold
    if best_match_time is not None and best_match_distance <= threshold:
        return best_match_time
    else:
        runner._log_message(f"[FrameMatch] No match found within threshold {threshold} (best was {best_match_distance})")
        return None


def apply_frame_matched_sync(
    subtitle_path: str,
    source_video: str,
    target_video: str,
    runner,
    config: dict = None
) -> Dict[str, Any]:
    """
    Apply frame-accurate subtitle synchronization using visual frame matching.

    For each subtitle line:
    1. Extract frame at subtitle.start from source video
    2. Find visually matching frame in target video
    3. Adjust subtitle.start to matched time
    4. Preserve duration (don't adjust end independently)

    This handles videos with different frame counts/positions while preserving
    subtitle durations and inline tags.

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        source_video: Path to video that subs were originally timed to
        target_video: Path to video to sync subs to
        runner: CommandRunner for logging
        config: Optional config dict with settings:
            - 'frame_match_search_window_sec': Search window in seconds (default: 10)
            - 'frame_match_hash_size': Hash size (default: 8)
            - 'frame_match_threshold': Max hamming distance (default: 5)
            - 'frame_match_method': Hash method (default: 'phash')
            - 'frame_match_skip_unmatched': Skip lines with no match (default: False)

    Returns:
        Dict with report statistics
    """
    # Check for imagehash
    try:
        import imagehash
    except ImportError:
        runner._log_message("[FrameMatch] ERROR: imagehash not installed. Install with: pip install imagehash")
        return {'error': 'imagehash library not installed'}

    config = config or {}

    # Get config values
    search_window_sec = config.get('frame_match_search_window_sec', 10)
    search_window_ms = search_window_sec * 1000
    hash_size = config.get('frame_match_hash_size', 8)
    threshold = config.get('frame_match_threshold', 5)
    hash_method = config.get('frame_match_method', 'phash')
    skip_unmatched = config.get('frame_match_skip_unmatched', False)

    runner._log_message(f"[FrameMatch] Mode: Visual frame matching")
    runner._log_message(f"[FrameMatch] Source video: {Path(source_video).name}")
    runner._log_message(f"[FrameMatch] Target video: {Path(target_video).name}")
    runner._log_message(f"[FrameMatch] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[FrameMatch] Search window: ±{search_window_sec} seconds")
    runner._log_message(f"[FrameMatch] Hash method: {hash_method} ({hash_size}x{hash_size})")
    runner._log_message(f"[FrameMatch] Match threshold: {threshold} (hamming distance)")

    # Detect FPS of both videos
    from .frame_sync import detect_video_fps
    source_fps = detect_video_fps(source_video, runner)
    target_fps = detect_video_fps(target_video, runner)

    runner._log_message(f"[FrameMatch] Source FPS: {source_fps:.3f}")
    runner._log_message(f"[FrameMatch] Target FPS: {target_fps:.3f}")

    # Load subtitle file
    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[FrameMatch] ERROR: Failed to load subtitle file: {e}")
        return {'error': str(e)}

    if not subs.events:
        runner._log_message(f"[FrameMatch] WARNING: No subtitle events found in file")
        return {
            'total_events': 0,
            'matched_events': 0,
            'unmatched_events': 0
        }

    runner._log_message(f"[FrameMatch] Processing {len(subs.events)} subtitle events...")
    runner._log_message(f"[FrameMatch] This may take a few minutes...")

    matched_count = 0
    unmatched_count = 0
    total_offset_ms = 0
    max_offset_ms = 0

    # Process each subtitle event
    for i, event in enumerate(subs.events):
        original_start = event.start
        original_end = event.end
        original_duration = original_end - original_start

        # Skip empty events
        if original_duration <= 0:
            continue

        # Progress logging every 50 lines
        if (i + 1) % 50 == 0:
            runner._log_message(f"[FrameMatch] Progress: {i+1}/{len(subs.events)} lines processed...")

        # Extract frame from source video at subtitle start
        source_frame = extract_frame_at_time(source_video, original_start, runner)

        if source_frame is None:
            runner._log_message(f"[FrameMatch] WARNING: Failed to extract frame from source at {original_start}ms (line {i+1})")
            unmatched_count += 1
            continue

        # Compute hash of source frame
        source_hash = compute_frame_hash(source_frame, hash_size=hash_size, method=hash_method)

        if source_hash is None:
            runner._log_message(f"[FrameMatch] WARNING: Failed to compute hash for source frame (line {i+1})")
            unmatched_count += 1
            continue

        # Find matching frame in target video
        matched_time_ms = find_matching_frame(
            source_hash,
            target_video,
            original_start,  # Start search around original time
            search_window_ms,
            threshold,
            target_fps,
            runner,
            config
        )

        if matched_time_ms is not None:
            # Update subtitle timing
            event.start = matched_time_ms
            event.end = matched_time_ms + original_duration

            # Track statistics
            offset_ms = abs(matched_time_ms - original_start)
            total_offset_ms += offset_ms
            max_offset_ms = max(max_offset_ms, offset_ms)

            matched_count += 1

            # Log individual match (verbose, only for first few)
            if i < 5:
                runner._log_message(f"[FrameMatch] Line {i+1}: {original_start}ms → {matched_time_ms}ms (offset: {matched_time_ms - original_start:+d}ms)")
        else:
            unmatched_count += 1
            runner._log_message(f"[FrameMatch] WARNING: No match found for line {i+1} at {original_start}ms")

            # Optionally keep original timing if no match
            if not skip_unmatched:
                runner._log_message(f"[FrameMatch] Keeping original timing for line {i+1}")

    # Save modified subtitle
    runner._log_message(f"[FrameMatch] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[FrameMatch] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Calculate statistics
    avg_offset_ms = total_offset_ms / matched_count if matched_count > 0 else 0

    # Log results
    runner._log_message(f"[FrameMatch] ✓ Successfully processed {len(subs.events)} events")
    runner._log_message(f"[FrameMatch]   - Matched: {matched_count}")
    runner._log_message(f"[FrameMatch]   - Unmatched: {unmatched_count}")
    runner._log_message(f"[FrameMatch]   - Average offset: {avg_offset_ms:.1f}ms")
    runner._log_message(f"[FrameMatch]   - Maximum offset: {max_offset_ms}ms")

    return {
        'total_events': len(subs.events),
        'matched_events': matched_count,
        'unmatched_events': unmatched_count,
        'average_offset_ms': avg_offset_ms,
        'max_offset_ms': max_offset_ms,
        'source_fps': source_fps,
        'target_fps': target_fps
    }
