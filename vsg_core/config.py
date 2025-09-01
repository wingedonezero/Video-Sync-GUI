# vsg_core/config.py

# -*- coding: utf-8 -*-
import json
from pathlib import Path
import shutil

class AppConfig:
    def __init__(self, settings_filename='settings.json'):
        self.script_dir = Path(__file__).resolve().parent.parent
        self.settings_path = self.script_dir / settings_filename
        self.defaults = {
            'last_ref_path': '',
            'last_sec_path': '',
            'last_ter_path': '',
            'output_folder': str(self.script_dir / 'sync_output'),
            'temp_root': str(self.script_dir / 'temp_work'),
            'videodiff_path': '',
            'analysis_mode': 'Audio Correlation',
            'analysis_lang_ref': '',
            'analysis_lang_sec': '',
            'analysis_lang_ter': '',
            'workflow': 'Analyze & Merge',
            'scan_chunk_count': 10,
            'scan_chunk_duration': 15,
            'min_match_pct': 5.0,
            'videodiff_error_min': 0.0,
            'videodiff_error_max': 100.0,
            'rename_chapters': False,
            'apply_dialog_norm_gain': False,
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
            'exclude_codecs': '',
            'disable_track_statistics_tags': False,
            'merge_mode': 'plan',
            'archive_logs': True,
            'merge_profile': [
                {"enabled": True, "source": "REF", "type": "Video", "lang": "any", "exclude_langs": "", "priority": 10, "is_default": False, "swap_first_two": False, "apply_track_name": False, "is_forced_display": False, "rescale": False},
                {"enabled": True, "source": "SEC", "type": "Audio", "lang": "any", "exclude_langs": "", "priority": 20, "is_default": True, "swap_first_two": False, "apply_track_name": False, "is_forced_display": False, "rescale": False},
                {"enabled": True, "source": "REF", "type": "Audio", "lang": "any", "exclude_langs": "", "priority": 30, "is_default": False, "swap_first_two": False, "apply_track_name": False, "is_forced_display": False, "rescale": False},
                {"enabled": True, "source": "TER", "type": "Subtitles", "lang": "any", "exclude_langs": "", "priority": 40, "is_default": False, "swap_first_two": False, "apply_track_name": True, "is_forced_display": True, "rescale": True},
                {"enabled": True, "source": "SEC", "type": "Subtitles", "lang": "any", "exclude_langs": "", "priority": 50, "is_default": True, "swap_first_two": True, "apply_track_name": True, "is_forced_display": False, "rescale": True},
                {"enabled": True, "source": "REF", "type": "Subtitles", "lang": "any", "exclude_langs": "", "priority": 60, "is_default": False, "swap_first_two": False, "apply_track_name": False, "is_forced_display": False, "rescale": False}
            ]
        }
        self.settings = self.defaults.copy()
        self.load()
        self.ensure_dirs_exist()

    def load(self):
        changed = False
        if self.settings_path.exists():
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                for key, default_value in self.defaults.items():
                    if key not in loaded_settings:
                        loaded_settings[key] = default_value
                        changed = True
                if 'merge_profile' in loaded_settings:
                    for rule in loaded_settings['merge_profile']:
                        if 'swap_first_two' not in rule: rule['swap_first_two'] = False; changed = True
                        if 'is_default' not in rule: rule['is_default'] = False; changed = True
                        if 'exclude_langs' not in rule: rule['exclude_langs'] = ''; changed = True
                        if 'apply_track_name' not in rule: rule['apply_track_name'] = False; changed = True
                        if 'is_forced_display' not in rule: rule['is_forced_display'] = False; changed = True
                        if 'is_forced' in rule: del rule['is_forced']; changed = True
                        if 'rescale' not in rule: rule['rescale'] = False; changed = True
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
        try:
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4)
        except IOError as e:
            print(f"Error saving settings: {e}")

    def get(self, key: str, default: any = None) -> any:
        return self.settings.get(key, default)

    def set(self, key: str, value: any):
        self.settings[key] = value

    def ensure_dirs_exist(self):
        Path(self.get('output_folder')).mkdir(parents=True, exist_ok=True)
        Path(self.get('temp_root')).mkdir(parents=True, exist_ok=True)
