# vsg_core/subtitles/frame_utils/video_reader.py
"""
Video reader with multi-backend support for efficient frame extraction.

Contains:
- VideoReader class with VapourSynth, FFMS2, OpenCV, FFmpeg backends
- Automatic deinterlacing support
- VapourSynth frame indexing utilities
"""

from __future__ import annotations

import gc
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


def _get_ffms2_cache_path(video_path: str, temp_dir: Path | None) -> Path:
    """
    Generate cache path for FFMS2 index in job's temp directory.

    Cache key: parent_dir + filename + size + mtime (unique per file path)
    Location: {job_temp_dir}/ffindex/{cache_key}.ffindex

    The index is created in the job's temp folder so it can be:
    1. Easily identified by filename and source
    2. Reused within the job (multiple sync operations on same video)
    3. Cleaned up automatically when job completes
    4. Avoid collisions when different sources have same episode numbers
    """
    import hashlib
    import os

    video_path_obj = Path(video_path)

    # Get file metadata for cache invalidation
    stat = os.stat(video_path)
    file_size = stat.st_size
    mtime = int(stat.st_mtime)

    # Include parent directory to distinguish between sources
    # E.g., "source1/1.mkv" vs "source2/1.mkv" get different indexes
    parent_dir = video_path_obj.parent.name

    # If parent is empty/root, use path hash instead
    if not parent_dir or parent_dir == ".":
        path_hash = hashlib.md5(str(video_path_obj.resolve()).encode()).hexdigest()[:8]
        cache_key = f"{video_path_obj.stem}_{path_hash}_{file_size}_{mtime}"
    else:
        cache_key = f"{parent_dir}_{video_path_obj.stem}_{file_size}_{mtime}"

    # ALWAYS use job's temp_dir for index storage (for cleanup)
    if temp_dir:
        cache_dir = temp_dir / "ffindex"
        cache_dir.mkdir(parents=True, exist_ok=True)
    else:
        # Fallback: use system temp (but warn - won't be cleaned up)
        cache_dir = Path(tempfile.gettempdir()) / "vsg_ffindex"
        cache_dir.mkdir(parents=True, exist_ok=True)

    return cache_dir / f"{cache_key}.ffindex"


def get_vapoursynth_frame_info(
    video_path: str, runner, temp_dir: Path | None = None
) -> tuple[int, float] | None:
    """
    Get frame count and last frame timestamp using VapourSynth indexing.

    This is MUCH faster than ffprobe -count_frames after the initial index:
    - First run: ~30-60s (generates .lwi index file)
    - Subsequent runs: <1s (reads cached index)

    Handles CFR and VFR videos perfectly.

    IMPORTANT: Properly frees memory after use to prevent RAM buildup.

    Args:
        video_path: Path to video file
        runner: CommandRunner for logging
        temp_dir: Optional job temp directory for index storage

    Returns:
        Tuple of (frame_count, last_frame_timestamp_ms) or None on error
    """
    try:
        import vapoursynth as vs

        runner._log_message(f"[VapourSynth] Indexing video: {Path(video_path).name}")

        # Create new core instance for isolation
        core = vs.core

        # Generate cache path for FFMS2 index
        index_path = _get_ffms2_cache_path(video_path, temp_dir)

        # Show where index is stored
        if temp_dir:
            # Show relative path from job temp dir
            try:
                rel_path = index_path.relative_to(temp_dir)
                location_msg = f"job_temp/{rel_path}"
            except ValueError:
                location_msg = str(index_path)
        else:
            location_msg = str(index_path)

        # Load video - this auto-generates index if not present
        # Try L-SMASH first (more accurate), fall back to FFmpegSource2
        clip = None
        try:
            clip = core.lsmas.LWLibavSource(str(video_path))
            runner._log_message("[VapourSynth] Using LWLibavSource (L-SMASH)")
        except AttributeError:
            # L-SMASH plugin not installed
            runner._log_message(
                "[VapourSynth] L-SMASH plugin not found, using FFmpegSource2"
            )
        except Exception as e:
            runner._log_message(
                f"[VapourSynth] L-SMASH failed: {e}, trying FFmpegSource2"
            )

        if clip is None:
            try:
                # Log whether index already exists
                if index_path.exists():
                    runner._log_message(
                        f"[VapourSynth] Reusing existing index from: {location_msg}"
                    )
                else:
                    runner._log_message(
                        f"[VapourSynth] Creating new index at: {location_msg}"
                    )
                    runner._log_message("[VapourSynth] This may take 1-2 minutes...")

                # Use FFMS2 with custom cache path
                clip = core.ffms2.Source(
                    source=str(video_path), cachefile=str(index_path)
                )
                runner._log_message("[VapourSynth] Using FFmpegSource2")
            except Exception as e:
                runner._log_message(
                    f"[VapourSynth] ERROR: FFmpegSource2 also failed: {e}"
                )
                del core
                gc.collect()
                return None

        # Get frame count
        frame_count = clip.num_frames
        runner._log_message(f"[VapourSynth] Frame count: {frame_count}")

        # Get last frame timestamp
        # VapourSynth uses rational time base, convert to milliseconds
        last_frame_idx = frame_count - 1
        last_frame = clip.get_frame(last_frame_idx)

        # Calculate timestamp from frame properties
        # _DurationNum / _DurationDen gives frame duration in seconds
        fps_num = clip.fps.numerator
        fps_den = clip.fps.denominator

        # Last frame timestamp = (frame_index / fps) * 1000
        last_frame_timestamp_ms = (last_frame_idx * fps_den * 1000.0) / fps_num

        runner._log_message(
            f"[VapourSynth] Last frame (#{last_frame_idx}) timestamp: {last_frame_timestamp_ms:.3f}ms"
        )
        runner._log_message(
            f"[VapourSynth] FPS: {fps_num}/{fps_den} ({fps_num / fps_den:.3f})"
        )

        # CRITICAL: Free memory immediately
        # VapourSynth can hold large amounts of RAM if not freed
        del clip
        del last_frame
        del core
        gc.collect()  # Force garbage collection

        runner._log_message("[VapourSynth] Index loaded, memory freed")

        return (frame_count, last_frame_timestamp_ms)

    except ImportError:
        runner._log_message(
            "[VapourSynth] WARNING: VapourSynth not installed, falling back to ffprobe"
        )
        return None
    except Exception as e:
        runner._log_message(f"[VapourSynth] ERROR: Failed to index video: {e}")
        # Ensure cleanup even on error (variables may not exist if import failed)
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


class VideoReader:
    """
    Efficient video reader that keeps video file open for fast frame access.

    Priority order:
    1. VapourSynth + FFMS2 plugin (fastest - persistent index caching, <1ms per frame, thread-safe)
    2. pyffms2 (fast - indexed seeking, but re-indexes each time)
    3. OpenCV (medium - keeps file open, but seeks from keyframes)
    4. FFmpeg (slow - spawns process per frame)

    Supports automatic deinterlacing for interlaced content with configurable methods:
    - 'auto': Auto-detect and deinterlace only if interlaced
    - 'none': Never deinterlace (raw frames)
    - 'yadif': YADIF deinterlacer (good quality, moderate speed)
    - 'yadifmod': YADIFmod (better edge handling than YADIF)
    - 'bob': Bob deinterlacer (fast, doubles framerate)
    - 'bwdif': BWDIF (motion adaptive, best quality)
    """

    # Available deinterlace methods
    DEINTERLACE_METHODS = ["auto", "none", "yadif", "yadifmod", "bob", "bwdif"]

    def __init__(
        self,
        video_path: str,
        runner,
        temp_dir: Path | None = None,
        deinterlace: str = "auto",
        config: dict | None = None,
        **kwargs,
    ):
        self.video_path = video_path
        self.runner = runner
        self.vs_clip = None  # VapourSynth clip
        self.source = None  # FFMS2 source
        self.cap = None  # OpenCV capture
        self.use_vapoursynth = False
        self.use_ffms2 = False
        self.use_opencv = False
        self.fps = None
        self.temp_dir = temp_dir
        self.deinterlace_method = deinterlace
        self.config = config or {}
        self.is_interlaced = False
        self.field_order = "progressive"
        self.deinterlace_applied = False

        # Detect video properties for interlacing info
        self._detect_interlacing()

        # Try VapourSynth first (fastest - persistent index caching)
        if self._try_vapoursynth():
            return

        # Try FFMS2 second (fast but re-indexes each time)
        try:
            import ffms2

            # Note: The pyffms2 Python bindings don't reliably support loading cached indexes
            # We create the index on-demand each time (still faster than OpenCV fallback)
            runner._log_message("[FrameUtils] Creating FFMS2 index...")
            runner._log_message(
                "[FrameUtils] This may take 1-2 minutes on first access..."
            )

            # Create indexer and generate index
            indexer = ffms2.Indexer(str(video_path))
            index = indexer.do_indexing2()

            # Get first video track
            track_number = index.get_first_indexed_track_of_type(ffms2.FFMS_TYPE_VIDEO)

            # Create video source from index
            self.source = ffms2.VideoSource(str(video_path), track_number, index)
            self.use_ffms2 = True

            # Get video properties
            self.fps = (
                self.source.properties.FPSNumerator
                / self.source.properties.FPSDenominator
            )

            runner._log_message(
                f"[FrameUtils] FFMS2 ready! Using instant frame seeking (FPS: {self.fps:.3f})"
            )
            return

        except ImportError:
            runner._log_message("[FrameUtils] FFMS2 not installed, trying opencv...")
            runner._log_message(
                "[FrameUtils] Install FFMS2 for 100x speedup: pip install ffms2"
            )
        except Exception as e:
            runner._log_message(
                f"[FrameUtils] WARNING: FFMS2 failed ({e}), trying opencv..."
            )

        # Fallback to opencv if FFMS2 unavailable
        try:
            import cv2

            self.cv2 = cv2
            self.cap = cv2.VideoCapture(str(video_path))
            if self.cap.isOpened():
                self.use_opencv = True
                self.fps = self.cap.get(cv2.CAP_PROP_FPS)
                runner._log_message(
                    f"[FrameUtils] Using opencv for frame access (FPS: {self.fps:.3f})"
                )
            else:
                runner._log_message(
                    "[FrameUtils] WARNING: opencv couldn't open video, falling back to ffmpeg"
                )
                self.cap = None
        except ImportError:
            runner._log_message(
                "[FrameUtils] WARNING: opencv not installed, using slower ffmpeg fallback"
            )
            runner._log_message(
                "[FrameUtils] Install opencv for better performance: pip install opencv-python"
            )

    def _detect_interlacing(self):
        """Detect if video is interlaced using ffprobe."""
        try:
            from .video_properties import detect_video_properties

            props = detect_video_properties(self.video_path, self.runner)
            self.is_interlaced = props.get("interlaced", False)
            self.field_order = props.get("field_order", "progressive")

            if self.is_interlaced:
                self.runner._log_message(
                    f"[FrameUtils] Interlaced content detected: {self.field_order.upper()}"
                )
        except Exception as e:
            self.runner._log_message(f"[FrameUtils] Could not detect interlacing: {e}")
            self.is_interlaced = False
            self.field_order = "progressive"

    def _should_deinterlace(self) -> bool:
        """Determine if deinterlacing should be applied."""
        if self.deinterlace_method == "none":
            return False
        if self.deinterlace_method == "auto":
            return self.is_interlaced
        # Explicit method selected - always deinterlace
        return True

    def _get_deinterlace_method(self) -> str:
        """Get the actual deinterlace method to use."""
        if self.deinterlace_method == "auto":
            # Use interlaced deinterlace method setting, default to bwdif
            return self.config.get("interlaced_deinterlace_method", "bwdif")
        return self.deinterlace_method

    def _apply_deinterlace_filter(self, clip, core):
        """
        Apply deinterlace filter to VapourSynth clip.

        Args:
            clip: VapourSynth clip
            core: VapourSynth core

        Returns:
            Deinterlaced clip
        """
        method = self._get_deinterlace_method()
        tff = self.field_order == "tff"  # True = Top Field First

        self.runner._log_message(
            f"[FrameUtils] Applying deinterlace: {method} (field order: {'TFF' if tff else 'BFF'})"
        )

        try:
            if method == "yadif":
                # YADIF - Yet Another DeInterlacing Filter
                # Mode 0 = output one frame per frame (not bob)
                # Order: 1 = TFF, 0 = BFF
                if hasattr(core, "yadifmod"):
                    # Prefer yadifmod if available (better edge handling)
                    clip = core.yadifmod.Yadifmod(clip, order=1 if tff else 0, mode=0)
                elif hasattr(core, "yadif"):
                    clip = core.yadif.Yadif(clip, order=1 if tff else 0, mode=0)
                else:
                    # Fallback to znedi3-based yadif alternative
                    self.runner._log_message(
                        "[FrameUtils] YADIF plugin not found, using std.SeparateFields + DoubleWeave"
                    )
                    clip = self._deinterlace_fallback(clip, core, tff)

            elif method == "yadifmod":
                # YADIFmod - improved edge handling
                if hasattr(core, "yadifmod"):
                    clip = core.yadifmod.Yadifmod(clip, order=1 if tff else 0, mode=0)
                else:
                    self.runner._log_message(
                        "[FrameUtils] YADIFmod not available, falling back to YADIF"
                    )
                    return self._apply_deinterlace_filter_method(
                        clip, core, "yadif", tff
                    )

            elif method == "bob":
                # Bob - doubles framerate by outputting each field as frame
                # Simple and fast, good for frame matching
                clip = core.std.SeparateFields(clip, tff=tff)
                clip = core.resize.Spline36(clip, height=clip.height * 2)

            elif method == "bwdif":
                # BWDIF - motion adaptive deinterlacer
                if hasattr(core, "bwdif"):
                    clip = core.bwdif.Bwdif(clip, field=1 if tff else 0)
                else:
                    self.runner._log_message(
                        "[FrameUtils] BWDIF not available, falling back to YADIF"
                    )
                    return self._apply_deinterlace_filter_method(
                        clip, core, "yadif", tff
                    )

            else:
                self.runner._log_message(
                    f"[FrameUtils] Unknown deinterlace method: {method}, using YADIF"
                )
                return self._apply_deinterlace_filter_method(clip, core, "yadif", tff)

            self.deinterlace_applied = True
            self.runner._log_message(
                "[FrameUtils] Deinterlace filter applied successfully"
            )
            return clip

        except Exception as e:
            self.runner._log_message(
                f"[FrameUtils] Deinterlace failed: {e}, using raw frames"
            )
            return clip

    def _apply_deinterlace_filter_method(self, clip, core, method: str, tff: bool):
        """Helper to apply a specific deinterlace method."""
        self.deinterlace_method = method
        return self._apply_deinterlace_filter(clip, core)

    def _deinterlace_fallback(self, clip, core, tff: bool):
        """Fallback deinterlacing using standard VapourSynth functions."""
        # Separate fields, then weave back
        clip = core.std.SeparateFields(clip, tff=tff)
        clip = core.std.DoubleWeave(clip, tff=tff)
        clip = core.std.SelectEvery(clip, 2, 0)
        return clip

    def _get_index_cache_path(self, video_path: str, temp_dir: Path) -> Path:
        """
        Generate cache path for FFMS2 index in job's temp directory.

        Cache key: parent_dir + filename + size + mtime (unique per file path)
        Location: {job_temp_dir}/ffindex/{cache_key}.ffindex

        The index is created in the job's temp folder so it can be:
        1. Easily identified by filename and source
        2. Reused within the job (multiple tracks using same source)
        3. Cleaned up automatically when job completes
        4. Avoid collisions when different sources have same episode numbers
        """
        import hashlib
        import os

        video_path_obj = Path(video_path)

        # Get file metadata for cache invalidation
        stat = os.stat(video_path)
        file_size = stat.st_size
        mtime = int(stat.st_mtime)

        # Include parent directory to distinguish between sources
        # E.g., "source1/1.mkv" vs "source2/1.mkv" get different indexes
        parent_dir = video_path_obj.parent.name

        # If parent is empty/root, use path hash instead
        if not parent_dir or parent_dir == ".":
            path_hash = hashlib.md5(str(video_path_obj.resolve()).encode()).hexdigest()[
                :8
            ]
            cache_key = f"{video_path_obj.stem}_{path_hash}_{file_size}_{mtime}"
        else:
            cache_key = f"{parent_dir}_{video_path_obj.stem}_{file_size}_{mtime}"

        # ALWAYS use job's temp_dir for index storage (for cleanup)
        if temp_dir:
            cache_dir = temp_dir / "ffindex"
            cache_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Fallback: use system temp (but warn - won't be cleaned up)
            cache_dir = Path(tempfile.gettempdir()) / "vsg_ffindex"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.runner._log_message(
                "[FrameUtils] WARNING: No job temp_dir provided, index won't be auto-cleaned"
            )

        index_path = cache_dir / f"{cache_key}.ffindex"
        return index_path

    def _try_vapoursynth(self) -> bool:
        """
        Try to initialize VapourSynth with FFMS2 plugin for persistent index caching.

        Returns:
            True if successful, False if VapourSynth unavailable or failed
        """
        try:
            import vapoursynth as vs

            self.runner._log_message(
                "[FrameUtils] Attempting VapourSynth with FFMS2 plugin..."
            )

            # Get VapourSynth core instance
            core = vs.core

            # Check if ffms2 plugin is available
            if not hasattr(core, "ffms2"):
                self.runner._log_message(
                    "[FrameUtils] VapourSynth installed but ffms2 plugin missing"
                )
                self.runner._log_message(
                    "[FrameUtils] Install FFMS2 plugin for VapourSynth"
                )
                return False

            # Generate cache path
            index_path = self._get_index_cache_path(self.video_path, self.temp_dir)

            # Show where index is stored
            if self.temp_dir:
                # Show relative path from job temp dir
                try:
                    rel_path = index_path.relative_to(self.temp_dir)
                    location_msg = f"job_temp/{rel_path}"
                except ValueError:
                    location_msg = str(index_path)
            else:
                location_msg = str(index_path)

            # Load video with index caching
            if index_path.exists():
                self.runner._log_message(
                    f"[FrameUtils] Reusing existing index from: {location_msg}"
                )
            else:
                self.runner._log_message(
                    f"[FrameUtils] Creating new index at: {location_msg}"
                )
                self.runner._log_message("[FrameUtils] This may take 1-2 minutes...")

            clip = core.ffms2.Source(
                source=str(self.video_path), cachefile=str(index_path)
            )

            # Apply deinterlacing if needed
            if self._should_deinterlace():
                clip = self._apply_deinterlace_filter(clip, core)

            # Keep clip in original format (usually YUV)
            # We'll extract only luma (Y) plane for hashing - more reliable than RGB
            self.vs_clip = clip

            # Get video properties
            self.fps = self.vs_clip.fps_num / self.vs_clip.fps_den
            self.use_vapoursynth = True

            deinterlace_status = ""
            if self.deinterlace_applied:
                deinterlace_status = (
                    f", deinterlaced with {self._get_deinterlace_method()}"
                )
            elif self.is_interlaced and self.deinterlace_method == "none":
                deinterlace_status = ", interlaced (deinterlace disabled)"

            self.runner._log_message(
                f"[FrameUtils] VapourSynth ready! Using persistent index cache (FPS: {self.fps:.3f}{deinterlace_status})"
            )
            self.runner._log_message(
                "[FrameUtils] Index will be shared across all workers (no re-indexing!)"
            )

            return True

        except ImportError:
            self.runner._log_message(
                "[FrameUtils] VapourSynth not installed, trying pyffms2..."
            )
            self.runner._log_message(
                "[FrameUtils] Install VapourSynth for persistent index caching: pip install VapourSynth"
            )
            return False
        except AttributeError as e:
            self.runner._log_message(
                f"[FrameUtils] VapourSynth ffms2 plugin not found: {e}"
            )
            self.runner._log_message(
                "[FrameUtils] Install FFMS2 plugin for VapourSynth"
            )
            return False
        except Exception as e:
            self.runner._log_message(
                f"[FrameUtils] VapourSynth initialization failed: {e}"
            )
            return False

    def get_frame_at_time(self, time_ms: int) -> Image.Image | None:
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

    def get_frame_pts(self, frame_num: int) -> float | None:
        """
        Get the Presentation Time Stamp (PTS) of a frame in milliseconds.

        For VFR (variable frame rate) content, this returns the actual container
        timestamp. For CFR content, it calculates from frame index × frame duration.

        This is essential for sub-frame accurate timing - once we identify which
        frames match between source and target, we use their actual PTS values
        to calculate the precise offset.

        Args:
            frame_num: Frame index (0-based)

        Returns:
            PTS in milliseconds, or None if unavailable
        """
        if self.use_vapoursynth and self.vs_clip:
            return self._get_pts_vapoursynth(frame_num)
        elif self.use_ffms2 and self.source:
            return self._get_pts_ffms2(frame_num)
        elif self.fps:
            # Fallback: calculate from frame index (CFR assumption)
            return (frame_num * 1000.0) / self.fps
        return None

    def _get_pts_vapoursynth(self, frame_num: int) -> float | None:
        """Get PTS using VapourSynth frame properties."""
        try:
            # Clamp to valid range
            frame_num = max(0, min(frame_num, len(self.vs_clip) - 1))

            # Get frame to access properties
            frame = self.vs_clip.get_frame(frame_num)

            # Try VFR timestamp first (_AbsoluteTime in seconds)
            props = frame.props
            if "_AbsoluteTime" in props:
                return props["_AbsoluteTime"] * 1000.0

            # Fall back to CFR calculation
            fps_num = self.vs_clip.fps_num
            fps_den = self.vs_clip.fps_den
            return (frame_num * fps_den * 1000.0) / fps_num

        except Exception as e:
            self.runner._log_message(f"[FrameUtils] Error getting VapourSynth PTS: {e}")
            # Fallback to CFR calculation
            if self.fps:
                return (frame_num * 1000.0) / self.fps
            return None

    def _get_pts_ffms2(self, frame_num: int) -> float | None:
        """Get PTS using FFMS2 track info."""
        try:
            # Clamp to valid range
            frame_num = max(0, min(frame_num, self.source.properties.NumFrames - 1))

            # FFMS2 provides frame info with PTS
            # Get track for timestamp information
            track = self.source.track
            frame_info = track.frame_info_list[frame_num]

            # PTS is in track timebase units, convert to milliseconds
            # frame_info.pts is in track.time_base units
            time_base = track.time_base
            pts_seconds = frame_info.pts * time_base.numerator / time_base.denominator
            return pts_seconds * 1000.0

        except Exception as e:
            self.runner._log_message(f"[FrameUtils] Error getting FFMS2 PTS: {e}")
            # Fallback to CFR calculation
            if self.fps:
                return (frame_num * 1000.0) / self.fps
            return None

    def get_frame_count(self) -> int:
        """Get total frame count of the video."""
        if self.use_vapoursynth and self.vs_clip:
            return len(self.vs_clip)
        elif self.use_ffms2 and self.source:
            return self.source.properties.NumFrames
        elif self.use_opencv and self.cap:
            return int(self.cap.get(self.cv2.CAP_PROP_FRAME_COUNT))
        return 0

    def get_frame_at_index(self, frame_num: int) -> Image.Image | None:
        """
        Extract frame by frame number directly (avoids time-to-frame conversion precision issues).

        This method bypasses the floating-point time conversion that can cause 1-frame
        offsets with NTSC framerates (23.976fps, 29.97fps) where int(time * fps) may
        truncate incorrectly (e.g., 1000.9999 -> 1000 instead of 1001).

        Args:
            frame_num: Frame index (0-based)

        Returns:
            PIL Image object, or None on failure
        """
        if self.use_vapoursynth and self.vs_clip:
            return self._get_frame_vapoursynth_by_index(frame_num)
        elif self.use_ffms2 and self.source:
            return self._get_frame_ffms2_by_index(frame_num)
        elif self.use_opencv and self.cap:
            # OpenCV doesn't have reliable frame-accurate seeking by index
            # Fall back to time-based seeking with best effort
            time_ms = int(frame_num * 1000.0 / self.fps) if self.fps else 0
            return self._get_frame_opencv(time_ms)
        else:
            # FFmpeg fallback - use time-based
            time_ms = int(frame_num * 1000.0 / self.fps) if self.fps else 0
            return self._get_frame_ffmpeg(time_ms)

    def _get_frame_vapoursynth_by_index(self, frame_num: int) -> Image.Image | None:
        """Extract frame by index using VapourSynth (frame-accurate)."""
        try:
            import numpy as np
            from PIL import Image

            # Clamp to valid range
            frame_num = max(0, min(frame_num, len(self.vs_clip) - 1))

            # Get frame directly by index (no time conversion!)
            frame = self.vs_clip.get_frame(frame_num)

            # Extract Y (luma) plane as grayscale
            y_plane = np.asarray(frame[0])

            # Normalize bit depth to 8-bit for PIL
            # VapourSynth can provide 8-bit, 10-bit, 12-bit, or 16-bit data
            if y_plane.dtype == np.uint16:
                # For 10-bit (0-1023) or 16-bit (0-65535), normalize to 8-bit (0-255)
                # Most anime is 10-bit, so values are in 0-1023 range
                # Right-shift by (bit_depth - 8) to normalize
                # For 10-bit: shift right by 2 (divide by 4)
                # For 16-bit: shift right by 8 (divide by 256)
                max_val = y_plane.max()
                if max_val <= 1023:  # 10-bit
                    y_plane = (y_plane >> 2).astype(np.uint8)
                else:  # 12-bit or 16-bit
                    y_plane = (y_plane >> 8).astype(np.uint8)
            elif y_plane.dtype != np.uint8:
                # Ensure we have uint8
                y_plane = y_plane.astype(np.uint8)

            return Image.fromarray(y_plane, "L")

        except Exception as e:
            self.runner._log_message(
                f"[FrameUtils] ERROR: VapourSynth frame extraction by index failed: {e}"
            )
            return None

    def _get_frame_ffms2_by_index(self, frame_num: int) -> Image.Image | None:
        """Extract frame by index using FFMS2 (frame-accurate)."""
        try:
            import numpy as np
            from PIL import Image

            # Clamp to valid range
            frame_num = max(0, min(frame_num, self.source.properties.NumFrames - 1))

            # Get frame directly by index (no time conversion!)
            frame = self.source.get_frame(frame_num)

            # Convert to PIL Image
            # FFMS2 typically returns Y plane as first plane for grayscale, or RGB
            frame_array = frame.planes[0]

            # Normalize bit depth to 8-bit for PIL if needed
            if frame_array.dtype == np.uint16:
                max_val = frame_array.max()
                if max_val <= 1023:  # 10-bit
                    frame_array = (frame_array >> 2).astype(np.uint8)
                else:  # 12-bit or 16-bit
                    frame_array = (frame_array >> 8).astype(np.uint8)
            elif frame_array.dtype != np.uint8:
                frame_array = frame_array.astype(np.uint8)

            return Image.fromarray(frame_array)

        except Exception as e:
            self.runner._log_message(
                f"[FrameUtils] ERROR: FFMS2 frame extraction by index failed: {e}"
            )
            return None

    def _get_frame_vapoursynth(self, time_ms: int) -> Image.Image | None:
        """
        Extract frame using VapourSynth (instant indexed seeking with persistent cache).

        Extracts only the luma (Y) plane as grayscale for better perceptual hashing.
        Luma contains most of the perceptual information and avoids color conversion artifacts.
        """
        try:
            import numpy as np
            from PIL import Image

            # Convert time to frame number
            frame_num = int((time_ms / 1000.0) * self.fps)

            # Clamp to valid range
            frame_num = max(0, min(frame_num, len(self.vs_clip) - 1))

            # Get frame (instant - uses FFMS2 index!)
            frame = self.vs_clip.get_frame(frame_num)

            # VapourSynth frames support the array protocol
            # frame[0] is the Y (luma) plane, np.asarray handles stride automatically
            y_plane = np.asarray(frame[0])

            # Normalize bit depth to 8-bit for PIL
            # VapourSynth can provide 8-bit, 10-bit, 12-bit, or 16-bit data
            if y_plane.dtype == np.uint16:
                # For 10-bit (0-1023) or 16-bit (0-65535), normalize to 8-bit (0-255)
                # Most anime is 10-bit, so values are in 0-1023 range
                # Right-shift by (bit_depth - 8) to normalize
                # For 10-bit: shift right by 2 (divide by 4)
                # For 16-bit: shift right by 8 (divide by 256)
                max_val = y_plane.max()
                if max_val <= 1023:  # 10-bit
                    y_plane = (y_plane >> 2).astype(np.uint8)
                else:  # 12-bit or 16-bit
                    y_plane = (y_plane >> 8).astype(np.uint8)
            elif y_plane.dtype != np.uint8:
                # Ensure we have uint8
                y_plane = y_plane.astype(np.uint8)

            # Convert to PIL Image (grayscale mode 'L')
            return Image.fromarray(y_plane, "L")

        except Exception as e:
            self.runner._log_message(
                f"[FrameUtils] ERROR: VapourSynth frame extraction failed: {e}"
            )
            return None

    def _get_frame_ffms2(self, time_ms: int) -> Image.Image | None:
        """Extract frame using FFMS2 (instant indexed seeking)."""
        try:
            import numpy as np
            from PIL import Image

            # Convert time to frame number
            frame_num = int((time_ms / 1000.0) * self.fps)

            # Clamp to valid range
            frame_num = max(0, min(frame_num, self.source.properties.NumFrames - 1))

            # Get frame (instant - uses index!)
            frame = self.source.get_frame(frame_num)

            # Convert to PIL Image
            # FFMS2 returns frames as numpy arrays in RGB format
            frame_array = frame.planes[0]  # Get RGB data

            # Normalize bit depth to 8-bit for PIL if needed
            if frame_array.dtype == np.uint16:
                max_val = frame_array.max()
                if max_val <= 1023:  # 10-bit
                    frame_array = (frame_array >> 2).astype(np.uint8)
                else:  # 12-bit or 16-bit
                    frame_array = (frame_array >> 8).astype(np.uint8)
            elif frame_array.dtype != np.uint8:
                frame_array = frame_array.astype(np.uint8)

            # Create PIL Image from numpy array
            return Image.fromarray(frame_array)

        except Exception as e:
            self.runner._log_message(
                f"[FrameUtils] ERROR: FFMS2 frame extraction failed: {e}"
            )
            return None

    def _get_frame_opencv(self, time_ms: int) -> Image.Image | None:
        """Extract frame using opencv (fast)."""
        try:
            from PIL import Image

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
            self.runner._log_message(
                f"[FrameUtils] ERROR: opencv frame extraction failed: {e}"
            )
            return None

    def _get_frame_ffmpeg(self, time_ms: int) -> Image.Image | None:
        """Extract frame using ffmpeg (slow fallback)."""
        import os
        import subprocess

        from PIL import Image

        tmp_path = None
        try:
            time_sec = time_ms / 1000.0

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name

            cmd = [
                "ffmpeg",
                "-ss",
                f"{time_sec:.3f}",
                "-i",
                str(self.video_path),
                "-vframes",
                "1",
                "-q:v",
                "2",
                "-y",
                tmp_path,
            ]

            # Import GPU environment support
            try:
                from vsg_core.system.gpu_env import get_subprocess_environment

                env = get_subprocess_environment()
            except ImportError:
                env = os.environ.copy()

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, env=env
            )

            if result.returncode != 0:
                return None

            frame = Image.open(tmp_path)
            frame.load()

            return frame

        except Exception:
            return None
        finally:
            # Always clean up temp file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

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

        # Force garbage collection to release nanobind objects
        gc.collect()
