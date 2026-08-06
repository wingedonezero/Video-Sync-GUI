# vsg_core/track_names.py
"""
Saved Track Names Manager

Manages a global list of reusable custom track names (e.g. subtitle naming
conventions like "Signs & Songs [SubsPlease]") persisted in the config
directory. Mirrors the FavoriteColorsManager pattern, but names are plain
strings — the name itself is the identity.
"""

from __future__ import annotations

import json
from pathlib import Path


class TrackNamesManager:
    """Loads and saves the reusable track-name list in ``track_names.json``."""

    VERSION = 1

    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "track_names.json"
        self._names: list[str] = []
        self._load()

    def _load(self) -> None:
        if not self.config_file.exists():
            self._names = []
            return

        try:
            with open(self.config_file, encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("names", [])
            self._names = [n for n in raw if isinstance(n, str) and n.strip()]
        except (OSError, json.JSONDecodeError) as e:
            # Corrupt file: start fresh but leave the file on disk so the
            # user can recover it manually.
            print(f"Warning: Could not load saved track names: {e}")
            self._names = []

    def _save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        data = {"version": self.VERSION, "names": self._names}
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"Error saving track names: {e}")

    def get_all(self) -> list[str]:
        """Return all saved names, sorted alphabetically (case-insensitive)."""
        return sorted(self._names, key=str.casefold)

    def add(self, name: str) -> bool:
        """Add a name. Returns False if empty or already saved."""
        name = name.strip()
        if not name or self._contains(name):
            return False
        self._names.append(name)
        self._save()
        return True

    def remove(self, name: str) -> bool:
        """Remove a name. Returns False if it was not in the list."""
        remaining = [n for n in self._names if n != name]
        if len(remaining) == len(self._names):
            return False
        self._names = remaining
        self._save()
        return True

    def rename(self, old: str, new: str) -> bool:
        """Rename an entry in place. Returns False if invalid or a duplicate."""
        new = new.strip()
        if not new or old not in self._names:
            return False
        # Allow case-only renames of the same entry; block real collisions.
        if new.casefold() != old.casefold() and self._contains(new):
            return False
        self._names = [new if n == old else n for n in self._names]
        self._save()
        return True

    def _contains(self, name: str) -> bool:
        target = name.casefold()
        return any(n.casefold() == target for n in self._names)
