from __future__ import annotations
from typing import List, Dict

def load_chapters(source_path) -> List[Dict]:
    """Load or extract chapters from `source_path`.

    Return a list of dicts: [{"start_ms": int, "end_ms": int | None, "title": str}, ...]
    """
    # TODO: implement using mkvextract or existing logic
    return []

def shift_chapters(chapters: List[Dict], shift_ms: int) -> List[Dict]:
    out = []
    for ch in chapters:
        start = ch.get("start_ms", 0) + shift_ms
        end = None if ch.get("end_ms") is None else ch["end_ms"] + shift_ms
        out.append({"start_ms": start, "end_ms": end, "title": ch.get("title", "")})
    return out

def snap_chapters(chapters: List[Dict], mode: str, tolerance_ms: int) -> List[Dict]:
    """Snap chapter boundaries to nearby keyframes.

    Stub: implement keyframe lookup and snapping logic; keep same signatures.
    """
    return chapters
