from __future__ import annotations

def infer_language_code(name_or_path: str) -> str:
    """Heuristic language inference (e.g., from filenames like 'jpn', 'eng')."""
    lower = name_or_path.lower()
    if any(tag in lower for tag in ["jpn", "ja-jp", "japanese"]):
        return "jpn"
    if any(tag in lower for tag in ["eng", "en-us", "english"]):
        return "eng"
    return "und"
