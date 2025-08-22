
from __future__ import annotations

# Single source of truth for defaults (UI + backend)
DEFAULTS = {
    # Storage / Paths
    "output_folder": "./sync_output",
    "temp_root": "./temp_work",
    "ffmpeg_path": "",
    "ffprobe_path": "",
    "mkvmerge_path": "",
    "mkvextract_path": "",
    "videodiff_path": "",

    # Workflow / Analysis
    "workflow": "Analyze & Merge",          # or "Analyze Only"
    "analysis_mode": "Audio Correlation",   # or "VideoDiff"
    "scan_chunk_count": 5,
    "scan_chunk_duration": 10,              # seconds per chunk
    "min_match_pct": 0.45,                  # 0.0 - 1.0
    "videodiff_error_min": 0.0,
    "videodiff_error_max": 1.0,

    # Matching / Preferences
    "match_jpn_secondary": False,
    "match_jpn_tertiary": False,
    "apply_dialog_norm_gain": False,
    "first_sub_default": False,

    # Chapters
    "rename_chapters": False,
    "shift_chapters": False,
    "snap_chapters": False,
    "snap_mode": "nearest",                 # "back" | "nearest"
    "snap_distance_ms": 400,

    # Logging
    "log_compact": True,
    "log_tail_lines": 2000,
    "log_error_tail": 50,
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
