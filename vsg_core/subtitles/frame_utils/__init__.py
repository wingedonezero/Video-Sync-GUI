# vsg_core/subtitles/frame_utils/__init__.py
"""
Shared frame timing and video utility functions for subtitle synchronization.

This package has been modularized for better maintainability:
- frame_clock.py: CFR frame-grid formula (eligibility + reported fallback only)
- video_properties.py: Video property detection (FPS, interlacing, resolution)
- video_reader.py: FFMS2 index cache path (shared by matcher and frame tables)
- frame_hashing.py: Perceptual hash and frame comparison functions
- frame_audit.py: Frame alignment audit (centisecond rounding drift)
- surgical_rounding.py: Surgical frame-aware rounding (floor→ceil when needed)
- frame_table.py: Real frame grid from the video's own timestamps (FrameTable)
- visual_verify.py: Visual frame verification (SSIM-based)

All public functions and classes are re-exported here for backwards compatibility.
Existing imports will continue to work:
    from vsg_core.subtitles.frame_utils import FrameTable, detect_video_fps
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
# Exact frame grid
# ============================================================================
from .frame_clock import FrameClock

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
from .frame_table import (
    FrameGrid,
    FrameGridNote,
    FrameShift,
    FrameTable,
    TimelineCheck,
    TimelineGap,
    build_frame_table,
    check_timeline,
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
# Video property detection
# ============================================================================
from .video_properties import (
    compare_video_properties,
    detect_frame_clock,
    detect_video_fps,
    detect_video_properties,
    frame_clock_from_props,
    get_video_duration_ms,
    get_video_properties,
)

# ============================================================================
# FFMS2 index cache location (shared by the matcher, frame tables, visual verify)
# ============================================================================
from .video_reader import _get_ffms2_cache_path

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
    "FrameClock",
    "FrameGrid",
    "FrameGridNote",
    "FrameShift",
    "FrameTable",
    "MultiMetricResult",
    "RegionStats",
    "SampleResult",
    "SurgicalBatchStats",
    "SurgicalEventResult",
    "SurgicalRoundResult",
    "TimelineCheck",
    "TimelineGap",
    "VisualVerifyResult",
    "build_frame_table",
    "check_timeline",
    "compare_frames",
    "compare_frames_multi",
    "compare_video_properties",
    "compute_frame_hash",
    "compute_hamming_distance",
    "compute_mse",
    "compute_perceptual_hash",
    "compute_ssim",
    "detect_frame_clock",
    "detect_video_fps",
    "detect_video_properties",
    "frame_clock_from_props",
    "get_video_duration_ms",
    "get_video_properties",
    "run_frame_audit",
    "run_visual_verify",
    "surgical_round_batch",
    "surgical_round_event",
    "surgical_round_single",
    "write_audit_report",
    "write_visual_verify_report",
]
