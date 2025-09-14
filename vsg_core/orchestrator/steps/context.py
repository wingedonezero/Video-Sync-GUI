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

    # Filled along the pipeline
    delays: Optional[Delays] = None
    extracted_items: Optional[List[PlanItem]] = None
    chapters_xml: Optional[str] = None
    attachments: Optional[List[str]] = None

    # (NEW) Stores flags for tracks that need segmented correction
    # Format: {'Source 2_3': {'has_segments': True, 'base_delay': -1013, 'analysis_track_key': 'Source 2_3'}}
    segment_flags: Dict[str, Dict] = field(default_factory=dict)

    # Results/summaries
    out_file: Optional[str] = None
    tokens: Optional[List[str]] = None
