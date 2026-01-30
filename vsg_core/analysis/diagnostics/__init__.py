# vsg_core/analysis/diagnostics/__init__.py
"""
Diagnostics module for audio sync analysis.

This module provides tools for detecting sync issues like drift
(PAL, linear) and stepping patterns in correlation results.

The actual implementations remain in the parent directory for now
to maintain backward compatibility during the refactor.
"""

from __future__ import annotations

# Re-export from existing modules for backward compatibility
# These will be moved into this directory in future cleanup
from ..drift_detection import diagnose_audio_issue
from ..sync_stability import analyze_sync_stability

__all__ = [
    "diagnose_audio_issue",
    "analyze_sync_stability",
]
