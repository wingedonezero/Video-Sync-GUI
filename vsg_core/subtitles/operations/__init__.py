# vsg_core/subtitles/operations/__init__.py
"""Subtitle operations (stepping, style patches, etc.)."""

from .stepping import apply_stepping
from .style_ops import (
    apply_font_replacement,
    apply_rescale,
    apply_size_multiplier,
    apply_style_filter,
    apply_style_patch,
)

__all__ = [
    'apply_font_replacement',
    'apply_rescale',
    'apply_size_multiplier',
    'apply_stepping',
    'apply_style_filter',
    'apply_style_patch',
]
