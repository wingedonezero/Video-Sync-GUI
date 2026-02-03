# vsg_core/subtitles/parsers/ass_parser.py
"""
ASS/SSA subtitle file parser with full metadata preservation.

Preserves EVERYTHING:
- All sections in original order
- All metadata (Script Info, Aegisub Garbage, Extradata)
- Comments (lines starting with ;)
- Unknown/custom sections
- Embedded fonts and graphics
- Format line field ordering
- Encoding and BOM
"""

from __future__ import annotations

import codecs
from pathlib import Path

from ..data import (
    EmbeddedFont,
    EmbeddedGraphic,
    SubtitleData,
    SubtitleEvent,
    SubtitleStyle,
)

# Encodings to try when auto-detecting
ENCODINGS_TO_TRY = [
    "utf-8-sig",  # UTF-8 with BOM
    "utf-8",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "shift_jis",
    "gbk",
    "gb2312",
    "big5",
    "cp1252",
    "latin1",
]


def detect_encoding(path: Path) -> tuple[str, bool]:
    """
    Detect file encoding.

    Returns:
        (encoding_name, has_bom)
    """
    with open(path, "rb") as f:
        raw = f.read(4)

    # Check for BOM
    if raw.startswith(codecs.BOM_UTF8):
        return ("utf-8-sig", True)
    if raw.startswith(codecs.BOM_UTF16_LE):
        return ("utf-16-le", True)
    if raw.startswith(codecs.BOM_UTF16_BE):
        return ("utf-16-be", True)

    # Try each encoding
    for encoding in ENCODINGS_TO_TRY:
        try:
            with open(path, encoding=encoding) as f:
                f.read()
            return (encoding, encoding == "utf-8-sig")
        except (UnicodeDecodeError, LookupError):
            continue

    return ("utf-8", False)


def parse_ass_file(path: Path) -> SubtitleData:
    """
    Parse ASS/SSA file with full metadata preservation.

    Args:
        path: Path to ASS/SSA file

    Returns:
        SubtitleData with all data preserved
    """
    path = Path(path)
    encoding, has_bom = detect_encoding(path)

    with open(path, encoding=encoding) as f:
        content = f.read()

    lines = content.splitlines()

    # Initialize data
    data = SubtitleData(
        source_path=path,
        source_format="ass" if path.suffix.lower() == ".ass" else "ssa",
        encoding=encoding,
        has_bom=has_bom,
    )

    # Parse state
    current_section: str | None = None
    current_lines: list[str] = []
    event_index = 0

    def flush_section():
        """Process accumulated section lines."""
        nonlocal current_section, current_lines, event_index

        if current_section is None:
            # Lines before any section
            data.header_lines = current_lines
        else:
            # Track section order
            if current_section not in data.section_order:
                data.section_order.append(current_section)

            section_lower = current_section.lower()

            if section_lower == "[script info]":
                _parse_script_info(data, current_lines)
            elif section_lower in ("[v4+ styles]", "[v4 styles]"):
                _parse_styles(data, current_lines)
            elif section_lower == "[events]":
                event_index = _parse_events(data, current_lines, event_index)
            elif section_lower == "[fonts]":
                _parse_fonts(data, current_lines)
            elif section_lower == "[graphics]":
                _parse_graphics(data, current_lines)
            elif section_lower == "[aegisub project garbage]":
                _parse_aegisub_garbage(data, current_lines)
            elif section_lower == "[aegisub extradata]":
                _parse_aegisub_extradata(data, current_lines)
            else:
                # Unknown section - preserve as raw lines
                data.custom_sections[current_section] = current_lines

        current_lines = []

    # Parse line by line
    for line in lines:
        stripped = line.strip()

        # Section header
        if stripped.startswith("[") and stripped.endswith("]"):
            flush_section()
            current_section = stripped
            continue

        current_lines.append(line)

    # Flush final section
    flush_section()

    return data


def _parse_script_info(data: SubtitleData, lines: list[str]) -> None:
    """Parse [Script Info] section."""
    comments_key = "__comments__"

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        # Comment line
        if stripped.startswith(";"):
            if comments_key not in data.script_info:
                data.script_info[comments_key] = []
            data.script_info[comments_key].append(stripped)
            continue

        # Key: Value
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            data.script_info[key.strip()] = value.strip()


def _parse_styles(data: SubtitleData, lines: list[str]) -> None:
    """Parse [V4+ Styles] or [V4 Styles] section."""
    format_fields = None

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith(";"):
            continue

        # Format line
        if stripped.lower().startswith("format:"):
            format_str = stripped[7:].strip()
            format_fields = [f.strip() for f in format_str.split(",")]
            data.styles_format = format_fields
            continue

        # Style line
        if stripped.lower().startswith("style:"):
            if format_fields is None:
                # Use default format
                format_fields = data.styles_format

            style_str = stripped[6:].strip()
            values = [v.strip() for v in style_str.split(",")]

            style = SubtitleStyle.from_format_line(format_fields, values)
            style._original_line = stripped
            data.styles[style.name] = style


def _parse_events(data: SubtitleData, lines: list[str], start_index: int) -> int:
    """
    Parse [Events] section.

    Returns:
        Next event index
    """
    format_fields = None
    event_index = start_index

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith(";"):
            continue

        # Format line
        if stripped.lower().startswith("format:"):
            format_str = stripped[7:].strip()
            format_fields = [f.strip() for f in format_str.split(",")]
            data.events_format = format_fields
            continue

        # Dialogue or Comment line
        is_comment = False
        event_str = None

        if stripped.lower().startswith("dialogue:"):
            event_str = stripped[9:].strip()
        elif stripped.lower().startswith("comment:"):
            event_str = stripped[8:].strip()
            is_comment = True
        else:
            continue

        if format_fields is None:
            format_fields = data.events_format

        # Split values (careful: text may contain commas)
        # Count fields before Text, split that many times
        text_idx = None
        for i, f in enumerate(format_fields):
            if f.strip().lower() == "text":
                text_idx = i
                break

        if text_idx is not None:
            values = event_str.split(",", text_idx)
        else:
            values = event_str.split(",")

        event = SubtitleEvent.from_format_line(format_fields, values, is_comment)
        event._original_line = stripped
        event.original_index = event_index
        data.events.append(event)
        event_index += 1

    return event_index


def _parse_fonts(data: SubtitleData, lines: list[str]) -> None:
    """Parse [Fonts] section."""
    current_name = None
    current_data_lines = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        # Font name line
        if stripped.lower().startswith("fontname:"):
            # Save previous font
            if current_name:
                data.fonts.append(
                    EmbeddedFont(name=current_name, data="\n".join(current_data_lines))
                )
            current_name = stripped[9:].strip()
            current_data_lines = []
        else:
            # Font data line
            current_data_lines.append(stripped)

    # Save last font
    if current_name:
        data.fonts.append(
            EmbeddedFont(name=current_name, data="\n".join(current_data_lines))
        )


def _parse_graphics(data: SubtitleData, lines: list[str]) -> None:
    """Parse [Graphics] section."""
    current_name = None
    current_data_lines = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.lower().startswith("filename:"):
            if current_name:
                data.graphics.append(
                    EmbeddedGraphic(
                        name=current_name, data="\n".join(current_data_lines)
                    )
                )
            current_name = stripped[9:].strip()
            current_data_lines = []
        else:
            current_data_lines.append(stripped)

    if current_name:
        data.graphics.append(
            EmbeddedGraphic(name=current_name, data="\n".join(current_data_lines))
        )


def _parse_aegisub_garbage(data: SubtitleData, lines: list[str]) -> None:
    """Parse [Aegisub Project Garbage] section."""
    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith(";"):
            continue

        if ":" in stripped:
            key, value = stripped.split(":", 1)
            data.aegisub_garbage[key.strip()] = value.strip()


def _parse_aegisub_extradata(data: SubtitleData, lines: list[str]) -> None:
    """Parse [Aegisub Extradata] section - preserve as raw lines."""
    for line in lines:
        stripped = line.strip()
        if stripped:
            data.aegisub_extradata.append(stripped)
