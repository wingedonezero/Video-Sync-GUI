# vsg/settings_core.py
from __future__ import annotations
import json, os
from pathlib import Path

# --- Defaults (mirror monolith) ---
DEFAULTS = {
    "output_folder": "/home/chaoz/Downloads/sync_output",
    "temp_root": "/home/chaoz/Downloads/temp_work",
    "analysis_mode": "Audio Correlation",
    "workflow": "Analyze & Merge",
    "scan_chunk_count": 10,
    "scan_chunk_duration": 15,
    "min_match_pct": 5.0,
    "videodiff_path": "",
    "videodiff_error_min": 0.0,
    "videodiff_error_max": 100.0,
    "swap_subtitle_order": false,
    "rename_chapters": false,
    "match_jpn_secondary": true,
    "match_jpn_tertiary": true,
    "apply_dialog_norm_gain": false,
    "first_sub_default": true,
    "snap_chapters": false,
    "snap_mode": "previous",
    "snap_threshold_ms": 250,
    "snap_starts_only": true,
    "chapter_snap_verbose": false,
    "chapter_snap_compact": true,
    "log_compact": true,
    "log_tail_lines": 0,
    "log_error_tail": 20,
    "log_progress_step": 20,
    "log_show_options_pretty": false,
    "log_show_options_json": false,
    "log_autoscroll": true,
    "schema_version": 2
}

SCHEMA_VERSION = DEFAULTS.get('schema_version', 2)

def _default_settings_path() -> Path:
    here = Path(__file__).resolve().parents[1]
    fallback = here / 'settings_gui.json'
    env = os.getenv('VSG_CONFIG')
    return Path(env) if env else fallback

SETTINGS_PATH = _default_settings_path()

CONFIG: dict = {}

def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)

def _ensure_dirs(cfg: dict) -> None:
    out = Path(cfg.get('output_folder', ''))
    tmp = Path(cfg.get('temp_root', ''))
    if out:
        try: out.mkdir(parents=True, exist_ok=True)
        except Exception: pass
    if tmp:
        try: tmp.mkdir(parents=True, exist_ok=True)
        except Exception: pass

def migrate_settings(data: dict) -> dict:
    for k, v in DEFAULTS.items():
        data.setdefault(k, v)
    mode = str(data.get('analysis_mode', ''))
    if mode.lower() in ('audio_xcorr','xcorr','audio correlation'):
        data['analysis_mode'] = 'Audio Correlation'
    elif mode.lower() in ('videodiff','video diff'):
        data['analysis_mode'] = 'VideoDiff'
    mm = data.get('min_match_pct')
    try:
        if isinstance(mm, (int, float)) and 0.0 <= mm <= 1.0:
            data['min_match_pct'] = round(float(mm) * 100.0, 3)
    except Exception:
        pass
    data['schema_version'] = SCHEMA_VERSION
    return data

def validate_settings(data: dict) -> dict:
    def clamp(val, lo, hi):
        try:
            x = float(val)
            if x < lo: x = lo
            if x > hi: x = hi
            return x
        except Exception:
            return lo
    data['scan_chunk_count'] = int(clamp(data.get('scan_chunk_count', 10), 1, 128))
    data['scan_chunk_duration'] = int(clamp(data.get('scan_chunk_duration', 15), 1, 3600))
    data['min_match_pct'] = float(clamp(data.get('min_match_pct', 5.0), 0.0, 100.0))
    data['videodiff_error_min'] = float(clamp(data.get('videodiff_error_min', 0.0), 0.0, 100000.0))
    data['videodiff_error_max'] = float(clamp(data.get('videodiff_error_max', 100.0), 0.0, 100000.0))
    data['snap_threshold_ms'] = int(clamp(data.get('snap_threshold_ms', 250), 0, 5000))
    data['log_tail_lines'] = int(clamp(data.get('log_tail_lines', 0), 0, 1000000))
    data['log_error_tail'] = int(clamp(data.get('log_error_tail', 20), 0, 1000000))
    data['log_progress_step'] = int(clamp(data.get('log_progress_step', 20), 1, 100))
    for k in (
        'swap_subtitle_order','rename_chapters','match_jpn_secondary','match_jpn_tertiary',
        'apply_dialog_norm_gain','first_sub_default','snap_chapters','snap_starts_only',
        'chapter_snap_verbose','chapter_snap_compact','log_compact','log_show_options_pretty',
        'log_show_options_json','log_autoscroll'):
        data[k] = bool(data.get(k, DEFAULTS[k]))
    for k in ('workflow','analysis_mode','snap_mode','output_folder','temp_root','videodiff_path'):
        data[k] = str(data.get(k, DEFAULTS[k]))
    return data

def load_settings() -> dict:
    global CONFIG
    p = Path(SETTINGS_PATH)
    if not p.exists():
        CONFIG = DEFAULTS.copy()
        _ensure_dirs(CONFIG)
        _atomic_write_text(p, json.dumps(CONFIG, indent=2))
        return CONFIG
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        try: p.rename(p.with_suffix(p.suffix + '.bak'))
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

def save_settings(cfg: dict | None = None) -> None:
    p = Path(SETTINGS_PATH)
    state = cfg if cfg is not None else CONFIG
    _atomic_write_text(p, json.dumps(state, indent=2))

def on_change(key: str, value) -> None:
    CONFIG[key] = value

def adopt_into_app() -> None:
    try:
        import video_sync_gui as app
        app.CONFIG = CONFIG
        app.load_settings = load_settings
        app.save_settings = save_settings
    except Exception:
        pass

# initialize
load_settings()
adopt_into_app()
