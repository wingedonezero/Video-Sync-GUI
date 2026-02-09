# vsg_core/orchestrator/steps/context.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from vsg_core.audit import AuditTrail
    from vsg_core.correction.stepping import AudioSegment
    from vsg_core.models.context_types import (
        DriftFlagsEntry,
        ManualLayoutItem,
        SegmentFlagsEntry,
        Source1Settings,
        SourceNSettings,
        SteppingQualityIssue,
        SyncStabilityIssue,
        VideoVerifiedResult,
    )
    from vsg_core.models.jobs import Delays, PlanItem
    from vsg_core.models.settings import AppSettings
    from vsg_core.reporting import DebugOutputPaths


@dataclass(slots=True)
class Context:
    # Provided by Orchestrator entry
    settings: AppSettings
    tool_paths: dict[str, str | None]
    log: Callable[[str], None]
    progress: Callable[[float], None]
    output_dir: str
    temp_dir: Path
    audit: AuditTrail | None = None  # Pipeline audit trail for debugging
    debug_paths: DebugOutputPaths | None = None  # Debug output paths for this job
    sources: dict[str, str] = field(default_factory=dict)
    and_merge: bool = False
    manual_layout: list[ManualLayoutItem] = field(default_factory=list)
    attachment_sources: list[str] = field(default_factory=list)

    # Per-source correlation settings (from job layout)
    # Format: {'Source 1': {'correlation_ref_track': 0}, 'Source 2': {'correlation_source_track': 1, 'use_source_separation': True}, ...}
    source_settings: dict[str, Source1Settings | SourceNSettings] = field(
        default_factory=dict
    )

    # Filled along the pipeline
    delays: Delays | None = None
    extracted_items: list[PlanItem] | None = None
    chapters_xml: str | None = None
    attachments: list[str] | None = None

    # Stores flags for tracks that need segmented (stepping) correction
    # Key format: "{source}_{track_id}" e.g. "Source 2_1"
    segment_flags: dict[str, SegmentFlagsEntry] = field(default_factory=dict)

    # Stores flags for tracks that need PAL drift correction
    pal_drift_flags: dict[str, DriftFlagsEntry] = field(default_factory=dict)

    # Stores flags for tracks that need linear drift correction
    linear_drift_flags: dict[str, DriftFlagsEntry] = field(default_factory=dict)

    # NEW FIELDS: Container delay tracking
    # Store Source 1's reference audio container delay for chain calculation
    source1_audio_container_delay_ms: int = 0

    # Store all container delays by source and track ID for logging/reference
    # Format: {source_key: {track_id: delay_ms}}
    container_delays: dict[str, dict[int, int]] = field(default_factory=dict)

    # A flag to determine if a global shift is necessary
    global_shift_is_required: bool = False

    # Timing sync mode ('positive_only', 'allow_negative', or 'preserve_existing')
    sync_mode: str = "positive_only"

    # NEW: Track which sources had stepping detected (for final report)
    stepping_sources: list[str] = field(default_factory=list)

    # NEW: Track sources where stepping was detected but correction is disabled
    stepping_detected_disabled: list[str] = field(default_factory=list)

    # NEW: Track sources where stepping was detected but skipped due to source separation
    # These need manual review since correction is unreliable on separated stems
    stepping_detected_separated: list[str] = field(default_factory=list)

    # Store EDLs (Edit Decision Lists) for stepping correction by source
    stepping_edls: dict[str, list[AudioSegment]] = field(default_factory=dict)

    # Store stepping quality issues for reporting
    stepping_quality_issues: list[SteppingQualityIssue] = field(default_factory=list)

    # Store sync stability issues (correlation variance) for reporting
    sync_stability_issues: list[SyncStabilityIssue] = field(default_factory=list)

    # Cache video-verified subtitle sync results per source
    # Format: {"Source 2": {"original_delay_ms": 100.0, "corrected_delay_ms": 102.5, ...}}
    video_verified_sources: dict[str, VideoVerifiedResult] = field(default_factory=dict)

    # Subtitle-specific delays (from sync modes like video-verified)
    # These are SEPARATE from audio delays in ctx.delays.source_delays_ms
    # Format: {"Source 2": delay_ms, "Source 3": delay_ms}
    # Used ONLY for subtitle tracks, never affects audio or global shift calculation
    subtitle_delays_ms: dict[str, float] = field(default_factory=dict)

    # Results/summaries
    out_file: str | None = None
    tokens: list[str] | None = None
