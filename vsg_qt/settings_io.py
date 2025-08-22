# vsg_qt/settings_io.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {}  # Qt uses vsg.settings as source of truth
class Settings:
    def __init__(self, project_root: Path) -> None:
        from vsg.settings import SETTINGS_PATH, load_settings
        self.project_root = project_root
        self.path = SETTINGS_PATH
        self.data: Dict[str, Any] = load_settings()

    def load(self) -> None:
        from vsg.settings import load_settings
        self.data = load_settings()

    def save(self) -> None:
        from vsg.settings import save_settings, CONFIG
        # Persist whatever is currently in self.data into vsg.settings.CONFIG before save
        CONFIG.clear(); CONFIG.update(self.data)
        save_settings()

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
