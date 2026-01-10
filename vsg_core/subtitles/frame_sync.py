# vsg_core/subtitles/frame_sync.py
# -*- coding: utf-8 -*-
"""
Subtitle synchronization module (refactored).

This module now acts as an orchestrator, importing functionality from specialized modules:
- frame_utils: Frame timing and video utilities
- checkpoint_selection: Smart checkpoint selection for verification
- sync_modes: Different synchronization strategies

For backward compatibility, all functions are re-exported here.
"""
from __future__ import annotations

# Re-export frame utilities
from .frame_utils import (
    # Frame timing conversions
    time_to_frame_floor,
    frame_to_time_floor,
    time_to_frame_middle,
    frame_to_time_middle,
    time_to_frame_aegisub,
    frame_to_time_aegisub,
    time_to_frame_vfr,
    frame_to_time_vfr,
    get_vfr_timestamps,

    # VapourSynth utilities
    get_vapoursynth_frame_info,
    detect_scene_changes,
    extract_frame_as_image,
    compute_perceptual_hash,
    validate_frame_alignment,

    # Video detection
    detect_video_fps,
    detect_video_properties,
    compare_video_properties,
)

# Re-export checkpoint selection
from .checkpoint_selection import select_smart_checkpoints as _select_smart_checkpoints

# Re-export sync modes
from .sync_modes import (
    apply_raw_delay_sync,
    apply_duration_align_sync,
    verify_alignment_with_sliding_window,
    apply_correlation_frame_snap_sync,
    verify_correlation_with_frame_snap,
    apply_subtitle_anchored_frame_snap_sync,
    apply_correlation_guided_frame_anchor_sync,
)

__all__ = [
    # Frame timing
    'time_to_frame_floor',
    'frame_to_time_floor',
    'time_to_frame_middle',
    'frame_to_time_middle',
    'time_to_frame_aegisub',
    'frame_to_time_aegisub',
    'time_to_frame_vfr',
    'frame_to_time_vfr',
    'get_vfr_timestamps',

    # VapourSynth
    'get_vapoursynth_frame_info',
    'detect_scene_changes',
    'extract_frame_as_image',
    'compute_perceptual_hash',
    'validate_frame_alignment',

    # Video detection
    'detect_video_fps',
    'detect_video_properties',
    'compare_video_properties',

    # Checkpoint selection
    '_select_smart_checkpoints',

    # Sync modes
    'apply_raw_delay_sync',
    'apply_duration_align_sync',
    'verify_alignment_with_sliding_window',
    'apply_correlation_frame_snap_sync',
    'verify_correlation_with_frame_snap',
    'apply_subtitle_anchored_frame_snap_sync',
    'apply_correlation_guided_frame_anchor_sync',
]
