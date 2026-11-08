# vsg_core/subtitles/ocr/line_fit.py
"""
Size positioned OCR lines from the disc.

Positioned lines (signs, notes, on-screen text) come in many sizes on the disc,
so each one is scaled to the width the disc's own text covers instead of using
the single OCR font size. Bottom and top regions keep the normal size.

Widths come from the selected font file, sized the way libass sizes fonts.
Anything that cannot be measured is left at the normal size.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont


@dataclass(frozen=True, slots=True)
class FontWidths:
    """Glyph advances of one font, in font units per character."""

    advances: dict[int, int]
    height_units: int  # What libass treats as "font size" in font units


def _height_units(font: TTFont) -> int:
    """Font-size basis as libass derives it: OS/2 win metrics, else hhea."""
    os2 = font.get("OS/2")
    if os2 is not None:
        # Read as signed: libass does, because some fonts store negatives here.
        ascent = int.from_bytes(os2.usWinAscent.to_bytes(2, "big"), "big", signed=True)
        descent = int.from_bytes(
            os2.usWinDescent.to_bytes(2, "big"), "big", signed=True
        )
        if ascent + descent != 0:
            return ascent + descent
    hhea = font["hhea"]
    return int(hhea.ascent - hhea.descent)


def load_font_widths(path: str | Path) -> FontWidths | None:
    """Read a font's advances, or None if the file cannot be used."""
    try:
        file_path = Path(path)
        font = (
            TTCollection(str(file_path)).fonts[0]
            if file_path.suffix.lower() == ".ttc"
            else TTFont(str(file_path), lazy=True)
        )
        metrics = font["hmtx"].metrics
        advances = {
            code: metrics[glyph][0]
            for code, glyph in font.getBestCmap().items()
            if glyph in metrics
        }
        units = _height_units(font)
    except Exception:  # A broken font must never fail an OCR job
        return None
    return FontWidths(advances, units) if units > 0 else None


def text_width(widths: FontWidths, text: str, font_size: float) -> float | None:
    """Width of text at font_size, or None if the font lacks a character."""
    total = 0
    for char in text:
        advance = widths.advances.get(ord(char))
        if advance is None:
            return None
        total += advance
    return total * font_size / widths.height_units


def box_scale_percent(
    width: float,
    pos_x: int,
    box_width: int,
    play_res_x: int,
    margin_l: int,
    margin_r: int,
) -> int | None:
    """Scale that sizes a positioned line to its disc box, or None for no tag.

    libass wraps at PlayResX minus the style margins wherever a line starts, so
    the result never exceeds that, or the room to the right edge of the screen.
    """
    if width <= 0 or box_width <= 0:
        return None
    limit = min(box_width, play_res_x - margin_l - margin_r, play_res_x - pos_x)
    if limit <= 0:
        return None
    scale = int(100 * limit / width)
    return scale if scale > 0 and scale != 100 else None


def find_font_file(font_name: str, fonts_dir: Path) -> str | None:
    """File of the font libass would call font_name in the fonts folder."""
    from vsg_core.font_manager import FontScanner

    for font_info in FontScanner(fonts_dir).scan(include_subdirs=True):
        # Mirror the picker's libass-name choice (full_name when it pins a
        # specific variant, else the bare family name).
        libass_name = (
            font_info.full_name
            if font_info.full_name and font_info.full_name != font_info.family_name
            else font_info.family_name
        )
        if libass_name == font_name:
            return str(font_info.file_path)
    return None
