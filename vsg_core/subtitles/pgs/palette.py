# vsg_core/subtitles/pgs/palette.py
# -*- coding: utf-8 -*-
"""
YCbCr to RGB color conversion for PGS subtitles.
Based on SubtitleEdit's BluRaySupPalette implementation.
"""
from __future__ import annotations
from typing import Tuple


def clamp(value: float, min_val: int = 0, max_val: int = 255) -> int:
    """Clamp value to range [min_val, max_val]"""
    return int(max(min_val, min(max_val, value)))


def ycbcr_to_rgb_bt601(y: int, cr: int, cb: int) -> Tuple[int, int, int]:
    """
    Convert YCbCr to RGB using BT.601 formula (standard for SD content).

    Formula from SubtitleEdit:
        r = (y - 16) * 1.164 + (cr - 128) * 1.596
        g = (y - 16) * 1.164 - (cr - 128) * 0.813 - (cb - 128) * 0.392
        b = (y - 16) * 1.164 + (cb - 128) * 2.017

    Args:
        y: Luma (0-255)
        cr: Red chroma difference (0-255)
        cb: Blue chroma difference (0-255)

    Returns:
        Tuple of (r, g, b) values (0-255)
    """
    c = y - 16
    d = cb - 128
    e = cr - 128

    r = c * 1.164 + e * 1.596
    g = c * 1.164 - e * 0.813 - d * 0.392
    b = c * 1.164 + d * 2.017

    return (clamp(r), clamp(g), clamp(b))


def ycbcr_to_rgb_bt709(y: int, cr: int, cb: int) -> Tuple[int, int, int]:
    """
    Convert YCbCr to RGB using BT.709 formula (standard for HD content).

    Formula from SubtitleEdit:
        r = (y - 16) * 1.164 + (cr - 128) * 1.793
        g = (y - 16) * 1.164 - (cr - 128) * 0.533 - (cb - 128) * 0.213
        b = (y - 16) * 1.164 + (cb - 128) * 2.112

    Args:
        y: Luma (0-255)
        cr: Red chroma difference (0-255)
        cb: Blue chroma difference (0-255)

    Returns:
        Tuple of (r, g, b) values (0-255)
    """
    c = y - 16
    d = cb - 128
    e = cr - 128

    r = c * 1.164 + e * 1.793
    g = c * 1.164 - e * 0.533 - d * 0.213
    b = c * 1.164 + d * 2.112

    return (clamp(r), clamp(g), clamp(b))


def ycbcr_to_rgba(y: int, cr: int, cb: int, alpha: int, use_bt709: bool = False) -> Tuple[int, int, int, int]:
    """
    Convert YCbCrA to RGBA.

    Args:
        y: Luma (0-255)
        cr: Red chroma difference (0-255)
        cb: Blue chroma difference (0-255)
        alpha: Alpha channel (0-255)
        use_bt709: If True, use BT.709 formula; else use BT.601

    Returns:
        Tuple of (r, g, b, a) values (0-255)
    """
    if use_bt709:
        r, g, b = ycbcr_to_rgb_bt709(y, cr, cb)
    else:
        r, g, b = ycbcr_to_rgb_bt601(y, cr, cb)

    return (r, g, b, alpha)
