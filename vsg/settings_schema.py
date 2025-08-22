
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
    "scan_chunk_count": 10,
    "scan_chunk_duration": 15,              # seconds per chunk
    # NOTE: Support both scales; if >1 treat as percent
    "min_match_pct": 5.0,                   # percent (0-100) from original
    "videodiff_error_min": 0.0,
    "videodiff_error_max": 100.0,

    # Matching / Preferences
    "match_jpn_secondary": True,
    "match_jpn_tertiary": True,
    "apply_dialog_norm_gain": False,
    "first_sub_default": True,
    "swap_subtitle_order": False,           # original option

    # Chapters
    "rename_chapters": False,
    "shift_chapters": False,
    "snap_chapters": False,
    "snap_mode": "previous",                # alias of "back"
    "snap_threshold_ms": 250,               # original key
    "snap_distance_ms": 250,                # keep alias for compatibility
    "snap_starts_only": True,
    "chapter_snap_verbose": False,
    "chapter_snap_compact": True,

    # Logging
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
