# vsg_core/config.py
"""
Application Configuration Module

Manages persistent user settings stored in settings.json.

IMPORTANT: All default values are defined in AppSettings (models/settings.py).
This module derives its defaults from AppSettings - do NOT add defaults here.

To add a new setting:
1. Add it to AppSettings in models/settings.py with a default value
2. That's it - this module will automatically pick it up

The AppConfig class handles:
- Loading settings from JSON with migration of old keys
- Saving settings to JSON
- Runtime path resolution (output_folder, temp_root, etc.)
- Directory creation
"""

import builtins
import json
import warnings
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vsg_core.models import AppSettings

# =====================================================================
# Standalone temp directory helpers
#
# These functions only need a temp_root path (from settings.temp_root).
# Use these instead of instantiating AppConfig when you only need
# temp dir operations (e.g., on the worker thread or in vsg_core code).
# =====================================================================


def get_style_editor_temp_path(temp_root: str | Path) -> Path:
    """Return the style_editor temp directory, creating it if needed."""
    temp_dir = Path(temp_root) / "style_editor"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def cleanup_style_editor_temp_files(temp_root: str | Path) -> int:
    """Remove all files in the style_editor temp directory.

    Returns:
        Number of items removed
    """
    import shutil

    temp_dir = Path(temp_root) / "style_editor"
    if not temp_dir.exists():
        return 0

    count = 0
    for item in temp_dir.iterdir():
        try:
            if item.is_file():
                item.unlink()
                count += 1
            elif item.is_dir():
                shutil.rmtree(item)
                count += 1
        except OSError:
            pass
    return count


def cleanup_old_style_editor_temp_files(
    temp_root: str | Path, max_age_hours: float = 1.0
) -> int:
    """Remove files older than *max_age_hours* from the style_editor temp dir.

    Returns:
        Number of items removed
    """
    import shutil
    import time

    temp_dir = Path(temp_root) / "style_editor"
    if not temp_dir.exists():
        return 0

    max_age_seconds = max_age_hours * 3600
    current_time = time.time()
    count = 0

    for item in temp_dir.iterdir():
        try:
            mtime = item.stat().st_mtime
            if (current_time - mtime) > max_age_seconds:
                if item.is_file():
                    item.unlink()
                    count += 1
                elif item.is_dir():
                    shutil.rmtree(item)
                    count += 1
        except OSError:
            pass
    return count


class AppConfig:
    """Configuration manager that uses AppSettings as the source of truth.

    Settings are stored as an AppSettings Pydantic model internally.
    Defaults are derived from AppSettings.get_defaults().
    """

    def __init__(self, settings_filename="settings.json"):
        self.script_dir = Path(__file__).resolve().parent.parent
        self.settings_path = self.script_dir / settings_filename

        # Get defaults from AppSettings (THE source of truth)
        # Then resolve runtime paths
        self.defaults = self._build_defaults()

        self.settings: AppSettings = None  # type: ignore  # Set by load()
        self._accessed_keys: set[str] = set()  # Track accessed keys for typo detection

        self.load()
        self.ensure_dirs_exist()

    def _build_defaults(self) -> dict[str, Any]:
        """Build defaults dict from AppSettings with runtime path resolution.

        AppSettings defines all defaults, but some paths need to be resolved
        at runtime based on script_dir.
        """
        defaults = AppSettings.get_defaults()

        # Resolve path sentinels to actual paths
        path_sentinel = AppSettings.PATH_SENTINEL

        if defaults.get("output_folder") == path_sentinel:
            defaults["output_folder"] = str(self.script_dir / "sync_output")

        if defaults.get("temp_root") == path_sentinel:
            defaults["temp_root"] = str(self.script_dir / "temp_work")

        if defaults.get("logs_folder") == path_sentinel:
            defaults["logs_folder"] = str(self.script_dir / ".config" / "logs")

        if defaults.get("source_separation_model_dir") == path_sentinel:
            defaults["source_separation_model_dir"] = str(
                self.script_dir / ".config" / "audio_separator_models"
            )

        return defaults

    def _migrate_legacy_keys(self, loaded_settings: dict[str, Any]) -> bool:
        """Apply all legacy key migrations to a loaded settings dict.

        Returns True if any changes were made.
        """
        changed = False

        # Remove deprecated keys
        if "post_mux_validate_metadata" in loaded_settings:
            del loaded_settings["post_mux_validate_metadata"]
            changed = True

        # Rename old language keys
        if "analysis_lang_ref" in loaded_settings and not loaded_settings.get(
            "analysis_lang_source1"
        ):
            loaded_settings["analysis_lang_source1"] = loaded_settings[
                "analysis_lang_ref"
            ]
            changed = True
        if "analysis_lang_sec" in loaded_settings and not loaded_settings.get(
            "analysis_lang_others"
        ):
            loaded_settings["analysis_lang_others"] = loaded_settings[
                "analysis_lang_sec"
            ]
            changed = True
        for old_key in [
            "analysis_lang_ref",
            "analysis_lang_sec",
            "analysis_lang_ter",
        ]:
            if old_key in loaded_settings:
                del loaded_settings[old_key]
                changed = True

        # Fix old source separation device
        if loaded_settings.get("source_separation_device") == "cpu":
            loaded_settings["source_separation_device"] = "auto"
            changed = True

        # Convert old source separation model names
        legacy_separation_map = {
            "Demucs - Music/Effects (Strip Vocals)": "instrumental",
            "Demucs - Vocals Only": "vocals",
        }
        legacy_selection = loaded_settings.get("source_separation_model")
        if legacy_selection in legacy_separation_map:
            loaded_settings["source_separation_mode"] = legacy_separation_map[
                legacy_selection
            ]
            loaded_settings["source_separation_model"] = "default"
            changed = True

        return changed

    def load(self):
        """Load settings from JSON file, applying migrations and defaults.

        Uses field-by-field recovery: starts from defaults, then overlays
        each saved value individually. If a single field fails Pydantic
        validation, only that field is reset to its default — all other
        customizations are preserved.
        """
        changed = False
        if self.settings_path.exists():
            try:
                with open(self.settings_path, encoding="utf-8") as f:
                    loaded_settings = json.load(f)

                # Apply legacy key migrations on the raw dict
                if self._migrate_legacy_keys(loaded_settings):
                    changed = True

                # Apply defaults for missing keys
                for key, default_value in self.defaults.items():
                    if key not in loaded_settings:
                        loaded_settings[key] = default_value
                        changed = True

                # Try loading all at once first (fast path for valid files)
                try:
                    self.settings = AppSettings.from_config(loaded_settings)
                except ValidationError:
                    # Field-by-field recovery: start from defaults, overlay
                    # each saved value individually, skip only broken fields
                    self.settings = AppSettings.from_config(self.defaults)
                    rejected: list[str] = []
                    for key, value in loaded_settings.items():
                        if key not in self.defaults:
                            continue
                        try:
                            setattr(self.settings, key, value)
                        except (ValidationError, ValueError, TypeError):
                            rejected.append(key)
                    if rejected:
                        warnings.warn(
                            f"Settings recovery: {len(rejected)} field(s) reset "
                            f"to defaults: {', '.join(rejected)}",
                            UserWarning,
                            stacklevel=2,
                        )
                    changed = True

            except (OSError, json.JSONDecodeError):
                self.settings = AppSettings.from_config(self.defaults)
                changed = True
        else:
            self.settings = AppSettings.from_config(self.defaults)
            changed = True

        if changed:
            self.save()

    def save(self):
        """Save current settings to JSON file.

        Saves all fields defined in AppSettings (derived from defaults).
        """
        try:
            # Pydantic model_dump() handles serialization
            settings_dict = self.settings.to_dict()

            # Only save keys that are in our defaults (which comes from AppSettings)
            # This ensures we don't save any orphaned keys
            keys_to_save = self.defaults.keys()
            settings_to_save = {
                k: settings_dict.get(k) for k in keys_to_save if k in settings_dict
            }

            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(settings_to_save, f, indent=4)
        except OSError as e:
            print(f"Error saving settings: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Gets a config value from the AppSettings model.

        Tracks accessed keys for typo detection. If a key is not in defaults
        and no default is provided, warns about potential typo.
        """
        self._accessed_keys.add(key)

        # Warn if accessing a key that's not in defaults and no default provided
        if key not in self.defaults and default is None:
            warnings.warn(
                f"Config key '{key}' not found in defaults. Possible typo? Returning None.",
                UserWarning,
                stacklevel=2,
            )

        # Use getattr to access AppSettings fields
        return getattr(self.settings, key, default)

    def set(self, key: str, value: Any) -> bool:
        """
        Sets a config value on the AppSettings model.

        Pydantic's validate_assignment handles type coercion and validation.
        If the value fails validation, a warning is emitted and the field
        keeps its previous value.

        Returns:
            True if the value was set, False if validation rejected it.
        """
        try:
            setattr(self.settings, key, value)
            return True
        except ValidationError:
            warnings.warn(
                f"Config key '{key}' rejected value {value!r} (validation failed). "
                f"Keeping previous value: {getattr(self.settings, key, None)!r}",
                UserWarning,
                stacklevel=2,
            )
            return False

    def validate_all(self) -> list[str]:
        """
        Validates all settings and returns list of error messages.

        With Pydantic, validation happens automatically on construction
        and assignment. This method re-validates the full model.

        Returns:
            List of validation error messages (empty if all valid)
        """
        try:
            AppSettings.model_validate(self.settings.to_dict())
            return []
        except Exception as e:
            return [str(e)]

    def validate_schema(self) -> list[str]:
        """
        Validates that AppSettings fields match what we expect.

        Returns:
            List of warning messages (empty if schema is valid)
        """
        warnings_list = []
        settings_fields = AppSettings.get_field_names()
        default_keys = set(self.defaults.keys())

        # Check for fields in AppSettings not in defaults (shouldn't happen)
        missing_in_defaults = settings_fields - default_keys
        if missing_in_defaults:
            warnings_list.append(
                f"AppSettings has fields not in defaults: {missing_in_defaults}"
            )

        # Check for keys in defaults not in AppSettings (shouldn't happen)
        extra_in_defaults = default_keys - settings_fields
        if extra_in_defaults:
            warnings_list.append(
                f"Defaults has keys not in AppSettings: {extra_in_defaults}"
            )

        return warnings_list

    def get_unrecognized_keys(self) -> builtins.set[str]:
        """
        Returns set of accessed keys that are not in defaults.

        Useful for detecting typos in config access.
        """
        return self._accessed_keys - set(self.defaults.keys())

    def get_orphaned_keys(self) -> builtins.set[str]:
        """
        Returns set of keys in settings that are not in defaults.

        Note: With AppSettings Pydantic model, this always returns empty set
        since the model has fixed fields.
        """
        return set()

    def remove_orphaned_keys(self) -> builtins.set[str]:
        """
        Removes orphaned keys from settings and saves.

        Note: With AppSettings Pydantic model, this is a no-op since there
        are no orphaned keys.
        """
        return set()

    def ensure_dirs_exist(self):
        Path(self.get("output_folder")).mkdir(parents=True, exist_ok=True)
        Path(self.get("temp_root")).mkdir(parents=True, exist_ok=True)
        Path(self.get("logs_folder")).mkdir(parents=True, exist_ok=True)
        # Create .config and .fonts directories for new features
        self.get_config_dir().mkdir(parents=True, exist_ok=True)
        self.get_fonts_dir().mkdir(parents=True, exist_ok=True)
        self.get_ocr_config_dir().mkdir(parents=True, exist_ok=True)

    def get_config_dir(self) -> Path:
        """Returns the path to the .config directory for storing app configuration files."""
        return self.script_dir / ".config"

    def get_fonts_dir(self) -> Path:
        """
        Returns the path to the fonts directory for user font files.

        Uses fonts_directory setting if set, otherwise falls back to .config/fonts.
        """
        custom_dir = self.get("fonts_directory")
        if custom_dir and Path(custom_dir).exists():
            return Path(custom_dir)
        return self.script_dir / ".config" / "fonts"

    def get_style_editor_temp_dir(self) -> Path:
        """Returns the path to the style_editor temp directory for preview files."""
        return get_style_editor_temp_path(self.get("temp_root"))

    def cleanup_style_editor_temp(self) -> int:
        """Clean up the style editor temp directory."""
        return cleanup_style_editor_temp_files(self.get("temp_root"))

    def cleanup_old_style_editor_temp(self, max_age_hours: float = 1.0) -> int:
        """Clean up old files (> max_age_hours) in the style editor temp dir."""
        return cleanup_old_style_editor_temp_files(self.get("temp_root"), max_age_hours)

    def get_vs_index_dir(self) -> Path:
        """
        Returns the path to the vapoursynth index directory.

        VapourSynth indexes are stored here for reuse across editor sessions.
        Indexes persist until job completion or manual cleanup.
        """
        index_dir = Path(self.get("temp_root")) / "vs_indexes"
        index_dir.mkdir(parents=True, exist_ok=True)
        return index_dir

    def get_vs_index_for_video(self, video_path: str) -> Path:
        """
        Get a unique index directory for a specific video file.

        Uses a hash of the video path to create a unique folder.

        Args:
            video_path: Path to the video file

        Returns:
            Path to the index directory for this video
        """
        import hashlib

        video_hash = hashlib.md5(video_path.encode()).hexdigest()[:16]
        index_dir = self.get_vs_index_dir() / video_hash
        index_dir.mkdir(parents=True, exist_ok=True)
        return index_dir

    def cleanup_vs_indexes(self) -> int:
        """
        Clean up all VapourSynth index directories.

        Called at job completion to free disk space.

        Returns:
            Number of directories removed
        """
        import shutil

        index_dir = self.get_vs_index_dir()
        if not index_dir.exists():
            return 0

        count = 0
        for item in index_dir.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                    count += 1
                elif item.is_file():
                    item.unlink()
                    count += 1
            except OSError:
                pass
        return count

    def get_ocr_config_dir(self) -> Path:
        """Returns the path to the .config/ocr directory for OCR configuration files."""
        return self.get_config_dir() / "ocr"

    def get_default_wordlist_path(self) -> Path:
        """Returns the default path for the OCR custom wordlist."""
        return self.get_ocr_config_dir() / "custom_wordlist.txt"
