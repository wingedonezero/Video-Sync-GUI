# Settings

All keys exist via `DEFAULT_CONFIG` and are merged with your saved JSON.

## Core
- `workflow`: `"Analyze & Merge"` | `"Analyze Only"`
- `analysis_mode`: `"videodiff"` | `"audio_xcorr"`
- `log_autoscroll`: bool

## Logging
- `log_compact`, `log_error_tail`, `log_tail_lines`

## Analysis
- `scan_chunk_count` (int), `scan_chunk_duration` (float), `min_match_pct` (float)

## Chapters
- `rename_chapters`: bool
- `snap_chapters`: bool
- `snap_mode`: `"previous" | "next" | "nearest"`
- `snap_threshold_ms`: int
- `snap_starts_only`: bool
- `chapter_snap_verbose`: bool
- `chapter_snap_compact`: bool
- `first_sub_default`: bool

## Paths
- `temp_root`, `output_folder`
- Tool paths: `ffmpeg_path`, `ffprobe_path`, `mkvmerge_path`, `mkvextract_path`, `videodiff_path`
