# vsg_core/subtitles/frame_utils/__init__.py
"""
Shared frame timing and video utility functions for subtitle synchronization.

This package has been modularized for better maintainability:
- timing.py: Frame/time conversion functions (CFR and VFR support)
- video_properties.py: Video property detection (FPS, interlacing, resolution)
- scene_detection.py: Scene detection using PySceneDetect
- video_reader.py: Multi-backend video reader (VapourSynth, FFMS2, OpenCV, FFmpeg)
- frame_hashing.py: Perceptual hash and frame comparison functions
- validation.py: Frame alignment validation

All public functions and classes are re-exported here for backwards compatibility.
Existing imports will continue to work:
    from vsg_core.subtitles.frame_utils import VideoReader, detect_video_fps
"""

from __future__ import annotations

# ============================================================================
# Frame audit (diagnostic)
# ============================================================================
from .frame_audit import (
    FrameAuditIssue,
    FrameAuditResult,
    run_frame_audit,
    write_audit_report,
)

# ============================================================================
# Visual frame verification (diagnostic)
# ============================================================================
from .visual_verify import (
    CreditsInfo,
    RegionStats,
    SampleResult,
    VisualVerifyResult,
    run_visual_verify,
    write_visual_verify_report,
)

# ============================================================================
# Frame hashing and comparison
# ============================================================================
from .frame_hashing import (
    compare_frames,
    compute_frame_hash,
    compute_hamming_distance,
    compute_mse,
    compute_perceptual_hash,
    compute_ssim,
)

# ============================================================================
# Scene detection
# ============================================================================
from .scene_detection import (
    detect_scene_changes,
)

# ============================================================================
# Timing functions (CFR and VFR)
# ============================================================================
from .timing import (
    # MODE 3: VFR (VideoTimestamps-based)
    clear_vfr_cache,
    frame_to_time_aegisub,
    frame_to_time_floor,
    frame_to_time_middle,
    frame_to_time_vfr,
    get_vfr_timestamps,
    # MODE 2: Aegisub-style
    time_to_frame_aegisub,
    # MODE 0: Frame START (floor-based, deterministic)
    time_to_frame_floor,
    # MODE 1: Middle of frame
    time_to_frame_middle,
    time_to_frame_vfr,
)

# ============================================================================
# Frame validation
# ============================================================================
from .validation import (
    extract_frame_as_image,
    validate_frame_alignment,
)

# ============================================================================
# Video property detection
# ============================================================================
from .video_properties import (
    ContentAnalysis,
    IdetResult,
    RepeatPictResult,
    analyze_content_type,
    clear_content_analysis_cache,
    compare_video_properties,
    detect_video_fps,
    detect_video_properties,
    get_video_duration_ms,  # Convenience function for duration
    get_video_properties,  # Convenience wrapper for detect_video_properties
)

# ============================================================================
# Video reader
# ============================================================================
from .video_reader import (
    VideoReader,
    _get_ffms2_cache_path,  # Internal but used by validation.py
    get_vapoursynth_frame_info,
)

# ============================================================================
# Public API
# ============================================================================
__all__ = [
    "ContentAnalysis",
    "CreditsInfo",
    "FrameAuditIssue",
    "FrameAuditResult",
    "IdetResult",
    "RegionStats",
    "RepeatPictResult",
    "SampleResult",
    "VideoReader",
    "VisualVerifyResult",
    "analyze_content_type",
    "clear_content_analysis_cache",
    "clear_vfr_cache",
    "compare_frames",
    "compare_video_properties",
    "compute_frame_hash",
    "compute_hamming_distance",
    "compute_mse",
    "compute_perceptual_hash",
    "compute_ssim",
    "detect_scene_changes",
    "detect_video_fps",
    "detect_video_properties",
    "extract_frame_as_image",
    "frame_to_time_aegisub",
    "frame_to_time_floor",
    "frame_to_time_middle",
    "frame_to_time_vfr",
    "get_vapoursynth_frame_info",
    "get_vfr_timestamps",
    "get_video_duration_ms",
    "get_video_properties",
    "run_frame_audit",
    "run_visual_verify",
    "time_to_frame_aegisub",
    "time_to_frame_floor",
    "time_to_frame_middle",
    "time_to_frame_vfr",
    "validate_frame_alignment",
    "write_audit_report",
    "write_visual_verify_report",
]
