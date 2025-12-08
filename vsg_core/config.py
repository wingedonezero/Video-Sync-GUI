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
            'ocr_cleanup_custom_wordlist_path': '',

            # --- Timing Fix Settings ---
            'timing_fix_enabled': False,
            'timing_fix_overlaps': True,
            'timing_overlap_min_gap_ms': 1,
            'timing_fix_short_durations': True,
            'timing_min_duration_ms': 500,
            'timing_fix_long_durations': True,
            'timing_max_cps': 20.0,

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
            'delay_selection_mode': 'Mode (Most Common)',
            'first_stable_min_chunks': 3,
            'first_stable_skip_unstable': True,
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

            # --- Timing Sync Mode ---
            'sync_mode': 'positive_only',

            # --- Post-merge options ---
            'post_mux_normalize_timestamps': False,
            'post_mux_strip_tags': False,

            # --- Enhanced Segmented Audio Correction ---
            'segmented_enabled': False,
            'segmented_qa_threshold': 85.0,
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

            # --- Stepping Correction Enhancements ---
            'stepping_first_stable_min_chunks': 3,  # Min chunks for first stable segment (stepping delay selection)
            'stepping_first_stable_skip_unstable': True,  # Skip unstable segments when detecting stepping delay
            'stepping_fill_mode': 'silence',  # 'auto', 'silence', or 'content' - how to fill delay gaps
            'stepping_diagnostics_verbose': True,  # Enable detailed cluster composition reports
            'stepping_content_correlation_threshold': 0.5,  # Min correlation for content extraction (for auto/content modes)
            'stepping_content_search_window_s': 5.0,  # Search window for finding matching content (for auto/content modes)
            'stepping_scan_start_percentage': 5.0,  # Independent scan start for stepping correction
            'stepping_scan_end_percentage': 99.0,  # Independent scan end for stepping correction (higher to catch end boundaries)
            'stepping_adjust_subtitles': True,  # Adjust subtitle timestamps to match stepped audio corrections
            'stepping_adjust_subtitles_no_audio': True,  # Apply stepping to subtitles when no audio is merged (uses correlation-based EDL)
            'stepping_boundary_mode': 'start',  # How to handle subs spanning boundaries: 'start', 'majority', 'midpoint'

            # --- Track Naming ---
            'stepping_corrected_track_label': '',  # Label for corrected audio in final MKV (empty = no label, e.g., "Stepping Corrected")
            'stepping_preserved_track_label': '',  # Label for preserved original in final MKV (empty = no label, e.g., "Original")

            # --- Silence-Aware Boundary Snapping ---
            'stepping_snap_to_silence': True,  # Enable boundary snapping to silence zones
            'stepping_silence_search_window_s': 3.0,  # Search window in seconds (±N seconds from detected boundary)
            'stepping_silence_threshold_db': -40.0,  # Audio level in dB to consider as silence
            'stepping_silence_min_duration_ms': 100.0,  # Minimum silence duration to be considered for snapping

            # --- Video-Aware Boundary Snapping ---
            'stepping_snap_to_video_frames': False,  # Enable boundary snapping to video frames/scenes
            'stepping_video_snap_mode': 'scenes',  # 'scenes', 'keyframes', or 'any_frame'
            'stepping_video_snap_max_offset_s': 2.0,  # Maximum distance to snap (seconds)
            'stepping_video_scene_threshold': 0.4,  # Scene detection sensitivity (0.1-1.0, lower=more sensitive)

            # --- Filtered Stepping Correction (New) ---
            'stepping_correction_mode': 'full',  # 'full', 'filtered', 'strict', 'disabled'
            'stepping_quality_mode': 'normal',  # 'strict', 'normal', 'lenient', 'custom'

            # Quality Validation Thresholds (for 'custom' mode)
            'stepping_min_chunks_per_cluster': 3,  # Minimum chunks required per cluster
            'stepping_min_cluster_percentage': 5.0,  # Min % of total chunks a cluster must represent
            'stepping_min_cluster_duration_s': 20.0,  # Min duration in seconds
            'stepping_min_match_quality_pct': 85.0,  # Min average match quality percentage
            'stepping_min_total_clusters': 2,  # Minimum number of total clusters required

            # Filtered Region Handling
            'stepping_filtered_fallback': 'nearest',  # 'nearest', 'interpolate', 'uniform', 'skip', 'reject'
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
