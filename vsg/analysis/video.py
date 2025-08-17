from __future__ import annotations
from pathlib import Path
from typing import Any, Tuple

import importlib

def analyze_video_offset(ref_path: Path, other_path: Path, logger: Any, videodiff_path: str, err_min: float, err_max: float) -> int:
    vsgui = importlib.import_module('video_sync_gui')
    delay_ms, err = vsgui.run_videodiff(str(ref_path), str(other_path), logger, videodiff_path)
    if err < float(err_min) or err > float(err_max):
        raise RuntimeError(f"VideoDiff confidence out of bounds: error={err:.2f} (allowed {err_min}..{err_max})")
    return int(delay_ms)
