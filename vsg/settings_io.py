
from __future__ import annotations

import json, os
from pathlib import Path
from typing import Dict, Any
from .settings_schema import DEFAULTS, SCHEMA_VERSION

CONFIG: Dict[str, Any] = {}

def _repo_root() -> Path:
    # assumes vsg/ sits under project root
    return Path(__file__).resolve().parents[2]

def settings_path() -> Path:
    return _repo_root() / "settings_gui.json"

def _merge_defaults(existing: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULTS)
    for k, v in (existing or {}).items():
        merged[k] = v  # preserve unknown keys too (we won't drop them on save)
    merged["_schema_version"] = SCHEMA_VERSION
    return merged

def load_settings() -> Dict[str, Any]:
    global CONFIG
    p = settings_path()
    data: Dict[str, Any] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    merged = _merge_defaults(data)

    # ensure folders exist
    for key in ("output_folder", "temp_root"):
        try:
            Path(merged[key]).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    CONFIG.clear()
    CONFIG.update(merged)
    return CONFIG

def save_settings(new_values: Dict[str, Any]) -> Dict[str, Any]:
    """Merge + save without wiping unknown keys."""
    p = settings_path()
    try:
        current = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        if not isinstance(current, dict):
            current = {}
    except Exception:
        current = {}

    merged = dict(current)
    for k, v in (new_values or {}).items():
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
    return merged
