# Modules

- `vsg/analysis/videodiff.py`
  - `run_videodiff(...)` — runs videodiff binary, parses output, returns signed delay.
  - `format_delay_ms(ms)` — helper to display delay in ms.

- `vsg/analysis/audio_xcorr.py`
  - `get_audio_stream_index(...)` — choose best audio stream.
  - `extract_audio_chunk(...)` — extract segment via ffmpeg.
  - `find_audio_delay(...)` — correlate and compute delay.
  - `best_from_results(...)` — select best candidate.
  - `run_audio_correlation_workflow(...)` — orchestrates above and returns delay.

- `vsg/plan/build.py`
  - `build_plan(...)` — compose merge plan dict from analysis + user settings.
  - `summarize_plan(...)` — human-readable text summary.

- `vsg/mux/tokens.py`
  - `_tokens_for_track(...)`, `build_mkvmerge_tokens(...)` — map plan tracks to mkvmerge representation.

- `vsg/mux/run.py`
  - `write_mkvmerge_json_options(path, opts)` — write JSON for mkvmerge.
  - `run_mkvmerge_with_json(path)` — spawn mkvmerge with JSON opts.

- `vsg/mux/chapters.py`
  - Extract REF chapters (mkvextract), rename, snap to keyframes (ffprobe), output XML.

- `vsg/jobs/discover.py`
  - `discover_jobs(...)` — scan inputs into jobs.

- `vsg/jobs/merge_job.py`
  - `merge_job(...)` — top-level job runner: analysis → plan → chapters → mux.

- `vsg/settings.py`
  - `DEFAULT_CONFIG`, `CONFIG`, `load_settings()`, `save_settings()`.

- `vsg/logbus.py`
  - `_log(...)`, `LOG_Q`, `pump_logs()`.

- `vsg/tools.py`
  - `find_required_tools()`, `run_command(cmd)` and tool path resolution.
