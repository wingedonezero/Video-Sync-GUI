# vsg_core/models/settings.py
"""Application settings dataclass - THE SINGLE SOURCE OF TRUTH.

This module defines ALL application settings with their default values.
AppConfig derives its defaults from this dataclass - do NOT maintain
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

from dataclasses import MISSING as dataclass_field_missing
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar

from .enums import AnalysisMode, SnapMode


# Sentinel for path defaults that need runtime resolution
# These will be resolved by AppConfig based on script_dir
_PATH_SENTINEL = "__PATH_NEEDS_RESOLUTION__"


@dataclass
class AppSettings:
    """Complete application settings with typed fields and defaults.

    All pipeline code should access settings through this dataclass,
    not through raw dict access. This ensures type safety and IDE support.

    IMPORTANT: All defaults are defined HERE. AppConfig derives from this.
    """

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
    analysis_mode: AnalysisMode = field(default=AnalysisMode.AUDIO)
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
    snap_mode: SnapMode = field(default=SnapMode.PREVIOUS)
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
    corr_anchor_anchor_positions: tuple[int, ...] = field(default=(10, 50, 90))
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
    # Class-level constants
    # =========================================================================
    # Path sentinel - fields with this default need runtime resolution
    PATH_SENTINEL: ClassVar[str] = _PATH_SENTINEL

    @classmethod
    def get_defaults(cls) -> dict[str, Any]:
        """Get all field defaults as a dictionary.

        This is THE source of truth for defaults. AppConfig should use this
        instead of maintaining a separate defaults dict.

        Returns:
            Dict mapping field names to their default values.
            Enum defaults are converted to their string values.
        """
        result = {}
        for f in fields(cls):
            # Get the default value
            if f.default is not dataclass_field_missing:
                default = f.default
            elif f.default_factory is not dataclass_field_missing:
                default = f.default_factory()
            else:
                # No default - this shouldn't happen with our dataclass
                default = None

            # Convert enums to their string values for JSON compatibility
            if hasattr(default, "value"):
                result[f.name] = default.value
            else:
                result[f.name] = default

        return result

    @classmethod
    def get_field_names(cls) -> set[str]:
        """Get all field names as a set.

        Useful for validation - checking if a key exists in settings.
        """
        return {f.name for f in fields(cls)}

    @classmethod
    def from_config(cls, cfg: dict) -> AppSettings:
        """Create AppSettings from a config dictionary.

        Handles legacy keys and provides defaults for all settings.
        """
        # Handle legacy language keys
        analysis_lang_source1 = cfg.get("analysis_lang_source1") or cfg.get(
            "analysis_lang_ref"
        )
        analysis_lang_others = cfg.get("analysis_lang_others") or cfg.get(
            "analysis_lang_sec"
        )

        # Get defaults for any missing values
        defaults = cls.get_defaults()

        def get_val(key: str, converter=None):
            """Get value from cfg with fallback to defaults."""
            val = cfg.get(key, defaults.get(key))
            if converter and val is not None:
                return converter(val)
            return val

        return cls(
            # Path Settings
            output_folder=str(get_val("output_folder") or ""),
            temp_root=str(get_val("temp_root") or ""),
            logs_folder=str(get_val("logs_folder") or ""),
            videodiff_path=str(get_val("videodiff_path") or ""),
            fonts_directory=str(get_val("fonts_directory") or ""),
            last_ref_path=str(get_val("last_ref_path") or ""),
            last_sec_path=str(get_val("last_sec_path") or ""),
            last_ter_path=str(get_val("last_ter_path") or ""),
            source_separation_model_dir=str(get_val("source_separation_model_dir") or ""),
            # Analysis Settings
            analysis_mode=AnalysisMode(get_val("analysis_mode") or "Audio Correlation"),
            analysis_lang_source1=analysis_lang_source1 or None,
            analysis_lang_others=analysis_lang_others or None,
            scan_chunk_count=int(get_val("scan_chunk_count")),
            scan_chunk_duration=int(get_val("scan_chunk_duration")),
            min_match_pct=float(get_val("min_match_pct")),
            videodiff_error_min=float(get_val("videodiff_error_min")),
            videodiff_error_max=float(get_val("videodiff_error_max")),
            # Chapter Settings
            rename_chapters=bool(get_val("rename_chapters")),
            snap_chapters=bool(get_val("snap_chapters")),
            snap_mode=SnapMode(get_val("snap_mode") or "previous"),
            snap_threshold_ms=int(get_val("snap_threshold_ms")),
            snap_starts_only=bool(get_val("snap_starts_only")),
            # Muxing Settings
            apply_dialog_norm_gain=bool(get_val("apply_dialog_norm_gain")),
            disable_track_statistics_tags=bool(get_val("disable_track_statistics_tags")),
            disable_header_compression=bool(get_val("disable_header_compression")),
            # Post-Mux Settings
            post_mux_normalize_timestamps=bool(get_val("post_mux_normalize_timestamps")),
            post_mux_strip_tags=bool(get_val("post_mux_strip_tags")),
            # Logging Settings
            log_compact=bool(get_val("log_compact")),
            log_autoscroll=bool(get_val("log_autoscroll")),
            log_error_tail=int(get_val("log_error_tail")),
            log_tail_lines=int(get_val("log_tail_lines")),
            log_progress_step=int(get_val("log_progress_step")),
            log_show_options_pretty=bool(get_val("log_show_options_pretty")),
            log_show_options_json=bool(get_val("log_show_options_json")),
            log_audio_drift=bool(get_val("log_audio_drift")),
            archive_logs=bool(get_val("archive_logs")),
            # Timing Sync Settings
            auto_apply_strict=bool(get_val("auto_apply_strict")),
            sync_mode=str(get_val("sync_mode")),
            # Timing Fix Settings
            timing_fix_enabled=bool(get_val("timing_fix_enabled")),
            timing_fix_overlaps=bool(get_val("timing_fix_overlaps")),
            timing_overlap_min_gap_ms=int(get_val("timing_overlap_min_gap_ms")),
            timing_fix_short_durations=bool(get_val("timing_fix_short_durations")),
            timing_min_duration_ms=int(get_val("timing_min_duration_ms")),
            timing_fix_long_durations=bool(get_val("timing_fix_long_durations")),
            timing_max_cps=float(get_val("timing_max_cps")),
            # Segmented Audio Correction
            segmented_enabled=bool(get_val("segmented_enabled")),
            # Subtitle Sync Settings
            subtitle_sync_mode=str(get_val("subtitle_sync_mode")),
            time_based_use_raw_values=bool(get_val("time_based_use_raw_values")),
            time_based_bypass_subtitle_data=bool(get_val("time_based_bypass_subtitle_data")),
            subtitle_rounding=str(get_val("subtitle_rounding")),
            subtitle_target_fps=float(get_val("subtitle_target_fps")),
            videotimestamps_snap_mode=str(get_val("videotimestamps_snap_mode")),
            videotimestamps_rounding=str(get_val("videotimestamps_rounding")),
            # Frame Matching Settings
            frame_hash_algorithm=str(get_val("frame_hash_algorithm")),
            frame_hash_size=int(get_val("frame_hash_size")),
            frame_hash_threshold=int(get_val("frame_hash_threshold")),
            frame_window_radius=int(get_val("frame_window_radius")),
            frame_search_range_ms=int(get_val("frame_search_range_ms")),
            frame_agreement_tolerance_ms=int(get_val("frame_agreement_tolerance_ms")),
            frame_use_vapoursynth=bool(get_val("frame_use_vapoursynth")),
            frame_comparison_method=str(get_val("frame_comparison_method")),
            # Correlation Snap Settings
            correlation_snap_fallback_mode=str(get_val("correlation_snap_fallback_mode")),
            correlation_snap_use_scene_changes=bool(get_val("correlation_snap_use_scene_changes")),
            # Correlation-Guided Frame Anchor Settings
            corr_anchor_fallback_mode=str(get_val("corr_anchor_fallback_mode")),
            corr_anchor_anchor_positions=tuple(get_val("corr_anchor_anchor_positions")),
            corr_anchor_refine_per_line=bool(get_val("corr_anchor_refine_per_line")),
            corr_anchor_refine_workers=int(get_val("corr_anchor_refine_workers")),
            # Subtitle-Anchored Frame Snap Settings
            sub_anchor_fallback_mode=str(get_val("sub_anchor_fallback_mode")),
            # Duration Align Settings
            duration_align_verify_with_frames=bool(get_val("duration_align_verify_with_frames")),
            duration_align_validate=bool(get_val("duration_align_validate")),
            duration_align_fallback_mode=str(get_val("duration_align_fallback_mode")),
            duration_align_validate_points=int(get_val("duration_align_validate_points")),
            duration_align_strictness=int(get_val("duration_align_strictness")),
            duration_align_skip_validation_generated_tracks=bool(
                get_val("duration_align_skip_validation_generated_tracks")
            ),
            # Frame Lock Settings
            frame_lock_submillisecond_precision=bool(get_val("frame_lock_submillisecond_precision")),
            # Video-Verified Sync Settings
            video_verified_zero_check_frames=int(get_val("video_verified_zero_check_frames")),
            video_verified_min_quality_advantage=float(get_val("video_verified_min_quality_advantage")),
            video_verified_num_checkpoints=int(get_val("video_verified_num_checkpoints")),
            video_verified_search_range_frames=int(get_val("video_verified_search_range_frames")),
            video_verified_sequence_length=int(get_val("video_verified_sequence_length")),
            video_verified_use_pts_precision=bool(get_val("video_verified_use_pts_precision")),
            video_verified_frame_audit=bool(get_val("video_verified_frame_audit")),
            # Interlaced Video Settings
            interlaced_handling_enabled=bool(get_val("interlaced_handling_enabled")),
            interlaced_force_mode=str(get_val("interlaced_force_mode")),
            interlaced_num_checkpoints=int(get_val("interlaced_num_checkpoints")),
            interlaced_search_range_frames=int(get_val("interlaced_search_range_frames")),
            interlaced_hash_algorithm=str(get_val("interlaced_hash_algorithm")),
            interlaced_hash_size=int(get_val("interlaced_hash_size")),
            interlaced_hash_threshold=int(get_val("interlaced_hash_threshold")),
            interlaced_comparison_method=str(get_val("interlaced_comparison_method")),
            interlaced_fallback_to_audio=bool(get_val("interlaced_fallback_to_audio")),
            interlaced_sequence_length=int(get_val("interlaced_sequence_length")),
            interlaced_deinterlace_method=str(get_val("interlaced_deinterlace_method")),
            interlaced_use_ivtc=bool(get_val("interlaced_use_ivtc")),
            # Analysis/Correlation Settings
            source_separation_mode=str(get_val("source_separation_mode")),
            source_separation_model=str(get_val("source_separation_model")),
            source_separation_device=str(get_val("source_separation_device")),
            source_separation_timeout=int(get_val("source_separation_timeout")),
            filtering_method=str(get_val("filtering_method")),
            correlation_method=str(get_val("correlation_method")),
            correlation_method_source_separated=str(get_val("correlation_method_source_separated")),
            # Delay Selection Settings
            delay_selection_mode=str(get_val("delay_selection_mode")),
            delay_selection_mode_source_separated=str(get_val("delay_selection_mode_source_separated")),
            min_accepted_chunks=int(get_val("min_accepted_chunks")),
            first_stable_min_chunks=int(get_val("first_stable_min_chunks")),
            first_stable_skip_unstable=bool(get_val("first_stable_skip_unstable")),
            early_cluster_window=int(get_val("early_cluster_window")),
            early_cluster_threshold=int(get_val("early_cluster_threshold")),
            # Multi-Correlation Comparison
            multi_correlation_enabled=bool(get_val("multi_correlation_enabled")),
            multi_corr_scc=bool(get_val("multi_corr_scc")),
            multi_corr_gcc_phat=bool(get_val("multi_corr_gcc_phat")),
            multi_corr_onset=bool(get_val("multi_corr_onset")),
            multi_corr_gcc_scot=bool(get_val("multi_corr_gcc_scot")),
            multi_corr_gcc_whiten=bool(get_val("multi_corr_gcc_whiten")),
            multi_corr_dtw=bool(get_val("multi_corr_dtw")),
            multi_corr_spectrogram=bool(get_val("multi_corr_spectrogram")),
            # DSP & Filtering
            filter_bandpass_lowcut_hz=float(get_val("filter_bandpass_lowcut_hz")),
            filter_bandpass_highcut_hz=float(get_val("filter_bandpass_highcut_hz")),
            filter_bandpass_order=int(get_val("filter_bandpass_order")),
            filter_lowpass_taps=int(get_val("filter_lowpass_taps")),
            scan_start_percentage=float(get_val("scan_start_percentage")),
            scan_end_percentage=float(get_val("scan_end_percentage")),
            use_soxr=bool(get_val("use_soxr")),
            audio_decode_native=bool(get_val("audio_decode_native")),
            audio_peak_fit=bool(get_val("audio_peak_fit")),
            audio_bandlimit_hz=int(get_val("audio_bandlimit_hz")),
            # Drift Detection Settings
            detection_dbscan_epsilon_ms=float(get_val("detection_dbscan_epsilon_ms")),
            detection_dbscan_min_samples=int(get_val("detection_dbscan_min_samples")),
            drift_detection_r2_threshold=float(get_val("drift_detection_r2_threshold")),
            drift_detection_r2_threshold_lossless=float(get_val("drift_detection_r2_threshold_lossless")),
            drift_detection_slope_threshold_lossy=float(get_val("drift_detection_slope_threshold_lossy")),
            drift_detection_slope_threshold_lossless=float(get_val("drift_detection_slope_threshold_lossless")),
            # Stepping Correction Settings
            stepping_adjust_subtitles=bool(get_val("stepping_adjust_subtitles")),
            stepping_adjust_subtitles_no_audio=bool(get_val("stepping_adjust_subtitles_no_audio")),
            stepping_boundary_mode=str(get_val("stepping_boundary_mode")),
            stepping_first_stable_min_chunks=int(get_val("stepping_first_stable_min_chunks")),
            stepping_first_stable_skip_unstable=bool(get_val("stepping_first_stable_skip_unstable")),
            # Segment Scan & Correction
            segment_triage_std_dev_ms=int(get_val("segment_triage_std_dev_ms")),
            segment_coarse_chunk_s=int(get_val("segment_coarse_chunk_s")),
            segment_coarse_step_s=int(get_val("segment_coarse_step_s")),
            segment_search_locality_s=int(get_val("segment_search_locality_s")),
            segment_fine_chunk_s=float(get_val("segment_fine_chunk_s")),
            segment_fine_iterations=int(get_val("segment_fine_iterations")),
            segment_min_confidence_ratio=float(get_val("segment_min_confidence_ratio")),
            # Segment Drift Detection
            segment_drift_r2_threshold=float(get_val("segment_drift_r2_threshold")),
            segment_drift_slope_threshold=float(get_val("segment_drift_slope_threshold")),
            segment_drift_outlier_sensitivity=float(get_val("segment_drift_outlier_sensitivity")),
            segment_drift_scan_buffer_pct=float(get_val("segment_drift_scan_buffer_pct")),
            # Stepping Scan Range
            stepping_scan_start_percentage=float(get_val("stepping_scan_start_percentage")),
            stepping_scan_end_percentage=float(get_val("stepping_scan_end_percentage")),
            # Silence Snapping
            stepping_snap_to_silence=bool(get_val("stepping_snap_to_silence")),
            stepping_silence_detection_method=str(get_val("stepping_silence_detection_method")),
            stepping_silence_search_window_s=float(get_val("stepping_silence_search_window_s")),
            stepping_silence_threshold_db=float(get_val("stepping_silence_threshold_db")),
            stepping_silence_min_duration_ms=float(get_val("stepping_silence_min_duration_ms")),
            stepping_ffmpeg_silence_noise=float(get_val("stepping_ffmpeg_silence_noise")),
            stepping_ffmpeg_silence_duration=float(get_val("stepping_ffmpeg_silence_duration")),
            # VAD (Voice Activity Detection)
            stepping_vad_enabled=bool(get_val("stepping_vad_enabled")),
            stepping_vad_aggressiveness=int(get_val("stepping_vad_aggressiveness")),
            stepping_vad_avoid_speech=bool(get_val("stepping_vad_avoid_speech")),
            stepping_vad_frame_duration_ms=int(get_val("stepping_vad_frame_duration_ms")),
            # Transient Detection
            stepping_transient_detection_enabled=bool(get_val("stepping_transient_detection_enabled")),
            stepping_transient_threshold=float(get_val("stepping_transient_threshold")),
            stepping_transient_avoid_window_ms=int(get_val("stepping_transient_avoid_window_ms")),
            # Smart Fusion Weights
            stepping_fusion_weight_silence=int(get_val("stepping_fusion_weight_silence")),
            stepping_fusion_weight_no_speech=int(get_val("stepping_fusion_weight_no_speech")),
            stepping_fusion_weight_scene_align=int(get_val("stepping_fusion_weight_scene_align")),
            stepping_fusion_weight_duration=int(get_val("stepping_fusion_weight_duration")),
            stepping_fusion_weight_no_transient=int(get_val("stepping_fusion_weight_no_transient")),
            # Video-Aware Boundary Snapping
            stepping_snap_to_video_frames=bool(get_val("stepping_snap_to_video_frames")),
            stepping_video_snap_mode=str(get_val("stepping_video_snap_mode")),
            stepping_video_snap_max_offset_s=float(get_val("stepping_video_snap_max_offset_s")),
            stepping_video_scene_threshold=float(get_val("stepping_video_scene_threshold")),
            # Fill Mode & Content
            stepping_fill_mode=str(get_val("stepping_fill_mode")),
            stepping_content_correlation_threshold=float(get_val("stepping_content_correlation_threshold")),
            stepping_content_search_window_s=float(get_val("stepping_content_search_window_s")),
            # Track Naming
            stepping_corrected_track_label=str(get_val("stepping_corrected_track_label")),
            stepping_preserved_track_label=str(get_val("stepping_preserved_track_label")),
            # Quality Audit Thresholds
            stepping_audit_min_score=float(get_val("stepping_audit_min_score")),
            stepping_audit_overflow_tolerance=float(get_val("stepping_audit_overflow_tolerance")),
            stepping_audit_large_correction_s=float(get_val("stepping_audit_large_correction_s")),
            # Filtered Stepping Correction
            stepping_correction_mode=str(get_val("stepping_correction_mode")),
            stepping_quality_mode=str(get_val("stepping_quality_mode")),
            stepping_min_chunks_per_cluster=int(get_val("stepping_min_chunks_per_cluster")),
            stepping_min_cluster_percentage=float(get_val("stepping_min_cluster_percentage")),
            stepping_min_cluster_duration_s=float(get_val("stepping_min_cluster_duration_s")),
            stepping_min_match_quality_pct=float(get_val("stepping_min_match_quality_pct")),
            stepping_min_total_clusters=int(get_val("stepping_min_total_clusters")),
            stepping_filtered_fallback=str(get_val("stepping_filtered_fallback")),
            stepping_diagnostics_verbose=bool(get_val("stepping_diagnostics_verbose")),
            # Segmented Audio QA
            segmented_qa_threshold=float(get_val("segmented_qa_threshold")),
            segment_qa_chunk_count=int(get_val("segment_qa_chunk_count")),
            segment_qa_min_accepted_chunks=int(get_val("segment_qa_min_accepted_chunks")),
            # Sync Stability Settings
            sync_stability_enabled=bool(get_val("sync_stability_enabled")),
            sync_stability_variance_threshold=float(get_val("sync_stability_variance_threshold")),
            sync_stability_min_chunks=int(get_val("sync_stability_min_chunks")),
            sync_stability_outlier_mode=str(get_val("sync_stability_outlier_mode")),
            sync_stability_outlier_threshold=float(get_val("sync_stability_outlier_threshold")),
            # Resampling Engine Settings
            segment_resample_engine=str(get_val("segment_resample_engine")),
            segment_rb_pitch_correct=bool(get_val("segment_rb_pitch_correct")),
            segment_rb_transients=str(get_val("segment_rb_transients")),
            segment_rb_smoother=bool(get_val("segment_rb_smoother")),
            segment_rb_pitchq=bool(get_val("segment_rb_pitchq")),
            # OCR Settings
            ocr_enabled=bool(get_val("ocr_enabled")),
            ocr_engine=str(get_val("ocr_engine")),
            ocr_language=str(get_val("ocr_language")),
            ocr_psm=int(get_val("ocr_psm")),
            ocr_char_whitelist=str(get_val("ocr_char_whitelist")),
            ocr_char_blacklist=str(get_val("ocr_char_blacklist")),
            ocr_low_confidence_threshold=float(get_val("ocr_low_confidence_threshold")),
            ocr_multi_pass=bool(get_val("ocr_multi_pass")),
            ocr_output_format=str(get_val("ocr_output_format")),
            # OCR Preprocessing
            ocr_preprocess_auto=bool(get_val("ocr_preprocess_auto")),
            ocr_upscale_threshold=int(get_val("ocr_upscale_threshold")),
            ocr_target_height=int(get_val("ocr_target_height")),
            ocr_border_size=int(get_val("ocr_border_size")),
            ocr_force_binarization=bool(get_val("ocr_force_binarization")),
            ocr_binarization_method=str(get_val("ocr_binarization_method")),
            ocr_denoise=bool(get_val("ocr_denoise")),
            ocr_save_debug_images=bool(get_val("ocr_save_debug_images")),
            # OCR Output & Position
            ocr_preserve_positions=bool(get_val("ocr_preserve_positions")),
            ocr_bottom_threshold=float(get_val("ocr_bottom_threshold")),
            ocr_video_width=int(get_val("ocr_video_width")),
            ocr_video_height=int(get_val("ocr_video_height")),
            # OCR Post-Processing
            ocr_cleanup_enabled=bool(get_val("ocr_cleanup_enabled")),
            ocr_cleanup_normalize_ellipsis=bool(get_val("ocr_cleanup_normalize_ellipsis")),
            ocr_custom_wordlist_path=str(get_val("ocr_custom_wordlist_path")),
            # OCR Debug & Runtime
            ocr_debug_output=bool(get_val("ocr_debug_output")),
            ocr_run_in_subprocess=bool(get_val("ocr_run_in_subprocess")),
            ocr_font_size_ratio=float(get_val("ocr_font_size_ratio")),
            ocr_generate_report=bool(get_val("ocr_generate_report")),
        )

    def to_dict(self) -> dict:
        """Convert AppSettings to a dictionary for serialization.

        Used when settings need to be passed to subprocesses or external tools
        that expect dict-based configuration.
        """
        result = {}
        for f in fields(self):
            value = getattr(self, f.name)
            # Convert enums to their string values
            if hasattr(value, "value"):
                result[f.name] = value.value
            # Convert tuples to lists for JSON
            elif isinstance(value, tuple):
                result[f.name] = list(value)
            else:
                result[f.name] = value
        return result
