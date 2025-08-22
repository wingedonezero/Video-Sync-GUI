from __future__ import annotations
import json, os
from pathlib import Path
from typing import Callable, Dict, Any

# Settings file (next to script by default)
SCRIPT_DIR = Path(__file__).resolve().parents[1]
SETTINGS_PATH = SCRIPT_DIR / "settings_gui.json"

# ----- defaults (monolith + appearance) -----
DEFAULTS: Dict[str, Any] = {
    "output_folder": str((SCRIPT_DIR / "sync_output").resolve()),
    "temp_root": str((SCRIPT_DIR / "temp_work").resolve()),
    "analysis_mode": "Audio Correlation",     # or "VideoDiff"
    "workflow": "Analyze & Merge",
    "scan_chunk_count": 10,
    "scan_chunk_duration": 15,
    "min_match_pct": 5.0,
    "videodiff_path": "",
    "videodiff_error_min": 0.0,
    "videodiff_error_max": 100.0,
    "swap_subtitle_order": False,
    "rename_chapters": False,
    "match_jpn_secondary": True,
    "match_jpn_tertiary": True,
    "apply_dialog_norm_gain": False,
    "first_sub_default": True,
    "snap_chapters": False,
    "snap_mode": "previous",
    "snap_threshold_ms": 250,
    "snap_starts_only": True,
    # logging defaults
    "chapter_snap_verbose": False,
    "chapter_snap_compact": True,
    "log_compact": True,
    "log_tail_lines": 0,
    "log_error_tail": 20,
    "log_progress_step": 20,
    "log_show_options_pretty": False,
    "log_show_options_json": False,
    "log_autoscroll": True,
    "schema_version": 2,
    # ---- appearance ----
    "ui_font_path": "",
    "ui_font_size": 18,
    "input_line_height": 40,
    "row_gap": 8,
    "ui_compact_controls": False,
}

CONFIG: Dict[str, Any] = dict(DEFAULTS)

_listeners = []  # type: list[Callable[[], None]]

def register_listener(fn: Callable[[], None]) -> None:
    """Register a callback to invoke after settings are applied/loaded/saved."""
    if fn not in _listeners:
        _listeners.append(fn)

def _notify_listeners() -> None:
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            pass

def merge_defaults(d: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(DEFAULTS)
    out.update(d or {})
    return out

def load_settings() -> Dict[str, Any]:
    global CONFIG
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                CONFIG = merge_defaults(loaded)
            else:
                CONFIG = dict(DEFAULTS)
        except Exception:
            CONFIG = dict(DEFAULTS)
    else:
        CONFIG = dict(DEFAULTS)
        save_settings()  # bootstrap
    return CONFIG

def save_settings() -> None:
    SETTINGS_PATH.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")

def on_change(sender=None, app_data=None, user_data=None, key: str | None = None, value: Any | None = None):
    # Supports DearPyGui callback signature or direct (key, value).
    if key is None and isinstance(user_data, str):
        key = user_data
    if key is not None:
        if value is None and app_data is not None:
            value = app_data
        CONFIG[key] = value
        save_settings()

def adopt_into_app(conf: Dict[str, Any]) -> Dict[str, Any]:
    """Hook for the app to adopt CONFIG; returns CONFIG for convenience."""
    global CONFIG
    CONFIG = merge_defaults(conf or {})
    save_settings()
    _notify_listeners()
    return CONFIG

def apply_and_notify() -> None:
    save_settings()
    _notify_listeners()
