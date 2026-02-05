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
- Validation of values
- Directory creation
"""

import builtins
import json
import warnings
from pathlib import Path
from typing import Any

from vsg_core.models import AppSettings


class AppConfig:
    """Configuration manager that uses AppSettings as the source of truth.

    Settings are stored as an AppSettings dataclass internally.
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
        self._validation_enabled = True  # Can be disabled for backwards compatibility

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

    def _validate_value(self, key: str, value: Any) -> tuple[bool, str | None]:
        """
        Validates a config value against expected type and range.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self._validation_enabled:
            return True, None

        # Type and range validation based on key patterns
        if key.endswith("_enabled") or (
            key.startswith("log_") and not key.endswith(("_lines", "_step", "_tail"))
        ):
            if not isinstance(value, bool):
                return False, f"{key} must be bool, got {type(value).__name__}"

        elif key.endswith(("_pct", "_percentage")):
            if not isinstance(value, (int, float)):
                return False, f"{key} must be numeric, got {type(value).__name__}"
            if not (0.0 <= value <= 100.0):
                return False, f"{key} must be 0-100, got {value}"

        elif key.endswith(
            ("_ms", "_duration_ms", "_gap_ms", "_window_ms", "_tolerance_ms")
        ) or key.endswith(("_hz", "_lowcut_hz", "_highcut_hz", "_bandlimit_hz")):
            if not isinstance(value, (int, float)):
                return False, f"{key} must be numeric, got {type(value).__name__}"
            if value < 0:
                return False, f"{key} cannot be negative, got {value}"

        elif key.endswith(("_db", "_threshold_db", "_noise")):
            if not isinstance(value, (int, float)):
                return False, f"{key} must be numeric, got {type(value).__name__}"
            if value > 0:
                warnings.warn(
                    f"{key} is typically negative (dB), got {value}", stacklevel=2
                )

        elif key.endswith(
            ("_count", "_chunks", "_samples", "_taps", "_workers", "_points")
        ):
            if not isinstance(value, int):
                return False, f"{key} must be int, got {type(value).__name__}"
            if value < 0:
                return False, f"{key} cannot be negative, got {value}"

        elif key.endswith(("_threshold", "_ratio")):
            if not isinstance(value, (int, float)):
                return False, f"{key} must be numeric, got {type(value).__name__}"
            if value < 0:
                return False, f"{key} cannot be negative, got {value}"

        # Enum validation for specific keys
        if key == "source_separation_device":
            valid = ["auto", "cpu", "cuda", "rocm", "mps"]
            if value not in valid:
                return False, f"{key} must be one of {valid}, got '{value}'"
        elif key == "source_separation_mode":
            valid = ["none", "instrumental", "vocals"]
            if value not in valid:
                return False, f"{key} must be one of {valid}, got '{value}'"

        elif key == "frame_hash_algorithm":
            valid = ["dhash", "phash", "average_hash", "whash"]
            if value not in valid:
                return False, f"{key} must be one of {valid}, got '{value}'"

        elif key.endswith("_fallback_mode"):
            # Don't enforce specific values as different modes have different options
            if not isinstance(value, str):
                return False, f"{key} must be string, got {type(value).__name__}"

        elif key in ("sync_mode", "delay_selection_mode"):
            if not isinstance(value, str):
                return False, f"{key} must be string, got {type(value).__name__}"

        elif key in ("analysis_mode", "snap_mode"):
            if not isinstance(value, str):
                return False, f"{key} must be string, got {type(value).__name__}"

        elif key == "stepping_silence_detection_method":
            valid = ["rms_basic", "ffmpeg_silencedetect", "smart_fusion"]
            if value not in valid:
                return False, f"{key} must be one of {valid}, got '{value}'"

        elif key == "segment_resample_engine":
            valid = ["aresample", "rubberband"]
            if value not in valid:
                return False, f"{key} must be one of {valid}, got '{value}'"

        return True, None

    def _coerce_type(self, key: str, value: Any, default_value: Any) -> Any:
        """
        Coerces a loaded value to match the type of its default.

        Handles JSON loading issues where numbers may be stored as strings.

        Args:
            key: Config key name
            value: Loaded value (may be wrong type)
            default_value: Default value (provides expected type)

        Returns:
            Coerced value matching default's type
        """
        # If value is already the correct type, return as-is
        if type(value) is type(default_value):
            return value

        # Try to coerce to default's type
        try:
            if isinstance(default_value, bool):
                # Handle bool specially - strings need explicit conversion
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes", "on")
                return bool(value)
            elif isinstance(default_value, int):
                # Convert to float first, then int (handles "10.0" strings)
                return int(float(value))
            elif isinstance(default_value, float):
                return float(value)
            elif isinstance(default_value, str):
                return str(value)
            elif isinstance(default_value, (list, tuple)):
                # Handle list/tuple - JSON loads as list
                if isinstance(value, (list, tuple)):
                    return value
                return default_value
            else:
                # Unknown type, return as-is
                return value
        except (ValueError, TypeError):
            # Coercion failed, return default value
            warnings.warn(
                f"Config key '{key}' has invalid value '{value}', using default: {default_value}",
                UserWarning,
                stacklevel=2,
            )
            return default_value

    def validate_all(self) -> list[str]:
        """
        Validates all settings and returns list of error messages.

        Returns:
            List of validation error messages (empty if all valid)
        """
        import dataclasses

        errors = []
        for field in dataclasses.fields(self.settings):
            value = getattr(self.settings, field.name)
            is_valid, error_msg = self._validate_value(field.name, value)
            if not is_valid:
                errors.append(error_msg)
        return errors

    def validate_schema(self) -> list[str]:
        """
        Validates that AppSettings fields match what we expect.

        This catches issues where AppSettings has fields not in defaults
        (which shouldn't happen if everything derives from AppSettings).

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

    def load(self):
        """Load settings from JSON file, applying migrations and defaults."""
        changed = False
        if self.settings_path.exists():
            try:
                with open(self.settings_path, encoding="utf-8") as f:
                    loaded_settings = json.load(f)

                # === Migration: Remove deprecated keys ===
                if "post_mux_validate_metadata" in loaded_settings:
                    del loaded_settings["post_mux_validate_metadata"]
                    changed = True

                # === Migration: Rename old language keys ===
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

                # === Migration: Fix old source separation device ===
                if loaded_settings.get("source_separation_device") == "cpu":
                    loaded_settings["source_separation_device"] = "auto"
                    changed = True

                # === Migration: Convert old source separation model names ===
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

                # === Apply defaults for missing keys ===
                for key, default_value in self.defaults.items():
                    if key not in loaded_settings:
                        loaded_settings[key] = default_value
                        changed = True

                # === Coerce types to match defaults (fixes string numbers from JSON) ===
                for key, value in loaded_settings.items():
                    if key in self.defaults:
                        coerced = self._coerce_type(key, value, self.defaults[key])
                        if coerced != value:
                            loaded_settings[key] = coerced
                            changed = True

                # Create AppSettings dataclass from the merged dict
                self.settings = AppSettings.from_config(loaded_settings)

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
            # Convert AppSettings to dict
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
        Gets a config value from the AppSettings dataclass.

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

        # Use getattr to access AppSettings dataclass fields
        return getattr(self.settings, key, default)

    def set(self, key: str, value: Any):
        """
        Sets a config value on the AppSettings dataclass.

        Validates the value before setting if validation is enabled.
        """
        if self._validation_enabled:
            is_valid, error_msg = self._validate_value(key, value)
            if not is_valid:
                raise ValueError(f"Invalid config value: {error_msg}")

        # Use setattr to modify AppSettings dataclass fields
        setattr(self.settings, key, value)

    def get_unrecognized_keys(self) -> builtins.set[str]:
        """
        Returns set of accessed keys that are not in defaults.

        Useful for detecting typos in config access.
        """
        return self._accessed_keys - set(self.defaults.keys())

    def get_orphaned_keys(self) -> builtins.set[str]:
        """
        Returns set of keys in settings that are not in defaults.

        Note: With AppSettings dataclass, this always returns empty set
        since the dataclass has fixed fields.
        """
        # AppSettings dataclass has fixed fields, no orphaned keys possible
        return set()

    def remove_orphaned_keys(self) -> builtins.set[str]:
        """
        Removes orphaned keys from settings and saves.

        Note: With AppSettings dataclass, this is a no-op since there
        are no orphaned keys.
        """
        # AppSettings dataclass has fixed fields, nothing to remove
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
        """
        Returns the path to the style_editor temp directory for preview files.

        This is inside the normal temp_work directory and gets cleaned up at job start,
        not when the style editor closes. This allows debugging of temp files
        and keeps all job-related temp files in one place.
        """
        temp_dir = Path(self.get("temp_root")) / "style_editor"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def cleanup_style_editor_temp(self) -> int:
        """
        Clean up the style editor temp directory.

        Called at job start or end to remove old preview files.

        Returns:
            Number of files removed
        """
        import shutil

        temp_dir = Path(self.get("temp_root")) / "style_editor"
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

    def cleanup_old_style_editor_temp(self, max_age_hours: float = 1.0) -> int:
        """
        Clean up old files in the style editor temp directory.

        Only removes files/directories older than max_age_hours. This is safe
        to call when opening the style editor as it won't affect the current
        session's files or any recently created files.

        Args:
            max_age_hours: Maximum age in hours before cleanup (default 1 hour)

        Returns:
            Number of items removed
        """
        import shutil
        import time

        temp_dir = Path(self.get("temp_root")) / "style_editor"
        if not temp_dir.exists():
            return 0

        max_age_seconds = max_age_hours * 3600
        current_time = time.time()
        count = 0

        for item in temp_dir.iterdir():
            try:
                # Get modification time of the item
                mtime = item.stat().st_mtime
                age_seconds = current_time - mtime

                if age_seconds > max_age_seconds:
                    if item.is_file():
                        item.unlink()
                        count += 1
                    elif item.is_dir():
                        shutil.rmtree(item)
                        count += 1
            except OSError:
                pass

        return count

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
