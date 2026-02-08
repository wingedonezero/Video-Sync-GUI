# vsg_core/subtitles/sync_mode_plugins/video_verified/__init__.py
"""
Video-Verified sync plugin package.

This package provides frame matching to find the TRUE video-to-video offset
for subtitle timing, addressing cases where audio correlation differs from
the actual video alignment.

Public API:
    - calculate_video_verified_offset(): Core algorithm, usable for any format
    - VideoVerifiedSync: SyncPlugin implementation for the subtitle pipeline
"""

from .matcher import calculate_video_verified_offset
from .plugin import VideoVerifiedSync

__all__ = [
    "VideoVerifiedSync",
    "calculate_video_verified_offset",
]
