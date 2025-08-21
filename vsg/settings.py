"""Settings with defaults + merge."""
from __future__ import annotations
import json
from pathlib import Path
from vsg.logbus import _log

DEFAULT_CONFIG = {
    "output_folder": "/home/chaoz/Downloads/sync_output",
    "temp_root": "/home/chaoz/Downloads/temp_work",
    "analysis_mode": "Audio Correlation",
    "workflow": "Analyze & Merge",
    "scan_chunk_count": 10,
    "scan_chunk_duration": 15,
    "min_match_pct": 5.0,
    "match_jpn_secondary": True,
    "match_jpn_tertiary": True,
    "apply_dialog_norm_gain": False,
    "first_sub_default": True,
    "swap_subtitle_order": False,
    "rename_chapters": False,
    "videodiff_path": "",
    "videodiff_error_min": 0.0,
    "videodiff_error_max": 100.0,
    "snap_chapters": False,
    "snap_mode": "previous",
    "snap_threshold_ms": 250,
    "snap_starts_only": True,
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
