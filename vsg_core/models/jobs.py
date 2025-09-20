# vsg_core/models/jobs.py
# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional, Dict, Any, List

from .media import Track

@dataclass(frozen=True)
class JobSpec:
    sources: Dict[str, Path]
    manual_layout: list[dict] | None = None

@dataclass(frozen=True)
class Delays:
    source_delays_ms: Dict[str, int] = field(default_factory=dict)
    global_shift_ms: int = 0

@dataclass
class PlanItem:
    track: Track
    extracted_path: Optional[Path] = None
    is_default: bool = False
    is_forced_display: bool = False
    apply_track_name: bool = False
    convert_to_ass: bool = False
    rescale: bool = False
    size_multiplier: float = 1.0
    style_patch: Optional[Dict[str, Any]] = None
    user_modified_path: Optional[str] = None
    sync_to: Optional[str] = None
    is_preserved: bool = False
    is_corrected: bool = False
    # --- FIX: Added missing field ---
    correction_source: Optional[str] = None

@dataclass(frozen=True)
class MergePlan:
    items: list[PlanItem]
    delays: Delays
    chapters_xml: Path | None = None
    attachments: list[Path] = field(default_factory=list)

@dataclass(frozen=True)
class JobResult:
    status: Literal['Merged', 'Analyzed', 'Failed']
    name: str
    output: str | None = None
    delays: Dict[str, int] | None = None
    error: str | None = None
