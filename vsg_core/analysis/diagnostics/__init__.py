# vsg_core/analysis/diagnostics/__init__.py
"""
Diagnostics module for audio sync analysis.

This module provides tools for detecting sync issues like drift
(PAL, linear) and stepping patterns in correlation results.
"""

from __future__ import annotations

# Re-export from existing modules
from ..drift_detection import diagnose_audio_issue
from ..sync_stability import analyze_sync_stability

# Flag handling for diagnosis results
from .flag_handler import apply_diagnosis_flags

__all__ = [
    "diagnose_audio_issue",
    "analyze_sync_stability",
    "apply_diagnosis_flags",
]
