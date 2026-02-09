# vsg_core/subtitles/diagnostics/timestamp_debug.py
"""
Timestamp debugging utilities for ASS/SSA subtitle files.

These functions read raw timestamp strings from subtitle files for comparison
with parsed values, helping diagnose timing precision issues.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def read_raw_ass_timestamps(
    file_path: Path, max_events: int = 5
) -> list[tuple[str, str, str]]:
    """
    Read raw timestamp strings from an ASS file without full parsing.

    Returns list of (start_str, end_str, style) tuples for first N events.
    Reads both Dialogue and Comment lines to match SubtitleData.events order.
    Used for diagnostics to compare original file timestamps with parsed values.
    """
    results = []
    try:
        # Try to detect encoding
        encodings = ["utf-8-sig", "utf-8", "utf-16", "cp1252", "latin1"]
        content = None
        for enc in encodings:
            try:
                with open(file_path, encoding=enc) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if not content:
            return results

        # Pattern: Dialogue/Comment: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        # Match both Dialogue and Comment lines to align with SubtitleData.events
        pattern = re.compile(
            r"^(?:Dialogue|Comment):\s*\d+,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),([^,]*),",
            re.MULTILINE,
        )

        for match in pattern.finditer(content):
            if len(results) >= max_events:
                break
            start_str = match.group(1)
            end_str = match.group(2)
            style = match.group(3)
            results.append((start_str, end_str, style))
    except Exception:
        pass
    return results


def check_timestamp_precision(timestamp_str: str) -> int:
    """
    Check the precision of a timestamp string (number of fractional digits).

    Standard ASS uses centiseconds (2 digits: "0:00:00.00").
    Some tools may output milliseconds (3 digits: "0:00:00.000").

    Returns number of fractional digits.
    """
    try:
        parts = timestamp_str.split(".")
        if len(parts) == 2:
            return len(parts[1])
    except Exception:
        pass
    return 2  # Default assumption


def parse_ass_time_str(time_str: str) -> float:
    """Parse ASS timestamp string to float ms (same logic as SubtitleData)."""
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
