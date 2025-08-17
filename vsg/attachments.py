from __future__ import annotations
from pathlib import Path
from typing import List

def collect_font_attachments(sub_paths: List[Path]) -> List[Path]:
    """Return a list of font files to attach based on subtitle dependencies.

    Stub: detect fonts referenced by ASS/SSA; fall back to globbing a 'fonts' folder.
    """
    return []
