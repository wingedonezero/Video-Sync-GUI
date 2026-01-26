# vsg_core/subtitles/__init__.py
# -*- coding: utf-8 -*-
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
    SubtitleData,
    SubtitleEvent,
    SubtitleStyle,
    OCREventData,
    OCRMetadata,
    SyncEventData,
    SteppingEventData,
    OperationRecord,
    OperationResult,
    EmbeddedFont,
    EmbeddedGraphic,
)

from .edit_plan import (
    SubtitleEditPlan,
    EventEdit,
    StyleEdit,
    NewEventSpec,
    NewStyleSpec,
    GroupDefinition,
    EventGroup,
    ApplyResult,
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
