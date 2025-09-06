# -*- coding: utf-8 -*-
from dataclasses import dataclass
from .enums import AnalysisMode, SnapMode

@dataclass
class AppSettings:
    output_folder: str
    temp_root: str
    videodiff_path: str
    analysis_mode: AnalysisMode
    analysis_lang_ref: str | None
    analysis_lang_sec: str | None
    analysis_lang_ter: str | None
    scan_chunk_count: int
    scan_chunk_duration: int
    min_match_pct: float
    videodiff_error_min: float
    videodiff_error_max: float
    rename_chapters: bool
    snap_chapters: bool
    snap_mode: SnapMode
    snap_threshold_ms: int
    snap_starts_only: bool
    apply_dialog_norm_gain: bool
    disable_track_statistics_tags: bool
    log_compact: bool
    log_autoscroll: bool
    log_error_tail: int
    log_tail_lines: int
    log_progress_step: int
    log_show_options_pretty: bool
    log_show_options_json: bool
    archive_logs: bool
    auto_apply_strict: bool

    @classmethod
    def from_config(cls, cfg: dict) -> "AppSettings":
        return cls(
            output_folder=cfg['output_folder'],
            temp_root=cfg['temp_root'],
            videodiff_path=cfg.get('videodiff_path',''),
            analysis_mode=AnalysisMode(cfg.get('analysis_mode','Audio Correlation')),
            analysis_lang_ref=cfg.get('analysis_lang_ref') or None,
            analysis_lang_sec=cfg.get('analysis_lang_sec') or None,
            analysis_lang_ter=cfg.get('analysis_lang_ter') or None,
            scan_chunk_count=int(cfg['scan_chunk_count']),
            scan_chunk_duration=int(cfg['scan_chunk_duration']),
            min_match_pct=float(cfg['min_match_pct']),
            videodiff_error_min=float(cfg['videodiff_error_min']),
            videodiff_error_max=float(cfg['videodiff_error_max']),
            rename_chapters=bool(cfg['rename_chapters']),
            snap_chapters=bool(cfg['snap_chapters']),
            snap_mode=SnapMode(cfg.get('snap_mode','previous')),
            snap_threshold_ms=int(cfg['snap_threshold_ms']),
            snap_starts_only=bool(cfg['snap_starts_only']),
            apply_dialog_norm_gain=bool(cfg['apply_dialog_norm_gain']),
            disable_track_statistics_tags=bool(cfg['disable_track_statistics_tags']),
            log_compact=bool(cfg['log_compact']),
            log_autoscroll=bool(cfg['log_autoscroll']),
            log_error_tail=int(cfg['log_error_tail']),
            log_tail_lines=int(cfg.get('log_tail_lines', 0)),
            log_progress_step=int(cfg['log_progress_step']),
            log_show_options_pretty=bool(cfg['log_show_options_pretty']),
            log_show_options_json=bool(cfg['log_show_options_json']),
            archive_logs=bool(cfg['archive_logs']),
            auto_apply_strict=bool(cfg.get('auto_apply_strict', False)),
        )
