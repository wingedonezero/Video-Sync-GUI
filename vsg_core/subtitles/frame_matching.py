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
import pysubs2
from PIL import Image
import numpy as np


class VideoReader:
    """
    Efficient video reader that keeps video file open for fast frame access.

    Priority order:
    1. FFMS2 (fastest - indexed seeking, <1ms per frame)
    2. OpenCV (fast - keeps file open, but seeks from keyframes)
    3. FFmpeg (slow - spawns process per frame)
    """
    def __init__(self, video_path: str, runner):
        self.video_path = video_path
        self.runner = runner
        self.source = None
        self.cap = None
        self.use_ffms2 = False
        self.use_opencv = False
        self.fps = None

        # Try FFMS2 first (fastest - indexed seeking)
        try:
            import ffms2
            runner._log_message(f"[FrameMatch] Indexing video with FFMS2 (one-time cost)...")
            runner._log_message(f"[FrameMatch] This may take 1-2 minutes, but enables instant frame access...")

            # Create FFMS2 source (will create/use index file)
            self.source = ffms2.VideoSource(str(video_path))
            self.use_ffms2 = True

            # Get video properties
            self.fps = self.source.properties.FPSNumerator / self.source.properties.FPSDenominator

            runner._log_message(f"[FrameMatch] ✓ FFMS2 indexed! Using instant frame seeking (FPS: {self.fps:.3f})")
            runner._log_message(f"[FrameMatch] Index cached to: {video_path}.ffindex")
            return

        except ImportError:
            runner._log_message(f"[FrameMatch] FFMS2 not installed, trying opencv...")
            runner._log_message(f"[FrameMatch] Install FFMS2 for 100x speedup: pip install ffms2")
        except Exception as e:
            runner._log_message(f"[FrameMatch] WARNING: FFMS2 failed ({e}), trying opencv...")

        # Fallback to opencv if FFMS2 unavailable
        try:
            import cv2
            self.cv2 = cv2
            self.cap = cv2.VideoCapture(str(video_path))
            if self.cap.isOpened():
                self.use_opencv = True
                self.fps = self.cap.get(cv2.CAP_PROP_FPS)
                runner._log_message(f"[FrameMatch] Using opencv for frame access (FPS: {self.fps:.3f})")
            else:
                runner._log_message(f"[FrameMatch] WARNING: opencv couldn't open video, falling back to ffmpeg")
                self.cap = None
        except ImportError:
            runner._log_message(f"[FrameMatch] WARNING: opencv not installed, using slower ffmpeg fallback")
            runner._log_message(f"[FrameMatch] Install opencv for better performance: pip install opencv-python")

    def get_frame_at_time(self, time_ms: int) -> Optional[Image.Image]:
        """
        Extract frame at specified timestamp.

        Args:
            time_ms: Timestamp in milliseconds

        Returns:
            PIL Image object, or None on failure
        """
        if self.use_ffms2 and self.source:
            return self._get_frame_ffms2(time_ms)
        elif self.use_opencv and self.cap:
            return self._get_frame_opencv(time_ms)
        else:
            return self._get_frame_ffmpeg(time_ms)

    def _get_frame_ffms2(self, time_ms: int) -> Optional[Image.Image]:
        """Extract frame using FFMS2 (instant indexed seeking)."""
        try:
            # Convert time to frame number
            frame_num = int((time_ms / 1000.0) * self.fps)

            # Clamp to valid range
            frame_num = max(0, min(frame_num, self.source.properties.NumFrames - 1))

            # Get frame (instant - uses index!)
            frame = self.source.get_frame(frame_num)

            # Convert to PIL Image
            # FFMS2 returns frames as numpy arrays in RGB format
            frame_array = frame.planes[0]  # Get RGB data

            # Create PIL Image from numpy array
            return Image.fromarray(frame_array)

        except Exception as e:
            self.runner._log_message(f"[FrameMatch] ERROR: FFMS2 frame extraction failed: {e}")
            return None

    def _get_frame_opencv(self, time_ms: int) -> Optional[Image.Image]:
        """Extract frame using opencv (fast)."""
        try:
            # Seek to timestamp (opencv uses milliseconds)
            self.cap.set(self.cv2.CAP_PROP_POS_MSEC, time_ms)

            # Read frame
            ret, frame_bgr = self.cap.read()

            if not ret or frame_bgr is None:
                return None

            # Convert BGR to RGB
            frame_rgb = self.cv2.cvtColor(frame_bgr, self.cv2.COLOR_BGR2RGB)

            # Convert to PIL Image
            return Image.fromarray(frame_rgb)

        except Exception as e:
            self.runner._log_message(f"[FrameMatch] ERROR: opencv frame extraction failed: {e}")
            return None

    def _get_frame_ffmpeg(self, time_ms: int) -> Optional[Image.Image]:
        """Extract frame using ffmpeg (slow fallback)."""
        import subprocess
        import tempfile
        import os

        try:
            time_sec = time_ms / 1000.0

            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp_path = tmp.name

            cmd = [
                'ffmpeg',
                '-ss', f'{time_sec:.3f}',
                '-i', str(self.video_path),
                '-vframes', '1',
                '-q:v', '2',
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
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return None

            frame = Image.open(tmp_path)
            frame.load()
            os.unlink(tmp_path)

            return frame

        except Exception:
            return None

    def close(self):
        """Release video resources."""
        if self.source:
            # FFMS2 sources don't need explicit closing, but clear reference
            self.source = None
        if self.cap:
            self.cap.release()
            self.cap = None


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
    target_reader: VideoReader,
    expected_time_ms: int,
    search_window_ms: int,
    threshold: int,
    fps: float,
    config: dict
) -> Optional[int]:
    """
    Find the frame in target video that best matches the source hash.

    Searches from center outward for efficiency (most likely match is in middle).

    Args:
        source_hash: ImageHash of the source frame
        target_reader: VideoReader for target video (keeps video open)
        expected_time_ms: Expected timestamp (center of search, already adjusted for audio delay)
        search_window_ms: Search window in milliseconds (±window from expected)
        threshold: Maximum hamming distance for match (0-64 for 8x8 hash)
        fps: Target video frame rate
        config: Config dict with hash settings

    Returns:
        Matched timestamp in milliseconds, or None if no match found
    """
    # Frame duration in ms
    frame_duration_ms = 1000.0 / fps

    # Search every frame in the window
    best_match_time = None
    best_match_distance = threshold + 1  # Start above threshold

    hash_size = config.get('frame_match_hash_size', 8)
    hash_method = config.get('frame_match_method', 'dhash')  # dhash default for speed

    # Calculate number of frames to search (radius from center)
    num_frames_radius = int(search_window_ms / frame_duration_ms)

    # Limit search to reasonable number
    max_search_frames = config.get('frame_match_max_search_frames', 300)
    if num_frames_radius * 2 > max_search_frames:
        num_frames_radius = max_search_frames // 2

    # Search from center outward (spiral pattern)
    # This finds matches faster when expected_time_ms is accurate (using audio delay)
    frames_checked = 0

    for offset in range(num_frames_radius + 1):
        # Check frames at ±offset from center
        for direction in ([0] if offset == 0 else [-1, 1]):
            current_time_ms = expected_time_ms + (offset * direction * frame_duration_ms)

            # Skip if out of bounds
            if current_time_ms < 0:
                continue

            # Extract frame from target using VideoReader (FAST with FFMS2!)
            target_frame = target_reader.get_frame_at_time(int(current_time_ms))

            if target_frame is None:
                continue

            # Compute hash
            target_hash = compute_frame_hash(target_frame, hash_size=hash_size, method=hash_method)

            if target_hash is None:
                continue

            # Compare hashes
            distance = source_hash - target_hash  # Hamming distance

            frames_checked += 1

            # Update best match if better
            if distance < best_match_distance:
                best_match_distance = distance
                best_match_time = int(current_time_ms)

                # If perfect or very close match, stop searching immediately
                if distance <= 2:
                    return best_match_time

    # Return best match if within threshold
    if best_match_time is not None and best_match_distance <= threshold:
        return best_match_time
    else:
        return None


def apply_frame_matched_sync(
    subtitle_path: str,
    source_video: str,
    target_video: str,
    runner,
    config: dict = None,
    audio_delay_ms: int = 0
) -> Dict[str, Any]:
    """
    Apply frame-accurate subtitle synchronization using visual frame matching.

    For each subtitle line:
    1. Extract frame at subtitle.start from source video
    2. Apply audio_delay_ms to get expected target time (smart centering)
    3. Search ±window around expected time for visually matching frame
    4. Adjust subtitle.start to matched time
    5. Preserve duration (don't adjust end independently)

    This handles videos with different frame counts/positions while preserving
    subtitle durations and inline tags.

    Args:
        subtitle_path: Path to subtitle file (.ass, .srt, .ssa, .vtt)
        source_video: Path to video that subs were originally timed to
        target_video: Path to video to sync subs to
        runner: CommandRunner for logging
        config: Optional config dict with settings:
            - 'frame_match_search_window_sec': Search window in seconds (default: 5)
            - 'frame_match_hash_size': Hash size (default: 8)
            - 'frame_match_threshold': Max hamming distance (default: 5)
            - 'frame_match_method': Hash method (default: 'phash')
            - 'frame_match_skip_unmatched': Skip lines with no match (default: False)
        audio_delay_ms: Audio delay from correlation (used for smart search centering)

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

    # Get config values (reduced default window to 1 second with smart centering + hash caching)
    search_window_sec = config.get('frame_match_search_window_sec', 1)
    search_window_ms = search_window_sec * 1000
    hash_size = config.get('frame_match_hash_size', 8)
    threshold = config.get('frame_match_threshold', 5)
    hash_method = config.get('frame_match_method', 'phash')
    skip_unmatched = config.get('frame_match_skip_unmatched', False)

    runner._log_message(f"[FrameMatch] Mode: Visual frame matching with smart search")
    runner._log_message(f"[FrameMatch] Source video: {Path(source_video).name}")
    runner._log_message(f"[FrameMatch] Target video: {Path(target_video).name}")
    runner._log_message(f"[FrameMatch] Loading subtitle: {Path(subtitle_path).name}")
    runner._log_message(f"[FrameMatch] Audio delay for centering: {audio_delay_ms:+d}ms")
    runner._log_message(f"[FrameMatch] Search window: ±{search_window_sec} seconds (from expected time)")
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

    # For large subtitle files, estimate processing time
    if len(subs.events) > 1000:
        runner._log_message(f"[FrameMatch] WARNING: Large subtitle file detected ({len(subs.events)} events)")
        runner._log_message(f"[FrameMatch] This will take some time. Consider using smaller search window if too slow.")

    runner._log_message(f"[FrameMatch] Opening video files...")

    # Create VideoReader instances (keeps videos open for fast access)
    source_reader = VideoReader(source_video, runner)
    target_reader = VideoReader(target_video, runner)

    # Hash caching to avoid recomputing hashes for duplicate timestamps
    # Critical for karaoke files where many subs have same timestamp!
    source_hash_cache = {}  # {time_ms: hash}

    runner._log_message(f"[FrameMatch] Hash caching enabled for duplicate timestamps")

    try:
        matched_count = 0
        unmatched_count = 0
        total_offset_ms = 0
        max_offset_ms = 0

        # Determine progress reporting interval based on number of events
        if len(subs.events) > 10000:
            progress_interval = 500  # Every 500 lines for huge files
        elif len(subs.events) > 1000:
            progress_interval = 100  # Every 100 lines for large files
        else:
            progress_interval = 50   # Every 50 lines for normal files

        runner._log_message(f"[FrameMatch] Starting frame matching...")

        # Process each subtitle event
        for i, event in enumerate(subs.events):
            original_start = event.start
            original_end = event.end
            original_duration = original_end - original_start

            # Skip empty events
            if original_duration <= 0:
                continue

            # Progress logging
            if (i + 1) % progress_interval == 0:
                percent = ((i + 1) / len(subs.events)) * 100
                runner._log_message(f"[FrameMatch] Progress: {i+1}/{len(subs.events)} ({percent:.1f}%) - Matched: {matched_count}, Unmatched: {unmatched_count}")

            # Check hash cache first (critical for karaoke with duplicate timestamps!)
            if original_start in source_hash_cache:
                source_hash = source_hash_cache[original_start]
            else:
                # Extract frame from source video at subtitle start using VideoReader
                source_frame = source_reader.get_frame_at_time(original_start)

                if source_frame is None:
                    unmatched_count += 1
                    continue

                # Compute hash of source frame
                source_hash = compute_frame_hash(source_frame, hash_size=hash_size, method=hash_method)

                if source_hash is None:
                    unmatched_count += 1
                    continue

                # Cache the hash for this timestamp
                source_hash_cache[original_start] = source_hash

            # Find matching frame in target video using VideoReader
            # Use audio delay to center search (smart search!)
            expected_target_time_ms = original_start + audio_delay_ms

            matched_time_ms = find_matching_frame(
                source_hash,
                target_reader,  # Pass VideoReader, not path!
                expected_target_time_ms,  # Center search on expected time (audio delay applied)
                search_window_ms,
                threshold,
                target_fps,
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

                # Log individual match (verbose, only for first 3)
                if i < 3:
                    runner._log_message(f"[FrameMatch] Line {i+1}: {original_start}ms → {matched_time_ms}ms (offset: {matched_time_ms - original_start:+d}ms)")
            else:
                unmatched_count += 1
                # Only log first few unmatched to avoid spam
                if unmatched_count <= 10:
                    runner._log_message(f"[FrameMatch] WARNING: No match found for line {i+1} at {original_start}ms")

    finally:
        # Always close video readers
        runner._log_message(f"[FrameMatch] Closing video files...")
        source_reader.close()
        target_reader.close()

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
    if matched_count > 0:
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
