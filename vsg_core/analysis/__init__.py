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

Legacy imports are preserved for backward compatibility.
"""

from __future__ import annotations

# Legacy import for backward compatibility
# run_audio_correlation is still in audio_corr.py during transition
from .audio_corr import (
    run_audio_correlation,
    run_multi_correlation as legacy_run_multi_correlation,
)

# New modular imports
from .correlation import run_correlation, run_multi_correlation
from .delay_selection import select_delay
from .diagnostics import analyze_sync_stability, diagnose_audio_issue
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
from .videodiff import run_videodiff

__all__ = [
    # New modular API
    "run_correlation",
    "run_multi_correlation",
    "select_delay",
    "diagnose_audio_issue",
    "analyze_sync_stability",
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
    # Legacy API (still supported)
    "run_audio_correlation",
    "run_videodiff",
]
