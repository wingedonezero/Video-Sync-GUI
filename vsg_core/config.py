# vsg_core/config.py
# -*- coding: utf-8 -*-
import json
from pathlib import Path

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
            'subtile_ocr_path': '',
            'subtile_ocr_char_blacklist': '',
            'ocr_cleanup_enabled': True,
            'ocr_cleanup_normalize_ellipsis': False,

            # --- Flexible Analysis Settings ---
            'source_separation_model': 'None (Use Original Audio)',
            'filtering_method': 'Dialogue Band-Pass Filter',
            'correlation_method': 'Phase Correlation (GCC-PHAT)',
            'min_accepted_chunks': 3,
            'log_audio_drift': True,

            # --- DSP & Filtering ---
            'filter_bandpass_lowcut_hz': 300.0,
            'filter_bandpass_highcut_hz': 3400.0,
            'filter_bandpass_order': 5,
            'filter_lowpass_taps': 101,
            'scan_start_percentage': 5.0,
            'scan_end_percentage': 95.0,

            'analysis_mode': 'Audio Correlation',
            'analysis_lang_source1': '',
            'analysis_lang_others': '',
            'scan_chunk_count': 10,
            'scan_chunk_duration': 15,
            'min_match_pct': 5.0,
            'videodiff_error_min': 0.0,
            'videodiff_error_max': 100.0,
            'use_soxr': False,
            'audio_decode_native': False,
            'audio_peak_fit': False,
            'audio_bandlimit_hz': 0,
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
            'disable_track_statistics_tags': False,
            'disable_header_compression': True,
            'archive_logs': True,
            'auto_apply_strict': False,

            # --- Post-merge options ---
            'post_mux_normalize_timestamps': False,
            'post_mux_strip_tags': False,

            # --- Enhanced Segmented Audio Correction ---
            'segmented_enabled': False,
            'segmented_qa_threshold': 85.0,
            'segment_scan_offset_s': 15.0,
            'segment_qa_chunk_count': 30,
            'segment_qa_min_accepted_chunks': 28,
            # Detection & Triage
            'detection_dbscan_epsilon_ms': 20.0,
            'detection_dbscan_min_samples': 2,
            'drift_detection_r2_threshold': 0.90,
            'drift_detection_r2_threshold_lossless': 0.95,
            'drift_detection_slope_threshold_lossy': 0.7,
            'drift_detection_slope_threshold_lossless': 0.2,
            'segment_triage_std_dev_ms': 50,
            # Segment Scan & Correction
            'segment_coarse_chunk_s': 15,
            'segment_coarse_step_s': 60,
            'segment_search_locality_s': 10,
            'segment_drift_r2_threshold': 0.75,
            'segment_drift_slope_threshold': 0.7,
            'segment_drift_outlier_sensitivity': 1.5,
            'segment_drift_scan_buffer_pct': 2.0,

            # --- Resampling Engine Settings ---
            'segment_resample_engine': 'aresample',
            'segment_rb_pitch_correct': False,
            'segment_rb_transients': 'crisp',
            'segment_rb_smoother': True,
            'segment_rb_pitchq': True,

            # Fine Scan & Confidence
            'segment_min_confidence_ratio': 5.0,
            'segment_fine_chunk_s': 2.0,
            'segment_fine_iterations': 10,
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

                if 'post_mux_validate_metadata' in loaded_settings:
                    del loaded_settings['post_mux_validate_metadata']
                    changed = True
                if 'analysis_lang_ref' in loaded_settings and not loaded_settings.get('analysis_lang_source1'):
                    loaded_settings['analysis_lang_source1'] = loaded_settings['analysis_lang_ref']
                    changed = True
                if 'analysis_lang_sec' in loaded_settings and not loaded_settings.get('analysis_lang_others'):
                    loaded_settings['analysis_lang_others'] = loaded_settings['analysis_lang_sec']
                    changed = True
                for old_key in ['analysis_lang_ref', 'analysis_lang_sec', 'analysis_lang_ter']:
                    if old_key in loaded_settings:
                        del loaded_settings[old_key]
                        changed = True

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
        try:
            keys_to_save = self.defaults.keys()
            settings_to_save = {k: self.settings.get(k) for k in keys_to_save if k in self.settings}
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings_to_save, f, indent=4)
        except IOError as e:
            print(f"Error saving settings: {e}")

    def get(self, key: str, default: any = None) -> any:
        return self.settings.get(key, default)

    def set(self, key: str, value: any):
        self.settings[key] = value

    def ensure_dirs_exist(self):
        Path(self.get('output_folder')).mkdir(parents=True, exist_ok=True)
        Path(self.get('temp_root')).mkdir(parents=True, exist_ok=True)
