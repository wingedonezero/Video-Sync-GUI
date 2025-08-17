from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple, Any

from .analysis.audio import analyze_audio_offset as _aa
from .analysis.video import analyze_video_offset as _av

def analyze_and_plan(
    ref_file: str,
    sec_file: Optional[str],
    ter_file: Optional[str],
    mode: str,
    prefer_lang_sec: Optional[str],
    prefer_lang_ter: Optional[str],
    chunks: int,
    chunk_dur: int,
    min_match_pct: float,
    videodiff_path: str,
    videodiff_error_min: float,
    videodiff_error_max: float,
    logger: Any,
) -> tuple[Optional[int], Optional[int], dict]:
    """Run analysis for secondary/tertiary and compute lossless global shift.

    Returns: (delay_sec, delay_ter, delays_dict) where delays_dict matches the GUI's
    expected shape: {'secondary_ms': int, 'tertiary_ms': int, '_global_shift': int}
    """
    delay_sec: Optional[int] = None
    delay_ter: Optional[int] = None

    if sec_file:
        if mode == 'VideoDiff':
            delay_sec = _av(Path(ref_file), Path(sec_file), logger, videodiff_path, videodiff_error_min, videodiff_error_max)
        else:
            delay_sec = _aa(Path(ref_file), Path(sec_file), logger, chunks, chunk_dur, min_match_pct, prefer_lang_sec, 'sec')

    if ter_file:
        if mode == 'VideoDiff':
            delay_ter = _av(Path(ref_file), Path(ter_file), logger, videodiff_path, videodiff_error_min, videodiff_error_max)
        else:
            delay_ter = _aa(Path(ref_file), Path(ter_file), logger, chunks, chunk_dur, min_match_pct, prefer_lang_ter, 'ter')

    # Compute positive-only normalization (lossless global shift)
    present = [0]
    if sec_file is not None and delay_sec is not None:
        present.append(int(delay_sec))
    if ter_file is not None and delay_ter is not None:
        present.append(int(delay_ter))
    min_delay = min(present) if present else 0
    global_shift = -min_delay if min_delay < 0 else 0

    delays = {
        'secondary_ms': int(delay_sec or 0),
        'tertiary_ms': int(delay_ter or 0),
        '_global_shift': int(global_shift),
    }
    return delay_sec, delay_ter, delays
