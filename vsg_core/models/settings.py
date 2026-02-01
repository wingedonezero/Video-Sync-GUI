# vsg_core/models/settings.py
"""Application settings dataclass.

This is the single source of truth for all pipeline configuration settings.
All settings are typed and have defaults, eliminating dict[str, Any] access.

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

from dataclasses import dataclass

from .enums import AnalysisMode, SnapMode


@dataclass
class AppSettings:
    """Complete application settings with typed fields.

    All pipeline code should access settings through this dataclass,
    not through raw dict access. This ensures type safety and IDE support.
    """

    # =========================================================================
    # Path Settings
    # =========================================================================
    output_folder: str
    temp_root: str
    logs_folder: str
    videodiff_path: str

    # =========================================================================
    # Analysis Settings
    # =========================================================================
    analysis_mode: AnalysisMode
    analysis_lang_source1: str | None
    analysis_lang_others: str | None
    scan_chunk_count: int
    scan_chunk_duration: int
    min_match_pct: float
    videodiff_error_min: float
    videodiff_error_max: float

    # =========================================================================
    # Chapter Settings
    # =========================================================================
    rename_chapters: bool
    snap_chapters: bool
    snap_mode: SnapMode
    snap_threshold_ms: int
    snap_starts_only: bool

    # =========================================================================
    # Muxing Settings
    # =========================================================================
    apply_dialog_norm_gain: bool
    disable_track_statistics_tags: bool
    disable_header_compression: bool

    # =========================================================================
    # Logging Settings
    # =========================================================================
    log_compact: bool
    log_autoscroll: bool
    log_error_tail: int
    log_tail_lines: int
    log_progress_step: int
    log_show_options_pretty: bool
    log_show_options_json: bool
    archive_logs: bool

    # =========================================================================
    # Timing Sync Settings
    # =========================================================================
    auto_apply_strict: bool
    sync_mode: str  # "positive_only", "allow_negative", "preserve_existing"

    # =========================================================================
    # Segmented Audio Correction
    # =========================================================================
    segmented_enabled: bool

    # =========================================================================
    # Subtitle Sync Settings
    # =========================================================================
    subtitle_sync_mode: str  # "time-based", "frame-based", etc.
    time_based_use_raw_values: bool
    time_based_bypass_subtitle_data: bool
    subtitle_rounding: str  # "floor", "round", "ceil"
    subtitle_target_fps: float  # Target FPS for frame-based modes
    videotimestamps_snap_mode: str  # Frame snap mode: "start", "exact"

    # =========================================================================
    # Frame Matching Settings (shared by all frame-based sync modes)
    # =========================================================================
    frame_hash_algorithm: str  # "dhash", "phash", "average_hash", "whash"
    frame_hash_size: int  # 4, 8, or 16
    frame_hash_threshold: int  # Max hamming distance (0-30)
    frame_window_radius: int  # Frames before/after center
    frame_search_range_ms: int  # Search ±N ms around expected position
    frame_agreement_tolerance_ms: int  # Checkpoints must agree within ±N ms
    frame_use_vapoursynth: bool  # Use VapourSynth for frame extraction
    frame_comparison_method: str  # "hash", "ssim", "mse"

    # =========================================================================
    # Correlation Snap Settings
    # =========================================================================
    correlation_snap_fallback_mode: str  # "snap-to-frame", "use-raw", "abort"
    correlation_snap_use_scene_changes: bool  # Use PySceneDetect for anchor points

    # =========================================================================
    # Video-Verified Sync Settings
    # =========================================================================
    video_verified_zero_check_frames: int  # Verify if correlation < N frames
    video_verified_min_quality_advantage: float  # Quality margin for non-zero offset
    video_verified_num_checkpoints: int  # Number of checkpoint times
    video_verified_search_range_frames: int  # Frame range to search
    video_verified_sequence_length: int  # Consecutive frames to verify
    video_verified_use_pts_precision: bool  # Use PTS for sub-frame precision

    # =========================================================================
    # Analysis/Correlation Settings
    # =========================================================================
    source_separation_mode: str  # "none", "instrumental", "vocals"
    source_separation_model: str  # Model filename or "default"
    source_separation_device: str  # "auto", "cpu", "cuda", "rocm", "mps"
    source_separation_timeout: int  # Timeout in seconds (0 = no timeout)
    filtering_method: str  # "Dialogue Band-Pass Filter", etc.
    correlation_method: (
        str  # "SCC (Sliding Cross-Correlation)", "Phase Correlation (GCC-PHAT)"
    )
    correlation_method_source_separated: str  # Method for source-separated audio

    # Delay Selection Settings
    delay_selection_mode: str  # "Mode (Most Common)", "Average", "First Stable", etc.
    delay_selection_mode_source_separated: str  # Delay mode for source-separated audio
    min_accepted_chunks: int  # Minimum accepted chunks for valid result
    first_stable_min_chunks: int  # Min chunks for first stable segment
    first_stable_skip_unstable: bool  # Skip unstable segments
    early_cluster_window: int  # Window size for early cluster detection
    early_cluster_threshold: int  # Threshold for early cluster detection

    # Multi-Correlation Comparison
    multi_correlation_enabled: bool  # Enable multi-method comparison
    multi_corr_scc: bool
    multi_corr_gcc_phat: bool
    multi_corr_onset: bool
    multi_corr_gcc_scot: bool
    multi_corr_gcc_whiten: bool
    multi_corr_dtw: bool
    multi_corr_spectrogram: bool

    # DSP & Filtering
    filter_bandpass_lowcut_hz: float
    filter_bandpass_highcut_hz: float
    filter_bandpass_order: int
    filter_lowpass_taps: int
    scan_start_percentage: float  # % of video to start scanning
    scan_end_percentage: float  # % of video to end scanning
    use_soxr: bool  # Use SoXR for resampling
    audio_decode_native: bool
    audio_peak_fit: bool
    audio_bandlimit_hz: int

    # Drift Detection Settings
    detection_dbscan_epsilon_ms: float
    detection_dbscan_min_samples: int
    drift_detection_r2_threshold: float
    drift_detection_r2_threshold_lossless: float
    drift_detection_slope_threshold_lossy: float
    drift_detection_slope_threshold_lossless: float

    # =========================================================================
    # Stepping Correction Settings
    # =========================================================================
    stepping_adjust_subtitles: bool
    stepping_adjust_subtitles_no_audio: bool  # Apply to subs when no audio merged
    stepping_boundary_mode: str  # "start", "majority", "midpoint"
    stepping_first_stable_min_chunks: int  # Min chunks for stepping delay selection
    stepping_first_stable_skip_unstable: bool  # Skip unstable segments in stepping

    # Segment Scan & Correction
    segment_triage_std_dev_ms: int  # Threshold for segment triage
    segment_coarse_chunk_s: int  # Coarse scan chunk duration
    segment_coarse_step_s: int  # Coarse scan step size
    segment_search_locality_s: int  # Search locality window
    segment_fine_chunk_s: float  # Fine scan chunk duration
    segment_fine_iterations: int  # Fine scan iterations
    segment_min_confidence_ratio: float  # Minimum confidence ratio

    # Segment Drift Detection
    segment_drift_r2_threshold: float
    segment_drift_slope_threshold: float
    segment_drift_outlier_sensitivity: float
    segment_drift_scan_buffer_pct: float

    # Stepping Scan Range
    stepping_scan_start_percentage: float  # Independent scan start %
    stepping_scan_end_percentage: (
        float  # Independent scan end % (higher for end boundaries)
    )

    # Silence Snapping
    stepping_snap_to_silence: bool  # Enable boundary snapping to silence
    stepping_silence_detection_method: (
        str  # "rms_basic", "ffmpeg_silencedetect", "smart_fusion"
    )
    stepping_silence_search_window_s: float  # Search window in seconds
    stepping_silence_threshold_db: float  # Audio level in dB for silence
    stepping_silence_min_duration_ms: float  # Minimum silence duration
    stepping_ffmpeg_silence_noise: float  # dB threshold for FFmpeg silencedetect
    stepping_ffmpeg_silence_duration: float  # Min silence duration in seconds

    # VAD (Voice Activity Detection)
    stepping_vad_enabled: bool  # Enable VAD to protect speech
    stepping_vad_aggressiveness: int  # 0-3: 0=least aggressive, 3=most
    stepping_vad_avoid_speech: bool  # Never cut in speech regions
    stepping_vad_frame_duration_ms: int  # VAD analysis frame size (10, 20, 30ms)

    # Transient Detection
    stepping_transient_detection_enabled: bool  # Avoid cutting on transients
    stepping_transient_threshold: float  # dB increase threshold
    stepping_transient_avoid_window_ms: int  # Avoid cuts within ±N ms of transients

    # Smart Fusion Weights
    stepping_fusion_weight_silence: int
    stepping_fusion_weight_no_speech: int
    stepping_fusion_weight_scene_align: int
    stepping_fusion_weight_duration: int
    stepping_fusion_weight_no_transient: int

    # Video-Aware Boundary Snapping
    stepping_snap_to_video_frames: bool  # Enable video frame/scene snapping
    stepping_video_snap_mode: str  # "scenes", "keyframes", "any_frame"
    stepping_video_snap_max_offset_s: float  # Maximum snap distance
    stepping_video_scene_threshold: float  # Scene detection sensitivity (0.1-1.0)

    # Fill Mode & Content
    stepping_fill_mode: str  # "auto", "silence", "content"
    stepping_content_correlation_threshold: (
        float  # Min correlation for content extraction
    )
    stepping_content_search_window_s: float  # Search window for content

    # Track Naming
    stepping_corrected_track_label: str  # Label for corrected audio
    stepping_preserved_track_label: str  # Label for preserved original

    # Quality Audit Thresholds
    stepping_audit_min_score: float  # Min boundary score (warning if below)
    stepping_audit_overflow_tolerance: float  # Max removal/silence ratio
    stepping_audit_large_correction_s: float  # Threshold for large corrections

    # Filtered Stepping Correction
    stepping_correction_mode: str  # "full", "filtered", "strict", "disabled"
    stepping_quality_mode: str  # "strict", "normal", "lenient", "custom"
    stepping_min_chunks_per_cluster: int  # Min chunks per cluster
    stepping_min_cluster_percentage: float  # Min % of total chunks
    stepping_min_cluster_duration_s: float  # Min duration in seconds
    stepping_min_match_quality_pct: float  # Min average match quality %
    stepping_min_total_clusters: int  # Min number of total clusters
    stepping_filtered_fallback: (
        str  # "nearest", "interpolate", "uniform", "skip", "reject"
    )
    stepping_diagnostics_verbose: bool  # Enable detailed cluster reports

    # Segmented Audio QA
    segmented_qa_threshold: float  # QA threshold %
    segment_qa_chunk_count: int  # Number of QA chunks
    segment_qa_min_accepted_chunks: int  # Min accepted QA chunks

    # =========================================================================
    # Sync Stability Settings
    # =========================================================================
    sync_stability_enabled: bool  # Enable variance detection in correlation results
    sync_stability_variance_threshold: (
        float  # Max allowed variance in ms (0 = any variance flagged)
    )
    sync_stability_min_chunks: int  # Minimum chunks needed to calculate variance
    sync_stability_outlier_mode: (
        str  # "any" = flag any variance, "threshold" = use custom threshold
    )
    sync_stability_outlier_threshold: float  # Custom outlier threshold in ms

    # =========================================================================
    # Resampling Engine Settings
    # =========================================================================
    segment_resample_engine: str  # "aresample", "rubberband"
    segment_rb_pitch_correct: bool
    segment_rb_transients: str  # "crisp", "mixed", "smooth"
    segment_rb_smoother: bool
    segment_rb_pitchq: bool

    # =========================================================================
    # OCR Settings
    # =========================================================================
    ocr_engine: str  # "tesseract", "easyocr", "paddleocr"
    ocr_language: str  # Tesseract language code e.g. "eng"
    ocr_psm: int  # Page segmentation mode (default 7)
    ocr_char_whitelist: str  # Characters to include
    ocr_char_blacklist: str  # Characters to exclude
    ocr_low_confidence_threshold: float  # Flag lines below this confidence
    ocr_multi_pass: bool  # Enable multi-pass OCR
    ocr_output_format: str  # "ass" or "srt"

    # OCR Preprocessing
    ocr_preprocess_auto: bool  # Auto-detect optimal preprocessing
    ocr_upscale_threshold: int  # Upscale if height < this (pixels)
    ocr_target_height: int  # Target height after upscaling
    ocr_border_size: int  # Border padding in pixels
    ocr_force_binarization: bool  # Force binary thresholding
    ocr_binarization_method: str  # "otsu", "adaptive", etc.
    ocr_denoise: bool  # Apply denoising
    ocr_save_debug_images: bool  # Save preprocessed images for debugging

    # OCR Output & Position
    ocr_preserve_positions: bool  # Keep non-bottom subtitle positions
    ocr_bottom_threshold: float  # Y% threshold for "bottom" detection
    ocr_video_width: int  # Video width for position calculation
    ocr_video_height: int  # Video height for position calculation

    # OCR Post-Processing
    ocr_cleanup_enabled: bool  # Enable pattern-based text cleanup
    ocr_cleanup_normalize_ellipsis: bool  # Convert ... to ellipsis
    ocr_custom_wordlist_path: str  # Path to custom wordlist

    # OCR Debug & Runtime
    ocr_debug_output: bool  # Save debug output by issue type
    ocr_run_in_subprocess: bool  # Run OCR in subprocess to release memory

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

        return cls(
            # Path Settings
            output_folder=cfg.get("output_folder", ""),
            temp_root=cfg.get("temp_root", ""),
            logs_folder=cfg.get("logs_folder", ""),
            videodiff_path=cfg.get("videodiff_path", ""),
            # Analysis Settings
            analysis_mode=AnalysisMode(cfg.get("analysis_mode", "Audio Correlation")),
            analysis_lang_source1=analysis_lang_source1 or None,
            analysis_lang_others=analysis_lang_others or None,
            scan_chunk_count=int(cfg.get("scan_chunk_count", 10)),
            scan_chunk_duration=int(cfg.get("scan_chunk_duration", 15)),
            min_match_pct=float(cfg.get("min_match_pct", 5.0)),
            videodiff_error_min=float(cfg.get("videodiff_error_min", 0.0)),
            videodiff_error_max=float(cfg.get("videodiff_error_max", 100.0)),
            # Chapter Settings
            rename_chapters=bool(cfg.get("rename_chapters", False)),
            snap_chapters=bool(cfg.get("snap_chapters", False)),
            snap_mode=SnapMode(cfg.get("snap_mode", "previous")),
            snap_threshold_ms=int(cfg.get("snap_threshold_ms", 250)),
            snap_starts_only=bool(cfg.get("snap_starts_only", True)),
            # Muxing Settings
            apply_dialog_norm_gain=bool(cfg.get("apply_dialog_norm_gain", False)),
            disable_track_statistics_tags=bool(
                cfg.get("disable_track_statistics_tags", False)
            ),
            disable_header_compression=bool(
                cfg.get("disable_header_compression", True)
            ),
            # Logging Settings
            log_compact=bool(cfg.get("log_compact", True)),
            log_autoscroll=bool(cfg.get("log_autoscroll", True)),
            log_error_tail=int(cfg.get("log_error_tail", 20)),
            log_tail_lines=int(cfg.get("log_tail_lines", 0)),
            log_progress_step=int(cfg.get("log_progress_step", 20)),
            log_show_options_pretty=bool(cfg.get("log_show_options_pretty", False)),
            log_show_options_json=bool(cfg.get("log_show_options_json", False)),
            archive_logs=bool(cfg.get("archive_logs", True)),
            # Timing Sync Settings
            auto_apply_strict=bool(cfg.get("auto_apply_strict", False)),
            sync_mode=str(cfg.get("sync_mode", "positive_only")),
            # Segmented Audio Correction
            segmented_enabled=bool(cfg.get("segmented_enabled", False)),
            # Subtitle Sync Settings
            subtitle_sync_mode=str(cfg.get("subtitle_sync_mode", "time-based")),
            time_based_use_raw_values=bool(cfg.get("time_based_use_raw_values", False)),
            time_based_bypass_subtitle_data=bool(
                cfg.get("time_based_bypass_subtitle_data", True)
            ),
            subtitle_rounding=str(cfg.get("subtitle_rounding", "floor")),
            subtitle_target_fps=float(cfg.get("subtitle_target_fps", 0.0)),
            videotimestamps_snap_mode=str(
                cfg.get("videotimestamps_snap_mode", "start")
            ),
            # Frame Matching Settings
            frame_hash_algorithm=str(cfg.get("frame_hash_algorithm", "dhash")),
            frame_hash_size=int(cfg.get("frame_hash_size", 8)),
            frame_hash_threshold=int(cfg.get("frame_hash_threshold", 5)),
            frame_window_radius=int(cfg.get("frame_window_radius", 5)),
            frame_search_range_ms=int(cfg.get("frame_search_range_ms", 2000)),
            frame_agreement_tolerance_ms=int(
                cfg.get("frame_agreement_tolerance_ms", 100)
            ),
            frame_use_vapoursynth=bool(cfg.get("frame_use_vapoursynth", True)),
            frame_comparison_method=str(cfg.get("frame_comparison_method", "hash")),
            # Correlation Snap Settings
            correlation_snap_fallback_mode=str(
                cfg.get("correlation_snap_fallback_mode", "snap-to-frame")
            ),
            correlation_snap_use_scene_changes=bool(
                cfg.get("correlation_snap_use_scene_changes", True)
            ),
            # Video-Verified Sync Settings
            video_verified_zero_check_frames=int(
                cfg.get("video_verified_zero_check_frames", 3)
            ),
            video_verified_min_quality_advantage=float(
                cfg.get("video_verified_min_quality_advantage", 0.1)
            ),
            video_verified_num_checkpoints=int(
                cfg.get("video_verified_num_checkpoints", 5)
            ),
            video_verified_search_range_frames=int(
                cfg.get("video_verified_search_range_frames", 3)
            ),
            video_verified_sequence_length=int(
                cfg.get("video_verified_sequence_length", 10)
            ),
            video_verified_use_pts_precision=bool(
                cfg.get("video_verified_use_pts_precision", False)
            ),
            # Analysis/Correlation Settings
            source_separation_mode=str(cfg.get("source_separation_mode", "none")),
            source_separation_model=str(cfg.get("source_separation_model", "default")),
            source_separation_device=str(cfg.get("source_separation_device", "auto")),
            source_separation_timeout=int(cfg.get("source_separation_timeout", 900)),
            filtering_method=str(
                cfg.get("filtering_method", "Dialogue Band-Pass Filter")
            ),
            correlation_method=str(
                cfg.get("correlation_method", "Phase Correlation (GCC-PHAT)")
            ),
            correlation_method_source_separated=str(
                cfg.get(
                    "correlation_method_source_separated",
                    "Phase Correlation (GCC-PHAT)",
                )
            ),
            # Delay Selection Settings
            delay_selection_mode=str(
                cfg.get("delay_selection_mode", "Mode (Most Common)")
            ),
            delay_selection_mode_source_separated=str(
                cfg.get("delay_selection_mode_source_separated", "Mode (Clustered)")
            ),
            min_accepted_chunks=int(cfg.get("min_accepted_chunks", 3)),
            first_stable_min_chunks=int(cfg.get("first_stable_min_chunks", 3)),
            first_stable_skip_unstable=bool(
                cfg.get("first_stable_skip_unstable", True)
            ),
            early_cluster_window=int(cfg.get("early_cluster_window", 10)),
            early_cluster_threshold=int(cfg.get("early_cluster_threshold", 5)),
            # Multi-Correlation Comparison
            multi_correlation_enabled=bool(cfg.get("multi_correlation_enabled", False)),
            multi_corr_scc=bool(cfg.get("multi_corr_scc", True)),
            multi_corr_gcc_phat=bool(cfg.get("multi_corr_gcc_phat", True)),
            multi_corr_onset=bool(cfg.get("multi_corr_onset", False)),
            multi_corr_gcc_scot=bool(cfg.get("multi_corr_gcc_scot", False)),
            multi_corr_gcc_whiten=bool(cfg.get("multi_corr_gcc_whiten", False)),
            multi_corr_dtw=bool(cfg.get("multi_corr_dtw", False)),
            multi_corr_spectrogram=bool(cfg.get("multi_corr_spectrogram", False)),
            # DSP & Filtering
            filter_bandpass_lowcut_hz=float(
                cfg.get("filter_bandpass_lowcut_hz", 300.0)
            ),
            filter_bandpass_highcut_hz=float(
                cfg.get("filter_bandpass_highcut_hz", 3400.0)
            ),
            filter_bandpass_order=int(cfg.get("filter_bandpass_order", 5)),
            filter_lowpass_taps=int(cfg.get("filter_lowpass_taps", 101)),
            scan_start_percentage=float(cfg.get("scan_start_percentage", 5.0)),
            scan_end_percentage=float(cfg.get("scan_end_percentage", 95.0)),
            use_soxr=bool(cfg.get("use_soxr", False)),
            audio_decode_native=bool(cfg.get("audio_decode_native", False)),
            audio_peak_fit=bool(cfg.get("audio_peak_fit", False)),
            audio_bandlimit_hz=int(cfg.get("audio_bandlimit_hz", 0)),
            # Drift Detection Settings
            detection_dbscan_epsilon_ms=float(
                cfg.get("detection_dbscan_epsilon_ms", 20.0)
            ),
            detection_dbscan_min_samples=int(
                cfg.get("detection_dbscan_min_samples", 2)
            ),
            drift_detection_r2_threshold=float(
                cfg.get("drift_detection_r2_threshold", 0.90)
            ),
            drift_detection_r2_threshold_lossless=float(
                cfg.get("drift_detection_r2_threshold_lossless", 0.95)
            ),
            drift_detection_slope_threshold_lossy=float(
                cfg.get("drift_detection_slope_threshold_lossy", 0.7)
            ),
            drift_detection_slope_threshold_lossless=float(
                cfg.get("drift_detection_slope_threshold_lossless", 0.2)
            ),
            # Stepping Correction Settings
            stepping_adjust_subtitles=bool(cfg.get("stepping_adjust_subtitles", True)),
            stepping_adjust_subtitles_no_audio=bool(
                cfg.get("stepping_adjust_subtitles_no_audio", True)
            ),
            stepping_boundary_mode=str(cfg.get("stepping_boundary_mode", "start")),
            stepping_first_stable_min_chunks=int(
                cfg.get("stepping_first_stable_min_chunks", 3)
            ),
            stepping_first_stable_skip_unstable=bool(
                cfg.get("stepping_first_stable_skip_unstable", True)
            ),
            # Segment Scan & Correction
            segment_triage_std_dev_ms=int(cfg.get("segment_triage_std_dev_ms", 50)),
            segment_coarse_chunk_s=int(cfg.get("segment_coarse_chunk_s", 15)),
            segment_coarse_step_s=int(cfg.get("segment_coarse_step_s", 60)),
            segment_search_locality_s=int(cfg.get("segment_search_locality_s", 10)),
            segment_fine_chunk_s=float(cfg.get("segment_fine_chunk_s", 2.0)),
            segment_fine_iterations=int(cfg.get("segment_fine_iterations", 10)),
            segment_min_confidence_ratio=float(
                cfg.get("segment_min_confidence_ratio", 5.0)
            ),
            # Segment Drift Detection
            segment_drift_r2_threshold=float(
                cfg.get("segment_drift_r2_threshold", 0.75)
            ),
            segment_drift_slope_threshold=float(
                cfg.get("segment_drift_slope_threshold", 0.7)
            ),
            segment_drift_outlier_sensitivity=float(
                cfg.get("segment_drift_outlier_sensitivity", 1.5)
            ),
            segment_drift_scan_buffer_pct=float(
                cfg.get("segment_drift_scan_buffer_pct", 2.0)
            ),
            # Stepping Scan Range
            stepping_scan_start_percentage=float(
                cfg.get("stepping_scan_start_percentage", 5.0)
            ),
            stepping_scan_end_percentage=float(
                cfg.get("stepping_scan_end_percentage", 99.0)
            ),
            # Silence Snapping
            stepping_snap_to_silence=bool(cfg.get("stepping_snap_to_silence", True)),
            stepping_silence_detection_method=str(
                cfg.get("stepping_silence_detection_method", "smart_fusion")
            ),
            stepping_silence_search_window_s=float(
                cfg.get("stepping_silence_search_window_s", 5.0)
            ),
            stepping_silence_threshold_db=float(
                cfg.get("stepping_silence_threshold_db", -40.0)
            ),
            stepping_silence_min_duration_ms=float(
                cfg.get("stepping_silence_min_duration_ms", 100.0)
            ),
            stepping_ffmpeg_silence_noise=float(
                cfg.get("stepping_ffmpeg_silence_noise", -40.0)
            ),
            stepping_ffmpeg_silence_duration=float(
                cfg.get("stepping_ffmpeg_silence_duration", 0.1)
            ),
            # VAD (Voice Activity Detection)
            stepping_vad_enabled=bool(cfg.get("stepping_vad_enabled", True)),
            stepping_vad_aggressiveness=int(cfg.get("stepping_vad_aggressiveness", 2)),
            stepping_vad_avoid_speech=bool(cfg.get("stepping_vad_avoid_speech", True)),
            stepping_vad_frame_duration_ms=int(
                cfg.get("stepping_vad_frame_duration_ms", 30)
            ),
            # Transient Detection
            stepping_transient_detection_enabled=bool(
                cfg.get("stepping_transient_detection_enabled", True)
            ),
            stepping_transient_threshold=float(
                cfg.get("stepping_transient_threshold", 8.0)
            ),
            stepping_transient_avoid_window_ms=int(
                cfg.get("stepping_transient_avoid_window_ms", 50)
            ),
            # Smart Fusion Weights
            stepping_fusion_weight_silence=int(
                cfg.get("stepping_fusion_weight_silence", 10)
            ),
            stepping_fusion_weight_no_speech=int(
                cfg.get("stepping_fusion_weight_no_speech", 8)
            ),
            stepping_fusion_weight_scene_align=int(
                cfg.get("stepping_fusion_weight_scene_align", 5)
            ),
            stepping_fusion_weight_duration=int(
                cfg.get("stepping_fusion_weight_duration", 2)
            ),
            stepping_fusion_weight_no_transient=int(
                cfg.get("stepping_fusion_weight_no_transient", 3)
            ),
            # Video-Aware Boundary Snapping
            stepping_snap_to_video_frames=bool(
                cfg.get("stepping_snap_to_video_frames", False)
            ),
            stepping_video_snap_mode=str(cfg.get("stepping_video_snap_mode", "scenes")),
            stepping_video_snap_max_offset_s=float(
                cfg.get("stepping_video_snap_max_offset_s", 2.0)
            ),
            stepping_video_scene_threshold=float(
                cfg.get("stepping_video_scene_threshold", 0.4)
            ),
            # Fill Mode & Content
            stepping_fill_mode=str(cfg.get("stepping_fill_mode", "silence")),
            stepping_content_correlation_threshold=float(
                cfg.get("stepping_content_correlation_threshold", 0.5)
            ),
            stepping_content_search_window_s=float(
                cfg.get("stepping_content_search_window_s", 5.0)
            ),
            # Track Naming
            stepping_corrected_track_label=str(
                cfg.get("stepping_corrected_track_label", "")
            ),
            stepping_preserved_track_label=str(
                cfg.get("stepping_preserved_track_label", "")
            ),
            # Quality Audit Thresholds
            stepping_audit_min_score=float(cfg.get("stepping_audit_min_score", 12.0)),
            stepping_audit_overflow_tolerance=float(
                cfg.get("stepping_audit_overflow_tolerance", 0.8)
            ),
            stepping_audit_large_correction_s=float(
                cfg.get("stepping_audit_large_correction_s", 3.0)
            ),
            # Filtered Stepping Correction
            stepping_correction_mode=str(cfg.get("stepping_correction_mode", "full")),
            stepping_quality_mode=str(cfg.get("stepping_quality_mode", "normal")),
            stepping_min_chunks_per_cluster=int(
                cfg.get("stepping_min_chunks_per_cluster", 3)
            ),
            stepping_min_cluster_percentage=float(
                cfg.get("stepping_min_cluster_percentage", 5.0)
            ),
            stepping_min_cluster_duration_s=float(
                cfg.get("stepping_min_cluster_duration_s", 20.0)
            ),
            stepping_min_match_quality_pct=float(
                cfg.get("stepping_min_match_quality_pct", 85.0)
            ),
            stepping_min_total_clusters=int(cfg.get("stepping_min_total_clusters", 2)),
            stepping_filtered_fallback=str(
                cfg.get("stepping_filtered_fallback", "nearest")
            ),
            stepping_diagnostics_verbose=bool(
                cfg.get("stepping_diagnostics_verbose", True)
            ),
            # Segmented Audio QA
            segmented_qa_threshold=float(cfg.get("segmented_qa_threshold", 85.0)),
            segment_qa_chunk_count=int(cfg.get("segment_qa_chunk_count", 30)),
            segment_qa_min_accepted_chunks=int(
                cfg.get("segment_qa_min_accepted_chunks", 28)
            ),
            # Sync Stability Settings
            sync_stability_enabled=bool(cfg.get("sync_stability_enabled", True)),
            sync_stability_variance_threshold=float(
                cfg.get("sync_stability_variance_threshold", 0.0)
            ),
            sync_stability_min_chunks=int(cfg.get("sync_stability_min_chunks", 3)),
            sync_stability_outlier_mode=str(
                cfg.get("sync_stability_outlier_mode", "any")
            ),
            sync_stability_outlier_threshold=float(
                cfg.get("sync_stability_outlier_threshold", 1.0)
            ),
            # Resampling Engine Settings
            segment_resample_engine=str(
                cfg.get("segment_resample_engine", "aresample")
            ),
            segment_rb_pitch_correct=bool(cfg.get("segment_rb_pitch_correct", False)),
            segment_rb_transients=str(cfg.get("segment_rb_transients", "crisp")),
            segment_rb_smoother=bool(cfg.get("segment_rb_smoother", True)),
            segment_rb_pitchq=bool(cfg.get("segment_rb_pitchq", True)),
            # OCR Settings
            ocr_engine=str(cfg.get("ocr_engine", "tesseract")),
            ocr_language=str(cfg.get("ocr_language", "eng")),
            ocr_psm=int(cfg.get("ocr_psm", 7)),
            ocr_char_whitelist=str(cfg.get("ocr_char_whitelist", "")),
            ocr_char_blacklist=str(cfg.get("ocr_char_blacklist", "|")),
            ocr_low_confidence_threshold=float(
                cfg.get("ocr_low_confidence_threshold", 60.0)
            ),
            ocr_multi_pass=bool(cfg.get("ocr_multi_pass", True)),
            ocr_output_format=str(cfg.get("ocr_output_format", "ass")),
            # OCR Preprocessing
            ocr_preprocess_auto=bool(cfg.get("ocr_preprocess_auto", True)),
            ocr_upscale_threshold=int(cfg.get("ocr_upscale_threshold", 40)),
            ocr_target_height=int(cfg.get("ocr_target_height", 80)),
            ocr_border_size=int(cfg.get("ocr_border_size", 5)),
            ocr_force_binarization=bool(cfg.get("ocr_force_binarization", False)),
            ocr_binarization_method=str(cfg.get("ocr_binarization_method", "otsu")),
            ocr_denoise=bool(cfg.get("ocr_denoise", False)),
            ocr_save_debug_images=bool(cfg.get("ocr_save_debug_images", False)),
            # OCR Output & Position
            ocr_preserve_positions=bool(cfg.get("ocr_preserve_positions", True)),
            ocr_bottom_threshold=float(cfg.get("ocr_bottom_threshold", 75.0)),
            ocr_video_width=int(cfg.get("ocr_video_width", 1920)),
            ocr_video_height=int(cfg.get("ocr_video_height", 1080)),
            # OCR Post-Processing
            ocr_cleanup_enabled=bool(cfg.get("ocr_cleanup_enabled", True)),
            ocr_cleanup_normalize_ellipsis=bool(
                cfg.get("ocr_cleanup_normalize_ellipsis", False)
            ),
            ocr_custom_wordlist_path=str(cfg.get("ocr_custom_wordlist_path", "")),
            # OCR Debug & Runtime
            ocr_debug_output=bool(cfg.get("ocr_debug_output", False)),
            ocr_run_in_subprocess=bool(cfg.get("ocr_run_in_subprocess", True)),
        )

    def to_dict(self) -> dict:
        """Convert AppSettings to a dictionary for serialization.

        Used when settings need to be passed to subprocesses or external tools
        that expect dict-based configuration.
        """
        from dataclasses import fields

        result = {}
        for f in fields(self):
            value = getattr(self, f.name)
            # Convert enums to their string values
            if hasattr(value, "value"):
                result[f.name] = value.value
            else:
                result[f.name] = value
        return result
