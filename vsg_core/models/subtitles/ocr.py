# vsg_core/models/subtitles/ocr.py
"""
Centralized OCR model definitions.

This module contains the canonical OCR result dataclasses used throughout
the OCR pipeline. Previously these were duplicated in engine.py and backends.py.

All OCR backends and engines should import from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OCRConfig:
    """Configuration for OCR engine."""

    language: str = "eng"
    psm: int = 6  # Block mode - works better for DVD subtitles than line mode
    oem: int = 3  # Default - use LSTM if available
    char_whitelist: str = ""  # Characters to allow (empty = all)
    char_blacklist: str = "|"  # Exclude pipe which is often misread

    # Confidence thresholds
    min_confidence: float = 0.0  # Minimum confidence to accept (0-100)
    low_confidence_threshold: float = 60.0  # Flag if below this

    # Multi-pass settings
    enable_multi_pass: bool = True  # Retry with different settings if low confidence
    fallback_psm: int = 4  # PSM to use on retry (single column)


@dataclass
class OCRLineResult:
    """
    Result for a single OCR line.

    Unified model combining fields from both engine.py and backends.py.
    """

    text: str
    confidence: float  # 0-100 scale
    word_confidences: list[tuple[str, float]] = field(default_factory=list)

    # Backend identification (from backends.py)
    backend: str = "unknown"

    # Tesseract-specific fields (from engine.py)
    psm_used: int = 7
    was_retry: bool = False


@dataclass
class OCRResult:
    """
    Complete OCR result for a subtitle image.

    Unified model combining fields from both engine.py and backends.py.
    """

    text: str  # Full recognized text
    lines: list[OCRLineResult] = field(default_factory=list)
    average_confidence: float = 0.0
    min_confidence: float = 0.0
    low_confidence: bool = False
    error: str | None = None

    # Backend identification (from backends.py)
    backend: str = "unknown"

    @property
    def success(self) -> bool:
        """Check if OCR was successful."""
        return self.error is None and len(self.text.strip()) > 0
