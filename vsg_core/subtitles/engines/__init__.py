# vsg_core/subtitles/engines/__init__.py
# -*- coding: utf-8 -*-
"""OCR engine integrations."""

from .tesseract import TesseractEngine, OCRResult

__all__ = ['TesseractEngine', 'OCRResult']
