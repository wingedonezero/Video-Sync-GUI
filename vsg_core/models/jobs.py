# vsg_core/models/jobs.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from .context_types import (
        FilterConfig,
        FontReplacements,
        ManualLayoutItem,
        SteppingQualityIssue,
        StylePatch,
        SyncStabilityIssue,
    )
    from .media import Track


@dataclass(frozen=True, slots=True)
class JobSpec:
    sources: dict[str, Path]
    manual_layout: list[ManualLayoutItem] | None = None


@dataclass(frozen=True, slots=True)
class Delays:
    source_delays_ms: dict[str, int] = field(default_factory=dict)
    raw_source_delays_ms: dict[str, float] = field(
        default_factory=dict
    )  # Unrounded delays for VideoTimestamps precision
    global_shift_ms: int = 0
    raw_global_shift_ms: float = (
        0.0  # Unrounded global shift for VideoTimestamps precision
    )


@dataclass(slots=True)
class PlanItem:
    track: Track
    extracted_path: Path | None = None
    is_default: bool = False
    is_forced_display: bool = False
    apply_track_name: bool = False
    convert_to_ass: bool = False
    rescale: bool = False
    size_multiplier: float = 1.0
    style_patch: StylePatch | None = None
    font_replacements: FontReplacements | None = (
        None  # Font replacement mappings from Font Manager
    )
    user_modified_path: str | None = None
    sync_to: str | None = None
    is_preserved: bool = False
    is_corrected: bool = False
    correction_source: str | None = None
    perform_ocr: bool = False
    container_delay_ms: int = 0
    custom_lang: str = ""
    custom_name: str = ""  # NEW: Custom track name set by user
    aspect_ratio: str | None = None  # NEW: Store original aspect ratio (e.g., "109:60")
    stepping_adjusted: bool = (
        False  # True if subtitle timestamps were adjusted for stepping corrections
    )
    frame_adjusted: bool = (
        False  # True if subtitle timestamps were adjusted for frame-level corrections
    )

    # Generated track fields (for tracks created by filtering styles from another track)
    is_generated: bool = False  # Marks this as a generated track
    source_track_id: int | None = None  # ID of the source track this was generated from
    filter_config: FilterConfig | None = (
        None  # Filter settings: mode, styles, forced_include, forced_exclude
    )
    original_style_list: list[str] = field(
        default_factory=list
    )  # Complete style list from original source (for validation)

    # Sync exclusion fields (for excluding styles from frame matching in anchor mode)
    sync_exclusion_styles: list[str] = field(
        default_factory=list
    )  # Style names to exclude/include from frame sync
    sync_exclusion_mode: str = "exclude"  # 'exclude' or 'include' styles
    sync_exclusion_original_style_list: list[str] = field(
        default_factory=list
    )  # Complete style list for validation

    # Stats from framelocked sync mode (for auditing)
    framelocked_stats: dict | None = None

    # Clamping info for negative timestamp warnings
    clamping_info: dict | None = None

    # Video-verified sync mode stats (for bitmap subtitles)
    video_verified_bitmap: bool = False
    video_verified_details: dict | None = None


@dataclass(frozen=True, slots=True)
class MergePlan:
    items: list[PlanItem]
    delays: Delays
    chapters_xml: Path | None = None
    attachments: list[Path] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class JobResult:
    """Simplified job result for public API."""

    status: Literal["Merged", "Analyzed", "Failed"]
    name: str
    output: str | None = None
    delays: dict[str, int] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Detailed result from pipeline.run_job() with all diagnostic info."""

    status: Literal["Merged", "Analyzed", "Failed"]
    name: str
    output: str | None = None
    delays: dict[str, int] | None = None
    error: str | None = None
    issues: int = 0
    stepping_sources: list[str] = field(default_factory=list)
    stepping_detected_disabled: list[str] = field(default_factory=list)
    stepping_detected_separated: list[str] = field(default_factory=list)
    stepping_quality_issues: list[SteppingQualityIssue] = field(default_factory=list)
    sync_stability_issues: list[SyncStabilityIssue] = field(default_factory=list)
