"""Settings with defaults + merge."""
from __future__ import annotations

import json
from pathlib import Path

from vsg.logbus import _log

DEFAULT_CONFIG = {
    "snap_starts_only": True,
    "snap_threshold_ms": 250,
    "snap_mode": "previous",
    "snap_chapters": False,
    "first_sub_default": True,
    "workflow": "Analyze & Merge",
    "analysis_mode": "videodiff",
    "log_autoscroll": True,
    "log_compact": True,
    "log_error_tail": True,
    "log_tail_lines": 200,
    "scan_chunk_count": 8,
    "scan_chunk_duration": 6.0,
    "min_match_pct": 0.8,
    "rename_chapters": False,
    "swap_subtitle_order": False,
    "match_jpn_secondary": True,
    "match_jpn_tertiary": True,
    "temp_root": "./temp_work",
    "output_folder": "./sync_output",
    "ffmpeg_path": "",
    "ffprobe_path": "",
    "mkvmerge_path": "",
    "mkvextract_path": "",
    "videodiff_path": "",
    "apply_dialog_norm_gain": True,
}

CONFIG: dict = DEFAULT_CONFIG.copy()
SETTINGS_PATH = Path("settings_gui.json")


def load_settings() -> None:
    global CONFIG
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text())
            merged = DEFAULT_CONFIG.copy()
            if isinstance(loaded, dict):
                merged.update(loaded)
            CONFIG = merged
            _log("Settings loaded (merged with defaults).")
        except Exception as e:
            CONFIG = DEFAULT_CONFIG.copy()
            _log(f"Failed to load settings, using defaults: {e}")
    else:
        CONFIG = DEFAULT_CONFIG.copy()
        _log("Settings file not found; using defaults.")


def save_settings() -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(CONFIG, indent=2))
        _log("Settings saved.")
    except Exception as e:
        _log(f"Failed to save settings: {e}")
