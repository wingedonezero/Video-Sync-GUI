# vsg_qt/subtitle_editor/utils/time_format.py
"""
Time formatting utilities for subtitle editor.

Handles conversion between:
- Milliseconds (internal representation)
- ASS time format (H:MM:SS.cc)
- Frame numbers (for frame-based editing)
"""


def ms_to_ass_time(ms: float) -> str:
    """
    Convert milliseconds to ASS timestamp format.

    Args:
        ms: Time in milliseconds

    Returns:
        ASS timestamp string (H:MM:SS.cc)
    """
    ms = max(ms, 0)

    total_cs = int(ms / 10)
    cs = total_cs % 100
    total_seconds = total_cs // 100
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60

    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def ass_time_to_ms(time_str: str) -> float:
    """
    Convert ASS timestamp to milliseconds.

    Args:
        time_str: ASS timestamp string (H:MM:SS.cc)

    Returns:
        Time in milliseconds
    """
    try:
        parts = time_str.strip().split(':')
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds_cs = parts[2].split('.')
            seconds = int(seconds_cs[0])
            centiseconds = int(seconds_cs[1]) if len(seconds_cs) > 1 else 0

            total_ms = (
                hours * 3600000 +
                minutes * 60000 +
                seconds * 1000 +
                centiseconds * 10
            )
            return float(total_ms)
    except (ValueError, IndexError):
        pass
    return 0.0


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
    return ms_to_ass_time(ms)
