# vsg_core/models/subtitles/__init__.py
"""
Centralized subtitle model definitions.

This package contains all subtitle-related data models:
- core.py: Subtitle events, styles, metadata (SubtitleData components)
- ocr.py: OCR result models (OCRResult, OCRLineResult, OCRConfig)
- edit_plan.py: Non-destructive edit plan models (future)

Import models from here for a clean API:
    from vsg_core.models.subtitles import SubtitleEvent, SubtitleStyle, OCRResult
"""

from .core import (
    EmbeddedFont,
    EmbeddedGraphic,
    OCREventData,
    OCRMetadata,
    OperationRecord,
    OperationResult,
    SteppingEventData,
    SubtitleEvent,
    SubtitleStyle,
    SyncEventData,
    format_ass_time,
    format_number,
    parse_ass_time,
)
from .ocr import OCRConfig, OCRLineResult, OCRResult

__all__ = [
    # Core subtitle models
    "SubtitleEvent",
    "SubtitleStyle",
    "OCREventData",
    "SyncEventData",
    "SteppingEventData",
    "OCRMetadata",
    "EmbeddedFont",
    "EmbeddedGraphic",
    "OperationRecord",
    "OperationResult",
    # OCR models
    "OCRConfig",
    "OCRLineResult",
    "OCRResult",
    # Timing helpers
    "parse_ass_time",
    "format_ass_time",
    "format_number",
]
