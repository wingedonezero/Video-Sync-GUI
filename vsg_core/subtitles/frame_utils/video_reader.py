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

    from vsg_core.models import AppSettings


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
        settings: AppSettings | None = None,
        content_type: str | None = None,
        ivtc_field_order: str | None = None,
        apply_ivtc: bool = False,
        apply_decimate: bool = False,
        skip_decimate_in_ivtc: bool = False,
        use_vapoursynth: bool = True,
    ):
        self.video_path = video_path
        self.runner = runner
        self.vs_clip = None  # VapourSynth clip
        self.source = None  # FFMS2 source
        self.cap = None  # OpenCV capture
        self._use_vapoursynth_requested = use_vapoursynth
        self.use_vapoursynth = False
        self.use_ffms2 = False
        self.use_opencv = False
        self.fps = None
        self.original_fps = None  # FPS before IVTC/decimate (if applied)
        self.temp_dir = temp_dir
        self.deinterlace_method = deinterlace
        self.settings = settings
        self.is_interlaced = False
        self.field_order = "progressive"
        self.deinterlace_applied = False
        self.content_type = content_type  # 'progressive', 'interlaced', 'telecine'
        # Optional field-order override from content analysis (idet/repeat_pict).
        # This is critical when container metadata reports "progressive" for
        # hard-telecined MPEG-2, where IVTC still needs a stable field order.
        self.ivtc_field_order = ivtc_field_order
        self.apply_ivtc = apply_ivtc  # Whether to apply IVTC for telecine content
        self.apply_decimate = apply_decimate  # Whether to apply VDecimate only (no VFM)
        self.skip_decimate_in_ivtc = skip_decimate_in_ivtc  # VFM only, no VDecimate
        self.ivtc_applied = False  # Whether full IVTC (VFM+VDecimate) was applied
        self.vfm_applied = False  # Whether VFM-only was applied (no VDecimate)
        self.decimate_applied = False  # Whether VDecimate-only was applied
        self.is_vfr = False  # True if VFR container detected
        self.is_soft_telecine = False  # True if VFR from soft-telecine removal
        self.target_fps = None  # Target FPS after normalization (for soft-telecine)
        self.fps_normalized = False  # Whether AssumeFPS was applied
        self.real_fps: float | None = None  # Actual FFMS2 fps before AssumeFPS

        # Detect video properties for interlacing info
        self._detect_interlacing()

        # Try VapourSynth first (fastest - persistent index caching)
        if self._use_vapoursynth_requested and self._try_vapoursynth():
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
        """Detect if video is interlaced and check for VFR/soft-telecine."""
        try:
            from .video_properties import detect_video_properties

            props = detect_video_properties(self.video_path, self.runner)
            self.is_interlaced = props.get("interlaced", False)
            self.field_order = props.get("field_order", "progressive")

            # Capture VFR and soft-telecine info
            self.is_vfr = props.get("is_vfr", False)
            self.is_soft_telecine = props.get("is_soft_telecine", False)

            if self.is_soft_telecine:
                # Store the original (correct) FPS for normalization
                self.target_fps = props.get("original_fps", 23.976)
                self.runner._log_message(
                    f"[FrameUtils] Soft-telecine detected: container={props.get('fps', 0):.3f}fps, "
                    f"original={self.target_fps:.3f}fps"
                )
                self.runner._log_message(
                    "[FrameUtils] Will apply AssumeFPS to normalize timing"
                )
            elif self.is_interlaced:
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
            if self.settings is not None:
                return self.settings.interlaced_deinterlace_method
            return "bwdif"
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

        # Use ivtc_field_order (from ContentAnalysis/idet) when available,
        # falling back to self.field_order (from ffprobe metadata).
        # This is critical when container says "progressive" but content is
        # actually interlaced (common with MPEG-2 telecine DVDs).
        field_order = self.field_order
        if self.ivtc_field_order in ("tff", "bff"):
            field_order = self.ivtc_field_order
        elif field_order not in ("tff", "bff"):
            # Safe default when no field order info available
            field_order = "tff"

        tff = field_order == "tff"

        self.runner._log_message(
            f"[FrameUtils] Applying deinterlace: {method} (field order: {'TFF' if tff else 'BFF'})"
        )

        try:
            # Force the correct field order on the clip via _FieldBased frame property.
            # Bwdif/Yadif read _FieldBased from each frame and OVERRIDE the field/order
            # parameter when it is set. FFMS2 sets _FieldBased per-frame based on
            # FFmpeg's AV_FRAME_FLAG_INTERLACED, which is often wrong or inconsistent
            # for MPEG-2 DVD content. Without this, two encodes of the same content
            # can get different _FieldBased values from FFMS2, causing bwdif to
            # deinterlace them with different field orders → completely different
            # progressive output → frame comparison fails (avg_dist 40+).
            clip = core.std.SetFieldBased(clip, 2 if tff else 1)
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

    def _should_apply_ivtc(self) -> bool:
        """Determine if IVTC should be applied to this video."""
        # Must be explicitly enabled
        if not self.apply_ivtc:
            return False

        # Content type must be telecine (either detected or passed in)
        if self.content_type in ("telecine", "telecine_hard", "mixed"):
            return True

        # Also check if detected as interlaced NTSC DVD (likely telecine)
        # This handles cases where content_type wasn't passed but we detected it
        return bool(self.is_interlaced and self.fps and abs(self.fps - 29.97) < 0.1)

    def _apply_ivtc_filter(self, clip, core):
        """
        Apply Inverse Telecine (IVTC) to recover progressive frames from telecine.

        Uses VIVTC (VFM + VDecimate) to:
        1. VFM: Field match to find original progressive frames
        2. VDecimate: Remove duplicate frames (30fps -> 24fps)

        This converts 29.97i telecine content back to ~23.976p progressive.

        Args:
            clip: VapourSynth clip (interlaced telecine)
            core: VapourSynth core

        Returns:
            Progressive clip at ~23.976fps
        """
        field_order_for_ivtc = self.field_order
        if self.ivtc_field_order in ("tff", "bff"):
            field_order_for_ivtc = self.ivtc_field_order
        elif field_order_for_ivtc not in ("tff", "bff"):
            # Safe default for NTSC DVD telecine when metadata has no field order.
            field_order_for_ivtc = "tff"

        tff = field_order_for_ivtc == "tff"

        self.runner._log_message(
            f"[FrameUtils] Applying IVTC (field order: {'TFF' if tff else 'BFF'})"
        )

        # Store original FPS before IVTC
        self.original_fps = clip.fps_num / clip.fps_den

        # Normalize telecine timebase before IVTC when FFMS2 exposes odd VFR-ish
        # rates (e.g. 29.778). This stabilizes VDecimate output cadence.
        if (
            29.0 < self.original_fps < 31.0
            and abs(self.original_fps - 30000 / 1001) > 0.01
        ):
            clip = core.std.AssumeFPS(clip, fpsnum=30000, fpsden=1001)
            self.runner._log_message(
                f"[FrameUtils] Normalized pre-IVTC FPS ({self.original_fps:.3f} -> 29.970)"
            )

        try:
            # Force correct field order in frame properties (same reason as
            # _apply_deinterlace_filter — FFMS2's per-frame _FieldBased can be
            # wrong for MPEG-2, and VFM reads it to override the order param).
            clip = core.std.SetFieldBased(clip, 2 if tff else 1)

            # Check if VIVTC is available
            if hasattr(core, "vivtc"):
                # VFM: Field matching - recovers progressive frames
                # order: 1 = TFF, 0 = BFF
                clip = core.vivtc.VFM(clip, order=1 if tff else 0)

                if self.skip_decimate_in_ivtc:
                    # VFM-only: progressive frames with preserved frame indices.
                    # Skipping VDecimate keeps all 30fps frames so that frame
                    # indices stay 1:1 across different encodes (VDecimate makes
                    # different drop decisions per encode, destroying alignment).
                    self.vfm_applied = True
                    self.runner._log_message(
                        f"[FrameUtils] VFM-only applied with VIVTC "
                        f"({self.original_fps:.3f}fps, VDecimate skipped)"
                    )
                    return clip

                # VDecimate: Remove duplicates (5 frames -> 4 frames)
                # This converts 29.97fps -> 23.976fps
                clip = core.vivtc.VDecimate(clip)

                # Force canonical film rate after IVTC for stable downstream
                # frame-index math across DVD telecine sources.
                clip = core.std.AssumeFPS(clip, fpsnum=24000, fpsden=1001)

                self.ivtc_applied = True
                self.runner._log_message(
                    f"[FrameUtils] IVTC applied with VIVTC "
                    f"({self.original_fps:.3f}fps -> {clip.fps_num / clip.fps_den:.3f}fps)"
                )
                return clip

            # Fallback: Try TIVTC if VIVTC not available
            elif hasattr(core, "tivtc"):
                # TFM: Field matching
                clip = core.tivtc.TFM(clip, order=1 if tff else 0)

                if self.skip_decimate_in_ivtc:
                    self.vfm_applied = True
                    self.runner._log_message(
                        f"[FrameUtils] VFM-only applied with TIVTC "
                        f"({self.original_fps:.3f}fps, TDecimate skipped)"
                    )
                    return clip

                # TDecimate: Decimation
                clip = core.tivtc.TDecimate(clip, mode=1)

                # Force canonical film rate after IVTC for stable downstream
                # frame-index math across DVD telecine sources.
                clip = core.std.AssumeFPS(clip, fpsnum=24000, fpsden=1001)

                self.ivtc_applied = True
                self.runner._log_message(
                    f"[FrameUtils] IVTC applied with TIVTC "
                    f"({self.original_fps:.3f}fps -> {clip.fps_num / clip.fps_den:.3f}fps)"
                )
                return clip

            else:
                self.runner._log_message(
                    "[FrameUtils] WARNING: No IVTC plugin available (vivtc or tivtc)"
                )
                self.runner._log_message(
                    "[FrameUtils] Install vivtc plugin for VapourSynth"
                )
                self.runner._log_message(
                    "[FrameUtils] Falling back to deinterlacing (may cause frame count mismatch)"
                )
                # Fall back to regular deinterlacing
                return self._apply_deinterlace_filter(clip, core)

        except Exception as e:
            self.runner._log_message(f"[FrameUtils] IVTC failed: {e}")
            self.runner._log_message("[FrameUtils] Falling back to deinterlacing")
            return self._apply_deinterlace_filter(clip, core)

    def _apply_decimate_filter(self, clip, core):
        """
        Apply VDecimate only (no VFM) for progressive content with duplicate frames.

        For progressive content with 2:3 pulldown (soft telecine), the frames are
        already progressive but contain duplicates from the pulldown pattern.
        VDecimate detects and removes these duplicates, converting ~30fps to ~24fps.

        Unlike full IVTC (VFM + VDecimate), this skips field matching since
        the content is already progressive.

        Args:
            clip: VapourSynth clip (progressive with duplicate frames)
            core: VapourSynth core

        Returns:
            Decimated clip at ~23.976fps
        """
        self.original_fps = clip.fps_num / clip.fps_den

        self.runner._log_message(
            f"[FrameUtils] Applying VDecimate for progressive-with-pulldown "
            f"({self.original_fps:.3f}fps)"
        )

        try:
            if hasattr(core, "vivtc"):
                clip = core.vivtc.VDecimate(clip)
                self.decimate_applied = True
                new_fps = clip.fps_num / clip.fps_den
                self.runner._log_message(
                    f"[FrameUtils] VDecimate applied "
                    f"({self.original_fps:.3f}fps -> {new_fps:.3f}fps)"
                )
                return clip

            elif hasattr(core, "tivtc"):
                clip = core.tivtc.TDecimate(clip, mode=1)
                self.decimate_applied = True
                new_fps = clip.fps_num / clip.fps_den
                self.runner._log_message(
                    f"[FrameUtils] TDecimate applied "
                    f"({self.original_fps:.3f}fps -> {new_fps:.3f}fps)"
                )
                return clip

            else:
                self.runner._log_message(
                    "[FrameUtils] WARNING: No decimation plugin available (vivtc or tivtc)"
                )
                self.runner._log_message(
                    "[FrameUtils] Duplicate frames will remain (~30fps instead of ~24fps)"
                )
                return clip

        except Exception as e:
            self.runner._log_message(f"[FrameUtils] Decimation failed: {e}")
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

            # Get the actual FPS from FFMS2 (based on frame timestamps)
            ffms2_fps = clip.fps_num / clip.fps_den
            # Store the real FPS before any AssumeFPS normalization.
            # This is needed for time→frame index calculation: AssumeFPS only
            # changes the fps label, not the number of frames. So frame N is
            # still at position N/real_fps in the video, not N/assumed_fps.
            self.real_fps = ffms2_fps
            self.runner._log_message(
                f"[FrameUtils] FFMS2 raw: {clip.fps_num}/{clip.fps_den} = {ffms2_fps:.6f}fps, "
                f"{clip.num_frames} frames"
            )

            # Detect soft-telecine: ffprobe says ~30fps but FFMS2 sees ~24fps
            # This happens when MakeMKV/mkvmerge removes soft-telecine pulldown
            # ffprobe reads container metadata (30fps), FFMS2 reads actual timestamps (~24fps)
            from .video_properties import detect_video_properties

            props = detect_video_properties(self.video_path, self.runner)
            ffprobe_fps = props.get("fps", 29.97)

            # Check for soft-telecine mismatch: ffprobe ~30fps, FFMS2 ~24fps
            fps_mismatch = (
                abs(ffprobe_fps - ffms2_fps) / ffprobe_fps * 100
                if ffprobe_fps > 0
                else 0
            )
            is_soft_telecine_mismatch = (
                fps_mismatch > 15  # More than 15% difference
                and abs(ffprobe_fps - 29.97) < 0.5  # ffprobe says ~30fps
                and 23.5 < ffms2_fps < 25.0  # FFMS2 sees ~24fps
            )

            if is_soft_telecine_mismatch:
                self.is_soft_telecine = True
                # Don't modify the clip - just override fps for calculations
                # The actual film content is 23.976fps, FFMS2's VFR timestamps are just display hints
                # Frame indices are still correct (sequential film frames)
                self.target_fps = 24000 / 1001  # 23.976fps - the actual film fps
                self.runner._log_message(
                    f"[FrameUtils] Soft-telecine detected: ffprobe={ffprobe_fps:.3f}fps, "
                    f"FFMS2={ffms2_fps:.3f}fps"
                )
                self.runner._log_message(
                    "[FrameUtils] Will use 23.976fps for calculations (actual film rate)"
                )

            # Normalize VFR-ish ~30fps to canonical 30000/1001 for consistent
            # frame-index math. FFMS2 can report slightly off rates (e.g. 29.778)
            # for MPEG-2 with VFR timing hints or mislabeled progressive content.
            clip_fps = clip.fps_num / clip.fps_den
            if 29.0 < clip_fps < 31.0 and abs(clip_fps - 30000 / 1001) > 0.01:
                clip = core.std.AssumeFPS(clip, fpsnum=30000, fpsden=1001)
                self.runner._log_message(
                    f"[FrameUtils] Normalized FPS ({clip_fps:.3f} -> 29.970)"
                )

            # Log final clip state before processing
            final_clip_fps = clip.fps_num / clip.fps_den
            self.runner._log_message(
                f"[FrameUtils] Pre-process state: clip_fps={final_clip_fps:.3f}, "
                f"is_soft_telecine={self.is_soft_telecine}, "
                f"target_fps={self.target_fps}, "
                f"deinterlace={self.deinterlace_method}, "
                f"content_type={self.content_type}"
            )

            # Apply IVTC or deinterlacing based on content type
            # Priority: IVTC for telecine > deinterlace for interlaced
            #         > decimate for progressive-with-pulldown > passthrough
            if self._should_apply_ivtc():
                # Telecine content: apply IVTC to recover progressive frames
                clip = self._apply_ivtc_filter(clip, core)
            elif self._should_deinterlace():
                # Pure interlaced content: apply deinterlacing
                clip = self._apply_deinterlace_filter(clip, core)
            elif self.apply_decimate and not self.is_soft_telecine:
                # Progressive content with duplicate frames (2:3 pulldown)
                # Skip when is_soft_telecine: pulldown already removed by container,
                # FFMS2 delivers real ~24fps frames — VDecimate would destroy content.
                clip = self._apply_decimate_filter(clip, core)
            elif self.apply_decimate and self.is_soft_telecine:
                self.runner._log_message(
                    "[FrameUtils] Skipping VDecimate: soft-telecine pulldown already "
                    "removed by container (FFMS2 sees actual film frames)"
                )

            # Keep clip in original format (usually YUV)
            # We'll extract only luma (Y) plane for hashing - more reliable than RGB
            self.vs_clip = clip

            # Get video properties
            # For soft-telecine, use the actual film fps (23.976) instead of VFR average
            if self.is_soft_telecine and self.target_fps:
                self.fps = self.target_fps  # Use 23.976fps for calculations
            else:
                self.fps = self.vs_clip.fps_num / self.vs_clip.fps_den
            self.use_vapoursynth = True

            # Build status message
            processing_status = ""
            if self.is_soft_telecine:
                processing_status = (
                    f", soft-telecine (using {self.fps:.3f}fps for calc)"
                )
            if self.vfm_applied:
                processing_status += (
                    f", VFM-only ({self.original_fps:.3f}fps, no VDecimate)"
                )
            elif self.ivtc_applied:
                processing_status += (
                    f", IVTC applied ({self.original_fps:.3f} -> {self.fps:.3f}fps)"
                )
            elif self.decimate_applied:
                processing_status += f", VDecimate applied ({self.original_fps:.3f} -> {self.fps:.3f}fps)"
            elif self.deinterlace_applied:
                processing_status += (
                    f", deinterlaced with {self._get_deinterlace_method()}"
                )
            elif self.is_interlaced and self.deinterlace_method == "none":
                processing_status += ", interlaced (deinterlace disabled)"

            self.runner._log_message(
                f"[FrameUtils] VapourSynth ready! Using persistent index cache (FPS: {self.fps:.3f}{processing_status})"
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

    def get_frame_index_for_time(self, time_ms: float) -> int | None:
        """
        Find the frame index closest to a given timestamp using FFMS2 _AbsoluteTime.

        Unlike simple ``int(time_ms / frame_duration)`` which assumes CFR, this
        method reads actual per-frame timestamps from FFMS2 and binary-searches
        them. This is critical for VFR content (e.g., MPEG-2 DVDs remuxed to
        MKV where mkvmerge introduces variable frame durations).

        A sparse timestamp table is built on first call (every 50 frames),
        then refined with a local linear scan for sub-50-frame accuracy.

        Falls back to CFR calculation if VapourSynth/_AbsoluteTime is not
        available.

        Args:
            time_ms: Target time in milliseconds

        Returns:
            Frame index (0-based), or None on failure
        """
        import bisect

        if not (self.use_vapoursynth and self.vs_clip):
            # No VapourSynth → fall back to CFR math
            if self.fps:
                real = getattr(self, "real_fps", None) or self.fps
                return int(time_ms / (1000.0 / real))
            return None

        # Build sparse timestamp table on first call
        if not hasattr(self, "_ts_table"):
            self._build_timestamp_table()

        if not self._ts_table:
            # Fallback: CFR
            if self.fps:
                real = getattr(self, "real_fps", None) or self.fps
                return int(time_ms / (1000.0 / real))
            return None

        target_s = time_ms / 1000.0
        sparse_times = self._ts_table_times  # seconds
        sparse_indices = self._ts_table_indices

        # Binary search in sparse table
        pos = bisect.bisect_left(sparse_times, target_s)

        # Get the bracketing sparse indices
        if pos >= len(sparse_times):
            start_frame = sparse_indices[-1]
        elif pos == 0:
            start_frame = sparse_indices[0]
        # Pick the closer bracket
        elif abs(sparse_times[pos] - target_s) < abs(
            sparse_times[pos - 1] - target_s
        ):
            start_frame = sparse_indices[pos]
        else:
            start_frame = sparse_indices[pos - 1]

        # Local linear scan: refine within ±step frames of the sparse match
        step = self._ts_table_step
        num_frames = len(self.vs_clip)
        lo = max(0, start_frame - step)
        hi = min(num_frames - 1, start_frame + step)

        best_frame = start_frame
        best_diff = float("inf")

        for i in range(lo, hi + 1):
            try:
                props = self.vs_clip.get_frame(i).props
                t = props.get("_AbsoluteTime", None)
                if t is None:
                    continue
                diff = abs(t - target_s)
                if diff < best_diff:
                    best_diff = diff
                    best_frame = i
                    if diff < 0.001:  # Within 1ms — good enough
                        break
                elif t > target_s + 0.1:
                    # Past the target, stop scanning forward
                    break
            except Exception:
                continue

        return best_frame

    def _build_timestamp_table(self) -> None:
        """Build a sparse _AbsoluteTime → frame_index lookup table."""
        self._ts_table: list[tuple[int, float]] = []
        self._ts_table_times: list[float] = []
        self._ts_table_indices: list[int] = []
        self._ts_table_step = 50  # Sample every 50 frames

        if not (self.use_vapoursynth and self.vs_clip):
            return

        num_frames = len(self.vs_clip)
        step = self._ts_table_step

        # Check if timestamps are actually variable by sampling a few points
        # If CFR, skip building the full table (waste of time)
        test_indices = [0, num_frames // 4, num_frames // 2, 3 * num_frames // 4]
        is_vfr = False
        for idx in test_indices:
            if idx >= num_frames:
                continue
            try:
                props = self.vs_clip.get_frame(idx).props
                actual_t = props.get("_AbsoluteTime", None)
                if actual_t is None:
                    # No _AbsoluteTime available — not VFR-aware
                    self.runner._log_message(
                        "[FrameUtils] No _AbsoluteTime in frame props — using CFR math"
                    )
                    return
                real = getattr(self, "real_fps", None) or self.fps or 29.970
                expected_t = idx / real
                if abs(actual_t - expected_t) > 0.5:  # >500ms drift = definitely VFR
                    is_vfr = True
            except Exception:
                pass

        if not is_vfr:
            self.runner._log_message(
                "[FrameUtils] Timestamps are CFR-linear — skipping timestamp table"
            )
            return

        self.runner._log_message(
            f"[FrameUtils] Building timestamp table for VFR content ({num_frames} frames, step={step})..."
        )

        for i in range(0, num_frames, step):
            try:
                props = self.vs_clip.get_frame(i).props
                t = props.get("_AbsoluteTime", None)
                if t is not None:
                    self._ts_table.append((i, t))
                    self._ts_table_times.append(t)
                    self._ts_table_indices.append(i)
            except Exception:
                pass

        # Always include the last frame
        if num_frames - 1 not in self._ts_table_indices:
            try:
                props = self.vs_clip.get_frame(num_frames - 1).props
                t = props.get("_AbsoluteTime", None)
                if t is not None:
                    self._ts_table.append((num_frames - 1, t))
                    self._ts_table_times.append(t)
                    self._ts_table_indices.append(num_frames - 1)
            except Exception:
                pass

        self.runner._log_message(
            f"[FrameUtils] Timestamp table built: {len(self._ts_table)} entries"
        )

    def get_frame_pts(self, frame_num: int) -> float | None:
        """
        Get the Presentation Time Stamp (PTS) of a frame in milliseconds.

        For VFR (variable frame rate) content, this returns the actual container
        timestamp. For CFR content, it calculates from frame index x frame duration.

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
