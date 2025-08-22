
from __future__ import annotations
import json
from pathlib import Path
from typing import Callable, Dict, Any

# -----------------------------------------------------------------------------
# Settings storage
# -----------------------------------------------------------------------------

# Project root (.../Video-Sync-GUI-main)
SCRIPT_DIR = Path(__file__).resolve().parents[1]
SETTINGS_PATH = SCRIPT_DIR / "settings_gui.json"

# Global in-memory settings
CONFIG: Dict[str, Any] = {
    # Paths
    "output_folder": str(SCRIPT_DIR / "sync_output"),
    "temp_root": str(SCRIPT_DIR / "temp_work"),
    "ffmpeg_path": "",
    "ffprobe_path": "",
    "mkvmerge_path": "",
    "mkvextract_path": "",
    "videodiff_path": "",
    # Workflow / analysis
    "workflow": "Analyze & Merge",              # or "Analyze Only"
    "analysis_mode": "Audio Correlation",       # or "VideoDiff"
    "scan_chunk_count": 10,
    "scan_chunk_duration": 15,
    "min_match_pct": 5.0,
    "videodiff_error_min": 0.0,
    "videodiff_error_max": 100.0,
    # Audio/Chapters
    "match_jpn_secondary": True,
    "match_jpn_tertiary": True,
    "apply_dialog_norm_gain": False,
    "first_sub_default": True,
    # Snapping
    "snap_chapters": False,
    "snap_mode": "previous",
    "snap_threshold_ms": 250,
    "snap_starts_only": True,
    # Logging
    "log_compact": True,
    "log_tail_lines": 0,
    "log_error_tail": 20,
    "log_progress_step": 20,
    "log_show_options_pretty": False,
    "log_show_options_json": False,
    "log_autoscroll": True,
    "chapter_snap_verbose": False,
    "chapter_snap_compact": True,
    # Appearance
    "ui_font_path": "",
    "ui_font_size": 20,
    "input_line_height": 41,
    "row_gap": 8,
    "ui_compact_controls": False,
    # Version
    "schema_version": 2,
}

_listeners: list[Callable[[], None]] = []

def register_listener(fn: Callable[[], None]) -> None:
    if fn not in _listeners:
        _listeners.append(fn)

def _notify_listeners() -> None:
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            pass

# -----------------------------------------------------------------------------
# Load / Save
# -----------------------------------------------------------------------------

def load_settings() -> Dict[str, Any]:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def preload_from_disk() -> None:
    """Load settings into CONFIG without notifying listeners (safe pre-UI)."""
    data = load_settings()
    if isinstance(data, dict) and data:
        CONFIG.update(data)

def save_settings() -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")

def adopt_into_app(data: Dict[str, Any]) -> None:
    if isinstance(data, dict) and data:
        CONFIG.update(data)
        _notify_listeners()

def apply_and_notify() -> None:
    save_settings()
    _notify_listeners()

# Generic DPG callback used by the options modal
def on_change(sender, app_data, user_data: str | None = None) -> None:
    key = user_data
    if not key:
        return
    CONFIG[key] = app_data
    _notify_listeners()

def notify_settings_applied() -> None:
    """Public way to trigger listeners after UI exists (called by app)."""
    _notify_listeners()
