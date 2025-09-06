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
    settings: AppSettings                  # typed settings
    settings_dict: Dict[str, Any]          # raw dict (legacy helpers expect dict)
    tool_paths: Dict[str, Optional[str]]
    log: Callable[[str], None]
    progress: Callable[[float], None]
    output_dir: str
    temp_dir: Path
    ref_file: str
    sec_file: Optional[str] = None
    ter_file: Optional[str] = None
    and_merge: bool = False
    manual_layout: List[Dict[str, Any]] = field(default_factory=list)

    # Filled along the pipeline
    delays: Optional[Delays] = None
    extracted_items: Optional[List[PlanItem]] = None
    chapters_xml: Optional[str] = None
    attachments: Optional[List[str]] = None

    # Results/summaries
    out_file: Optional[str] = None
    delay_sec_val: Optional[int] = None
    delay_ter_val: Optional[int] = None

    # mkvmerge @opts tokens produced by MuxStep
    tokens: Optional[List[str]] = None
