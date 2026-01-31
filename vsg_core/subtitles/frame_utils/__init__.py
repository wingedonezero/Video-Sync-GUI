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
    # Timing
    "time_to_frame_floor",
    "frame_to_time_floor",
    "time_to_frame_middle",
    "frame_to_time_middle",
    "time_to_frame_aegisub",
    "frame_to_time_aegisub",
    "clear_vfr_cache",
    "get_vfr_timestamps",
    "frame_to_time_vfr",
    "time_to_frame_vfr",
    # Video properties
    "detect_video_fps",
    "detect_video_properties",
    "get_video_properties",
    "get_video_duration_ms",
    "compare_video_properties",
    # Scene detection
    "detect_scene_changes",
    # Video reader
    "VideoReader",
    "get_vapoursynth_frame_info",
    # Frame hashing
    "compute_perceptual_hash",
    "compute_frame_hash",
    "compute_hamming_distance",
    "compute_ssim",
    "compute_mse",
    "compare_frames",
    # Validation
    "extract_frame_as_image",
    "validate_frame_alignment",
]
