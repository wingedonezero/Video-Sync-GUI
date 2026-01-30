# vsg_core/analysis/__init__.py
"""
Audio analysis module for sync detection.

This module provides comprehensive audio correlation and sync detection
capabilities through a modular architecture:

- correlation/: Pluggable correlation algorithms (GCC-PHAT, SCC, Onset, etc.)
- delay_selection/: Delay selection strategies (mode, average, first stable, etc.)
- preprocessing/: Audio decoding, filtering, and chunking
- diagnostics/: Drift and stability detection
- separation/: Audio source separation
- track_selection: Audio track selection for correlation
- config_builder: Source-specific configuration
- delay_calculation: Container delay chain and global shift

Legacy imports are preserved for backward compatibility.
"""

from __future__ import annotations

# Config and track selection
from .config_builder import (
    build_source_config,
    get_correlation_track_settings,
    get_reference_track_settings,
    should_use_source_separation,
)

# New modular imports
from .correlation import run_correlation, run_multi_correlation
from .delay_calculation import (
    ContainerDelayOverride,
    FinalDelay,
    apply_global_shift,
    calculate_final_delay,
    calculate_global_shift,
    convert_to_relative_delays,
    extract_container_delays,
    get_actual_container_delay,
)
from .delay_selection import (
    SteppingOverrideResult,
    evaluate_stepping_override,
    select_delay,
)
from .diagnostics import (
    analyze_sync_stability,
    apply_diagnosis_flags,
    diagnose_audio_issue,
)
from .preprocessing import (
    decode_to_memory,
    get_audio_stream_info,
    normalize_lang,
)
from .separation import (
    SEPARATION_MODES,
    apply_source_separation,
    is_audio_separator_available,
    is_separation_enabled,
    list_available_models,
)
from .track_selection import (
    format_track_details,
    get_audio_tracks,
    get_video_tracks,
    select_audio_track,
)
from .videodiff import run_videodiff

__all__ = [
    # New modular API
    "run_correlation",
    "run_multi_correlation",
    "select_delay",
    "diagnose_audio_issue",
    "analyze_sync_stability",
    "apply_diagnosis_flags",
    # Track selection
    "select_audio_track",
    "format_track_details",
    "get_audio_tracks",
    "get_video_tracks",
    # Config building
    "build_source_config",
    "should_use_source_separation",
    "get_correlation_track_settings",
    "get_reference_track_settings",
    # Delay calculation
    "calculate_final_delay",
    "calculate_global_shift",
    "apply_global_shift",
    "extract_container_delays",
    "convert_to_relative_delays",
    "get_actual_container_delay",
    "FinalDelay",
    "ContainerDelayOverride",
    # Delay selection
    "evaluate_stepping_override",
    "SteppingOverrideResult",
    # Preprocessing
    "decode_to_memory",
    "get_audio_stream_info",
    "normalize_lang",
    # Separation
    "apply_source_separation",
    "is_separation_enabled",
    "is_audio_separator_available",
    "list_available_models",
    "SEPARATION_MODES",
    # Videodiff
    "run_videodiff",
]
