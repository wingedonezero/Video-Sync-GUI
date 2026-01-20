# vsg_core/subtitles/ocr/__init__.py
# -*- coding: utf-8 -*-
"""
Integrated OCR System for VOB and PGS Subtitles

This module provides a complete OCR pipeline for converting image-based subtitles
(VobSub .sub/.idx and PGS .sup) to text-based formats (ASS/SRT).

Components:
    - parsers: Extract subtitle images and metadata from VOB/PGS files
    - preprocessing: Adaptive image preprocessing for optimal OCR accuracy
    - engine: Tesseract OCR wrapper with confidence tracking
    - postprocess: Pattern fixes and dictionary validation
    - report: OCR quality reporting (unknown words, confidence, fixes)
    - output: ASS/SRT generation with position support

The pipeline is designed to:
    1. Parse image-based subtitle formats, extracting timing and position
    2. Preprocess images adaptively based on quality analysis
    3. Run OCR with confidence tracking per line
    4. Apply pattern-based and dictionary-validated fixes
    5. Generate output with position tags for non-bottom subtitles
    6. Report unknown words and low-confidence results
"""

from .engine import OCREngine
from .pipeline import OCRPipeline
from .report import OCRReport, UnknownWord, LowConfidenceLine

__all__ = [
    'OCREngine',
    'OCRPipeline',
    'OCRReport',
    'UnknownWord',
    'LowConfidenceLine',
]
