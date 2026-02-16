# vsg_core/subtitles/frame_utils/__init__.py
"""
Shared frame timing and video utility functions for subtitle synchronization.

This package has been modularized for better maintainability:
- timing.py: Frame/time conversion functions (CFR and VFR support)
- video_properties.py: Video property detection (FPS, interlacing, resolution)
- video_reader.py: Multi-backend video reader (VapourSynth, FFMS2, OpenCV, FFmpeg)
- frame_hashing.py: Perceptual hash and frame comparison functions
- frame_audit.py: Frame alignment audit (centisecond rounding drift)
- surgical_rounding.py: Surgical frame-aware rounding (floor→ceil when needed)
- visual_verify.py: Visual frame verification (SSIM-based)

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
# Frame hashing and comparison
# ============================================================================
from .frame_hashing import (
    MultiMetricResult,
    compare_frames,
    compare_frames_multi,
    compute_frame_hash,
    compute_hamming_distance,
    compute_mse,
    compute_perceptual_hash,
    compute_ssim,
)

# ============================================================================
# Surgical rounding (frame-aware fix)
# ============================================================================
from .surgical_rounding import (
    SurgicalBatchStats,
    SurgicalEventResult,
    SurgicalRoundResult,
    surgical_round_batch,
    surgical_round_event,
    surgical_round_single,
)

# ============================================================================
# Timing functions (CFR and VFR)
# ============================================================================
from .timing import (
    clear_vfr_cache,
    frame_to_time_aegisub,
    frame_to_time_floor,
    frame_to_time_middle,
    get_vfr_timestamps,
    time_to_frame_aegisub,
    time_to_frame_floor,
    time_to_frame_middle,
)

# ============================================================================
# Video property detection
# ============================================================================
from .video_properties import (
    compare_video_properties,
    detect_video_fps,
    detect_video_properties,
    get_video_duration_ms,
    get_video_properties,
)

# ============================================================================
# Video reader
# ============================================================================
from .video_reader import (
    VideoReader,
    _get_ffms2_cache_path,  # Internal but used by visual_verify.py
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
# Public API
# ============================================================================
__all__ = [
    "CreditsInfo",
    "FrameAuditIssue",
    "FrameAuditResult",
    "MultiMetricResult",
    "RegionStats",
    "SampleResult",
    "SurgicalBatchStats",
    "SurgicalEventResult",
    "SurgicalRoundResult",
    "VideoReader",
    "VisualVerifyResult",
    "clear_vfr_cache",
    "compare_frames",
    "compare_frames_multi",
    "compare_video_properties",
    "compute_frame_hash",
    "compute_hamming_distance",
    "compute_mse",
    "compute_perceptual_hash",
    "compute_ssim",
    "detect_video_fps",
    "detect_video_properties",
    "frame_to_time_aegisub",
    "frame_to_time_floor",
    "frame_to_time_middle",
    "get_vfr_timestamps",
    "get_video_duration_ms",
    "get_video_properties",
    "run_frame_audit",
    "run_visual_verify",
    "surgical_round_batch",
    "surgical_round_event",
    "surgical_round_single",
    "time_to_frame_aegisub",
    "time_to_frame_floor",
    "time_to_frame_middle",
    "write_audit_report",
    "write_visual_verify_report",
]
