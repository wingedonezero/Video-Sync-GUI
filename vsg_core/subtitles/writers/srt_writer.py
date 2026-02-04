# vsg_core/subtitles/writers/srt_writer.py
"""
SRT subtitle file writer.

Converts SubtitleData to SRT format.
Float milliseconds are rounded to integer ms here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..utils.timestamps import format_srt_timestamp

if TYPE_CHECKING:
    from pathlib import Path

    from ..data import SubtitleData


def write_srt_file(data: SubtitleData, path: Path, rounding: str = "round") -> None:
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
        start_str = format_srt_timestamp(event.start_ms, rounding)
        end_str = format_srt_timestamp(event.end_ms, rounding)
        lines.append(f"{start_str} --> {end_str}")

        # Text (convert ASS tags to HTML-ish)
        text = _convert_ass_to_srt(event.text)
        lines.append(text)

        # Blank line separator
        lines.append("")

    # Write file
    content = "\n".join(lines)

    # Handle encoding
    encoding = "utf-8"
    if data.has_bom:
        encoding = "utf-8-sig"

    with open(path, "w", encoding=encoding) as f:
        f.write(content)


def _convert_ass_to_srt(text: str) -> str:
    """
    Convert ASS override tags to SRT-compatible format.

    Args:
        text: Text with ASS tags

    Returns:
        Text with SRT tags (or plain text)
    """
    # Convert line breaks
    text = text.replace("\\N", "\n")
    text = text.replace("\\n", "\n")

    # Convert bold
    text = re.sub(r"\{\\b1\}", "<b>", text)
    text = re.sub(r"\{\\b0\}", "</b>", text)

    # Convert italic
    text = re.sub(r"\{\\i1\}", "<i>", text)
    text = re.sub(r"\{\\i0\}", "</i>", text)

    # Convert underline
    text = re.sub(r"\{\\u1\}", "<u>", text)
    text = re.sub(r"\{\\u0\}", "</u>", text)

    # Remove all other ASS tags (override blocks)
    text = re.sub(r"\{[^}]*\}", "", text)

    return text
