
from __future__ import annotations
import json, os
from pathlib import Path

# Base directory of the app (parent of vsg/)
BASE_DIR = Path(__file__).resolve().parents[1]

def _default_settings_path() -> Path:
    env = os.getenv("VSG_CONFIG")
    return Path(env) if env else (BASE_DIR / "settings_gui.json")

SETTINGS_PATH = _default_settings_path()

# Dynamic defaults anchored to the app folder
DEFAULTS = {
    "output_folder": str((BASE_DIR / "sync_output").resolve()),
    "temp_root": str((BASE_DIR / "temp_work").resolve()),
    "analysis_mode": "Audio Correlation",
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
    "chapter_snap_verbose": False,
    "chapter_snap_compact": True,
    "log_compact": True,
    "log_tail_lines": 0,
    "log_error_tail": 20,
    "log_progress_step": 20,
    "log_show_options_pretty": False,
    "log_show_options_json": False,
    "log_autoscroll": True,
    "ffmpeg_path": "",
    "ffprobe_path": "",
    "mkvmerge_path": "",
    "mkvextract_path": "",
    "schema_version": 2,
}

SCHEMA_VERSION = DEFAULTS["schema_version"]
CONFIG: dict = {}

def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)

def _ensure_dirs(cfg: dict) -> None:
    try: Path(cfg.get("output_folder","")).mkdir(parents=True, exist_ok=True)
    except Exception: pass
    try: Path(cfg.get("temp_root","")).mkdir(parents=True, exist_ok=True)
    except Exception: pass

def migrate_settings(data: dict) -> dict:
    for k, v in DEFAULTS.items():
        data.setdefault(k, v)
    mode = str(data.get("analysis_mode",""))
    m = mode.lower()
    if m in ("audio_xcorr","audio correlation","audio-correlation","xcorr"):
        data["analysis_mode"] = "Audio Correlation"
    elif m in ("videodiff","video diff","video-diff"):
        data["analysis_mode"] = "VideoDiff"
    mm = data.get("min_match_pct")
    try:
        if isinstance(mm, (int,float)) and 0.0 <= mm <= 1.0:
            data["min_match_pct"] = round(float(mm)*100.0, 3)
    except Exception:
        pass
    # None tool paths -> empty string
    for k in ("ffmpeg_path","ffprobe_path","mkvmerge_path","mkvextract_path","videodiff_path"):
        if data.get(k) is None:
            data[k] = ""
    data["schema_version"] = SCHEMA_VERSION
    return data

def validate_settings(data: dict) -> dict:
    def clamp(val, lo, hi, default):
        try:
            x = float(val)
        except Exception:
            return default
        return lo if x < lo else hi if x > hi else x

    data["scan_chunk_count"] = int(clamp(data.get("scan_chunk_count",10), 1, 128, 10))
    data["scan_chunk_duration"] = int(clamp(data.get("scan_chunk_duration",15), 1, 3600, 15))
    data["min_match_pct"] = float(clamp(data.get("min_match_pct",5.0), 0.0, 100.0, 5.0))
    data["videodiff_error_min"] = float(clamp(data.get("videodiff_error_min",0.0), 0.0, 1e6, 0.0))
    data["videodiff_error_max"] = float(clamp(data.get("videodiff_error_max",100.0), 0.0, 1e6, 100.0))
    data["snap_threshold_ms"] = int(clamp(data.get("snap_threshold_ms",250), 0, 5000, 250))
    data["log_tail_lines"] = int(clamp(data.get("log_tail_lines",0), 0, 1_000_000, 0))
    data["log_error_tail"] = int(clamp(data.get("log_error_tail",20), 0, 1_000_000, 20))
    data["log_progress_step"] = int(clamp(data.get("log_progress_step",20), 1, 100, 20))

    for k in ("swap_subtitle_order","rename_chapters","match_jpn_secondary","match_jpn_tertiary",
              "apply_dialog_norm_gain","first_sub_default","snap_chapters","snap_starts_only",
              "chapter_snap_verbose","chapter_snap_compact","log_compact","log_show_options_pretty",
              "log_show_options_json","log_autoscroll"):
        data[k] = bool(data.get(k, DEFAULTS[k]))

    for k in ("workflow","analysis_mode","snap_mode","output_folder","temp_root","videodiff_path",
              "ffmpeg_path","ffprobe_path","mkvmerge_path","mkvextract_path"):
        v = data.get(k, DEFAULTS.get(k,""))
        data[k] = "" if v is None else str(v)
    return data

def load_settings() -> dict:
    global CONFIG
    p = SETTINGS_PATH
    if not p.exists():
        CONFIG = DEFAULTS.copy()
        _ensure_dirs(CONFIG)
        _atomic_write_text(p, json.dumps(CONFIG, indent=2))
        return CONFIG
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        try: p.rename(p.with_suffix(p.suffix+".bak"))
        except Exception: pass
        CONFIG = DEFAULTS.copy()
        _ensure_dirs(CONFIG)
        _atomic_write_text(p, json.dumps(CONFIG, indent=2))
        return CONFIG
    data = migrate_settings(data)
    data = validate_settings(data)
    CONFIG = data
    _ensure_dirs(CONFIG)
    return CONFIG

def save_settings(cfg: dict|None=None) -> None:
    state = cfg if cfg is not None else CONFIG
    _atomic_write_text(SETTINGS_PATH, json.dumps(state, indent=2))

def on_change(key: str, value) -> None:
    CONFIG[key] = value

def adopt_into_app() -> None:
    try:
        import video_sync_gui as app
        app.CONFIG = CONFIG
        app.load_settings = load_settings
        app.save_settings = save_settings
        # Fallback set_status to prevent NameError during Analyze
        if not hasattr(app, "set_status"):
            def set_status(msg: str):
                try:
                    import dearpygui.dearpygui as dpg
                    if dpg.does_item_exist("status_text"):
                        dpg.set_value("status_text", msg)
                except Exception:
                    pass
            app.set_status = set_status
    except Exception:
        pass

# Init once
load_settings()
adopt_into_app()
