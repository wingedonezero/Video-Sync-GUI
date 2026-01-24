# vsg_core/subtitles/writers/srt_writer.py
# -*- coding: utf-8 -*-
"""
SRT subtitle file writer.

Converts SubtitleData to SRT format.
Float milliseconds are rounded to integer ms here.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data import SubtitleData


def write_srt_file(data: 'SubtitleData', path: Path, rounding: str = 'round') -> None:
    """
    Write SubtitleData to SRT file.

    Timing is rounded to integer milliseconds here.

    Args:
        data: SubtitleData to write
        path: Output path
    """
    lines = []

    # Get dialogue events only (not comments)
    dialogue_events = [e for e in data.events if not e.is_comment]

    for idx, event in enumerate(dialogue_events, start=1):
        # Use original SRT index if available
        srt_idx = event.srt_index if event.srt_index is not None else idx

        # Index line
        lines.append(str(srt_idx))

        # Timing line (round to integer ms)
        start_str = _format_srt_time(event.start_ms, rounding)
        end_str = _format_srt_time(event.end_ms, rounding)
        lines.append(f'{start_str} --> {end_str}')

        # Text (convert ASS tags to HTML-ish)
        text = _convert_ass_to_srt(event.text)
        lines.append(text)

        # Blank line separator
        lines.append('')

    # Write file
    content = '\n'.join(lines)

    # Handle encoding
    encoding = 'utf-8'
    if data.has_bom:
        encoding = 'utf-8-sig'

    with open(path, 'w', encoding=encoding) as f:
        f.write(content)


def _format_srt_time(ms: float, rounding: str) -> str:
    """
    Format float milliseconds to SRT timestamp.

    Rounds to integer milliseconds.

    Args:
        ms: Time in float milliseconds

    Returns:
        SRT timestamp (HH:MM:SS,mmm)
    """
    # Round to integer ms
    total_ms = _round_ms(ms, rounding)

    if total_ms < 0:
        total_ms = 0

    milliseconds = total_ms % 1000
    total_seconds = total_ms // 1000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60

    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _round_ms(ms: float, rounding: str) -> int:
    """Round milliseconds to integer based on rounding mode."""
    mode = (rounding or 'round').lower()
    if mode == 'ceil':
        return int(math.ceil(ms))
    if mode == 'floor':
        return int(math.floor(ms))
    return int(round(ms))


def _convert_ass_to_srt(text: str) -> str:
    """
    Convert ASS override tags to SRT-compatible format.

    Args:
        text: Text with ASS tags

    Returns:
        Text with SRT tags (or plain text)
    """
    # Convert line breaks
    text = text.replace('\\N', '\n')
    text = text.replace('\\n', '\n')

    # Convert bold
    text = re.sub(r'\{\\b1\}', '<b>', text)
    text = re.sub(r'\{\\b0\}', '</b>', text)

    # Convert italic
    text = re.sub(r'\{\\i1\}', '<i>', text)
    text = re.sub(r'\{\\i0\}', '</i>', text)

    # Convert underline
    text = re.sub(r'\{\\u1\}', '<u>', text)
    text = re.sub(r'\{\\u0\}', '</u>', text)

    # Remove all other ASS tags (override blocks)
    text = re.sub(r'\{[^}]*\}', '', text)

    return text
