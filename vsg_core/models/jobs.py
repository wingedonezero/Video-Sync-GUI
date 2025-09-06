# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from .media import Track
from .enums import SourceRole

@dataclass(frozen=True)
class JobSpec:
    ref: Path
    sec: Path | None = None
    ter: Path | None = None
    # When present, this is the Manual Selection payload from the UI (list of dicts).
    manual_layout: list[dict] | None = None

@dataclass(frozen=True)
class Delays:
    secondary_ms: int | None = None
    tertiary_ms: int | None = None
    global_shift_ms: int = 0  # computed from min([0, sec?, ter?])

@dataclass(frozen=True)
class PlanItem:
    track: Track
    extracted_path: Path | None = None  # filled after extraction
    # UI flags:
    is_default: bool = False
    is_forced_display: bool = False       # subs only
    apply_track_name: bool = False
    convert_to_ass: bool = False          # srt -> ass
    rescale: bool = False                 # ASS/SSA PlayRes match
    size_multiplier: float = 1.0          # subs only

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
    delay_sec: int | None = None
    delay_ter: int | None = None
    error: str | None = None
