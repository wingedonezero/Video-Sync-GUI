# vsg_core/subtitles/edit_plan.py
"""
Non-destructive subtitle edit plan system.

NOTE: All model classes have been moved to vsg_core/models/subtitles/edit_plan.py
This file re-exports them for backward compatibility.

Import from vsg_core.models instead:
    from vsg_core.models import SubtitleEditPlan, EventEdit, StyleEdit
"""

from __future__ import annotations

# Re-export all models from centralized location
from vsg_core.models.subtitles.edit_plan import (
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
    "EventGroup",
    "EventEdit",
    "StyleEdit",
    "NewEventSpec",
    "NewStyleSpec",
    "GroupDefinition",
    "SubtitleEditPlan",
    "ApplyResult",
]
