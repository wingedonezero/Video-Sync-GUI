# vsg_core/models/context_types.py
"""TypedDict definitions for Context and PlanItem fields.

These types define the shape of dict-based data structures used throughout
the pipeline. They provide type safety without changing runtime behavior.

Following Rules.txt Section 7c: TypedDict for external boundaries and
complex nested dict structures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Required, TypedDict

# =============================================================================
# Video Correction Types (Context.pulldown_removal_info)
# =============================================================================


@dataclass(frozen=True, slots=True)
class PulldownRemovalInfo:
    """Records details of a pulldown removal operation for audit/logging."""

    source_fps: float
    target_fps: float
    pictures_modified: int
    sequence_headers_modified: int


# =============================================================================
# Manual Layout Types (Context.manual_layout)
# =============================================================================


class ManualLayoutItem(TypedDict, total=False):
    """A single track selection from the user's manual layout.

    This represents a track the user has selected for inclusion in the
    final mux, along with all processing options they've configured.
    """

    # Core identification
    source: str  # "Source 1", "Source 2", "External"
    id: int  # Track ID within the source
    type: str  # "video", "audio", "subtitles"

    # Stream properties (from mkvmerge)
    codec_id: str
    lang: str
    name: str

    # Track flags
    is_default: bool
    is_forced_display: bool
    apply_track_name: bool

    # Processing options
    perform_ocr: bool
    convert_to_ass: bool
    rescale: bool
    size_multiplier: float

    # Custom metadata overrides
    custom_lang: str
    custom_name: str

    # Sync configuration
    sync_to: str | None  # Source key to sync this track to
    correction_source: str | None  # Source key for correction reference

    # Style modifications (subtitle tracks)
    style_patch: StylePatch | None
    font_replacements: FontReplacements | None

    # Generated track fields (for tracks created by style filtering)
    is_generated: bool
    source_track_id: int | None  # ID of source track this was generated from
    filter_config: FilterConfig | None
    original_style_list: list[str]

    # External subtitle fields
    original_path: str  # Path to external subtitle file
    needs_configuration: bool

    # Sync exclusion fields (for anchor mode)
    sync_exclusion_styles: list[str]
    sync_exclusion_mode: str  # "exclude" or "include"
    sync_exclusion_original_style_list: list[str]


# =============================================================================
# Source Settings Types (Context.source_settings)
# =============================================================================


class Source1Settings(TypedDict, total=False):
    """Settings for Source 1 (reference source)."""

    correlation_ref_track: int | None  # Audio track ID for correlation reference


class SourceNSettings(TypedDict, total=False):
    """Settings for Source 2+ (sources to be synced)."""

    correlation_source_track: int | None  # Audio track ID for correlation
    use_source_separation: bool  # Whether to use source separation for analysis


# =============================================================================
# Stepping Correction Types (Context.segment_flags)
# =============================================================================


class ClusterDetail(TypedDict):
    """Details about a single delay cluster found during stepping detection."""

    delay_ms: int
    count: int
    percentage: float
    segments: list[int]  # Segment indices belonging to this cluster


class ValidationResult(TypedDict, total=False):
    """Results from validating a stepping correction cluster."""

    cluster_delay: int
    validated: bool
    confidence: float
    method: str  # "silence", "correlation", etc.
    details: str


class SegmentFlagsEntry(TypedDict, total=False):
    """Stepping correction metadata for a single track.

    Key format in segment_flags: "{source}_{track_id}" e.g. "Source 2_1"
    """

    base_delay: Required[int]  # Base delay from correlation analysis (always present)
    cluster_details: list[ClusterDetail]
    valid_clusters: dict[str, ValidationResult]  # delay_ms string -> result
    invalid_clusters: dict[str, ValidationResult]
    validation_results: dict[str, ValidationResult]
    correction_mode: str  # "uniform", "stepped", "failed"
    fallback_mode: str | None
    subs_only: bool  # True if only subtitle adjustment, no audio correction
    audit_metadata: list[dict[str, object]] | None


# =============================================================================
# Drift Correction Types (Context.pal_drift_flags, Context.linear_drift_flags)
# =============================================================================


class DriftFlagsEntry(TypedDict, total=False):
    """Drift correction metadata for a single track.

    Used for both PAL drift (25->23.976) and linear drift detection.
    """

    detected: bool
    drift_rate: float  # ms per second of drift
    total_drift_ms: float
    correction_applied: bool
    method: str  # Detection method used
    confidence: float


# =============================================================================
# Quality Issue Types (Context.stepping_quality_issues)
# =============================================================================


class QualityIssueDetails(TypedDict, total=False):
    """Details specific to each quality issue type."""

    segment_index: int
    expected_silence_at: float
    actual_content: str
    threshold_exceeded_by: float


class SteppingQualityIssue(TypedDict):
    """A quality issue detected during stepping correction."""

    source: str  # Source key, e.g. "Source 2"
    issue_type: str  # "no_silence_found", "silence_overflow", "boundary_mismatch"
    severity: str  # "high", "medium", "low"
    message: str  # Human-readable description
    details: QualityIssueDetails


# =============================================================================
# Sync Stability Types (Context.sync_stability_issues)
# =============================================================================


class OutlierChunk(TypedDict):
    """A correlation chunk that was identified as an outlier."""

    chunk_index: int
    delay_ms: float
    deviation_ms: float


class SyncStabilityIssue(TypedDict, total=False):
    """Sync stability (correlation variance) data for a source."""

    source: str
    variance_detected: bool
    max_variance_ms: float
    std_dev_ms: float
    mean_delay_ms: float
    chunk_count: int
    outlier_count: int
    outliers: list[OutlierChunk]
    cluster_count: int
    is_stepping: bool  # True if variance suggests stepping correction needed


# =============================================================================
# PlanItem Style Types (PlanItem.style_patch, PlanItem.font_replacements)
# =============================================================================


class ASSStyleAttributes(TypedDict, total=False):
    """ASS subtitle style attributes that can be patched.

    These map to the standard ASS style format fields.
    """

    fontname: str
    fontsize: float
    primary_color: str  # "&HAABBGGRR" format
    secondary_color: str
    outline_color: str
    back_color: str
    bold: int  # -1 (true) or 0 (false)
    italic: int
    underline: int
    strikeout: int
    scale_x: float
    scale_y: float
    spacing: float
    angle: float
    border_style: int
    outline: float
    shadow: float
    alignment: int
    margin_l: int
    margin_r: int
    margin_v: int
    encoding: int


# StylePatch maps style names to their attribute overrides
StylePatch = dict[str, ASSStyleAttributes]


class FontReplacement(TypedDict, total=False):
    """Font replacement configuration for a single style."""

    original_font: str
    new_font_name: str
    font_file_path: str | None  # Path to the replacement font file


# FontReplacements maps style names to their font replacement config
FontReplacements = dict[str, FontReplacement]


# =============================================================================
# PlanItem Filter Types (PlanItem.filter_config)
# =============================================================================


class FilterConfig(TypedDict, total=False):
    """Configuration for style-based track filtering.

    Used when generating a new track by filtering styles from an existing track.
    """

    filter_mode: str  # "include" or "exclude"
    filter_styles: list[str]  # Style names to include/exclude
    forced_include: list[int]  # Event indices to always include
    forced_exclude: list[int]  # Event indices to always exclude


# =============================================================================
# Video Verified Types (Context.video_verified_sources)
# =============================================================================


class VideoVerifiedResult(TypedDict, total=False):
    """Result from video-verified subtitle sync for a source.

    Stores the original and corrected delay values after frame matching.
    """

    original_delay_ms: float
    corrected_delay_ms: float
    details: dict[str, object]  # Frame matching details


# =============================================================================
# Correlation Results Types (used in analysis steps)
# =============================================================================


class CorrelationChunkResult(TypedDict, total=False):
    """Result from correlating a single audio chunk."""

    chunk_index: int
    start_s: float
    end_s: float
    delay_ms: float
    raw_delay_ms: float
    match_pct: float
    accepted: bool
    rejection_reason: str | None


class CorrelationSummary(TypedDict, total=False):
    """Summary of correlation analysis for a source."""

    source: str
    final_delay_ms: int
    raw_delay_ms: float
    chunk_count: int
    accepted_count: int
    confidence: float
    method: str  # "median", "mode", "weighted", etc.
    variance_ms: float
    is_uniform: bool
