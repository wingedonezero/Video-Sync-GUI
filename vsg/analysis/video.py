from __future__ import annotations
from pathlib import Path
from typing import Optional
from ..settings import AppSettings

def analyze_video_offset(ref_path: Path, other_path: Path, settings: Optional[AppSettings]) -> int:
    """Return delay in ms (positive => `other` behind REF).

    Stub: wire to your VideoDiff-based analyzer.
    """
    # TODO: integrate your existing analyzer here
    return 0
