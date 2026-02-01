# vsg_core/subtitles/__init__.py
"""
Unified subtitle processing system.

This package provides:
- SubtitleData: Universal container for all subtitle formats
- SubtitleEditPlan: Non-destructive edit plan system
- Parsers for ASS, SRT, VTT formats
- Writers for ASS, SRT formats
- Operations: sync, stepping, style modifications
"""

from .data import (
    EmbeddedFont,
    EmbeddedGraphic,
    OCREventData,
    OCRMetadata,
    OperationRecord,
    OperationResult,
    SteppingEventData,
    SubtitleData,
    SubtitleEvent,
    SubtitleStyle,
    SyncEventData,
)
from .edit_plan import (
    ApplyResult,
    EventEdit,
    EventGroup,
    GroupDefinition,
    NewEventSpec,
    NewStyleSpec,
    StyleEdit,
    SubtitleEditPlan,
)

__all__ = [
    "ApplyResult",
    "EmbeddedFont",
    "EmbeddedGraphic",
    "EventEdit",
    "EventGroup",
    "GroupDefinition",
    "NewEventSpec",
    "NewStyleSpec",
    "OCREventData",
    "OCRMetadata",
    "OperationRecord",
    "OperationResult",
    "SteppingEventData",
    "StyleEdit",
    # Data containers
    "SubtitleData",
    # Edit plan system
    "SubtitleEditPlan",
    "SubtitleEvent",
    "SubtitleStyle",
    "SyncEventData",
]
