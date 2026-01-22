# vsg_core/subtitles/writers/srt_writer.py
# -*- coding: utf-8 -*-
"""
SRT subtitle file writer.

Converts SubtitleData back to SRT format.
Preserves original index numbers if available.
"""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING
import math

if TYPE_CHECKING:
    from ..data import SubtitleData


def write_srt_file(data: 'SubtitleData', path: Path) -> None:
    """
    Write SubtitleData to SRT file.

    Args:
        data: SubtitleData object to write
        path: Output file path
    """
    path = Path(path)
    lines = []

    # Get only dialogue events (not comments)
    dialogue_events = [e for e in data.events if not e.is_comment]

    # Sort by start time
    sorted_events = sorted(dialogue_events, key=lambda e: e.start_ms)

    for i, event in enumerate(sorted_events, start=1):
        # Use original SRT index if available, otherwise sequential
        index = event.srt_index if event.srt_index is not None else i

        # Timing
        start_str = _ms_to_srt_time(event.start_ms)
        end_str = _ms_to_srt_time(event.end_ms)

        # Text - convert ASS line breaks back to actual line breaks
        text = event.text.replace('\\N', '\n').replace('\\n', '\n')

        # Build entry
        lines.append(str(index))
        lines.append(f'{start_str} --> {end_str}')
        lines.append(text)
        lines.append('')  # Blank line between entries

    # Join and write
    content = '\n'.join(lines)

    # Determine encoding
    encoding = data.encoding
    if encoding == 'utf-8-sig':
        encoding = 'utf-8'

    with open(path, 'w', encoding=encoding, newline='\n') as f:
        # Add BOM if original had one
        if data.has_bom:
            f.write('\ufeff')
        f.write(content)


def _ms_to_srt_time(ms: float) -> str:
    """
    Convert milliseconds to SRT timestamp.

    Format: HH:MM:SS,mmm (comma for milliseconds)

    Args:
        ms: Time in milliseconds (float)

    Returns:
        SRT timestamp string
    """
    # Round to nearest millisecond
    total_ms = int(round(ms))

    milliseconds = total_ms % 1000
    total_seconds = total_ms // 1000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60

    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}'
