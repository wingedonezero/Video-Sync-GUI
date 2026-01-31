# vsg_core/subtitles/ocr/parsers/__init__.py
"""
Subtitle Image Parsers

Parsers for extracting subtitle images and metadata from image-based formats:
    - VobSub (.sub/.idx) - DVD subtitle format
    - PGS (.sup) - Blu-ray PGS subtitle format (Phase 2)

Each parser extracts:
    - Subtitle bitmap images
    - Timing (start/end timestamps)
    - Position coordinates (x, y)
    - Palette/color information
"""

from .base import SubtitleImage, SubtitleImageParser
from .vobsub import VobSubParser

__all__ = [
    'SubtitleImage',
    'SubtitleImageParser',
    'VobSubParser',
]
