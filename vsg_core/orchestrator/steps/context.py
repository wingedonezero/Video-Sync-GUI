# vsg_core/orchestrator/steps/context.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any

from vsg_core.models.settings import AppSettings
from vsg_core.models.jobs import PlanItem, Delays

@dataclass
class Context:
    # Provided by Orchestrator entry
    settings: AppSettings
    settings_dict: Dict[str, Any]
    tool_paths: Dict[str, Optional[str]]
    log: Callable[[str], None]
    progress: Callable[[float], None]
    output_dir: str
    temp_dir: Path
    sources: Dict[str, str] = field(default_factory=dict)
    and_merge: bool = False
    manual_layout: List[Dict[str, Any]] = field(default_factory=list)
    attachment_sources: List[str] = field(default_factory=list)

    # Per-source correlation settings (from job layout)
    # Format: {'Source 2': {'correlation_target_track': 2, 'use_source_separation': True}, ...}
    source_settings: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Filled along the pipeline
    delays: Optional[Delays] = None
    extracted_items: Optional[List[PlanItem]] = None
    chapters_xml: Optional[str] = None
    attachments: Optional[List[str]] = None

    # Stores flags for tracks that need segmented (stepping) correction
    segment_flags: Dict[str, Dict] = field(default_factory=dict)

    # Stores flags for tracks that need PAL drift correction
    pal_drift_flags: Dict[str, Dict] = field(default_factory=dict)

    # Stores flags for tracks that need linear drift correction
    linear_drift_flags: Dict[str, Dict] = field(default_factory=dict)

    # NEW FIELDS: Container delay tracking
    # Store Source 1's reference audio container delay for chain calculation
    source1_audio_container_delay_ms: int = 0

    # Store all container delays by source and track ID for logging/reference
    # Format: {source_key: {track_id: delay_ms}}
    container_delays: Dict[str, Dict[int, int]] = field(default_factory=dict)

    # A flag to determine if a global shift is necessary
    global_shift_is_required: bool = False

    # Timing sync mode ('positive_only', 'allow_negative', or 'preserve_existing')
    sync_mode: str = 'positive_only'

    # NEW: Track which sources had stepping detected (for final report)
    stepping_sources: List[str] = field(default_factory=list)

    # NEW: Track sources where stepping was detected but correction is disabled
    stepping_detected_disabled: List[str] = field(default_factory=list)

    # Store EDLs (Edit Decision Lists) for stepping correction by source
    # Format: {source_key: List[AudioSegment]}
    stepping_edls: Dict[str, List[Any]] = field(default_factory=dict)

    # Flag if any subtitle track used raw delay fallback due to no scene matches
    # (correlation-frame-snap mode couldn't find scenes to verify against)
    correlation_snap_no_scenes_fallback: bool = False

    # Results/summaries
    out_file: Optional[str] = None
    tokens: Optional[List[str]] = None
