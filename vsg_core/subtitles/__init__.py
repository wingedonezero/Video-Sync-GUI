# vsg_core/subtitles/__init__.py
"""
Unified subtitle processing system.

This package provides:
- SubtitleData: Universal container for all subtitle formats
- Parsers for ASS, SRT, VTT formats
- Writers for ASS, SRT formats
- Operations: sync, stepping, style modifications

Model classes are in vsg_core.models - import from there.
"""

from .data import SubtitleData

__all__ = ["SubtitleData"]
