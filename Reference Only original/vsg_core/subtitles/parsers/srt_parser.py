# vsg_core/subtitles/parsers/srt_parser.py
"""
SRT and VTT subtitle file parsers.

Converts to SubtitleData with float millisecond timing.
SRT indices are preserved for round-trip if needed.
"""

from __future__ import annotations

import codecs
import re
from pathlib import Path

from ..data import SubtitleData, SubtitleEvent, SubtitleStyle

# Encodings to try
ENCODINGS_TO_TRY = [
    "utf-8-sig",
    "utf-8",
    "utf-16",
    "cp1252",
    "latin1",
]


def detect_encoding(path: Path) -> tuple[str, bool]:
    """Detect file encoding."""
    with open(path, "rb") as f:
        raw = f.read(4)

    if raw.startswith(codecs.BOM_UTF8):
        return ("utf-8-sig", True)
    if raw.startswith(codecs.BOM_UTF16_LE):
        return ("utf-16-le", True)

    for encoding in ENCODINGS_TO_TRY:
        try:
            with open(path, encoding=encoding) as f:
                f.read()
            return (encoding, encoding == "utf-8-sig")
        except (UnicodeDecodeError, LookupError):
            continue

    return ("utf-8", False)


def parse_srt_file(path: Path) -> SubtitleData:
    """
    Parse SRT file to SubtitleData.

    Args:
        path: Path to SRT file

    Returns:
        SubtitleData with float ms timing
    """
    path = Path(path)
    encoding, has_bom = detect_encoding(path)

    with open(path, encoding=encoding) as f:
        content = f.read()

    data = SubtitleData(
        source_path=path,
        source_format="srt",
        encoding=encoding,
        has_bom=has_bom,
    )

    # Add default style for ASS conversion
    data.styles["Default"] = SubtitleStyle.default()

    # SRT timing pattern: 00:00:00,000 --> 00:00:00,000
    timing_pattern = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})"
    )

    # Split into blocks (separated by blank lines)
    blocks = re.split(r"\n\s*\n", content.strip())

    for block_idx, block in enumerate(blocks):
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # First line might be index
        first_line = lines[0].strip()
        timing_line_idx = 0

        # Check if first line is a number (SRT index)
        srt_index = None
        if first_line.isdigit():
            srt_index = int(first_line)
            timing_line_idx = 1

        if timing_line_idx >= len(lines):
            continue

        # Parse timing line
        timing_match = timing_pattern.match(lines[timing_line_idx].strip())
        if not timing_match:
            continue

        # Extract timing as float ms
        start_ms = (
            int(timing_match.group(1)) * 3600000
            + int(timing_match.group(2)) * 60000
            + int(timing_match.group(3)) * 1000
            + int(timing_match.group(4))
        )
        end_ms = (
            int(timing_match.group(5)) * 3600000
            + int(timing_match.group(6)) * 60000
            + int(timing_match.group(7)) * 1000
            + int(timing_match.group(8))
        )

        # Remaining lines are text
        text_lines = lines[timing_line_idx + 1 :]
        text = "\n".join(text_lines)

        # Convert basic HTML tags to ASS
        text = _convert_srt_tags_to_ass(text)

        event = SubtitleEvent(
            start_ms=float(start_ms),
            end_ms=float(end_ms),
            text=text,
            style="Default",
            srt_index=srt_index,
            original_index=block_idx,
        )
        data.events.append(event)

    return data


def parse_vtt_file(path: Path) -> SubtitleData:
    """
    Parse WebVTT file to SubtitleData.

    Args:
        path: Path to VTT file

    Returns:
        SubtitleData with float ms timing
    """
    path = Path(path)
    encoding, has_bom = detect_encoding(path)

    with open(path, encoding=encoding) as f:
        content = f.read()

    data = SubtitleData(
        source_path=path,
        source_format="vtt",
        encoding=encoding,
        has_bom=has_bom,
    )

    data.styles["Default"] = SubtitleStyle.default()

    # VTT timing: 00:00:00.000 --> 00:00:00.000
    # Hours are optional
    timing_pattern = re.compile(
        r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[.](\d{3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})[.](\d{3})"
    )

    # Skip WEBVTT header
    lines = content.split("\n")
    start_idx = 0
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("WEBVTT"):
            start_idx = i + 1
            break

    # Rejoin and split into blocks
    content = "\n".join(lines[start_idx:])
    blocks = re.split(r"\n\s*\n", content.strip())

    for block_idx, block in enumerate(blocks):
        lines = block.strip().split("\n")
        if not lines:
            continue

        # Find timing line
        timing_match = None
        timing_line_idx = 0

        for i, line in enumerate(lines):
            match = timing_pattern.match(line.strip())
            if match:
                timing_match = match
                timing_line_idx = i
                break

        if not timing_match:
            continue

        # Extract timing
        h1 = int(timing_match.group(1) or 0)
        m1 = int(timing_match.group(2))
        s1 = int(timing_match.group(3))
        ms1 = int(timing_match.group(4))

        h2 = int(timing_match.group(5) or 0)
        m2 = int(timing_match.group(6))
        s2 = int(timing_match.group(7))
        ms2 = int(timing_match.group(8))

        start_ms = h1 * 3600000 + m1 * 60000 + s1 * 1000 + ms1
        end_ms = h2 * 3600000 + m2 * 60000 + s2 * 1000 + ms2

        # Text is after timing line
        text_lines = lines[timing_line_idx + 1 :]
        text = "\n".join(text_lines)

        # Convert VTT tags
        text = _convert_vtt_tags_to_ass(text)

        event = SubtitleEvent(
            start_ms=float(start_ms),
            end_ms=float(end_ms),
            text=text,
            style="Default",
            original_index=block_idx,
        )
        data.events.append(event)

    return data


def _convert_srt_tags_to_ass(text: str) -> str:
    """Convert SRT HTML tags to ASS override tags."""
    # <b>text</b> -> {\b1}text{\b0}
    text = re.sub(r"<b>", r"{\\b1}", text, flags=re.IGNORECASE)
    text = re.sub(r"</b>", r"{\\b0}", text, flags=re.IGNORECASE)

    # <i>text</i> -> {\i1}text{\i0}
    text = re.sub(r"<i>", r"{\\i1}", text, flags=re.IGNORECASE)
    text = re.sub(r"</i>", r"{\\i0}", text, flags=re.IGNORECASE)

    # <u>text</u> -> {\u1}text{\u0}
    text = re.sub(r"<u>", r"{\\u1}", text, flags=re.IGNORECASE)
    text = re.sub(r"</u>", r"{\\u0}", text, flags=re.IGNORECASE)

    # <font color="...">text</font> -> {\c&H...&}text{\c}
    def convert_color(match):
        color = match.group(1)
        # Convert #RRGGBB to ASS &HBBGGRR&
        if color.startswith("#"):
            color = color[1:]
            if len(color) == 6:
                r, g, b = color[0:2], color[2:4], color[4:6]
                return r"{\\c&H" + b + g + r + "&}"
        return ""

    text = re.sub(
        r'<font\s+color=["\']?([^"\'>\s]+)["\']?\s*>',
        convert_color,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"</font>", r"{\\c}", text, flags=re.IGNORECASE)

    # Remove other HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Convert \n to ASS line break
    text = text.replace("\n", "\\N")

    return text


def _convert_vtt_tags_to_ass(text: str) -> str:
    """Convert VTT tags to ASS override tags."""
    # VTT uses similar tags to SRT
    text = _convert_srt_tags_to_ass(text)

    # VTT-specific: <c.classname>text</c>
    text = re.sub(r"<c[^>]*>", "", text)
    text = re.sub(r"</c>", "", text)

    # Voice spans: <v name>text</v>
    text = re.sub(r"<v[^>]*>", "", text)
    text = re.sub(r"</v>", "", text)

    return text
