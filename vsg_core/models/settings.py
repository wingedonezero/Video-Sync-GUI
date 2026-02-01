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
