# vsg_core/subtitles/parsers/srt_parser.py
# -*- coding: utf-8 -*-
"""
SRT and VTT subtitle file parsers.

Parses SRT/VTT into SubtitleData internal format.
Preserves:
- Original index numbers
- Millisecond timing precision (float)
- Multi-line text (converted to ASS \\N line breaks)
- Positioning tags (kept in text as-is)

Conversion to ASS happens at output time (save_ass).
"""
from __future__ import annotations
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple
import codecs
import re

from ..data import SubtitleData, SubtitleStyle, SubtitleEvent


# Encodings to try when auto-detecting
ENCODINGS_TO_TRY = [
    'utf-8-sig',  # UTF-8 with BOM
    'utf-8',
    'utf-16',
    'utf-16-le',
    'utf-16-be',
    'cp1252',     # Windows Western European
    'latin1',
]


def detect_encoding(path: Path) -> Tuple[str, bool]:
    """Detect file encoding."""
    with open(path, 'rb') as f:
        raw = f.read(4)

    if raw.startswith(codecs.BOM_UTF8):
        return ('utf-8-sig', True)
    elif raw.startswith(codecs.BOM_UTF16_LE):
        return ('utf-16-le', True)
    elif raw.startswith(codecs.BOM_UTF16_BE):
        return ('utf-16-be', True)

    for encoding in ENCODINGS_TO_TRY:
        try:
            with open(path, 'r', encoding=encoding) as f:
                f.read()
            return (encoding, False)
        except (UnicodeDecodeError, LookupError):
            continue

    return ('utf-8', False)


def _parse_srt_time(time_str: str) -> float:
    """
    Parse SRT timestamp to milliseconds (float).

    Format: HH:MM:SS,mmm (comma separator for ms)
    Example: "00:01:23,456" = 83456.0 ms
    """
    # SRT uses comma for milliseconds, but some files use period
    time_str = time_str.replace(',', '.')

    try:
        parts = time_str.split(':')
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            sec_parts = parts[2].split('.')
            seconds = int(sec_parts[0])
            milliseconds = int(sec_parts[1].ljust(3, '0')[:3]) if len(sec_parts) > 1 else 0

            return float(hours * 3600000 + minutes * 60000 + seconds * 1000 + milliseconds)
    except (ValueError, IndexError):
        pass

    return 0.0


def _parse_vtt_time(time_str: str) -> float:
    """
    Parse VTT timestamp to milliseconds (float).

    Format: HH:MM:SS.mmm or MM:SS.mmm (period separator)
    Example: "01:23.456" = 83456.0 ms
    """
    try:
        parts = time_str.split(':')

        if len(parts) == 3:
            # HH:MM:SS.mmm
            hours = int(parts[0])
            minutes = int(parts[1])
            sec_parts = parts[2].split('.')
            seconds = int(sec_parts[0])
            milliseconds = int(sec_parts[1].ljust(3, '0')[:3]) if len(sec_parts) > 1 else 0
        elif len(parts) == 2:
            # MM:SS.mmm
            hours = 0
            minutes = int(parts[0])
            sec_parts = parts[1].split('.')
            seconds = int(sec_parts[0])
            milliseconds = int(sec_parts[1].ljust(3, '0')[:3]) if len(sec_parts) > 1 else 0
        else:
            return 0.0

        return float(hours * 3600000 + minutes * 60000 + seconds * 1000 + milliseconds)
    except (ValueError, IndexError):
        pass

    return 0.0


def parse_srt_file(path: Path) -> SubtitleData:
    """
    Parse SRT file into SubtitleData.

    SRT format:
    ```
    1
    00:00:01,000 --> 00:00:04,000
    First subtitle line
    Maybe second line

    2
    00:00:05,000 --> 00:00:08,000
    Second subtitle
    ```

    Args:
        path: Path to SRT file

    Returns:
        SubtitleData object
    """
    path = Path(path)
    encoding, has_bom = detect_encoding(path)

    with open(path, 'r', encoding=encoding) as f:
        content = f.read()

    # Initialize data
    data = SubtitleData(
        source_path=path,
        source_format='srt',
        encoding=encoding,
        has_bom=has_bom,
    )

    # Set up default ASS structure for eventual conversion
    data.script_info = OrderedDict([
        ('ScriptType', 'v4.00+'),
        ('PlayResX', '1920'),
        ('PlayResY', '1080'),
        ('WrapStyle', '0'),
    ])

    # Add default style
    data.styles['Default'] = SubtitleStyle.default()

    # Parse SRT blocks
    # SRT uses blank lines to separate entries
    blocks = re.split(r'\n\s*\n', content.strip())

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue

        # First line should be index number
        try:
            index = int(lines[0].strip())
        except ValueError:
            # Not a valid index, skip this block
            continue

        # Second line should be timing
        timing_line = lines[1].strip()
        timing_match = re.match(
            r'(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})',
            timing_line
        )
        if not timing_match:
            continue

        start_ms = _parse_srt_time(timing_match.group(1))
        end_ms = _parse_srt_time(timing_match.group(2))

        # Remaining lines are text (join with ASS line break)
        text_lines = lines[2:] if len(lines) > 2 else []
        text = '\\N'.join(line.strip() for line in text_lines)

        # Create event
        event = SubtitleEvent(
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            style='Default',
            srt_index=index,
            original_line=block,
        )
        data.events.append(event)

    return data


def parse_vtt_file(path: Path) -> SubtitleData:
    """
    Parse WebVTT file into SubtitleData.

    VTT format:
    ```
    WEBVTT

    00:00:01.000 --> 00:00:04.000
    First subtitle line

    00:00:05.000 --> 00:00:08.000
    Second subtitle
    ```

    Args:
        path: Path to VTT file

    Returns:
        SubtitleData object
    """
    path = Path(path)
    encoding, has_bom = detect_encoding(path)

    with open(path, 'r', encoding=encoding) as f:
        content = f.read()

    # Initialize data
    data = SubtitleData(
        source_path=path,
        source_format='vtt',
        encoding=encoding,
        has_bom=has_bom,
    )

    # Set up default ASS structure
    data.script_info = OrderedDict([
        ('ScriptType', 'v4.00+'),
        ('PlayResX', '1920'),
        ('PlayResY', '1080'),
        ('WrapStyle', '0'),
    ])

    # Add default style
    data.styles['Default'] = SubtitleStyle.default()

    # Skip WEBVTT header
    lines = content.split('\n')
    start_idx = 0
    for i, line in enumerate(lines):
        if line.strip().upper().startswith('WEBVTT'):
            start_idx = i + 1
            break

    # Parse VTT cues
    content_after_header = '\n'.join(lines[start_idx:])
    blocks = re.split(r'\n\s*\n', content_after_header.strip())

    index = 0
    for block in blocks:
        block_lines = block.strip().split('\n')
        if not block_lines:
            continue

        # Find timing line
        timing_line_idx = 0
        for i, line in enumerate(block_lines):
            if '-->' in line:
                timing_line_idx = i
                break
        else:
            # No timing line found
            continue

        timing_line = block_lines[timing_line_idx].strip()

        # VTT timing can have positioning: "00:00:01.000 --> 00:00:04.000 position:50%"
        timing_match = re.match(
            r'(\d{1,2}:?\d{2}:\d{2}\.\d{1,3})\s*-->\s*(\d{1,2}:?\d{2}:\d{2}\.\d{1,3})',
            timing_line
        )
        if not timing_match:
            continue

        start_ms = _parse_vtt_time(timing_match.group(1))
        end_ms = _parse_vtt_time(timing_match.group(2))

        # Text is after timing line
        text_lines = block_lines[timing_line_idx + 1:] if len(block_lines) > timing_line_idx + 1 else []
        text = '\\N'.join(line.strip() for line in text_lines)

        # VTT can have cue identifiers before timing
        cue_id = None
        if timing_line_idx > 0:
            potential_id = block_lines[0].strip()
            if potential_id and '-->' not in potential_id:
                cue_id = potential_id

        index += 1
        event = SubtitleEvent(
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            style='Default',
            srt_index=index,
            original_line=block,
        )
        data.events.append(event)

    return data
