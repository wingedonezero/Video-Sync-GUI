
from __future__ import annotations

import json, os, shutil
from pathlib import Path
from typing import Dict, Any
from .settings_schema import DEFAULTS, SCHEMA_VERSION

CONFIG: Dict[str, Any] = {}

def _repo_root() -> Path:
    # assumes vsg/ sits under project root
    return Path(__file__).resolve().parents[2]

def settings_path() -> Path:
    return _repo_root() / "settings_gui.json"

def _merge_defaults(user: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULTS)
    if user:
        merged.update({k: v for k, v in user.items() if k in DEFAULTS})
    merged["schema_version"] = SCHEMA_VERSION
    return merged

def load_settings() -> Dict[str, Any]:
    global CONFIG
    p = settings_path()
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            # keep data empty; we'll regenerate from defaults
            data = {}
    CONFIG = _merge_defaults(data)

    # ensure folders
    for key in ("output_folder", "temp_root"):
        try:
            Path(CONFIG[key]).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    return CONFIG

def save_settings(cfg: Dict[str, Any] | None = None) -> None:
    cfg = cfg or CONFIG
    # never drop unknown keys in file; merge file->cfg->defaults
    on_disk = {}
    p = settings_path()
    if p.exists():
        try:
            on_disk = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            on_disk = {}
    merged = dict(on_disk)
    for k, v in cfg.items():
        merged[k] = v
    merged = _merge_defaults(merged)

    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)

    # ensure folders after potential path edits
    for key in ("output_folder", "temp_root"):
        try:
            Path(merged[key]).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    # sync back to global
    CONFIG.clear()
    CONFIG.update(merged)
