
from __future__ import annotations

DEFAULTS = {
    # Storage
    "output_folder": "./sync_output",
    "temp_root": "./temp_work",
    "ffmpeg_path": "",
    "ffprobe_path": "",
    "mkvmerge_path": "",
    "mkvextract_path": "",
    "videodiff_path": "",

    # Analysis
    "workflow": "Analyze & Merge",          # "Analyze Only" | "Analyze & Merge"
    "analysis_mode": "Audio Correlation",   # "Audio Correlation" | "VideoDiff"
    "scan_chunk_count": 10,
    "scan_chunk_duration": 15,
    "min_match_pct": 5.0,
    "videodiff_error_min": 0.0,
    "videodiff_error_max": 100.0,

    # Global (audio/subtitle behavior + chapter snap)
    "rename_chapters": False,
    "match_jpn_secondary": True,
    "match_jpn_tertiary": True,
    "apply_dialog_norm_gain": False,
    "first_sub_default": True,

    "snap_chapters": False,
    "snap_mode": "previous",   # "previous" | "next" | "nearest" | "none"
    "snap_threshold_ms": 250,
    "snap_starts_only": True,

    # Logging
    "chapter_snap_verbose": False,
    "chapter_snap_compact": True,
    "log_compact": True,
    "log_tail_lines": 0,
    "log_error_tail": 20,
    "log_progress_step": 20,
    "log_show_options_pretty": False,
    "log_show_options_json": False,
    "log_autoscroll": True,

    # Appearance
    "ui_font_family": "",
    "ui_font_size_pt": 10,
    "row_spacing_px": 8,
    "input_height_px": 32,
    "compact_controls": False,
}

SCHEMA_VERSION = 2
