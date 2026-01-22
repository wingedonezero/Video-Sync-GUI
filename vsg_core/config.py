# vsg_core/config.py
# -*- coding: utf-8 -*-
"""
Application Configuration Module

Manages persistent user settings stored in settings.json. Settings are organized
into categories:

- Paths: Last used paths, output folders, tool locations
- Subtitle Sync: Time-based vs frame-based sync modes, FPS, rounding
- Frame Matching: Hash-based frame alignment settings (window, threshold, workers)
- Timing Fixes: Overlap correction, duration limits, CPS enforcement
- Audio Analysis: Source separation, filtering, correlation methods, drift detection
- DSP & Filtering: Band-pass filters, chunk scanning parameters
- Stepping Correction: Advanced audio stepping detection/correction with silence
  snapping, VAD protection, transient detection, quality thresholds
- Resampling: Engine selection (aresample/rubberband) and quality settings
- Track Naming: Custom labels for corrected/preserved audio tracks
- Post-Processing: Timestamp normalization, tag stripping, metadata options
- Logging: Compact mode, autoscroll, error tailing, progress display

The AppConfig class handles loading, saving, migrating old settings, and ensuring
required directories exist. New settings are automatically added with defaults when
the config file is loaded.

Validation ensures type safety and catches configuration errors early.
"""
import json
import warnings
from pathlib import Path
from typing import Any, Optional, Set

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
            'logs_folder': str(self.script_dir / 'logs'),
            'videodiff_path': '',

            # --- OCR Settings ---
            'ocr_enabled': True,  # Enable OCR for image-based subtitles
            'ocr_engine': 'tesseract',  # OCR engine: 'tesseract', 'easyocr', 'paddleocr'
            'ocr_language': 'eng',  # Tesseract language code
            'ocr_char_blacklist': '',  # Characters to exclude from OCR
            'ocr_output_format': 'ass',  # 'ass' or 'srt'

            # OCR Preprocessing
            'ocr_preprocess_auto': True,  # Auto-detect optimal preprocessing
            'ocr_force_binarization': False,  # Force binary thresholding
            'ocr_upscale_threshold': 40,  # Upscale if height < this (pixels)
            'ocr_denoise': False,  # Apply denoising

            # OCR Post-Processing
            'ocr_cleanup_enabled': True,  # Enable pattern-based text cleanup
            'ocr_cleanup_normalize_ellipsis': False,  # Convert … to ...
            'ocr_custom_wordlist_path': '',  # Custom wordlist for anime names, etc.
            'ocr_low_confidence_threshold': 60.0,  # Flag lines below this confidence

            # OCR Position Handling
            'ocr_preserve_positions': True,  # Keep non-bottom subtitle positions
            'ocr_bottom_threshold': 75.0,  # Y% threshold for "bottom" (configurable)

            # OCR Reporting
            'ocr_generate_report': True,  # Generate detailed OCR report
            'ocr_save_debug_images': False,  # Save preprocessed images for debugging
            'ocr_debug_output': False,  # Save debug output by issue type (unknown words, fixes, low confidence)

            # --- Subtitle Sync Settings ---
            'subtitle_sync_mode': 'time-based',
            'subtitle_target_fps': 0.0,
            'time_based_use_raw_values': False,  # Use pysubs instead of mkvmerge --sync

            # --- Unified Frame Matching Settings (shared by all frame-based sync modes) ---
            'frame_hash_algorithm': 'dhash',  # Hash algorithm: 'dhash', 'phash', 'average_hash', 'whash'
            'frame_hash_size': 8,  # Hash size: 4, 8, or 16 (higher = more precise but stricter)
            'frame_hash_threshold': 5,  # Max hamming distance for frame match (0-30)
            'frame_window_radius': 5,  # Frames before/after center (5 = 11 frame window)
            'frame_search_range_ms': 2000,  # Search ±N ms around expected position
            'frame_agreement_tolerance_ms': 100,  # Checkpoints must agree within ±N ms
            'frame_use_vapoursynth': True,  # Use VapourSynth for frame extraction (faster with cache)

            # --- Unified Rounding Settings ---
            'subtitle_rounding': 'floor',  # Final rounding for all sync modes: floor, round, ceil

            # --- Time-Based Frame-Locked Timestamps Settings ---
            'videotimestamps_rounding': 'floor',  # VideoTimestamps rounding method: 'floor' or 'round' (deprecated, use subtitle_rounding)

            # --- Duration-Align Sync Settings ---
            'duration_align_validate': True,  # Enable validation of duration-based sync
            'duration_align_validate_points': 3,  # Number of validation checkpoints (1 or 3)
            'duration_align_strictness': 80,  # Validation strictness: percentage of frames that must match (0-100)
            'duration_align_verify_with_frames': False,  # Enable hybrid: duration + sliding window verification
            'duration_align_skip_validation_generated_tracks': True,  # Skip validation for generated tracks
            'duration_align_fallback_mode': 'none',  # Fallback: 'none', 'abort', 'auto-fallback', 'duration-offset'

            # --- Correlation + Frame Snap Settings ---
            'correlation_snap_fallback_mode': 'snap-to-frame',  # Fallback: 'snap-to-frame', 'use-raw', 'abort'
            'correlation_snap_use_scene_changes': True,  # Use PySceneDetect to find anchor points

            # --- Subtitle-Anchored Frame Snap Settings ---
            'sub_anchor_fallback_mode': 'abort',  # Fallback: 'abort', 'use-median'

            # --- Correlation-Guided Frame Anchor Settings ---
            'corr_anchor_fallback_mode': 'use-correlation',  # Fallback: 'abort', 'use-median', 'use-correlation'
            'corr_anchor_anchor_positions': [10, 50, 90],  # % of video duration for anchor points
            'corr_anchor_refine_per_line': False,  # Refine each subtitle line to exact frames after checkpoint validation
            'corr_anchor_refine_workers': 4,  # Number of parallel workers for refinement

            # ===== DEPRECATED: Mode-specific settings (use unified frame_* settings instead) =====
            # Kept for backwards compatibility - unified settings take precedence
            'raw_delay_rounding': 'floor',  # DEPRECATED: Use subtitle_rounding
            'duration_align_hash_algorithm': 'dhash',
            'duration_align_hash_size': 8,
            'duration_align_hash_threshold': 5,
            'duration_align_use_vapoursynth': True,
            'duration_align_verify_search_window_ms': 2000,
            'duration_align_verify_agreement_tolerance_ms': 100,
            'duration_align_verify_checkpoints': 3,
            'duration_align_fallback_target': 'source1',
            'correlation_snap_hash_algorithm': 'dhash',
            'correlation_snap_hash_size': 8,
            'correlation_snap_hash_threshold': 5,
            'correlation_snap_window_radius': 3,
            'correlation_snap_search_range': 5,
            'sub_anchor_search_range_ms': 2000,
            'sub_anchor_hash_algorithm': 'dhash',
            'sub_anchor_hash_size': 8,
            'sub_anchor_hash_threshold': 5,
            'sub_anchor_window_radius': 5,
            'sub_anchor_agreement_tolerance_ms': 100,
            'sub_anchor_use_vapoursynth': True,
            'corr_anchor_search_range_ms': 2000,
            'corr_anchor_hash_algorithm': 'dhash',
            'corr_anchor_hash_size': 8,
            'corr_anchor_hash_threshold': 5,
            'corr_anchor_window_radius': 5,
            'corr_anchor_agreement_tolerance_ms': 100,
            'corr_anchor_use_vapoursynth': True,
            # Old frame_match_* settings - deprecated
            'frame_match_method': 'dhash',
            'frame_match_hash_size': 8,
            'frame_match_threshold': 5,
            'frame_match_search_window_frames': 10,
            'frame_match_search_window_sec': 2.0,
            'frame_match_max_search_frames': 100,
            'frame_match_skip_unmatched': False,
            'frame_match_use_timestamp_prefilter': True,
            'frame_match_workers': 4,

            # --- Timing Fix Settings ---
            'timing_fix_enabled': False,
            'timing_fix_overlaps': True,
            'timing_overlap_min_gap_ms': 1,
            'timing_fix_short_durations': True,
            'timing_min_duration_ms': 500,
            'timing_fix_long_durations': True,
            'timing_max_cps': 20.0,

            # --- Flexible Analysis Settings ---
            'source_separation_mode': 'none',  # 'none', 'instrumental', 'vocals'
            'source_separation_model': 'default',  # Model filename or 'default'
            'source_separation_model_dir': str(self.script_dir / 'audio_separator_models'),
            'source_separation_device': 'auto',  # Device for source separation: 'auto', 'cpu', 'cuda', 'rocm', 'mps'
            'source_separation_timeout': 900,  # Timeout in seconds for source separation (0 = no timeout, default 900s = 15 min)
            'filtering_method': 'Dialogue Band-Pass Filter',
            'correlation_method': 'Phase Correlation (GCC-PHAT)',
            'correlation_method_source_separated': 'Phase Correlation (GCC-PHAT)',
            'min_accepted_chunks': 3,
            'log_audio_drift': True,

            # --- Multi-Correlation Comparison (Analyze Only) ---
            'multi_correlation_enabled': False,
            'multi_corr_scc': True,
            'multi_corr_gcc_phat': True,
            'multi_corr_onset': False,
            'multi_corr_gcc_scot': False,
            'multi_corr_gcc_whiten': False,
            'multi_corr_dtw': False,
            'multi_corr_spectrogram': False,

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
            'delay_selection_mode_source_separated': 'Mode (Clustered)',
            'first_stable_min_chunks': 3,
            'first_stable_skip_unstable': True,
            'early_cluster_window': 10,
            'early_cluster_threshold': 5,
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
            'stepping_silence_search_window_s': 5.0,  # Search window in seconds (±N seconds from detected boundary)
            'stepping_silence_threshold_db': -40.0,  # Audio level in dB to consider as silence
            'stepping_silence_min_duration_ms': 100.0,  # Minimum silence duration to be considered for snapping

            # --- Advanced Silence Detection Methods ---
            'stepping_silence_detection_method': 'smart_fusion',  # 'rms_basic', 'ffmpeg_silencedetect', 'smart_fusion'

            # FFmpeg silencedetect options (most accurate, frame-perfect)
            'stepping_ffmpeg_silence_noise': -40.0,  # dB threshold for FFmpeg silencedetect
            'stepping_ffmpeg_silence_duration': 0.1,  # Minimum silence duration in seconds

            # Speech Protection (prevents cutting dialogue mid-sentence)
            'stepping_vad_enabled': True,  # Enable Voice Activity Detection to protect speech
            'stepping_vad_aggressiveness': 2,  # 0-3: 0=least aggressive (keeps more audio), 3=most aggressive
            'stepping_vad_avoid_speech': True,  # Never cut in detected speech regions
            'stepping_vad_frame_duration_ms': 30,  # VAD analysis frame size (10, 20, or 30ms)

            # Transient Detection (prevents cutting on musical beats/impacts)
            'stepping_transient_detection_enabled': True,  # Avoid cutting on musical transients
            'stepping_transient_threshold': 8.0,  # dB increase threshold for transient detection
            'stepping_transient_avoid_window_ms': 50,  # Avoid cuts within ±N ms of transients

            # Smart Fusion Scoring Weights (for 'smart_fusion' method)
            'stepping_fusion_weight_silence': 10,  # Weight for deep silence (low RMS)
            'stepping_fusion_weight_no_speech': 8,  # Weight for non-speech regions
            'stepping_fusion_weight_scene_align': 5,  # Weight for alignment with scene changes
            'stepping_fusion_weight_duration': 2,  # Weight for longer silence zones
            'stepping_fusion_weight_no_transient': 3,  # Weight for avoiding transients

            # --- Video-Aware Boundary Snapping ---
            'stepping_snap_to_video_frames': False,  # Enable boundary snapping to video frames/scenes
            'stepping_video_snap_mode': 'scenes',  # 'scenes', 'keyframes', or 'any_frame'
            'stepping_video_snap_max_offset_s': 2.0,  # Maximum distance to snap (seconds)
            'stepping_video_scene_threshold': 0.4,  # Scene detection sensitivity (0.1-1.0, lower=more sensitive)

            # --- Stepping Quality Audit Thresholds ---
            'stepping_audit_min_score': 12.0,  # Minimum boundary score (warning if below)
            'stepping_audit_overflow_tolerance': 0.8,  # Max removal/silence ratio (0.8 = 80% of silence)
            'stepping_audit_large_correction_s': 3.0,  # Threshold for large correction warnings

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

            # --- Sync Stability (Correlation Variance Detection) ---
            'sync_stability_enabled': True,  # Enable variance detection in correlation results
            'sync_stability_variance_threshold': 0.0,  # Max allowed variance in ms (0 = any variance flagged)
            'sync_stability_min_chunks': 3,  # Minimum chunks needed to calculate variance
            'sync_stability_outlier_mode': 'any',  # 'any' = flag any variance, 'threshold' = use custom threshold
            'sync_stability_outlier_threshold': 1.0,  # Custom outlier threshold in ms (when mode='threshold')
        }
        self.settings = self.defaults.copy()
        self._accessed_keys: Set[str] = set()  # Track accessed keys for typo detection
        self._validation_enabled = True  # Can be disabled for backwards compatibility
        self.load()
        self._ensure_types_coerced()  # Additional safety: ensure all values have correct types
        self.ensure_dirs_exist()

    def _validate_value(self, key: str, value: Any) -> tuple[bool, Optional[str]]:
        """
        Validates a config value against expected type and range.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self._validation_enabled:
            return True, None

        # Type and range validation based on key patterns
        if key.endswith('_enabled') or key.startswith('log_') and not key.endswith(('_lines', '_step', '_tail')):
            if not isinstance(value, bool):
                return False, f"{key} must be bool, got {type(value).__name__}"

        elif key.endswith(('_pct', '_percentage')):
            if not isinstance(value, (int, float)):
                return False, f"{key} must be numeric, got {type(value).__name__}"
            if not (0.0 <= value <= 100.0):
                return False, f"{key} must be 0-100, got {value}"

        elif key.endswith(('_ms', '_duration_ms', '_gap_ms', '_window_ms', '_tolerance_ms')):
            if not isinstance(value, (int, float)):
                return False, f"{key} must be numeric, got {type(value).__name__}"
            if value < 0:
                return False, f"{key} cannot be negative, got {value}"

        elif key.endswith(('_hz', '_lowcut_hz', '_highcut_hz', '_bandlimit_hz')):
            if not isinstance(value, (int, float)):
                return False, f"{key} must be numeric, got {type(value).__name__}"
            if value < 0:
                return False, f"{key} cannot be negative, got {value}"

        elif key.endswith(('_db', '_threshold_db', '_noise')):
            if not isinstance(value, (int, float)):
                return False, f"{key} must be numeric, got {type(value).__name__}"
            if value > 0:
                warnings.warn(f"{key} is typically negative (dB), got {value}")

        elif key.endswith(('_count', '_chunks', '_samples', '_taps', '_workers', '_points')):
            if not isinstance(value, int):
                return False, f"{key} must be int, got {type(value).__name__}"
            if value < 0:
                return False, f"{key} cannot be negative, got {value}"

        elif key.endswith(('_threshold', '_ratio')):
            if not isinstance(value, (int, float)):
                return False, f"{key} must be numeric, got {type(value).__name__}"
            if value < 0:
                return False, f"{key} cannot be negative, got {value}"

        # Enum validation for specific keys
        if key == 'source_separation_device':
            valid = ['auto', 'cpu', 'cuda', 'rocm', 'mps']
            if value not in valid:
                return False, f"{key} must be one of {valid}, got '{value}'"
        elif key == 'source_separation_mode':
            valid = ['none', 'instrumental', 'vocals']
            if value not in valid:
                return False, f"{key} must be one of {valid}, got '{value}'"

        elif key in ('frame_match_method', 'duration_align_hash_algorithm', 'correlation_snap_hash_algorithm',
                     'sub_anchor_hash_algorithm', 'corr_anchor_hash_algorithm'):
            valid = ['dhash', 'phash', 'average_hash']
            if value not in valid:
                return False, f"{key} must be one of {valid}, got '{value}'"

        elif key.endswith('_fallback_mode'):
            # Don't enforce specific values as different modes have different options
            if not isinstance(value, str):
                return False, f"{key} must be string, got {type(value).__name__}"

        elif key in ('sync_mode', 'analysis_mode', 'delay_selection_mode'):
            if not isinstance(value, str):
                return False, f"{key} must be string, got {type(value).__name__}"

        elif key == 'stepping_silence_detection_method':
            valid = ['rms_basic', 'ffmpeg_silencedetect', 'smart_fusion']
            if value not in valid:
                return False, f"{key} must be one of {valid}, got '{value}'"

        elif key == 'segment_resample_engine':
            valid = ['aresample', 'rubberband']
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
        if type(value) == type(default_value):
            return value

        # Try to coerce to default's type
        try:
            if isinstance(default_value, bool):
                # Handle bool specially - strings need explicit conversion
                if isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes', 'on')
                return bool(value)
            elif isinstance(default_value, int):
                # Convert to float first, then int (handles "10.0" strings)
                return int(float(value))
            elif isinstance(default_value, float):
                return float(value)
            elif isinstance(default_value, str):
                return str(value)
            else:
                # Unknown type, return as-is
                return value
        except (ValueError, TypeError):
            # Coercion failed, return default value
            warnings.warn(
                f"Config key '{key}' has invalid value '{value}', using default: {default_value}",
                UserWarning
            )
            return default_value

    def _ensure_types_coerced(self):
        """
        Ensures all values in self.settings match the expected types from defaults.

        This provides an additional safety layer for UI code that accesses
        config.settings dict directly, bypassing the get() method.
        """
        for key in list(self.settings.keys()):  # Use list() to avoid dict size change during iteration
            if key in self.defaults:
                current_value = self.settings[key]
                expected_type_value = self.defaults[key]
                coerced_value = self._coerce_type(key, current_value, expected_type_value)
                self.settings[key] = coerced_value

    def validate_all(self) -> list[str]:
        """
        Validates all settings and returns list of error messages.

        Returns:
            List of validation error messages (empty if all valid)
        """
        errors = []
        for key, value in self.settings.items():
            is_valid, error_msg = self._validate_value(key, value)
            if not is_valid:
                errors.append(error_msg)
        return errors

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

                if loaded_settings.get('source_separation_device') == 'cpu':
                    loaded_settings['source_separation_device'] = 'auto'
                    changed = True

                legacy_separation_map = {
                    'Demucs - Music/Effects (Strip Vocals)': 'instrumental',
                    'Demucs - Vocals Only': 'vocals',
                }
                legacy_selection = loaded_settings.get('source_separation_model')
                if legacy_selection in legacy_separation_map:
                    loaded_settings['source_separation_mode'] = legacy_separation_map[legacy_selection]
                    loaded_settings['source_separation_model'] = 'default'
                    changed = True

                for key, default_value in self.defaults.items():
                    if key not in loaded_settings:
                        loaded_settings[key] = default_value
                        changed = True

                # Coerce types to match defaults (fixes string numbers from JSON)
                for key, value in loaded_settings.items():
                    if key in self.defaults:
                        coerced = self._coerce_type(key, value, self.defaults[key])
                        if coerced != value:
                            loaded_settings[key] = coerced
                            changed = True

                self.settings = loaded_settings

                # Validate loaded settings
                if self._validation_enabled:
                    validation_errors = self.validate_all()
                    if validation_errors:
                        warnings.warn(
                            f"Config validation found {len(validation_errors)} issue(s):\n" +
                            "\n".join(f"  - {err}" for err in validation_errors[:5]) +
                            (f"\n  ... and {len(validation_errors) - 5} more" if len(validation_errors) > 5 else ""),
                            UserWarning
                        )
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

    def get(self, key: str, default: Any = None) -> Any:
        """
        Gets a config value with automatic type coercion.

        Tracks accessed keys for typo detection. If a key is not in defaults
        and no default is provided, warns about potential typo.

        Always coerces the value to match the expected type from defaults,
        providing an additional safety layer against type mismatches.
        """
        self._accessed_keys.add(key)

        # Warn if accessing a key that's not in defaults and no default provided
        if key not in self.defaults and default is None:
            warnings.warn(
                f"Config key '{key}' not found in defaults. Possible typo? Returning None.",
                UserWarning,
                stacklevel=2
            )

        value = self.settings.get(key, default)

        # Apply type coercion if we have a default to match against
        if key in self.defaults and value is not None:
            value = self._coerce_type(key, value, self.defaults[key])

        return value

    def set(self, key: str, value: Any):
        """
        Sets a config value with optional validation.

        Validates the value before setting if validation is enabled.
        """
        if self._validation_enabled:
            is_valid, error_msg = self._validate_value(key, value)
            if not is_valid:
                raise ValueError(f"Invalid config value: {error_msg}")

        self.settings[key] = value

    def get_unrecognized_keys(self) -> Set[str]:
        """
        Returns set of accessed keys that are not in defaults.

        Useful for detecting typos in config access.
        """
        return self._accessed_keys - set(self.defaults.keys())

    def ensure_dirs_exist(self):
        Path(self.get('output_folder')).mkdir(parents=True, exist_ok=True)
        Path(self.get('temp_root')).mkdir(parents=True, exist_ok=True)
        Path(self.get('logs_folder')).mkdir(parents=True, exist_ok=True)
        # Create .config and .fonts directories for new features
        self.get_config_dir().mkdir(parents=True, exist_ok=True)
        self.get_fonts_dir().mkdir(parents=True, exist_ok=True)
        self.get_ocr_config_dir().mkdir(parents=True, exist_ok=True)

    def get_config_dir(self) -> Path:
        """Returns the path to the .config directory for storing app configuration files."""
        return self.script_dir / '.config'

    def get_fonts_dir(self) -> Path:
        """Returns the path to the .fonts directory for user font files."""
        return self.script_dir / '.fonts'

    def get_ocr_config_dir(self) -> Path:
        """Returns the path to the .config/ocr directory for OCR configuration files."""
        return self.get_config_dir() / 'ocr'

    def get_default_wordlist_path(self) -> Path:
        """Returns the default path for the OCR custom wordlist."""
        return self.get_ocr_config_dir() / 'custom_wordlist.txt'
