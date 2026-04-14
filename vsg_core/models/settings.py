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
    CorrelationMethodSourceSepStr,
    CorrelationMethodStr,
    DelaySelectionModeStr,
    FilteringMethodStr,
    OcrEngineStr,
    OcrOutputFormatStr,
    ResampleEngineStr,
    RubberbandTransientsStr,
    SnapModeStr,
    SourceSeparationDeviceStr,
    SourceSeparationModeStr,
    SteppingBoundaryModeStr,
    SteppingCorrectionModeStr,
    SteppingFilteredFallbackStr,
    SteppingQualityModeStr,
    SubtitleRoundingStr,
    SubtitleSyncModeStr,
    SyncModeStr,
    SyncStabilityOutlierModeStr,
    VideoVerifiedBackendStr,
    VideoVerifiedCrossCheckBackendStr,
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
    analysis_lang_source1: str = ""
    analysis_lang_others: str = ""
    min_match_pct: float = 10.0

    # Dense sliding window correlation (GPU)
    dense_window_s: float = 10.0
    dense_hop_s: float = 2.0
    dense_silence_threshold_db: float = -60.0
    dense_outlier_threshold_ms: float = 50.0
    videodiff_error_min: float = 0.0
    videodiff_error_max: float = 100.0
    videodiff_sample_fps: float = 0
    videodiff_match_threshold: int = 5
    videodiff_min_matches: int = 50
    videodiff_inlier_threshold_ms: float = 100.0

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
    trim_audio_to_video_duration: bool = False

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
    sync_mode: SyncModeStr = "positive_only"

    # =========================================================================
    # Segmented Audio Correction
    # =========================================================================
    stepping_enabled: bool = False

    # =========================================================================
    # Subtitle Sync Settings
    # =========================================================================
    subtitle_sync_mode: SubtitleSyncModeStr = "time-based"
    time_based_use_raw_values: bool = False
    time_based_bypass_subtitle_data: bool = True
    subtitle_rounding: SubtitleRoundingStr = "floor"
    subtitle_target_fps: float = 0.0

    # =========================================================================
    # Video-Verified Sync Settings (sliding-window matcher)
    # =========================================================================
    # Diagnostics (always available regardless of backend)
    video_verified_frame_audit: bool = False
    video_verified_visual_verify: bool = False

    # Backend selection
    video_verified_backend: VideoVerifiedBackendStr = "isc"
    video_verified_cross_check_backend: VideoVerifiedCrossCheckBackendStr = "none"
    video_verified_cross_check_tolerance_frames: int = 0  # 0 = strict match

    # Sliding search geometry (shared across all backends)
    video_verified_window_seconds: int = 10
    video_verified_slide_range_seconds: int = 5
    video_verified_num_positions: int = 9
    video_verified_batch_size: int = 32

    # Backend-specific tunables
    video_verified_hash_size: int = 32  # pHash/dHash: 8/16/32/64 (1024-bit default)
    video_verified_ssim_input_size: int = 256  # SSIM: 128/256/384/512

    # Runtime
    video_verified_run_in_subprocess: bool = True
    video_verified_debug_report: bool = False

    # =========================================================================
    # Analysis/Correlation Settings
    # =========================================================================
    source_separation_mode: SourceSeparationModeStr = "none"
    source_separation_model: str = "default"
    source_separation_device: SourceSeparationDeviceStr = "auto"
    source_separation_timeout: int = 900
    filtering_method: FilteringMethodStr = "Dialogue Band-Pass Filter"
    correlation_method: CorrelationMethodStr = "Phase Correlation (GCC-PHAT)"
    correlation_method_source_separated: CorrelationMethodSourceSepStr = (
        "Phase Correlation (GCC-PHAT)"
    )

    # Delay Selection Settings
    delay_selection_mode: DelaySelectionModeStr = "Mode (Most Common)"
    delay_selection_mode_source_separated: DelaySelectionModeStr = "Mode (Clustered)"
    min_accepted_pct: float = 5.0
    first_stable_early_pct: float = 15.0
    early_cluster_early_pct: float = 15.0
    early_cluster_min_presence_pct: float = 10.0

    # Multi-Correlation Comparison
    multi_correlation_enabled: bool = False
    multi_corr_scc: bool = True
    multi_corr_gcc_phat: bool = True
    multi_corr_onset: bool = False
    multi_corr_gcc_scot: bool = False
    multi_corr_gcc_whiten: bool = False
    multi_corr_spectrogram: bool = False

    # DSP & Filtering
    filter_bandpass_lowcut_hz: float = 300.0
    filter_bandpass_highcut_hz: float = 3400.0
    filter_bandpass_order: int = 5
    filter_lowpass_taps: int = 101
    scan_start_percentage: float = 0.0
    scan_end_percentage: float = 100.0
    use_soxr: bool = False
    audio_decode_native: bool = False
    audio_peak_fit: bool = False
    audio_bandlimit_hz: int = 0

    # Drift Detection Settings
    detection_dbscan_epsilon_ms: float = 20.0
    detection_dbscan_min_samples_pct: float = 1.5
    drift_detection_r2_threshold: float = 0.90
    drift_detection_r2_threshold_lossless: float = 0.95
    drift_detection_slope_threshold_lossy: float = 0.7
    drift_detection_slope_threshold_lossless: float = 0.2

    # =========================================================================
    # Stepping Correction Settings
    # =========================================================================
    stepping_adjust_subtitles: bool = True
    stepping_adjust_subtitles_no_audio: bool = True
    stepping_boundary_mode: SteppingBoundaryModeStr = "start"

    # Triage (used by subtitle-only EDL path)
    stepping_triage_std_dev_ms: int = 50

    # Boundary Refinement — Silence Detection
    stepping_silence_search_window_s: float = 5.0
    stepping_silence_threshold_db: float = -70.0
    stepping_silence_min_duration_ms: float = 30.0

    # Boundary Refinement — Scene Detection + Silero VAD
    stepping_scene_detection_enabled: bool = True
    stepping_silero_vad_enabled: bool = True
    stepping_silero_vad_threshold: float = 0.5
    stepping_noise_recovery_enabled: bool = True

    # Boundary Refinement — VAD (Voice Activity Detection / WebRTC fallback)
    stepping_vad_enabled: bool = True
    stepping_vad_aggressiveness: int = 2

    # Boundary Refinement — Transient Detection
    stepping_transient_detection_enabled: bool = True
    stepping_transient_threshold: float = 8.0

    # Boundary Refinement — Scoring Weights
    stepping_fusion_weight_silence: int = 10
    stepping_fusion_weight_duration: int = 2

    # Boundary Refinement — Video Keyframe Snapping
    stepping_snap_to_video_frames: bool = False
    stepping_video_snap_max_offset_s: float = 2.0

    # Track Naming
    stepping_corrected_track_label: str = ""
    stepping_preserved_track_label: str = ""

    # Filtered Stepping Correction
    stepping_correction_mode: SteppingCorrectionModeStr = "full"
    stepping_quality_mode: SteppingQualityModeStr = "normal"
    stepping_min_cluster_percentage: float = 5.0
    stepping_min_cluster_duration_s: float = 20.0
    stepping_min_match_quality_pct: float = 85.0
    stepping_min_total_clusters: int = 2
    stepping_filtered_fallback: SteppingFilteredFallbackStr = "nearest"
    stepping_diagnostics_verbose: bool = True

    # Stepping QA (post-correction verification)
    stepping_qa_threshold: float = 85.0
    stepping_qa_min_accepted_pct: float = 90.0

    # =========================================================================
    # Sync Stability Settings
    # =========================================================================
    sync_stability_enabled: bool = True
    sync_stability_variance_threshold: float = 1.0
    sync_stability_min_windows: int = 3
    sync_stability_outlier_mode: SyncStabilityOutlierModeStr = "threshold"
    sync_stability_outlier_threshold: float = 1.0

    # =========================================================================
    # Resampling Engine Settings
    # =========================================================================
    segment_resample_engine: ResampleEngineStr = "aresample"
    segment_rb_pitch_correct: bool = False
    segment_rb_transients: RubberbandTransientsStr = "crisp"
    segment_rb_smoother: bool = True
    segment_rb_pitchq: bool = True

    # =========================================================================
    # OCR Settings
    # =========================================================================
    ocr_enabled: bool = True
    ocr_engine: OcrEngineStr = "paddleocr-vl"
    ocr_language: str = "eng"
    ocr_low_confidence_threshold: float = 60.0
    ocr_output_format: OcrOutputFormatStr = "ass"

    # OCR Post-Processing
    ocr_cleanup_enabled: bool = True
    ocr_custom_wordlist_path: str = ""

    # OCR Debug & Runtime
    ocr_debug_output: bool = False
    ocr_run_in_subprocess: bool = True
    ocr_font_size_ratio: float = 5.80
    ocr_generate_report: bool = True

    # PGS (Blu-ray) specific
    ocr_pgs_save_object_crops: bool = False
    ocr_pgs_keep_bot_colors: bool = False
    ocr_pgs_keep_top_colors: bool = False
    ocr_pgs_keep_pos_colors: bool = False

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
