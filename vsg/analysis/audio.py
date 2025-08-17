from __future__ import annotations
from pathlib import Path
from typing import Optional
from ..settings import AppSettings

def analyze_audio_offset(ref_path: Path, other_path: Path, settings: Optional[AppSettings]) -> int:
    """Return delay in ms (positive => `other` behind REF).

    Stub: replace with real cross-correlation implementation wired to your existing code.
    """
    # TODO: integrate your existing analyzer here
    return 0
