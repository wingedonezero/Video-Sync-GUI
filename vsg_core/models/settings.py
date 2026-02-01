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
    # Stepping Correction Settings
    # =========================================================================
    stepping_adjust_subtitles: bool
    stepping_boundary_mode: str  # "start", "majority", "midpoint"

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
            # Stepping Correction Settings
            stepping_adjust_subtitles=bool(cfg.get("stepping_adjust_subtitles", True)),
            stepping_boundary_mode=str(cfg.get("stepping_boundary_mode", "start")),
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
