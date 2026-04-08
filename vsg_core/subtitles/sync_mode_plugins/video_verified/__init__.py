# vsg_core/subtitles/sync_mode_plugins/video_verified/__init__.py
"""
Video-Verified sync plugin package.

This package provides sliding-window video-to-video feature matching to
find the TRUE video-to-video offset for subtitle timing, addressing
cases where audio correlation differs from the actual video alignment.

Public API:
    - calculate_sliding_offset(): Sliding-window matcher with pluggable
      backends (ISC, SSCD mixup/large, pHash, dHash, SSIM). This is the
      primary entrypoint for new code.
    - calculate_neural_verified_offset(): Backward-compat alias for the
      sliding matcher with backend="isc" (scheduled for removal in
      Phase 5 of the refactor).
    - calculate_video_verified_offset(): Classic per-frame checkpoint
      matcher. Still importable while the legacy module lives on disk;
      scheduled for removal in Phase 5.
    - VideoVerifiedSync: SyncPlugin implementation for the subtitle pipeline.

See ``backends/__init__.py`` for the backend registry and
``sliding_matcher.py`` for the orchestrator.
"""

from .matcher import calculate_video_verified_offset
from .plugin import VideoVerifiedSync
from .sliding_matcher import (
    calculate_neural_verified_offset,
    calculate_sliding_offset,
)

__all__ = [
    "VideoVerifiedSync",
    "calculate_neural_verified_offset",
    "calculate_sliding_offset",
    "calculate_video_verified_offset",
]
