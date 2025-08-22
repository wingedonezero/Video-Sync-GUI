"""Settings with defaults + JSON load/save (UI-agnostic)."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict
from vsg.logbus import _log

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "settings_gui.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "output_folder": str(PROJECT_ROOT / "sync_output"),
    "temp_root": str(PROJECT_ROOT / "temp_work"),
    "ffmpeg_path": "",
    "ffprobe_path": "",
    "mkvmerge_path": "",
    "mkvextract_path": "",
    "videodiff_path": "",
    "workflow": "Analyze & Merge",
    "analysis_mode": "Audio Correlation",
    "scan_chunk_count": 10,
    "scan_chunk_duration": 15,
    "min_match_pct": 5.0,
    "videodiff_error_min": 0.0,
    "videodiff_error_max": 100.0,
    "match_jpn_secondary": True,
    "match_jpn_tertiary": True,
    "apply_dialog_norm_gain": False,
    "first_sub_default": True,
    "snap_chapters": False,
    "snap_mode": "previous",
    "snap_threshold_ms": 250,
    "snap_starts_only": True,
    "log_compact": True,
    "log_tail_lines": 0,
    "log_error_tail": 20,
    "log_progress_step": 20,
    "log_show_options_pretty": False,
    "log_show_options_json": False,
    "log_autoscroll": True,
    "chapter_snap_verbose": False,
    "chapter_snap_compact": True,
    "font_family": "",
    "font_point_size": 10,
    "row_spacing_px": 8,
    "input_height_px": 32,
    "schema_version": 2,
}

CONFIG: Dict[str, Any] = dict(DEFAULT_CONFIG)

def load_settings() -> Dict[str, Any]:
    global CONFIG
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = dict(DEFAULT_CONFIG)
                merged.update(data)
                CONFIG = merged
                return CONFIG
        except Exception as e:
            _log("Failed loading settings:", e)
    # ensure defaults and folders
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "sync_output").mkdir(exist_ok=True, parents=True)
    (PROJECT_ROOT / "temp_work").mkdir(exist_ok=True, parents=True)
    return CONFIG

def save_settings() -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        _log("Failed saving settings:", e)
