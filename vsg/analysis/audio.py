from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple, Any
import importlib

def analyze_audio_offset(ref_path: Path, other_path: Path, logger: Any, chunks: int, chunk_dur: int, min_match_pct: float, match_lang: Optional[str], role_tag: str) -> int:
    vsgui = importlib.import_module('video_sync_gui')
    results = vsgui.run_audio_correlation_workflow(
        str(ref_path), str(other_path), logger, chunks, chunk_dur, match_lang, role_tag
    )
    best = vsgui.best_from_results(results, min_match_pct)
    if not best:
        raise RuntimeError(f"Audio analysis for {role_tag} yielded no valid result.")
    return int(best['delay'])
