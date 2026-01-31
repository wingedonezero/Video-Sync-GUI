# vsg_core/orchestrator/steps/context.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vsg_core.models.jobs import Delays, PlanItem
from vsg_core.models.settings import AppSettings

if TYPE_CHECKING:
    from vsg_core.audit import AuditTrail

@dataclass
class Context:
    # Provided by Orchestrator entry
    settings: AppSettings
    settings_dict: dict[str, Any]
    tool_paths: dict[str, str | None]
    log: Callable[[str], None]
    progress: Callable[[float], None]
    output_dir: str
    temp_dir: Path
    audit: AuditTrail | None = None  # Pipeline audit trail for debugging
    sources: dict[str, str] = field(default_factory=dict)
    and_merge: bool = False
    manual_layout: list[dict[str, Any]] = field(default_factory=list)
    attachment_sources: list[str] = field(default_factory=list)

    # Per-source correlation settings (from job layout)
    # Format: {'Source 1': {'correlation_ref_track': 0}, 'Source 2': {'correlation_source_track': 1, 'use_source_separation': True}, ...}
    source_settings: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Filled along the pipeline
    delays: Delays | None = None
    extracted_items: list[PlanItem] | None = None
    chapters_xml: str | None = None
    attachments: list[str] | None = None

    # Stores flags for tracks that need segmented (stepping) correction
    segment_flags: dict[str, dict] = field(default_factory=dict)

    # Stores flags for tracks that need PAL drift correction
    pal_drift_flags: dict[str, dict] = field(default_factory=dict)

    # Stores flags for tracks that need linear drift correction
    linear_drift_flags: dict[str, dict] = field(default_factory=dict)

    # NEW FIELDS: Container delay tracking
    # Store Source 1's reference audio container delay for chain calculation
    source1_audio_container_delay_ms: int = 0

    # Store all container delays by source and track ID for logging/reference
    # Format: {source_key: {track_id: delay_ms}}
    container_delays: dict[str, dict[int, int]] = field(default_factory=dict)

    # A flag to determine if a global shift is necessary
    global_shift_is_required: bool = False

    # Timing sync mode ('positive_only', 'allow_negative', or 'preserve_existing')
    sync_mode: str = 'positive_only'

    # NEW: Track which sources had stepping detected (for final report)
    stepping_sources: list[str] = field(default_factory=list)

    # NEW: Track sources where stepping was detected but correction is disabled
    stepping_detected_disabled: list[str] = field(default_factory=list)

    # NEW: Track sources where stepping was detected but skipped due to source separation
    # These need manual review since correction is unreliable on separated stems
    stepping_detected_separated: list[str] = field(default_factory=list)

    # Store EDLs (Edit Decision Lists) for stepping correction by source
    # Format: {source_key: List[AudioSegment]}
    stepping_edls: dict[str, list[Any]] = field(default_factory=dict)

    # Store stepping quality issues for reporting
    # Format: [{'source': str, 'issue_type': str, 'severity': str, 'message': str, 'details': dict}]
    stepping_quality_issues: list[dict[str, Any]] = field(default_factory=list)

    # Store sync stability issues (correlation variance) for reporting
    # Format: [{'source': str, 'variance_detected': bool, 'max_variance_ms': float, 'outliers': list, 'details': dict}]
    sync_stability_issues: list[dict[str, Any]] = field(default_factory=list)

    # Flag if any subtitle track used raw delay fallback due to no scene matches
    # (correlation-frame-snap mode couldn't find scenes to verify against)
    correlation_snap_no_scenes_fallback: bool = False

    # Results/summaries
    out_file: str | None = None
    tokens: list[str] | None = None
