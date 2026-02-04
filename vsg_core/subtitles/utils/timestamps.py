# vsg_core/subtitles/utils/timestamps.py
"""
Unified timestamp parsing and formatting for subtitle files.

Consolidates duplicate implementations from:
- data.py:_parse_ass_time, _format_ass_time
- subtitles_step.py:_parse_ass_time_str, _check_timestamp_precision
- time_format.py:ms_to_ass_time, ass_time_to_ms
- ass_writer.py:_format_ass_time, _round_centiseconds
- srt_writer.py:_format_srt_time, _round_ms
- frame_audit.py:_format_timestamp
- ocr/parsers/base.py:_ms_to_timestamp

Formats:
- ASS: H:MM:SS.cc (single digit hour, centiseconds)
- SRT: HH:MM:SS,mmm (two digit hour with comma, milliseconds)
- Display: HH:MM:SS.cc (two digit hour with period, centiseconds)
"""

from __future__ import annotations

import math


def parse_ass_timestamp(time_str: str) -> float:
    """
    Parse ASS timestamp to float milliseconds.

    Format: H:MM:SS.cc (centiseconds)

    Args:
        time_str: ASS timestamp string (e.g., "0:01:23.45")

    Returns:
        Time in float milliseconds
    """
    try:
        parts = time_str.strip().split(":")
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds_cs = parts[2].split(".")
            seconds = int(seconds_cs[0])
            centiseconds = int(seconds_cs[1]) if len(seconds_cs) > 1 else 0

            total_ms = (
                hours * 3600000 + minutes * 60000 + seconds * 1000 + centiseconds * 10
            )
            return float(total_ms)
    except (ValueError, IndexError):
        pass
    return 0.0


def format_ass_timestamp(ms: float, rounding: str = "floor") -> str:
    """
    Format float milliseconds to ASS timestamp.

    THIS IS WHERE ROUNDING HAPPENS for ASS output.

    Args:
        ms: Time in float milliseconds
        rounding: Rounding mode - "floor" (default), "round", or "ceil"

    Returns:
        ASS timestamp string (H:MM:SS.cc)
    """
    total_cs = round_to_centiseconds(ms, rounding)

    # Ensure non-negative
    total_cs = max(total_cs, 0)

    cs = total_cs % 100
    total_seconds = total_cs // 100
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60

    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def format_srt_timestamp(ms: float, rounding: str = "round") -> str:
    """
    Format float milliseconds to SRT timestamp.

    Args:
        ms: Time in float milliseconds
        rounding: Rounding mode - "floor", "round" (default), or "ceil"

    Returns:
        SRT timestamp (HH:MM:SS,mmm)
    """
    total_ms = round_to_milliseconds(ms, rounding)

    # Ensure non-negative
    total_ms = max(total_ms, 0)

    milliseconds = total_ms % 1000
    total_seconds = total_ms // 1000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60

    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def format_display_timestamp(ms: float) -> str:
    """
    Format milliseconds for human-readable display.

    Uses HH:MM:SS.cc format (two digit hour with period, centiseconds).

    Args:
        ms: Time in milliseconds

    Returns:
        Display timestamp (HH:MM:SS.cc)
    """
    # Simple truncation for display
    total_cs = int(ms / 10)
    total_cs = max(total_cs, 0)

    cs = total_cs % 100
    total_seconds = total_cs // 100
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def format_milliseconds_timestamp(ms: int) -> str:
    """
    Format milliseconds to HH:MM:SS.mmm format.

    Used primarily for OCR debug output and detailed logging.

    Args:
        ms: Time in milliseconds (integer)

    Returns:
        Timestamp string (HH:MM:SS.mmm)
    """
    ms = max(ms, 0)
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    milliseconds = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def round_to_centiseconds(ms: float, rounding: str = "floor") -> int:
    """
    Round milliseconds to centiseconds based on rounding mode.

    Args:
        ms: Time in float milliseconds
        rounding: Rounding mode - "floor" (default), "round", or "ceil"

    Returns:
        Time in integer centiseconds
    """
    mode = (rounding or "floor").lower()
    value = ms / 10

    if mode == "ceil":
        return int(math.ceil(value))
    if mode == "round":
        return int(round(value))
    return int(math.floor(value))


def round_to_milliseconds(ms: float, rounding: str = "round") -> int:
    """
    Round float milliseconds to integer milliseconds based on rounding mode.

    Args:
        ms: Time in float milliseconds
        rounding: Rounding mode - "floor", "round" (default), or "ceil"

    Returns:
        Time in integer milliseconds
    """
    mode = (rounding or "round").lower()

    if mode == "ceil":
        return int(math.ceil(ms))
    if mode == "floor":
        return int(math.floor(ms))
    return int(round(ms))


def check_timestamp_precision(timestamp_str: str) -> int:
    """
    Check the precision of a timestamp string (number of fractional digits).

    Standard ASS uses centiseconds (2 digits: "0:00:00.00").
    Some tools may output milliseconds (3 digits: "0:00:00.000").

    Args:
        timestamp_str: Timestamp string to check

    Returns:
        Number of fractional digits (typically 2 or 3)
    """
    try:
        parts = timestamp_str.split(".")
        if len(parts) == 2:
            return len(parts[1])
    except Exception:
        pass
    return 2  # Default assumption for ASS
