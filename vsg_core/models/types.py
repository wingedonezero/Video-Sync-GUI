# vsg_core/models/types.py
"""Literal type aliases for type-safe string values.

These replace enums to avoid JSON serialization issues while maintaining
type safety through Literal types. Type checkers (mypy, pyright) will
flag invalid string values.

Usage:
    from vsg_core.models.types import TrackTypeStr, AnalysisModeStr, SnapModeStr
"""

from typing import Literal

# Track types - used in Track dataclass for categorizing media tracks
TrackTypeStr = Literal["video", "audio", "subtitles"]

# Analysis mode - determines how source comparison is performed
AnalysisModeStr = Literal["Audio Correlation", "VideoDiff"]

# Snap mode - determines how chapter timestamps snap to keyframes
SnapModeStr = Literal["previous", "nearest"]
