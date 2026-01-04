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
from typing import Dict, Any, Optional, Tuple, List
import pysubs2
from PIL import Image
import numpy as np
import threading
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from .metadata_preserver import SubtitleMetadata
from .frame_sync import time_to_frame_vfr, frame_to_time_vfr


class VideoReader:
    """
    Efficient video reader that keeps video file open for fast frame access.

    Priority order:
    1. VapourSynth + FFMS2 plugin (fastest - persistent index caching, <1ms per frame, thread-safe)
    2. pyffms2 (fast - indexed seeking, but re-indexes each time)
    3. OpenCV (medium - keeps file open, but seeks from keyframes)
    4. FFmpeg (slow - spawns process per frame)
    """
    def __init__(self, video_path: str, runner, temp_dir: Path = None):
        self.video_path = video_path
        self.runner = runner
        self.vs_clip = None  # VapourSynth clip
        self.source = None   # FFMS2 source
        self.cap = None      # OpenCV capture
        self.use_vapoursynth = False
        self.use_ffms2 = False
        self.use_opencv = False
        self.fps = None
        self.temp_dir = temp_dir

        # Try VapourSynth first (fastest - persistent index caching)
        if self._try_vapoursynth():
            return

        # Try FFMS2 second (fast but re-indexes each time)
        try:
            import ffms2

            # Note: The pyffms2 Python bindings don't reliably support loading cached indexes
            # We create the index on-demand each time (still faster than OpenCV fallback)
            runner._log_message(f"[FrameMatch] Creating FFMS2 index...")
            runner._log_message(f"[FrameMatch] This may take 1-2 minutes on first access...")

            # Create indexer and generate index
            indexer = ffms2.Indexer(str(video_path))
            index = indexer.do_indexing2()

            # Get first video track
            track_number = index.get_first_indexed_track_of_type(ffms2.FFMS_TYPE_VIDEO)

            # Create video source from index
            self.source = ffms2.VideoSource(str(video_path), track_number, index)
            self.use_ffms2 = True

            # Get video properties
            self.fps = self.source.properties.FPSNumerator / self.source.properties.FPSDenominator

            runner._log_message(f"[FrameMatch] ✓ FFMS2 ready! Using instant frame seeking (FPS: {self.fps:.3f})")
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

    def _get_index_cache_path(self, video_path: str, temp_dir: Path) -> Path:
        """
        Generate persistent cache path for FFMS2 index.

        Cache key: video filename + size + mtime (detects file changes)
        Location: {temp_dir}/ffindex/{cache_key}.ffindex
        """
        import os

        video_path_obj = Path(video_path)

        # Get file metadata for cache invalidation
        stat = os.stat(video_path)
        file_size = stat.st_size
        mtime = int(stat.st_mtime)

        # Generate cache key
        cache_key = f"{video_path_obj.stem}_{file_size}_{mtime}"

        # Use temp_dir if available, otherwise use system temp
        if temp_dir:
            cache_dir = temp_dir / "ffindex"
        else:
            import tempfile
            cache_dir = Path(tempfile.gettempdir()) / "vsg_ffindex"

        return cache_dir / f"{cache_key}.ffindex"

    def _try_vapoursynth(self) -> bool:
        """
        Try to initialize VapourSynth with FFMS2 plugin for persistent index caching.

        Returns:
            True if successful, False if VapourSynth unavailable or failed
        """
        try:
            import vapoursynth as vs

            self.runner._log_message("[FrameMatch] Attempting VapourSynth with FFMS2 plugin...")

            # Get VapourSynth core instance
            core = vs.core

            # Check if ffms2 plugin is available
            if not hasattr(core, 'ffms2'):
                self.runner._log_message("[FrameMatch] VapourSynth installed but ffms2 plugin missing")
                self.runner._log_message("[FrameMatch] Install FFMS2 plugin for VapourSynth")
                return False

            # Generate cache path
            index_path = self._get_index_cache_path(self.video_path, self.temp_dir)

            # Ensure cache directory exists
            index_path.parent.mkdir(parents=True, exist_ok=True)

            # Load video with persistent index caching
            if index_path.exists():
                self.runner._log_message(f"[FrameMatch] ✓ Reusing existing index: {index_path.name}")
            else:
                self.runner._log_message(f"[FrameMatch] Creating new index (this may take 1-2 minutes)...")

            clip = core.ffms2.Source(
                source=str(self.video_path),
                cachefile=str(index_path)
            )

            # Keep clip in original format (usually YUV)
            # We'll extract only luma (Y) plane for hashing - more reliable than RGB
            self.vs_clip = clip

            # Get video properties
            self.fps = self.vs_clip.fps_num / self.vs_clip.fps_den
            self.use_vapoursynth = True

            self.runner._log_message(f"[FrameMatch] ✓ VapourSynth ready! Using persistent index cache (FPS: {self.fps:.3f})")
            self.runner._log_message(f"[FrameMatch] ✓ Index will be shared across all workers (no re-indexing!)")

            return True

        except ImportError:
            self.runner._log_message("[FrameMatch] VapourSynth not installed, trying pyffms2...")
            self.runner._log_message("[FrameMatch] Install VapourSynth for persistent index caching: pip install VapourSynth")
            return False
        except AttributeError as e:
            self.runner._log_message(f"[FrameMatch] VapourSynth ffms2 plugin not found: {e}")
            self.runner._log_message("[FrameMatch] Install FFMS2 plugin for VapourSynth")
            return False
        except Exception as e:
            self.runner._log_message(f"[FrameMatch] VapourSynth initialization failed: {e}")
            return False

    def get_frame_at_time(self, time_ms: int) -> Optional[Image.Image]:
        """
        Extract frame at specified timestamp.

        Args:
            time_ms: Timestamp in milliseconds

        Returns:
            PIL Image object, or None on failure
        """
        if self.use_vapoursynth and self.vs_clip:
            return self._get_frame_vapoursynth(time_ms)
        elif self.use_ffms2 and self.source:
            return self._get_frame_ffms2(time_ms)
        elif self.use_opencv and self.cap:
            return self._get_frame_opencv(time_ms)
        else:
            return self._get_frame_ffmpeg(time_ms)

    def _get_frame_vapoursynth(self, time_ms: int) -> Optional[Image.Image]:
        """
        Extract frame using VapourSynth (instant indexed seeking with persistent cache).

        Extracts only the luma (Y) plane as grayscale for better perceptual hashing.
        Luma contains most of the perceptual information and avoids color conversion artifacts.
        """
        try:
            import numpy as np

            # Convert time to frame number
            frame_num = int((time_ms / 1000.0) * self.fps)

            # Clamp to valid range
            frame_num = max(0, min(frame_num, len(self.vs_clip) - 1))

            # Get frame (instant - uses FFMS2 index!)
            frame = self.vs_clip.get_frame(frame_num)

            # Get frame dimensions and stride
            width = frame.width
            height = frame.height

            # VapourSynth frames have stride (row padding for alignment)
            # We need to handle this properly
            plane_data = frame.get_read_ptr(0)  # Get pointer to Y plane
            stride = frame.get_stride(0)  # Get stride (bytes per row including padding)

            # Create array from pointer with stride
            arr = np.frombuffer(plane_data, dtype=np.uint8, count=stride * height)
            arr = arr.reshape(height, stride)

            # Extract only the actual image data (remove padding)
            y_plane = arr[:, :width]

            # Convert to PIL Image (grayscale mode 'L')
            return Image.fromarray(y_plane, 'L')

        except Exception as e:
            self.runner._log_message(f"[FrameMatch] ERROR: VapourSynth frame extraction failed: {e}")
            return None

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
        # VapourSynth cleanup
        if self.vs_clip:
            # VapourSynth clips are reference counted, just clear reference
            self.vs_clip = None

        # FFMS2 cleanup
        if self.source:
            # FFMS2 sources don't need explicit closing, but clear reference
            self.source = None

        # OpenCV cleanup
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

    # Determine search window size
    # NEW: Frame-based search window (more precise, faster)
    search_window_frames = config.get('frame_match_search_window_frames', 0)

    if search_window_frames > 0:
        # Use frame-based window (±N frames)
        num_frames_radius = search_window_frames
    else:
        # Fall back to time-based window (±N seconds converted to frames)
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


def _precompute_source_hashes(
    subs: pysubs2.SSAFile,
    source_reader: VideoReader,
    hash_size: int,
    hash_method: str,
    runner
) -> Dict[int, Any]:
    """
    Phase 1: Pre-compute source frame hashes for all unique timestamps.

    This is done single-threaded since:
    1. Hash caching makes duplicate timestamps instant
    2. Source frame extraction is fast with FFMS2
    3. Avoids thread-safety issues with VideoReader

    Returns:
        Dict mapping timestamp (ms) -> hash object
    """
    source_hash_cache = {}
    unique_timestamps = set()

    # Collect unique timestamps
    for event in subs.events:
        if event.end - event.start > 0:  # Skip zero-duration
            unique_timestamps.add(event.start)

    runner._log_message(f"[FrameMatch] Phase 1: Pre-computing {len(unique_timestamps)} unique source frame hashes...")

    computed_count = 0
    for i, timestamp in enumerate(sorted(unique_timestamps)):
        # Extract frame from source video
        source_frame = source_reader.get_frame_at_time(timestamp)

        if source_frame is None:
            continue

        # Compute hash
        source_hash = compute_frame_hash(source_frame, hash_size=hash_size, method=hash_method)

        if source_hash is None:
            continue

        # Cache it
        source_hash_cache[timestamp] = source_hash
        computed_count += 1

        # Progress reporting (every 10%)
        if (i + 1) % max(1, len(unique_timestamps) // 10) == 0:
            percent = ((i + 1) / len(unique_timestamps)) * 100
            runner._log_message(f"[FrameMatch] Phase 1 Progress: {i+1}/{len(unique_timestamps)} ({percent:.1f}%)")

    runner._log_message(f"[FrameMatch] Phase 1 Complete: {computed_count}/{len(unique_timestamps)} hashes computed")

    return source_hash_cache


def _process_subtitle_batch(
    batch_indices: List[int],
    events: List[pysubs2.SSAEvent],
    source_hash_cache: Dict[int, Any],
    source_video: str,
    target_video: str,
    runner,
    search_window_ms: int,
    threshold: int,
    source_fps: float,
    target_fps: float,
    audio_delay_ms: int,
    config: dict,
    progress_lock: threading.Lock,
    progress_counter: Dict[str, int],
    temp_dir: Path = None
) -> List[Tuple[int, Optional[int], int, int]]:
    """
    Phase 2 Worker: Process a batch of subtitles to find matching frames.

    Each worker has its own target VideoReader instance to avoid conflicts.
    Source hashes are read from cache (read-only, thread-safe).

    Args:
        batch_indices: List of subtitle indices to process
        events: Full list of subtitle events (read-only)
        source_hash_cache: Pre-computed source hashes (read-only)
        source_video: Path to source video (for timestamp pre-filtering)
        target_video: Path to target video
        runner: CommandRunner for logging (thread-safe methods only)
        ... other matching parameters ...
        progress_lock: Lock for thread-safe progress updates
        progress_counter: Shared counter dict {'matched': 0, 'unmatched': 0, 'processed': 0}
        temp_dir: Optional temp directory for FFMS2 index storage

    Returns:
        List of (index, matched_time_ms, offset_ms, original_start) tuples
    """
    # Create worker's own target VideoReader
    # Pass temp_dir so workers can reuse the same cached FFMS2 index!
    target_reader = VideoReader(target_video, runner, temp_dir=temp_dir)

    # Check if timestamp pre-filtering is enabled
    use_timestamp_prefilter = config.get('frame_match_use_timestamp_prefilter', True)

    results = []

    try:
        for idx in batch_indices:
            event = events[idx]
            original_start = event.start
            original_duration = event.end - event.start

            # Skip empty events
            if original_duration <= 0:
                continue

            # Get source hash from cache (read-only, no locking needed)
            source_hash = source_hash_cache.get(original_start)

            if source_hash is None:
                # No hash for this timestamp (failed in Phase 1)
                with progress_lock:
                    progress_counter['unmatched'] += 1
                    progress_counter['processed'] += 1
                continue

            # Calculate expected target time with optional timestamp pre-filtering
            if use_timestamp_prefilter:
                # TIMESTAMP PRE-FILTERING: Use VideoTimestamps to refine search center
                # This gives us a frame-accurate center point for visual search
                #
                # Steps:
                # 1. Convert source time → source frame (exact)
                # 2. Convert source frame → source timestamp (frame-snapped)
                # 3. Add delay to get expected target time
                # 4. Convert to target frame (exact)
                # 5. Convert target frame → target timestamp (frame-snapped)
                # 6. Use this refined timestamp as visual search center
                #
                # This allows ±5 frame search instead of ±24, giving ~5x speedup!

                source_frame = time_to_frame_vfr(original_start, source_video, source_fps, runner, config)

                if source_frame is not None:
                    # Get exact source timestamp for this frame
                    source_timestamp_exact = frame_to_time_vfr(source_frame, source_video, source_fps, runner, config)

                    if source_timestamp_exact is not None:
                        # Add delay to get expected target time
                        adjusted_time = source_timestamp_exact + audio_delay_ms

                        # Convert to target frame and back to get frame-snapped center
                        target_frame = time_to_frame_vfr(adjusted_time, target_video, target_fps, runner, config)

                        if target_frame is not None:
                            expected_target_time_ms = frame_to_time_vfr(target_frame, target_video, target_fps, runner, config)
                            if expected_target_time_ms is None:
                                # Fallback to basic calculation if frame conversion fails
                                expected_target_time_ms = original_start + audio_delay_ms
                        else:
                            expected_target_time_ms = original_start + audio_delay_ms
                    else:
                        expected_target_time_ms = original_start + audio_delay_ms
                else:
                    expected_target_time_ms = original_start + audio_delay_ms
            else:
                # Basic calculation without pre-filtering
                expected_target_time_ms = original_start + audio_delay_ms

            matched_time_ms = find_matching_frame(
                source_hash,
                target_reader,
                expected_target_time_ms,
                search_window_ms,
                threshold,
                target_fps,
                config
            )

            # Update progress (thread-safe)
            with progress_lock:
                if matched_time_ms is not None:
                    progress_counter['matched'] += 1
                    offset_ms = abs(matched_time_ms - original_start)
                    results.append((idx, matched_time_ms, offset_ms, original_start))
                else:
                    progress_counter['unmatched'] += 1

                progress_counter['processed'] += 1

    finally:
        # Clean up worker's VideoReader
        target_reader.close()

    return results


def apply_frame_matched_sync(
    subtitle_path: str,
    source_video: str,
    target_video: str,
    runner,
    config: dict = None,
    audio_delay_ms: int = 0,
    temp_dir: Path = None
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
        temp_dir: Optional temp directory for FFMS2 index storage (for reuse across tracks)

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

    # Log search window optimization settings
    search_window_frames = config.get('frame_match_search_window_frames', 0)
    use_timestamp_prefilter = config.get('frame_match_use_timestamp_prefilter', True)

    if search_window_frames > 0:
        runner._log_message(f"[FrameMatch] Search window: ±{search_window_frames} frames (frame-based)")
    else:
        runner._log_message(f"[FrameMatch] Search window: ±{search_window_sec} seconds (time-based)")

    if use_timestamp_prefilter:
        runner._log_message(f"[FrameMatch] ✓ Timestamp pre-filtering enabled (VideoTimestamps-guided search center)")

    runner._log_message(f"[FrameMatch] Hash method: {hash_method} ({hash_size}x{hash_size})")
    runner._log_message(f"[FrameMatch] Match threshold: {threshold} (hamming distance)")

    # Detect FPS of both videos
    from .frame_sync import detect_video_fps
    source_fps = detect_video_fps(source_video, runner)
    target_fps = detect_video_fps(target_video, runner)

    runner._log_message(f"[FrameMatch] Source FPS: {source_fps:.3f}")
    runner._log_message(f"[FrameMatch] Target FPS: {target_fps:.3f}")

    # Capture original metadata before pysubs2 processing
    metadata = SubtitleMetadata(subtitle_path)
    metadata.capture()

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

    # Determine number of worker threads
    num_workers = config.get('frame_match_workers', 0)
    if num_workers == 0:
        # Auto: use cpu_count - 1, but at least 1
        num_workers = max(1, os.cpu_count() - 1)
    # Limit to reasonable range
    num_workers = max(1, min(num_workers, 16))

    runner._log_message(f"[FrameMatch] Multithreading enabled: {num_workers} worker threads")
    runner._log_message(f"[FrameMatch] Opening source video for Phase 1...")

    # Create source VideoReader for Phase 1
    # Pass temp_dir for persistent FFMS2 index caching
    source_reader = VideoReader(source_video, runner, temp_dir=temp_dir)

    try:
        # ============================================================
        # PHASE 1: Pre-compute all unique source frame hashes
        # ============================================================
        source_hash_cache = _precompute_source_hashes(
            subs,
            source_reader,
            hash_size,
            hash_method,
            runner
        )

        # Close source reader after Phase 1
        source_reader.close()

        runner._log_message(f"[FrameMatch] Source video closed (Phase 1 complete)")

        # ============================================================
        # PHASE 2: Parallel target frame matching
        # ============================================================
        runner._log_message(f"[FrameMatch] Phase 2: Starting parallel frame matching with {num_workers} workers...")

        # Create batches of subtitle indices for parallel processing
        total_subs = len(subs.events)
        batch_size = max(1, total_subs // (num_workers * 4))  # 4 batches per worker for better load balancing

        batches = []
        for i in range(0, total_subs, batch_size):
            batch_indices = list(range(i, min(i + batch_size, total_subs)))
            batches.append(batch_indices)

        runner._log_message(f"[FrameMatch] Created {len(batches)} batches (avg {batch_size} subs/batch)")

        # Shared progress tracking (thread-safe)
        progress_lock = threading.Lock()
        progress_counter = {'matched': 0, 'unmatched': 0, 'processed': 0}

        # Progress reporter thread
        def log_progress():
            while progress_counter['processed'] < total_subs:
                with progress_lock:
                    processed = progress_counter['processed']
                    matched = progress_counter['matched']
                    unmatched = progress_counter['unmatched']

                if processed > 0:
                    percent = (processed / total_subs) * 100
                    runner._log_message(
                        f"[FrameMatch] Phase 2 Progress: {processed}/{total_subs} ({percent:.1f}%) - "
                        f"Matched: {matched}, Unmatched: {unmatched}"
                    )

                # Sleep before next update
                import time
                time.sleep(5)  # Log every 5 seconds

        # Start progress reporter in background
        import threading as thread_module
        progress_thread = thread_module.Thread(target=log_progress, daemon=True)
        progress_thread.start()

        # Process batches in parallel with ThreadPoolExecutor
        all_results = []

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            # Submit all batches to thread pool
            future_to_batch = {}
            for batch_idx, batch_indices in enumerate(batches):
                future = executor.submit(
                    _process_subtitle_batch,
                    batch_indices,
                    subs.events,
                    source_hash_cache,
                    source_video,
                    target_video,
                    runner,
                    search_window_ms,
                    threshold,
                    source_fps,
                    target_fps,
                    audio_delay_ms,
                    config,
                    progress_lock,
                    progress_counter,
                    temp_dir  # Pass temp_dir for FFMS2 index reuse
                )
                future_to_batch[future] = batch_idx

            # Collect results as they complete
            for future in as_completed(future_to_batch):
                batch_idx = future_to_batch[future]
                try:
                    batch_results = future.result()
                    all_results.extend(batch_results)
                except Exception as e:
                    runner._log_message(f"[FrameMatch] ERROR: Batch {batch_idx} failed: {e}")

        # Wait for progress thread to finish
        progress_thread.join(timeout=1)

        runner._log_message(f"[FrameMatch] Phase 2 Complete: All workers finished")

        # ============================================================
        # Apply results to subtitle events
        # ============================================================
        runner._log_message(f"[FrameMatch] Applying {len(all_results)} matched timings to subtitles...")

        matched_count = 0
        unmatched_count = 0
        total_offset_ms = 0
        max_offset_ms = 0

        for idx, matched_time_ms, offset_ms, original_start in all_results:
            event = subs.events[idx]
            original_duration = event.end - event.start

            # Update subtitle timing
            event.start = matched_time_ms
            event.end = matched_time_ms + original_duration

            # Track statistics
            total_offset_ms += offset_ms
            max_offset_ms = max(max_offset_ms, offset_ms)
            matched_count += 1

            # Log individual match (verbose, only for first 3)
            if matched_count <= 3:
                runner._log_message(f"[FrameMatch] Line {idx+1}: {original_start}ms → {matched_time_ms}ms (offset: {matched_time_ms - original_start:+d}ms)")

        # Count unmatched from progress counter
        unmatched_count = progress_counter['unmatched']

        runner._log_message(f"[FrameMatch] Timing adjustments applied")

    finally:
        # Ensure source reader is closed (in case of early exit)
        if source_reader.cap or source_reader.source:
            source_reader.close()
        runner._log_message(f"[FrameMatch] Cleanup complete")

    # Save modified subtitle
    runner._log_message(f"[FrameMatch] Saving modified subtitle file...")
    try:
        subs.save(subtitle_path, encoding='utf-8')
    except Exception as e:
        runner._log_message(f"[FrameMatch] ERROR: Failed to save subtitle file: {e}")
        return {'error': str(e)}

    # Validate and restore lost metadata
    metadata.validate_and_restore(runner)

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
