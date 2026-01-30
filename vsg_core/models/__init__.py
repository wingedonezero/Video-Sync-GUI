# vsg_core/models/__init__.py
"""
Centralized model definitions for Video-Sync-GUI.

This package is the single source of truth for all data models.
Import models from here for a clean, consistent API:

    from vsg_core.models import (
        # Core job models
        JobSpec, Delays, PlanItem, MergePlan, JobResult,
        # Media models
        Track, StreamProps, Attachment, TrackType,
        # Settings
        AppSettings, AnalysisMode, SnapMode,
        # Results
        StepStatus, StepResult,
        # Context
        Context,
        # Correction
        CorrectionVerdict, CorrectionResult, AudioSegment,
        # Subtitle models
        SubtitleEvent, SubtitleStyle, OCREventData, OCRMetadata,
        # OCR models
        OCRConfig, OCRLineResult, OCRResult,
    )

Model Organization:
    - enums.py: Core enums (TrackType, AnalysisMode, SnapMode)
    - media.py: Media/track models (Track, StreamProps, Attachment)
    - jobs.py: Job-related models (JobSpec, Delays, PlanItem, etc.)
    - settings.py: Application settings (AppSettings)
    - results.py: Pipeline result models (StepStatus, StepResult)
    - context.py: Pipeline execution context (Context)
    - correction.py: Correction models (CorrectionVerdict, AudioSegment)
    - subtitles/: Subtitle-specific models
        - core.py: Events, styles, metadata
        - ocr.py: OCR result models
"""

# Core enums
# Context
from .context import Context

# Correction models
from .correction import AudioSegment, CorrectionResult, CorrectionVerdict
from .enums import AnalysisMode, SnapMode, TrackType

# Job models
from .jobs import Delays, JobResult, JobSpec, MergePlan, PlanItem

# Media models
from .media import Attachment, StreamProps, Track

# Results
from .results import StepResult, StepStatus

# Settings
from .settings import AppSettings

# Subtitle models (re-export from subtitles subpackage)
from .subtitles import (
    EmbeddedFont,
    EmbeddedGraphic,
    OCRConfig,
    OCREventData,
    OCRLineResult,
    OCRMetadata,
    OCRResult,
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

__all__ = [
    # Enums
    "TrackType",
    "AnalysisMode",
    "SnapMode",
    "StepStatus",
    "CorrectionVerdict",
    # Media
    "StreamProps",
    "Track",
    "Attachment",
    # Jobs
    "JobSpec",
    "Delays",
    "PlanItem",
    "MergePlan",
    "JobResult",
    # Settings
    "AppSettings",
    # Results
    "StepResult",
    # Context
    "Context",
    # Correction
    "CorrectionResult",
    "AudioSegment",
    # Subtitle core
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
    # OCR
    "OCRConfig",
    "OCRLineResult",
    "OCRResult",
    # Timing helpers
    "parse_ass_time",
    "format_ass_time",
    "format_number",
]
