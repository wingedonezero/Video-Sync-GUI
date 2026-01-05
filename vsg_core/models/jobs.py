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
    raw_source_delays_ms: Dict[str, float] = field(default_factory=dict)  # Raw delays with raw global shift for VideoTimestamps
    global_shift_ms: int = 0
    raw_global_shift_ms: float = 0.0  # Raw global shift for VideoTimestamps precision

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
    correction_source: Optional[str] = None
    perform_ocr: bool = False
    perform_ocr_cleanup: bool = False
    container_delay_ms: int = 0
    custom_lang: str = ''
    custom_name: str = ''  # NEW: Custom track name set by user
    aspect_ratio: Optional[str] = None  # NEW: Store original aspect ratio (e.g., "109:60")
    stepping_adjusted: bool = False  # True if subtitle timestamps were adjusted for stepping corrections

    # Generated track fields (for tracks created by filtering styles from another track)
    is_generated: bool = False  # Marks this as a generated track
    generated_source_track_id: Optional[int] = None  # ID of the source track this was generated from
    generated_source_path: Optional[str] = None  # Path to source subtitle file
    generated_filter_mode: str = 'exclude'  # 'include' or 'exclude' styles
    generated_filter_styles: List[str] = field(default_factory=list)  # Style names to include/exclude
    generated_original_style_list: List[str] = field(default_factory=list)  # Complete style list from original source (for validation)
    generated_verify_only_lines_removed: bool = True  # Verify only event lines removed, nothing else changed

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
