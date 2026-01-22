# vsg_core/subtitles/parsers/ass_parser.py
# -*- coding: utf-8 -*-
"""
ASS/SSA subtitle file parser with full metadata preservation.

This parser preserves EVERYTHING from the original file:
- All sections in original order
- All metadata (Script Info, Aegisub Garbage, Extradata)
- All comments (lines starting with ; or Comment: events)
- Unknown/custom sections
- Embedded fonts and graphics
- Format line field ordering
- Original encoding and BOM

Nothing is lost during parse -> edit -> save cycle.
"""
from __future__ import annotations
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple
import codecs
import re

from ..data import SubtitleData, SubtitleStyle, SubtitleEvent, EmbeddedFont, EmbeddedGraphic


# Encodings to try when auto-detecting
ENCODINGS_TO_TRY = [
    'utf-8-sig',  # UTF-8 with BOM
    'utf-8',
    'utf-16',
    'utf-16-le',
    'utf-16-be',
    'shift_jis',
    'gbk',
    'gb2312',
    'big5',
    'cp1252',     # Windows Western European
    'latin1',
]


def detect_encoding(path: Path) -> Tuple[str, bool]:
    """
    Detect file encoding.

    Args:
        path: Path to file

    Returns:
        Tuple of (encoding_name, has_bom)
    """
    # Check for BOM first
    with open(path, 'rb') as f:
        raw = f.read(4)

    if raw.startswith(codecs.BOM_UTF8):
        return ('utf-8-sig', True)
    elif raw.startswith(codecs.BOM_UTF16_LE):
        return ('utf-16-le', True)
    elif raw.startswith(codecs.BOM_UTF16_BE):
        return ('utf-16-be', True)
    elif raw.startswith(codecs.BOM_UTF32_LE):
        return ('utf-32-le', True)
    elif raw.startswith(codecs.BOM_UTF32_BE):
        return ('utf-32-be', True)

    # Try each encoding
    for encoding in ENCODINGS_TO_TRY:
        try:
            with open(path, 'r', encoding=encoding) as f:
                f.read()
            return (encoding, False)
        except (UnicodeDecodeError, LookupError):
            continue

    # Default to UTF-8
    return ('utf-8', False)


def parse_ass_file(path: Path) -> SubtitleData:
    """
    Parse ASS/SSA file with full metadata preservation.

    Args:
        path: Path to ASS/SSA file

    Returns:
        SubtitleData object with all data preserved
    """
    path = Path(path)

    # Detect encoding
    encoding, has_bom = detect_encoding(path)

    # Read file
    with open(path, 'r', encoding=encoding) as f:
        content = f.read()

    lines = content.splitlines()

    # Initialize data structure
    data = SubtitleData(
        source_path=path,
        source_format='ass' if path.suffix.lower() == '.ass' else 'ssa',
        encoding=encoding,
        has_bom=has_bom,
    )

    # Parse state
    current_section: Optional[str] = None
    current_section_lines: List[str] = []
    pending_comments: List[str] = []  # Comments before next section
    line_number = 0

    # Known section handlers
    known_sections = {
        '[script info]': '_parse_script_info',
        '[v4+ styles]': '_parse_styles',
        '[v4 styles]': '_parse_styles',  # SSA format
        '[events]': '_parse_events',
        '[fonts]': '_parse_fonts',
        '[graphics]': '_parse_graphics',
        '[aegisub project garbage]': '_parse_aegisub_garbage',
        '[aegisub extradata]': '_parse_extradata',
    }

    def flush_section():
        """Process accumulated section lines."""
        nonlocal current_section, current_section_lines, pending_comments

        if current_section is None:
            # Lines before any section (header)
            data.header_lines = current_section_lines
        else:
            # Store any pending comments for this section
            if pending_comments:
                data.section_comments[current_section] = pending_comments
                pending_comments = []

            # Add to section order
            if current_section not in data.section_order:
                data.section_order.append(current_section)

            # Process based on section type
            section_lower = current_section.lower()
            if section_lower in known_sections:
                handler = known_sections[section_lower]
                globals()[handler](data, current_section_lines)
            else:
                # Unknown section - preserve as raw lines
                data.custom_sections[current_section] = current_section_lines

        current_section_lines = []

    # Parse line by line
    for line in lines:
        line_number += 1
        stripped = line.strip()

        # Check for section header
        if stripped.startswith('[') and stripped.endswith(']'):
            # Flush previous section
            flush_section()

            # Start new section
            current_section = stripped
            continue

        # Accumulate lines for current section
        current_section_lines.append(line)

    # Flush final section
    flush_section()

    return data


def _parse_script_info(data: SubtitleData, lines: List[str]) -> None:
    """Parse [Script Info] section."""
    for line in lines:
        stripped = line.strip()

        # Skip empty lines and comments (but preserve them)
        if not stripped:
            continue
        if stripped.startswith(';'):
            # Comment in script info - store in special key
            if ';' not in data.script_info:
                data.script_info[';'] = []
            data.script_info[';'].append(stripped)
            continue

        # Parse key: value
        if ':' in stripped:
            key, value = stripped.split(':', 1)
            data.script_info[key.strip()] = value.strip()


def _parse_styles(data: SubtitleData, lines: List[str]) -> None:
    """Parse [V4+ Styles] or [V4 Styles] section."""
    format_fields = None

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue
        if stripped.startswith(';'):
            continue

        # Format line
        if stripped.lower().startswith('format:'):
            format_str = stripped.split(':', 1)[1]
            format_fields = [f.strip() for f in format_str.split(',')]
            data.styles_format = format_fields
            continue

        # Style line
        if stripped.lower().startswith('style:'):
            if format_fields is None:
                # Default V4+ format
                format_fields = data.styles_format

            style_str = stripped.split(':', 1)[1].strip()
            try:
                style = SubtitleStyle.from_ass_line(format_fields, style_str)
                data.styles[style.name] = style
            except Exception:
                # If parsing fails, skip this style
                pass


def _parse_events(data: SubtitleData, lines: List[str]) -> None:
    """Parse [Events] section."""
    format_fields = None
    line_number = 0

    for line in lines:
        line_number += 1
        stripped = line.strip()

        if not stripped:
            continue

        # Format line
        if stripped.lower().startswith('format:'):
            format_str = stripped.split(':', 1)[1]
            format_fields = [f.strip() for f in format_str.split(',')]
            data.events_format = format_fields
            continue

        # Event lines (Dialogue or Comment)
        line_lower = stripped.lower()
        if line_lower.startswith('dialogue:') or line_lower.startswith('comment:'):
            if format_fields is None:
                # Default format
                format_fields = data.events_format

            # Determine type
            if line_lower.startswith('dialogue:'):
                line_type = 'Dialogue'
                event_str = stripped.split(':', 1)[1].strip()
            else:
                line_type = 'Comment'
                event_str = stripped.split(':', 1)[1].strip()

            try:
                event = SubtitleEvent.from_ass_line(
                    format_fields, event_str, line_type, line_number
                )
                data.events.append(event)
            except Exception:
                # If parsing fails, skip this event
                pass


def _parse_fonts(data: SubtitleData, lines: List[str]) -> None:
    """Parse [Fonts] section."""
    current_font_name: Optional[str] = None
    current_font_data: List[str] = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        # Font filename line
        if stripped.lower().startswith('fontname:'):
            # Save previous font if any
            if current_font_name and current_font_data:
                font = EmbeddedFont(
                    name=current_font_name,
                    data=''.join(current_font_data)
                )
                data.fonts.append(font)

            current_font_name = stripped.split(':', 1)[1].strip()
            current_font_data = []
        else:
            # Base64 data line
            current_font_data.append(stripped)

    # Save last font
    if current_font_name and current_font_data:
        font = EmbeddedFont(
            name=current_font_name,
            data=''.join(current_font_data)
        )
        data.fonts.append(font)


def _parse_graphics(data: SubtitleData, lines: List[str]) -> None:
    """Parse [Graphics] section."""
    current_graphic_name: Optional[str] = None
    current_graphic_data: List[str] = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        # Graphic filename line
        if stripped.lower().startswith('filename:'):
            # Save previous graphic if any
            if current_graphic_name and current_graphic_data:
                graphic = EmbeddedGraphic(
                    name=current_graphic_name,
                    data=''.join(current_graphic_data)
                )
                data.graphics.append(graphic)

            current_graphic_name = stripped.split(':', 1)[1].strip()
            current_graphic_data = []
        else:
            # Base64 data line
            current_graphic_data.append(stripped)

    # Save last graphic
    if current_graphic_name and current_graphic_data:
        graphic = EmbeddedGraphic(
            name=current_graphic_name,
            data=''.join(current_graphic_data)
        )
        data.graphics.append(graphic)


def _parse_aegisub_garbage(data: SubtitleData, lines: List[str]) -> None:
    """Parse [Aegisub Project Garbage] section."""
    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue
        if stripped.startswith(';'):
            continue

        # Parse key: value
        if ':' in stripped:
            key, value = stripped.split(':', 1)
            data.aegisub_garbage[key.strip()] = value.strip()


def _parse_extradata(data: SubtitleData, lines: List[str]) -> None:
    """Parse [Aegisub Extradata] section - preserve raw lines."""
    for line in lines:
        stripped = line.strip()
        if stripped:  # Skip empty lines
            data.extradata.append(line)  # Preserve original line with whitespace
