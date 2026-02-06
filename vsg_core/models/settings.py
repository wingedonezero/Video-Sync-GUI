# vsg_core/models/settings.py
"""Application settings Pydantic model - THE SINGLE SOURCE OF TRUTH.

This module defines ALL application settings with their default values.
AppConfig derives its defaults from this model - do NOT maintain
separate defaults elsewhere.

To add a new setting:
1. Add the field here with a default value
2. That's it - AppConfig will automatically pick it up

Settings are organized by category:
- Paths: Output, temp, logs directories
- Analysis: Audio correlation, video diff settings
- Chapters: Renaming, snapping options
- Muxing: Track statistics, compression options
- Logging: Display, archiving options
- OCR: Optical character recognition settings
- Subtitle Sync: Time-based, frame-based sync modes
- Stepping Correction: Segmented audio correction
- Resampling: Audio resampling engine settings
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from .types import (  # noqa: TC001 - Pydantic needs these at runtime
    AnalysisModeStr,
    SnapModeStr,
)

# Sentinel for path defaults that need runtime resolution
# These will be resolved by AppConfig based on script_dir
_PATH_SENTINEL = "__PATH_NEEDS_RESOLUTION__"


class AppSettings(BaseModel):
    """Complete application settings with typed fields and defaults.

    All pipeline code should access settings through this model,
    not through raw dict access. This ensures type safety and IDE support.

    IMPORTANT: All defaults are defined HERE. AppConfig derives from this.

    Pydantic handles:
    - Type coercion (str "10" -> int 10, str "true" -> bool True)
    - Validation (Literal types, ranges)
    - JSON serialization/deserialization
    - Extra key handling (ignored gracefully)
    """

    model_config = ConfigDict(
        extra="ignore",  # Unknown JSON keys are silently dropped
        validate_assignment=True,  # Validate on setattr too
        str_strip_whitespace=False,  # Don't strip whitespace from strings
    )

    # =========================================================================
    # Path Settings (defaults resolved at runtime by AppConfig)
    # =========================================================================
    output_folder: str = _PATH_SENTINEL
    temp_root: str = _PATH_SENTINEL
    logs_folder: str = _PATH_SENTINEL
    videodiff_path: str = ""
    fonts_directory: str = ""
    last_ref_path: str = ""
    last_sec_path: str = ""
    last_ter_path: str = ""
    source_separation_model_dir: str = _PATH_SENTINEL

    # =========================================================================
    # Analysis Settings
    # =========================================================================
    analysis_mode: AnalysisModeStr = "Audio Correlation"
    analysis_lang_source1: str | None = None
    analysis_lang_others: str | None = None
    scan_chunk_count: int = 10
    scan_chunk_duration: int = 15
    min_match_pct: float = 5.0
    videodiff_error_min: float = 0.0
    videodiff_error_max: float = 100.0

    # =========================================================================
    # Chapter Settings
    # =========================================================================
    rename_chapters: bool = False
    snap_chapters: bool = False
    snap_mode: SnapModeStr = "previous"
    snap_threshold_ms: int = 250
    snap_starts_only: bool = True

    # =========================================================================
    # Muxing Settings
    # =========================================================================
    apply_dialog_norm_gain: bool = False
    disable_track_statistics_tags: bool = False
    disable_header_compression: bool = True

    # =========================================================================
    # Post-Mux Settings
    # =========================================================================
    post_mux_normalize_timestamps: bool = False
    post_mux_strip_tags: bool = False

    # =========================================================================
    # Logging Settings
    # =========================================================================
    log_compact: bool = True
    log_autoscroll: bool = True
    log_error_tail: int = 20
    log_tail_lines: int = 0
    log_progress_step: int = 20
    log_show_options_pretty: bool = False
    log_show_options_json: bool = False
    log_audio_drift: bool = True
    archive_logs: bool = True

    # =========================================================================
    # Timing Sync Settings
    # =========================================================================
    auto_apply_strict: bool = False
    sync_mode: str = "positive_only"

    # =========================================================================
    # Timing Fix Settings
    # =========================================================================
    timing_fix_enabled: bool = False
    timing_fix_overlaps: bool = True
    timing_overlap_min_gap_ms: int = 1
    timing_fix_short_durations: bool = True
    timing_min_duration_ms: int = 500
    timing_fix_long_durations: bool = True
    timing_max_cps: float = 20.0

    # =========================================================================
    # Segmented Audio Correction
    # =========================================================================
    segmented_enabled: bool = False

    # =========================================================================
    # Subtitle Sync Settings
    # =========================================================================
    subtitle_sync_mode: str = "time-based"
    time_based_use_raw_values: bool = False
    time_based_bypass_subtitle_data: bool = True
    subtitle_rounding: str = "floor"
    subtitle_target_fps: float = 0.0
    videotimestamps_snap_mode: str = "start"
    videotimestamps_rounding: str = "round"

    # =========================================================================
    # Frame Matching Settings (shared by all frame-based sync modes)
    # =========================================================================
    frame_hash_algorithm: str = "dhash"
    frame_hash_size: int = 8
    frame_hash_threshold: int = 5
    frame_window_radius: int = 5
    frame_search_range_ms: int = 2000
    frame_agreement_tolerance_ms: int = 100
    frame_use_vapoursynth: bool = True
    frame_comparison_method: str = "hash"

    # =========================================================================
    # Correlation Snap Settings
    # =========================================================================
    correlation_snap_fallback_mode: str = "snap-to-frame"
    correlation_snap_use_scene_changes: bool = True

    # =========================================================================
    # Correlation-Guided Frame Anchor Settings
    # =========================================================================
    corr_anchor_fallback_mode: str = "use-correlation"
    corr_anchor_anchor_positions: list[int] = [10, 50, 90]
    corr_anchor_refine_per_line: bool = False
    corr_anchor_refine_workers: int = 4

    # =========================================================================
    # Subtitle-Anchored Frame Snap Settings
    # =========================================================================
    sub_anchor_fallback_mode: str = "abort"

    # =========================================================================
    # Duration Align Settings
    # =========================================================================
    duration_align_verify_with_frames: bool = False
    duration_align_validate: bool = True
    duration_align_fallback_mode: str = "duration-offset"
    duration_align_validate_points: int = 3
    duration_align_strictness: int = 80
    duration_align_skip_validation_generated_tracks: bool = True

    # =========================================================================
    # Frame Lock Settings
    # =========================================================================
    frame_lock_submillisecond_precision: bool = False

    # =========================================================================
    # Video-Verified Sync Settings
    # =========================================================================
    video_verified_zero_check_frames: int = 3
    video_verified_min_quality_advantage: float = 0.1
    video_verified_num_checkpoints: int = 5
    video_verified_search_range_frames: int = 3
    video_verified_sequence_length: int = 10
    video_verified_use_pts_precision: bool = False
    video_verified_frame_audit: bool = False

    # =========================================================================
    # Interlaced Video Settings
    # =========================================================================
    interlaced_handling_enabled: bool = False
    interlaced_force_mode: str = "auto"
    interlaced_num_checkpoints: int = 5
    interlaced_search_range_frames: int = 5
    interlaced_hash_algorithm: str = "ahash"
    interlaced_hash_size: int = 8
    interlaced_hash_threshold: int = 25
    interlaced_comparison_method: str = "ssim"
    interlaced_fallback_to_audio: bool = True
    interlaced_sequence_length: int = 5
    interlaced_deinterlace_method: str = "bwdif"
    interlaced_use_ivtc: bool = False

    # =========================================================================
    # Analysis/Correlation Settings
    # =========================================================================
    source_separation_mode: str = "none"
    source_separation_model: str = "default"
    source_separation_device: str = "auto"
    source_separation_timeout: int = 900
    filtering_method: str = "Dialogue Band-Pass Filter"
    correlation_method: str = "Phase Correlation (GCC-PHAT)"
    correlation_method_source_separated: str = "Phase Correlation (GCC-PHAT)"

    # Delay Selection Settings
    delay_selection_mode: str = "Mode (Most Common)"
    delay_selection_mode_source_separated: str = "Mode (Clustered)"
    min_accepted_chunks: int = 3
    first_stable_min_chunks: int = 3
    first_stable_skip_unstable: bool = True
    early_cluster_window: int = 10
    early_cluster_threshold: int = 5

    # Multi-Correlation Comparison
    multi_correlation_enabled: bool = False
    multi_corr_scc: bool = True
    multi_corr_gcc_phat: bool = True
    multi_corr_onset: bool = False
    multi_corr_gcc_scot: bool = False
    multi_corr_gcc_whiten: bool = False
    multi_corr_dtw: bool = False
    multi_corr_spectrogram: bool = False

    # DSP & Filtering
    filter_bandpass_lowcut_hz: float = 300.0
    filter_bandpass_highcut_hz: float = 3400.0
    filter_bandpass_order: int = 5
    filter_lowpass_taps: int = 101
    scan_start_percentage: float = 5.0
    scan_end_percentage: float = 95.0
    use_soxr: bool = False
    audio_decode_native: bool = False
    audio_peak_fit: bool = False
    audio_bandlimit_hz: int = 0

    # Drift Detection Settings
    detection_dbscan_epsilon_ms: float = 20.0
    detection_dbscan_min_samples: int = 2
    drift_detection_r2_threshold: float = 0.90
    drift_detection_r2_threshold_lossless: float = 0.95
    drift_detection_slope_threshold_lossy: float = 0.7
    drift_detection_slope_threshold_lossless: float = 0.2

    # =========================================================================
    # Stepping Correction Settings
    # =========================================================================
    stepping_adjust_subtitles: bool = True
    stepping_adjust_subtitles_no_audio: bool = True
    stepping_boundary_mode: str = "start"
    stepping_first_stable_min_chunks: int = 3
    stepping_first_stable_skip_unstable: bool = True

    # Segment Scan & Correction
    segment_triage_std_dev_ms: int = 50
    segment_coarse_chunk_s: int = 15
    segment_coarse_step_s: int = 60
    segment_search_locality_s: int = 10
    segment_fine_chunk_s: float = 2.0
    segment_fine_iterations: int = 10
    segment_min_confidence_ratio: float = 5.0

    # Segment Drift Detection
    segment_drift_r2_threshold: float = 0.75
    segment_drift_slope_threshold: float = 0.7
    segment_drift_outlier_sensitivity: float = 1.5
    segment_drift_scan_buffer_pct: float = 2.0

    # Stepping Scan Range
    stepping_scan_start_percentage: float = 5.0
    stepping_scan_end_percentage: float = 99.0

    # Silence Snapping
    stepping_snap_to_silence: bool = True
    stepping_silence_detection_method: str = "smart_fusion"
    stepping_silence_search_window_s: float = 5.0
    stepping_silence_threshold_db: float = -40.0
    stepping_silence_min_duration_ms: float = 100.0
    stepping_ffmpeg_silence_noise: float = -40.0
    stepping_ffmpeg_silence_duration: float = 0.1

    # VAD (Voice Activity Detection)
    stepping_vad_enabled: bool = True
    stepping_vad_aggressiveness: int = 2
    stepping_vad_avoid_speech: bool = True
    stepping_vad_frame_duration_ms: int = 30

    # Transient Detection
    stepping_transient_detection_enabled: bool = True
    stepping_transient_threshold: float = 8.0
    stepping_transient_avoid_window_ms: int = 50

    # Smart Fusion Weights
    stepping_fusion_weight_silence: int = 10
    stepping_fusion_weight_no_speech: int = 8
    stepping_fusion_weight_scene_align: int = 5
    stepping_fusion_weight_duration: int = 2
    stepping_fusion_weight_no_transient: int = 3

    # Video-Aware Boundary Snapping
    stepping_snap_to_video_frames: bool = False
    stepping_video_snap_mode: str = "scenes"
    stepping_video_snap_max_offset_s: float = 2.0
    stepping_video_scene_threshold: float = 0.4

    # Fill Mode & Content
    stepping_fill_mode: str = "silence"
    stepping_content_correlation_threshold: float = 0.5
    stepping_content_search_window_s: float = 5.0

    # Track Naming
    stepping_corrected_track_label: str = ""
    stepping_preserved_track_label: str = ""

    # Quality Audit Thresholds
    stepping_audit_min_score: float = 12.0
    stepping_audit_overflow_tolerance: float = 0.8
    stepping_audit_large_correction_s: float = 3.0

    # Filtered Stepping Correction
    stepping_correction_mode: str = "full"
    stepping_quality_mode: str = "normal"
    stepping_min_chunks_per_cluster: int = 3
    stepping_min_cluster_percentage: float = 5.0
    stepping_min_cluster_duration_s: float = 20.0
    stepping_min_match_quality_pct: float = 85.0
    stepping_min_total_clusters: int = 2
    stepping_filtered_fallback: str = "nearest"
    stepping_diagnostics_verbose: bool = True

    # Segmented Audio QA
    segmented_qa_threshold: float = 85.0
    segment_qa_chunk_count: int = 30
    segment_qa_min_accepted_chunks: int = 28

    # =========================================================================
    # Sync Stability Settings
    # =========================================================================
    sync_stability_enabled: bool = True
    sync_stability_variance_threshold: float = 0.0
    sync_stability_min_chunks: int = 3
    sync_stability_outlier_mode: str = "any"
    sync_stability_outlier_threshold: float = 1.0

    # =========================================================================
    # Resampling Engine Settings
    # =========================================================================
    segment_resample_engine: str = "aresample"
    segment_rb_pitch_correct: bool = False
    segment_rb_transients: str = "crisp"
    segment_rb_smoother: bool = True
    segment_rb_pitchq: bool = True

    # =========================================================================
    # OCR Settings
    # =========================================================================
    ocr_enabled: bool = True
    ocr_engine: str = "tesseract"
    ocr_language: str = "eng"
    ocr_psm: int = 7
    ocr_char_whitelist: str = ""
    ocr_char_blacklist: str = "|"
    ocr_low_confidence_threshold: float = 60.0
    ocr_multi_pass: bool = True
    ocr_output_format: str = "ass"

    # OCR Preprocessing
    ocr_preprocess_auto: bool = True
    ocr_upscale_threshold: int = 40
    ocr_target_height: int = 80
    ocr_border_size: int = 5
    ocr_force_binarization: bool = False
    ocr_binarization_method: str = "otsu"
    ocr_denoise: bool = False
    ocr_save_debug_images: bool = False

    # OCR Output & Position
    ocr_preserve_positions: bool = True
    ocr_bottom_threshold: float = 75.0
    ocr_video_width: int = 1920
    ocr_video_height: int = 1080

    # OCR Post-Processing
    ocr_cleanup_enabled: bool = True
    ocr_cleanup_normalize_ellipsis: bool = False
    ocr_custom_wordlist_path: str = ""

    # OCR Debug & Runtime
    ocr_debug_output: bool = False
    ocr_run_in_subprocess: bool = True
    ocr_font_size_ratio: float = 5.80
    ocr_generate_report: bool = True

    # =========================================================================
    # Class-level constants (excluded from serialization)
    # =========================================================================
    PATH_SENTINEL: ClassVar[str] = _PATH_SENTINEL

    @classmethod
    def get_defaults(cls) -> dict[str, Any]:
        """Get all field defaults as a dictionary.

        This is THE source of truth for defaults. AppConfig should use this
        instead of maintaining a separate defaults dict.

        Returns:
            Dict mapping field names to their default values.
            All values are JSON-compatible (no enums or tuples).
        """
        result = {}
        for name, field_info in cls.model_fields.items():
            default = field_info.default
            if default is not None:
                result[name] = default
            # Check for default_factory
            elif field_info.default_factory is not None:
                result[name] = field_info.default_factory()
            else:
                result[name] = None
        return result

    @classmethod
    def get_field_names(cls) -> set[str]:
        """Get all field names as a set.

        Useful for validation - checking if a key exists in settings.
        """
        return set(cls.model_fields.keys())

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> AppSettings:
        """Create AppSettings from a config dictionary.

        Pydantic handles type coercion, unknown key filtering, and defaults.
        Legacy key migration is handled by AppConfig.load() before calling this.
        """
        return cls.model_validate(cfg)

    def to_dict(self) -> dict[str, Any]:
        """Convert AppSettings to a dictionary for serialization.

        Used when settings need to be passed to subprocesses or external tools
        that expect dict-based configuration.

        All fields are JSON-compatible (str, int, float, bool, list, None).
        """
        return self.model_dump()
