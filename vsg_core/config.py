# -*- coding: utf-8 -*-

"""
Manages application settings, loading from and saving to a JSON file.
"""

import json
from pathlib import Path
import shutil

class AppConfig:
    """Handles loading, saving, and accessing application settings."""

    def __init__(self, settings_filename='settings.json'):
        self.script_dir = Path(__file__).resolve().parent.parent
        self.settings_path = self.script_dir / settings_filename
        self.defaults = {
            'output_folder': str(self.script_dir / 'sync_output'),
            'temp_root': str(self.script_dir / 'temp_work'),
            'videodiff_path': '',
            'analysis_mode': 'Audio Correlation',
            'workflow': 'Analyze & Merge',
            'scan_chunk_count': 10,
            'scan_chunk_duration': 15,
            'min_match_pct': 5.0,
            'videodiff_error_min': 0.0,
            'videodiff_error_max': 100.0,
            'swap_subtitle_order': False,
            'rename_chapters': False,
            'match_jpn_secondary': True,
            'match_jpn_tertiary': True,
            'apply_dialog_norm_gain': False,
            'first_sub_default': True,
            'snap_chapters': False,
            'snap_mode': 'previous',
            'snap_threshold_ms': 250,
            'snap_starts_only': True,
            'log_compact': True,
            'log_autoscroll': True,
            'log_error_tail': 20,
            'log_tail_lines': 0,
            'log_progress_step': 20,
            'log_show_options_pretty': False,
            'log_show_options_json': False,
        }
        self.settings = self.defaults.copy()
        self.load()
        self.ensure_dirs_exist()

    def load(self):
        """Loads settings from the JSON file, merging with defaults."""
        changed = False
        if self.settings_path.exists():
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)

                # Merge loaded settings with defaults to ensure all keys exist
                for key, default_value in self.defaults.items():
                    if key not in loaded_settings:
                        loaded_settings[key] = default_value
                        changed = True
                self.settings = loaded_settings

            except (json.JSONDecodeError, IOError):
                self.settings = self.defaults.copy()
                changed = True
        else:
            self.settings = self.defaults.copy()
            changed = True

        if changed:
            self.save()

    def save(self):
        """Saves the current settings to the JSON file."""
        try:
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4)
        except IOError as e:
            print(f"Error saving settings: {e}")

    def get(self, key: str, default: any = None) -> any:
        """Gets a setting value by key."""
        return self.settings.get(key, default)

    def set(self, key: str, value: any):
        """Sets a setting value by key."""
        self.settings[key] = value

    def ensure_dirs_exist(self):
        """Ensures that the output and temp directories exist."""
        Path(self.get('output_folder')).mkdir(parents=True, exist_ok=True)
        Path(self.get('temp_root')).mkdir(parents=True, exist_ok=True)

    def find_tool_path(self, tool_name: str) -> str:
        """Finds a required tool in PATH or returns the name."""
        path = shutil.which(tool_name)
        if not path:
            raise FileNotFoundError(f"Required tool '{tool_name}' not found in system PATH.")
        return path
