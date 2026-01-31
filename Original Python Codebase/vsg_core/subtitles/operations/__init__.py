# vsg_core/subtitles/operations/__init__.py
# -*- coding: utf-8 -*-
"""Subtitle operations (stepping, style patches, etc.)."""

from .stepping import apply_stepping
from .style_ops import (
    apply_style_patch,
    apply_font_replacement,
    apply_size_multiplier,
    apply_rescale,
    apply_style_filter,
)

__all__ = [
    'apply_stepping',
    'apply_style_patch',
    'apply_font_replacement',
    'apply_size_multiplier',
    'apply_rescale',
    'apply_style_filter',
]
