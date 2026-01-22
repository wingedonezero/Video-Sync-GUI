# vsg_core/subtitles/writers/ass_writer.py
# -*- coding: utf-8 -*-
"""
ASS/SSA subtitle file writer with full metadata preservation.

THIS IS THE SINGLE ROUNDING POINT for timing in the entire pipeline.
All float millisecond timings are converted to ASS centiseconds here.

The writer preserves:
- Original section order
- All metadata (Script Info, Aegisub Garbage, Extradata)
- All comments
- Custom/unknown sections
- Embedded fonts and graphics
- Format line field ordering
- Proper encoding
"""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING
import codecs

if TYPE_CHECKING:
    from ..data import SubtitleData


def write_ass_file(data: 'SubtitleData', path: Path) -> None:
    """
    Write SubtitleData to ASS file.

    THIS IS THE SINGLE ROUNDING POINT - all timing converted here.

    Args:
        data: SubtitleData object to write
        path: Output file path
    """
    path = Path(path)
    lines = []

    # Determine encoding
    encoding = data.encoding
    if encoding == 'utf-8-sig':
        encoding = 'utf-8'  # We'll add BOM separately

    # Build section order - use original if available, otherwise default
    section_order = data.section_order if data.section_order else _default_section_order()

    # Ensure all sections are included
    all_sections = set(section_order)
    if data.script_info and '[Script Info]' not in all_sections:
        section_order.insert(0, '[Script Info]')
    if data.aegisub_garbage and '[Aegisub Project Garbage]' not in all_sections:
        # Insert after Script Info
        idx = section_order.index('[Script Info]') + 1 if '[Script Info]' in section_order else 0
        section_order.insert(idx, '[Aegisub Project Garbage]')
    if data.extradata and '[Aegisub Extradata]' not in all_sections:
        idx = section_order.index('[Aegisub Project Garbage]') + 1 if '[Aegisub Project Garbage]' in section_order else 1
        section_order.insert(idx, '[Aegisub Extradata]')
    if data.styles and '[V4+ Styles]' not in all_sections and '[V4 Styles]' not in all_sections:
        section_order.append('[V4+ Styles]')
    if data.events and '[Events]' not in all_sections:
        section_order.append('[Events]')
    if data.fonts and '[Fonts]' not in all_sections:
        section_order.append('[Fonts]')
    if data.graphics and '[Graphics]' not in all_sections:
        section_order.append('[Graphics]')

    # Add any custom sections not in order
    for section_name in data.custom_sections.keys():
        if section_name not in section_order:
            section_order.append(section_name)

    # Header lines (before any section)
    for line in data.header_lines:
        lines.append(line)

    # Write each section
    for section_name in section_order:
        section_lower = section_name.lower()

        # Add section comments if any
        if section_name in data.section_comments:
            for comment in data.section_comments[section_name]:
                lines.append(comment)

        if section_lower == '[script info]':
            _write_script_info(data, lines)
        elif section_lower == '[aegisub project garbage]':
            _write_aegisub_garbage(data, lines)
        elif section_lower == '[aegisub extradata]':
            _write_extradata(data, lines)
        elif section_lower in ('[v4+ styles]', '[v4 styles]'):
            _write_styles(data, lines, section_name)
        elif section_lower == '[events]':
            _write_events(data, lines)
        elif section_lower == '[fonts]':
            _write_fonts(data, lines)
        elif section_lower == '[graphics]':
            _write_graphics(data, lines)
        elif section_name in data.custom_sections:
            _write_custom_section(data, lines, section_name)

    # Join with proper line endings
    content = '\n'.join(lines)

    # Write file
    with open(path, 'w', encoding=encoding, newline='\n') as f:
        # Add BOM if original had one
        if data.has_bom:
            f.write('\ufeff')
        f.write(content)


def _default_section_order() -> list:
    """Default section order for ASS files."""
    return [
        '[Script Info]',
        '[Aegisub Project Garbage]',
        '[Aegisub Extradata]',
        '[V4+ Styles]',
        '[Events]',
        '[Fonts]',
        '[Graphics]',
    ]


def _write_script_info(data: 'SubtitleData', lines: list) -> None:
    """Write [Script Info] section."""
    if not data.script_info:
        return

    lines.append('[Script Info]')

    for key, value in data.script_info.items():
        if key == ';':
            # Comments stored under ';' key
            for comment in value:
                lines.append(comment)
        else:
            lines.append(f'{key}: {value}')

    lines.append('')  # Blank line after section


def _write_aegisub_garbage(data: 'SubtitleData', lines: list) -> None:
    """Write [Aegisub Project Garbage] section."""
    if not data.aegisub_garbage:
        return

    lines.append('[Aegisub Project Garbage]')

    for key, value in data.aegisub_garbage.items():
        lines.append(f'{key}: {value}')

    lines.append('')


def _write_extradata(data: 'SubtitleData', lines: list) -> None:
    """Write [Aegisub Extradata] section."""
    if not data.extradata:
        return

    lines.append('[Aegisub Extradata]')

    for line in data.extradata:
        lines.append(line)

    lines.append('')


def _write_styles(data: 'SubtitleData', lines: list, section_name: str = '[V4+ Styles]') -> None:
    """Write [V4+ Styles] section."""
    if not data.styles:
        return

    lines.append(section_name)

    # Format line
    format_str = ', '.join(data.styles_format)
    lines.append(f'Format: {format_str}')

    # Style lines
    for style in data.styles.values():
        style_str = style.to_ass_line(data.styles_format)
        lines.append(f'Style: {style_str}')

    lines.append('')


def _write_events(data: 'SubtitleData', lines: list) -> None:
    """
    Write [Events] section.

    THIS IS WHERE TIMING ROUNDING HAPPENS via event.to_ass_line().
    """
    if not data.events:
        return

    lines.append('[Events]')

    # Format line
    format_str = ', '.join(data.events_format)
    lines.append(f'Format: {format_str}')

    # Event lines
    for event in data.events:
        event_str = event.to_ass_line(data.events_format)
        line_type = 'Comment' if event.is_comment else 'Dialogue'
        lines.append(f'{line_type}: {event_str}')

    lines.append('')


def _write_fonts(data: 'SubtitleData', lines: list) -> None:
    """Write [Fonts] section."""
    if not data.fonts:
        return

    lines.append('[Fonts]')

    for font in data.fonts:
        lines.append(f'fontname: {font.name}')
        # Write data in chunks of ~80 chars for readability (ASS convention)
        font_data = font.data
        chunk_size = 80
        for i in range(0, len(font_data), chunk_size):
            lines.append(font_data[i:i + chunk_size])

    lines.append('')


def _write_graphics(data: 'SubtitleData', lines: list) -> None:
    """Write [Graphics] section."""
    if not data.graphics:
        return

    lines.append('[Graphics]')

    for graphic in data.graphics:
        lines.append(f'filename: {graphic.name}')
        # Write data in chunks
        graphic_data = graphic.data
        chunk_size = 80
        for i in range(0, len(graphic_data), chunk_size):
            lines.append(graphic_data[i:i + chunk_size])

    lines.append('')


def _write_custom_section(data: 'SubtitleData', lines: list, section_name: str) -> None:
    """Write a custom/unknown section (preserved raw)."""
    if section_name not in data.custom_sections:
        return

    lines.append(section_name)

    for line in data.custom_sections[section_name]:
        lines.append(line)

    lines.append('')
