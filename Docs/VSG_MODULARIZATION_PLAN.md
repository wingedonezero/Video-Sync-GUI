
# Modularization Plan — Video‑Sync‑GUI

This document maps **current functions** in `video_sync_gui.py` to the new **`vsg/` modules**, with signatures, responsibilities, and notes for safe extraction. The goal is **zero behavior change** while we move logic behind an API facade the GUI calls.

> Source analyzed: the `video_sync_gui.py` you shared (≈1600 lines). Function names below reflect that file.

---

## Phase 0 — Principles

- **No behavior change.** Move code as‑is; only fix imports & paths.  
- **Small steps.** Extract 1–3 functions per PR, then wire GUI to call `vsg.*`.  
- **Black + type hints.** Keep code Black‑formatted and add minimal hints/docstrings.  
- **Stable data shapes.** Use simple dicts/tuples for now (we can dataclass later).

---

## Phase 1 — Analysis & Delay Planning

### Move → `vsg/analysis/audio.py`
- `ffprobe_duration(path) -> float`
- `get_audio_stream_index(path, prefer_lang=None) -> int`
- `extract_audio_chunk(path, start_s, duration_s, stream_index) -> Path`
- `find_audio_delay(ref_path, other_path, settings) -> int`
- `run_audio_correlation_workflow(ref_path, other_path, settings) -> dict`
  - **Returns**: `{ "chunks": [...], "best_ms": int, "best_match": float }`
- **Keep** the console/GUI logging in the caller; return structured results.

### Move → `vsg/analysis/video.py`
- `run_videodiff(ref_path, other_path, settings) -> int`
  - Parse tool output; single sign convention: **positive = behind REF**.

### Move → `vsg/plan.py`
- `build_plan(ref_tracks, sec_tracks, ter_tracks, delays) -> list`
  - (If `build_plan` currently also computes *normalized* delays, split:)
- `build_positive_only_delays(measured: {"ref":0,"sec":int|None,"ter":int|None}) -> PositiveOnlyDelayPlan`
  - Implementation already included in scaffold (`G = max(...)` logic).

### GUI calls → `vsg.api`
- `analyze_and_plan(ref, sec, ter, mode, settings) -> PositiveOnlyDelayPlan`
  - Under the hood calls `analysis.*` then `build_positive_only_delays`.

**Checklist**
- [ ] Copy functions verbatim; import from `vsg.analysis.*` in GUI.
- [ ] Add docstrings; keep return shapes identical.
- [ ] Verify analysis-only run prints the same lines as before.

---

## Phase 2 — Chapters

### Move → `vsg/chapters.py`
- `_normalize_chapter_end_times(xml_text) -> xml_text`
- `_snap_chapter_times_inplace(ch_xml_path, mode, tolerance_ms) -> None`
- `rename_chapters_xml(in_path, out_path, shift_ms, normalize_names, ...) -> Path`
- Internal helpers:
  - `_parse_ns`, `_parse_hhmmss_ns`, `_pick_candidate` (and duplicates) → **consolidate** into private helpers in `chapters.py`.
  - `_probe_keyframes_ns(ffprobe_json)` and `_fmt_ns` → keep as chapter helpers for now.

**API surface (proposed)**
- `load_chapters(source_path) -> List[dict]` (if already in code; otherwise keep XML path model)
- `shift_chapters(chapters, shift_ms) -> chapters`
- `snap_chapters(chapters, mode, tolerance_ms) -> chapters`

**Checklist**
- [ ] Move code but keep existing XML in/out behavior to avoid regressions.
- [ ] Only refactor the *namespacing* (module placement), not logic.

---

## Phase 3 — Mux Tokens & mkvmerge

### Move → `vsg/opts.py`
- `_ext_for_track(path) -> str`
- `_tokens_for_track(track_dict, defaults, language, delay_ms, ...) -> List[str]`
- `build_mkvmerge_tokens(output_path, ref_path, sec_path, ter_path, plan, chapters_xml, settings) -> List[str]`
- `is_signs_name(name: str) -> bool`
- `format_delay_ms(ms: int) -> str`

### Move → `vsg/mux/mkvmerge.py`
- `write_mkvmerge_json_options(tokens, json_path, logger) -> Path`
  - Writes **raw JSON array** and **opts.pretty.txt**.
- `run_mkvmerge_with_json(json_path, logger) -> (rc, out, err)`
  - (Optional) Replace with `run_mkvmerge_with_tokens(tokens)` if calling directly.
- `_vsg_tokenize_opts_json` and `_vsg_parse_mkvmerge_tokens` → keep as private helpers in `opts.py` for round‑trip testing.
- `_vsg_log_merge_summary_from_opts(json_tokens, logger)` → move to `vsg/logging.py` (new file).

**Track defaults & order**
- Keep current rules *as‑is*: exactly one audio default, subtitle default priority (Signs/Songs > fallback if no ENG audio), explicit `--track-order`.

**Checklist**
- [ ] Ensure per‑file scoping order is preserved (options immediately before file).
- [ ] Keep **attachments** free of compression flags.
- [ ] Preserve pretty dump format so logs remain identical.

---

## Phase 4 — Logging & Settings

### Move → `vsg/utils/proc.py`
- `run_command(argv) -> (rc, out, err)` (already in scaffold).

### New → `vsg/logging.py`
- `_log(logger, msg)` (rename to `log_line` and keep GUI’s logger adapter)  
- `job_logger_for(index, out_dir)` (if it’s a pure helper)  
- `_vsg_log_merge_summary_from_opts(tokens, logger)` → public `log_merge_summary(...)`

### Move → `vsg/settings.py`
- `load_settings(path) -> dict | AppSettings`
- `save_settings(path, settings) -> None`
- `apply_settings_to_ui(settings)` / `pull_ui_to_settings()` stay in GUI for now (UI‑specific).

**Checklist**
- [ ] GUI remains the only place that touches DearPyGUI.
- [ ] Core modules accept plain data (paths, ints), never UI handles.

---

## Phase 5 — Jobs & Orchestration

### Move orchestration helpers that don’t touch UI:
- `discover_jobs(input_dir, ...) -> List[Job]`
- `merge_job(job, ...) -> Path`
- `best_from_results(results) -> dict` (if not UI‑specific)

Place these in `vsg/api.py` (facade) or a `vsg/jobs.py` if they grow.

**Checklist**
- [ ] Keep `worker_run_jobs` and UI callbacks (`do_analyze_only`, `do_analyze_and_merge`) in GUI until the end.

---

## Function‑to‑Module Mapping (Quick Table)

| Area | Current Function(s) | Target Module |
|---|---|---|
| Analysis (audio) | `ffprobe_duration`, `get_audio_stream_index`, `extract_audio_chunk`, `find_audio_delay`, `run_audio_correlation_workflow` | `vsg.analysis.audio` |
| Analysis (video) | `run_videodiff` | `vsg.analysis.video` |
| Plan | `build_plan`, `best_from_results` (if generic) | `vsg.plan` |
| Positive‑only delays | _new_ normalized plan builder | `vsg.plan` |
| Chapters | `_normalize_chapter_end_times`, `_snap_chapter_times_inplace`, `rename_chapters_xml`, `_parse_*`, `_pick_*`, `_probe_keyframes_ns`, `_fmt_ns` | `vsg.chapters` |
| mkvmerge tokens | `_ext_for_track`, `_tokens_for_track`, `build_mkvmerge_tokens`, `is_signs_name`, `format_delay_ms` | `vsg.opts` |
| mkvmerge IO | `write_mkvmerge_json_options`, `run_mkvmerge_with_json`, `_vsg_tokenize_opts_json`, `_vsg_parse_mkvmerge_tokens` | `vsg.mux.mkvmerge` (and `vsg.opts` for tokenize/parse) |
| Merge summary | `_vsg_log_merge_summary_from_opts` | `vsg.logging` |
| Logging | `_log`, `job_logger_for`, `pump_logs` | `vsg.logging` (GUI keeps UI plumbing) |
| Settings | `load_settings`, `save_settings` | `vsg.settings` |
| Jobs/orchestration | `discover_jobs`, `merge_job`, `best_from_results` | `vsg.api` or `vsg.jobs` |
| GUI only | `build_ui`, `on_*`, `set_progress`, `ui_save_settings`, `_bind_control_theme`, `_safe_bind_input_enhancements`, `do_analyze_*`, `worker_run_jobs`, `add_input` | stay in `video_sync_gui.py` for now |

---

## Safe‑Extraction Checklist (each PR)

1. Copy functions into the target `vsg/` module.  
2. Add docstrings and minimal type hints; keep logic identical.  
3. Update imports in `video_sync_gui.py` to call `vsg.*`.  
4. Run through **Analyze** and **Analyze & Merge** with the same inputs; verify:  
   - identical logs (commands, progress, merge summary),  
   - identical `opts.json` and `opts.pretty.txt`,  
   - identical output MKV (track order, defaults, chapters).  
5. Format with `make format` (Black/isort).

---

## Notes from Code Review (spots to watch)

- Duplicate helpers (`_pick_candidate`, `_parse_ns`) → consolidate in `chapters.py`.
- `_tokens_for_track` must keep **options immediately before file**, and pretty dump mirrors grouping.
- Ensure we **never** set compression on attachments.
- Keep Signs/Songs default‑subtitle priority intact; fallback rule if no English audio.
- Positive‑only delay math remains in **plan** (not scattered across GUI paths).
- `run_command` should be the **only** subprocess runner used by core.

---

## Final Step

When all pieces are migrated, collapse the GUI into a thin shell:  
- GUI collects inputs & settings → calls `vsg.api.analyze_and_plan()` → `vsg.api.merge_with_plan()`  
- All behavior is tested in `vsg/`, enabling a future CLI without duplication.

