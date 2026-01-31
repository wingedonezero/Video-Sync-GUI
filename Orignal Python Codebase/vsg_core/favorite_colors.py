# vsg_core/favorite_colors.py
# -*- coding: utf-8 -*-
"""
Favorite Colors Manager

Manages a global list of favorite colors that can be saved and reused
across subtitle style editing sessions.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any


class FavoriteColorsManager:
    """
    Manages favorite colors stored in a JSON file.

    Colors are stored with:
    - id: Unique identifier
    - name: User-friendly name
    - hex: Qt-format hex color (#AARRGGBB)
    - created: ISO timestamp
    """

    VERSION = 1

    def __init__(self, config_dir: Path):
        """
        Initialize the manager with a config directory.

        Args:
            config_dir: Path to the .config directory
        """
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / 'favorite_colors.json'
        self._favorites: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        """Load favorites from the JSON file."""
        if not self.config_file.exists():
            self._favorites = []
            return

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Handle version migrations if needed in the future
            version = data.get('version', 1)
            self._favorites = data.get('favorites', [])

            # Validate loaded data
            valid_favorites = []
            for fav in self._favorites:
                if self._validate_favorite(fav):
                    valid_favorites.append(fav)
            self._favorites = valid_favorites

        except (json.JSONDecodeError, IOError, KeyError) as e:
            # If file is corrupt, start fresh but don't delete the file
            # (user can manually recover if needed)
            print(f"Warning: Could not load favorite colors: {e}")
            self._favorites = []

    def _validate_favorite(self, fav: Dict) -> bool:
        """Validate a favorite color entry."""
        required_keys = ['id', 'name', 'hex']
        if not all(key in fav for key in required_keys):
            return False
        if not isinstance(fav['hex'], str) or not fav['hex'].startswith('#'):
            return False
        return True

    def _save(self):
        """Save favorites to the JSON file."""
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        data = {
            'version': self.VERSION,
            'favorites': self._favorites
        }

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"Error saving favorite colors: {e}")

    def get_all(self) -> List[Dict[str, Any]]:
        """
        Get all favorite colors.

        Returns:
            List of favorite color dictionaries
        """
        return self._favorites.copy()

    def add(self, name: str, hex_color: str) -> str:
        """
        Add a new favorite color.

        Args:
            name: User-friendly name for the color
            hex_color: Qt-format hex color (#AARRGGBB or #RRGGBB)

        Returns:
            The ID of the newly created favorite
        """
        # Normalize hex color to uppercase
        hex_color = hex_color.upper()
        if not hex_color.startswith('#'):
            hex_color = '#' + hex_color

        favorite = {
            'id': str(uuid.uuid4()),
            'name': name.strip() if name else 'Unnamed Color',
            'hex': hex_color,
            'created': datetime.now().isoformat()
        }

        self._favorites.append(favorite)
        self._save()
        return favorite['id']

    def update(self, favorite_id: str, name: Optional[str] = None, hex_color: Optional[str] = None) -> bool:
        """
        Update an existing favorite color.

        Args:
            favorite_id: The ID of the favorite to update
            name: New name (optional)
            hex_color: New hex color (optional)

        Returns:
            True if updated successfully, False if not found
        """
        for fav in self._favorites:
            if fav['id'] == favorite_id:
                if name is not None:
                    fav['name'] = name.strip() if name else 'Unnamed Color'
                if hex_color is not None:
                    hex_color = hex_color.upper()
                    if not hex_color.startswith('#'):
                        hex_color = '#' + hex_color
                    fav['hex'] = hex_color
                self._save()
                return True
        return False

    def remove(self, favorite_id: str) -> bool:
        """
        Remove a favorite color.

        Args:
            favorite_id: The ID of the favorite to remove

        Returns:
            True if removed successfully, False if not found
        """
        original_count = len(self._favorites)
        self._favorites = [f for f in self._favorites if f['id'] != favorite_id]

        if len(self._favorites) < original_count:
            self._save()
            return True
        return False

    def get_by_id(self, favorite_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a favorite by its ID.

        Args:
            favorite_id: The ID to look up

        Returns:
            The favorite dict or None if not found
        """
        for fav in self._favorites:
            if fav['id'] == favorite_id:
                return fav.copy()
        return None

    def reorder(self, favorite_ids: List[str]):
        """
        Reorder favorites to match the given ID list.

        Args:
            favorite_ids: List of IDs in desired order
        """
        id_to_fav = {f['id']: f for f in self._favorites}
        new_order = []

        for fid in favorite_ids:
            if fid in id_to_fav:
                new_order.append(id_to_fav[fid])

        # Add any favorites not in the list at the end
        for fav in self._favorites:
            if fav['id'] not in favorite_ids:
                new_order.append(fav)

        self._favorites = new_order
        self._save()

    def clear_all(self):
        """Remove all favorite colors."""
        self._favorites = []
        self._save()
