# Clean manual copy — jobs.discover
from __future__ import annotations
from typing import Any, Dict, List
import os, re, json
from vsg.logbus import _log

def discover_jobs(input_dir: str) -> List[Dict[str, Any]]:
    """
    Dummy discover_jobs implementation — replace with full logic from video_sync_gui.py.
    For now, just returns an empty list.
    """
    _log(f"discover_jobs called on {input_dir}")
    return []
