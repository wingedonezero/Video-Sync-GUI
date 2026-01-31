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
    # Data containers
    'SubtitleData',
    'SubtitleEvent',
    'SubtitleStyle',
    'OCREventData',
    'OCRMetadata',
    'SyncEventData',
    'SteppingEventData',
    'OperationRecord',
    'OperationResult',
    'EmbeddedFont',
    'EmbeddedGraphic',
    # Edit plan system
    'SubtitleEditPlan',
    'EventEdit',
    'StyleEdit',
    'NewEventSpec',
    'NewStyleSpec',
    'GroupDefinition',
    'EventGroup',
    'ApplyResult',
]
