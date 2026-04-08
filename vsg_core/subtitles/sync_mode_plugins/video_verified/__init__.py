# vsg_core/subtitles/sync_mode_plugins/video_verified/__init__.py
"""
Video-Verified sync plugin package.

This package provides sliding-window video-to-video feature matching to
find the TRUE video-to-video offset for subtitle timing, addressing
cases where audio correlation differs from the actual video alignment.

Public API:
    - calculate_sliding_offset(): Sliding-window matcher with pluggable
      backends (ISC, SSCD mixup/large, pHash, dHash, SSIM). This is the
      single entrypoint for video-verified matching.
    - VideoVerifiedSync: SyncPlugin implementation for the subtitle pipeline.

See ``backends/__init__.py`` for the backend registry and
``sliding_matcher.py`` for the orchestrator.
"""

from .plugin import VideoVerifiedSync
from .sliding_matcher import calculate_sliding_offset

__all__ = [
    "VideoVerifiedSync",
    "calculate_sliding_offset",
]
