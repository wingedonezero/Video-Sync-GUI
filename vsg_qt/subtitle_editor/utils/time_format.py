# vsg_qt/subtitle_editor/utils/time_format.py
"""
Time formatting utilities for subtitle editor.

Handles conversion between:
- Milliseconds (internal representation)
- ASS time format (H:MM:SS.cc)
- Frame numbers (for frame-based editing)

Note: Core timestamp functions are re-exported from vsg_core.subtitles.utils.timestamps
for backward compatibility with existing imports.
"""

from vsg_core.subtitles.utils.timestamps import (
    format_ass_timestamp,
    parse_ass_timestamp,
)

# Re-export with original names for backward compatibility
ms_to_ass_time = format_ass_timestamp
ass_time_to_ms = parse_ass_timestamp


def ms_to_frame(ms: float, fps: float) -> int:
    """
    Convert milliseconds to frame number.

    Args:
        ms: Time in milliseconds
        fps: Frames per second

    Returns:
        Frame number (0-indexed)
    """
    if fps <= 0:
        return 0
    return int(ms * fps / 1000.0)


def frame_to_ms(frame: int, fps: float) -> float:
    """
    Convert frame number to milliseconds.

    Args:
        frame: Frame number (0-indexed)
        fps: Frames per second

    Returns:
        Time in milliseconds
    """
    if fps <= 0:
        return 0.0
    return frame * 1000.0 / fps


def format_duration(ms: float) -> str:
    """
    Format duration for display (e.g., "0:00:01.50" for 1.5 seconds).

    Args:
        ms: Duration in milliseconds

    Returns:
        Formatted duration string
    """
    return format_ass_timestamp(ms)
