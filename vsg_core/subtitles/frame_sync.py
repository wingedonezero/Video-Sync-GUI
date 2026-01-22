# vsg_core/subtitles/frame_sync.py
# -*- coding: utf-8 -*-
"""
Subtitle synchronization utilities.

This module provides frame timing and video utilities. Sync modes are now
handled via the plugin system in sync_modes/__init__.py.

Use get_sync_plugin() from sync_modes to access sync functionality.
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
from .checkpoint_selection import select_smart_checkpoints

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
    'select_smart_checkpoints',
]
