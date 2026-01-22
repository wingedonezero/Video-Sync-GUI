# vsg_core/subtitles/writers/ass_writer.py
# -*- coding: utf-8 -*-
"""
ASS subtitle file writer with full metadata preservation.

THIS IS THE SINGLE ROUNDING POINT for timing.
Float milliseconds are converted to centiseconds here and only here.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data import SubtitleData


def write_ass_file(data: 'SubtitleData', path: Path) -> None:
    """
    Write SubtitleData to ASS file.

    THIS IS WHERE TIMING ROUNDING HAPPENS.
    Float ms → centiseconds (floor).

    Args:
        data: SubtitleData to write
        path: Output path
    """
    lines = []

    # Determine section order
    section_order = data.section_order if data.section_order else _default_section_order()

    # Track what we've written
    written_sections = set()

    # Write header lines (before any section)
    for line in data.header_lines:
        lines.append(line)

    # Write sections in order
    for section in section_order:
        section_lower = section.lower()

        if section_lower == '[script info]':
            _write_script_info(data, lines)
            written_sections.add(section_lower)

        elif section_lower in ('[v4+ styles]', '[v4 styles]'):
            _write_styles(data, lines, section)
            written_sections.add('[v4+ styles]')
            written_sections.add('[v4 styles]')

        elif section_lower == '[events]':
            _write_events(data, lines)
            written_sections.add(section_lower)

        elif section_lower == '[fonts]':
            _write_fonts(data, lines)
            written_sections.add(section_lower)

        elif section_lower == '[graphics]':
            _write_graphics(data, lines)
            written_sections.add(section_lower)

        elif section_lower == '[aegisub project garbage]':
            _write_aegisub_garbage(data, lines)
            written_sections.add(section_lower)

        elif section_lower == '[aegisub extradata]':
            _write_aegisub_extradata(data, lines)
            written_sections.add(section_lower)

        elif section in data.custom_sections:
            # Custom section - write as-is
            lines.append(section)
            for line in data.custom_sections[section]:
                lines.append(line)
            lines.append('')
            written_sections.add(section_lower)

    # Write any sections not in section_order
    if '[script info]' not in written_sections and data.script_info:
        _write_script_info(data, lines)

    if '[v4+ styles]' not in written_sections and '[v4 styles]' not in written_sections and data.styles:
        _write_styles(data, lines, '[V4+ Styles]')

    if '[events]' not in written_sections and data.events:
        _write_events(data, lines)

    if '[fonts]' not in written_sections and data.fonts:
        _write_fonts(data, lines)

    if '[graphics]' not in written_sections and data.graphics:
        _write_graphics(data, lines)

    if '[aegisub project garbage]' not in written_sections and data.aegisub_garbage:
        _write_aegisub_garbage(data, lines)

    if '[aegisub extradata]' not in written_sections and data.aegisub_extradata:
        _write_aegisub_extradata(data, lines)

    # Write custom sections not in order
    for section, section_lines in data.custom_sections.items():
        if section.lower() not in written_sections:
            lines.append(section)
            for line in section_lines:
                lines.append(line)
            lines.append('')

    # Write to file
    content = '\n'.join(lines)

    # Handle encoding
    encoding = data.encoding
    if encoding == 'utf-8-sig':
        encoding = 'utf-8-sig'  # Python handles BOM
    elif data.has_bom and encoding == 'utf-8':
        encoding = 'utf-8-sig'

    with open(path, 'w', encoding=encoding, newline='\r\n') as f:
        f.write(content)


def _default_section_order() -> list:
    """Default ASS section order."""
    return [
        '[Script Info]',
        '[Aegisub Project Garbage]',
        '[V4+ Styles]',
        '[Events]',
        '[Fonts]',
        '[Graphics]',
        '[Aegisub Extradata]',
    ]


def _write_script_info(data: 'SubtitleData', lines: list) -> None:
    """Write [Script Info] section."""
    lines.append('[Script Info]')

    for key, value in data.script_info.items():
        if key == '__comments__':
            # Write comments
            for comment in value:
                lines.append(comment)
        else:
            lines.append(f'{key}: {value}')

    lines.append('')


def _write_styles(data: 'SubtitleData', lines: list, section_name: str) -> None:
    """Write [V4+ Styles] section."""
    lines.append(section_name)

    # Format line
    format_line = 'Format: ' + ', '.join(data.styles_format)
    lines.append(format_line)

    # Style lines
    for style in data.styles.values():
        values = style.to_format_values(data.styles_format)
        lines.append('Style: ' + ','.join(values))

    lines.append('')


def _write_events(data: 'SubtitleData', lines: list) -> None:
    """
    Write [Events] section.

    THIS IS WHERE TIMING ROUNDING HAPPENS.
    """
    lines.append('[Events]')

    # Format line
    format_line = 'Format: ' + ', '.join(data.events_format)
    lines.append(format_line)

    # Event lines
    for event in data.events:
        event_type = 'Comment' if event.is_comment else 'Dialogue'

        # Build values
        values = []
        for field in data.events_format:
            field_lower = field.strip().lower()

            if field_lower == 'layer':
                values.append(str(event.layer))
            elif field_lower == 'start':
                # ROUNDING HAPPENS HERE
                values.append(_format_ass_time(event.start_ms))
            elif field_lower == 'end':
                # ROUNDING HAPPENS HERE
                values.append(_format_ass_time(event.end_ms))
            elif field_lower == 'style':
                values.append(event.style)
            elif field_lower in ('name', 'actor'):
                values.append(event.name)
            elif field_lower == 'marginl':
                values.append(str(event.margin_l))
            elif field_lower == 'marginr':
                values.append(str(event.margin_r))
            elif field_lower == 'marginv':
                values.append(str(event.margin_v))
            elif field_lower == 'effect':
                values.append(event.effect)
            elif field_lower == 'text':
                values.append(event.text)
            else:
                values.append('')

        lines.append(f'{event_type}: ' + ','.join(values))

    lines.append('')


def _write_fonts(data: 'SubtitleData', lines: list) -> None:
    """Write [Fonts] section."""
    if not data.fonts:
        return

    lines.append('[Fonts]')

    for font in data.fonts:
        lines.append(f'fontname: {font.name}')
        # Write font data lines
        for data_line in font.data.split('\n'):
            lines.append(data_line)

    lines.append('')


def _write_graphics(data: 'SubtitleData', lines: list) -> None:
    """Write [Graphics] section."""
    if not data.graphics:
        return

    lines.append('[Graphics]')

    for graphic in data.graphics:
        lines.append(f'filename: {graphic.name}')
        for data_line in graphic.data.split('\n'):
            lines.append(data_line)

    lines.append('')


def _write_aegisub_garbage(data: 'SubtitleData', lines: list) -> None:
    """Write [Aegisub Project Garbage] section."""
    if not data.aegisub_garbage:
        return

    lines.append('[Aegisub Project Garbage]')

    for key, value in data.aegisub_garbage.items():
        lines.append(f'{key}: {value}')

    lines.append('')


def _write_aegisub_extradata(data: 'SubtitleData', lines: list) -> None:
    """Write [Aegisub Extradata] section."""
    if not data.aegisub_extradata:
        return

    lines.append('[Aegisub Extradata]')

    for line in data.aegisub_extradata:
        lines.append(line)

    lines.append('')


def _format_ass_time(ms: float) -> str:
    """
    Format float milliseconds to ASS timestamp.

    THIS IS THE SINGLE ROUNDING POINT.
    Uses floor() for consistency.

    Args:
        ms: Time in float milliseconds

    Returns:
        ASS timestamp (H:MM:SS.cc)
    """
    # Floor to centiseconds for consistency
    total_cs = int(math.floor(ms / 10))

    # Ensure non-negative
    if total_cs < 0:
        total_cs = 0

    cs = total_cs % 100
    total_seconds = total_cs // 100
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60

    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"
