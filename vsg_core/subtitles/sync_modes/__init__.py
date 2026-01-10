# vsg_core/subtitles/sync_modes/__init__.py
# -*- coding: utf-8 -*-
"""
Subtitle synchronization modes.

Each mode provides a different strategy for aligning subtitles to video:
- time_based: Apply raw delay without frame verification
- duration_align: Align by total video duration difference
- correlation_frame_snap: Audio correlation + frame verification
- subtitle_anchored_frame_snap: Visual-only sync using subtitle positions
"""

from .time_based import apply_raw_delay_sync
from .duration_align import apply_duration_align_sync, verify_alignment_with_sliding_window
from .correlation_frame_snap import apply_correlation_frame_snap_sync, verify_correlation_with_frame_snap
from .subtitle_anchored_frame_snap import apply_subtitle_anchored_frame_snap_sync

__all__ = [
    'apply_raw_delay_sync',
    'apply_duration_align_sync',
    'verify_alignment_with_sliding_window',
    'apply_correlation_frame_snap_sync',
    'verify_correlation_with_frame_snap',
    'apply_subtitle_anchored_frame_snap_sync',
]
