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
    # NEW: Stores the list of sources to pull attachments from
    attachment_sources: List[str] = field(default_factory=list)

    # Filled along the pipeline
    delays: Optional[Delays] = None
    extracted_items: Optional[List[PlanItem]] = None
    chapters_xml: Optional[str] = None
    attachments: Optional[List[str]] = None

    # Results/summaries
    out_file: Optional[str] = None

    # mkvmerge @opts tokens produced by MuxStep
    tokens: Optional[List[str]] = None
