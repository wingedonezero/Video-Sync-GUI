# Moved from video_sync_gui.py — analysis.videodiff (Phase B, move-only)
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple, List
import re, json, math, logging, subprocess
from vsg.logbus import _log

def format_delay_ms(ms):
    if ms is None:
        return '—'
    ms = int(ms)
    sign = '-' if ms < 0 else ''
    return f'{sign}{abs(ms)} ms'



def run_videodiff(ref: str, target: str, logger, videodiff_path: Path | str) -> Tuple[int, float]:
    """Run videodiff once and parse ONLY the final '[Result] - (itsoffset|ss): X.XXXXXs, ... error: YYY' line.
       Returns (delay_ms, error_value).  Mapping: itsoffset -> +ms, ss -> -ms.
    """
    vp = str(videodiff_path) if videodiff_path else ''
    if not vp:
        vp = shutil.which('videodiff') or str(SCRIPT_DIR / 'videodiff')
    vp_path = Path(vp)
    if not vp_path.exists():
        raise FileNotFoundError(f'videodiff not found at {vp_path}')
    _log(logger, f'videodiff path: {vp_path}')
    out = run_command([str(vp_path), str(ref), str(target)], logger)
    if not out:
        raise RuntimeError('videodiff produced no output')
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    last_line = ''
    for ln in reversed(lines):
        if '[Result]' in ln and ('ss:' in ln or 'itsoffset:' in ln):
            last_line = ln
            break
    if not last_line:
        last_line = lines[-1] if lines else ''
    m = re.search('(itsoffset|ss)\\s*:\\s*(-?\\d+(?:\\.\\d+)?)s.*?error:\\s*([0-9.]+)', last_line, flags=re.IGNORECASE)
    if not m:
        raise RuntimeError(f"videodiff: could not parse final line: '{last_line}'")
    kind, sval, err = m.groups()
    seconds = float(sval)
    delay_ms = int(round(seconds * 1000))
    if kind.lower() == 'ss':
        delay_ms = -delay_ms
    err_val = float(err)
    _log(logger, f'[VideoDiff] final -> {kind.lower()} {seconds:.5f}s, error {err_val:.2f}  =>  delay {delay_ms:+} ms')
    return (delay_ms, err_val)


