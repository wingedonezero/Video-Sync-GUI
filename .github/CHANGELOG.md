# Changelog
All notable changes to **Video Sync GUI** will be documented in this file.

> Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and dates are in `YYYY-MM-DD` (America/New_York).

## [1.01] — 2025-08-16
### Summary
Stabilizes the pipeline and logging across **Analyze** and **Analyze & Merge**, ensures settings are loaded/merged early and safely, codifies the **positive‑only (lossless)** delay scheme, fixes chapter end‑time issues, guarantees subtitle residual delays are applied to **all** subtitle tracks, and enforces deterministic default‑track rules. Also standardizes mkvmerge flags (`--compression 0:none` on non‑attachments; optional dialog‑norm removal only for audio).

### Added
- **Compact logger** for external tools (`run_command`): one `$ …` line, throttled `Progress: N%`, brief error tail on failure, optional short tail on success.
- **Robust settings merge** (`load_settings()`): reads `settings_gui.json`, merges with in‑code defaults, **writes back missing keys**; “Load Settings” is resilient to missing widget tags.
- **Positive‑only delay plan** (`compute_positive_delay_plan()`): converts raw offsets into a global shift + per‑source residuals → avoids negative (cropping) delays to keep operations **lossless**.
- **Chapter utilities**: 
  - `rename_chapters_normalized()` → `Chapter 01`, `Chapter 02`, … (no locale/language prefix like `en:`).
  - `shift_chapters_by()` applies the global shift and enforces **end ≤ next start − 1 ms** guard to prevent overlap after shifting.
- **Default‑track rules** (deterministic playback):
  - **Audio**: only the first audio in the final order is default.
  - **Subtitles**: prefer **“Signs / Songs”** when enabled; otherwise first sub. If **no ENG audio** exists, first subtitle defaults.
- **Token assembly hardening** (argv style): ensures `--compression 0:none` on all non‑attachments; **never** on attachments. Optional `--remove-dialog-normalization-gain 0` applied to audio only.
- **Log auto‑scroll helper** (respects `log_autoscroll`).

### Changed
- Track ordering remains deterministic (**ref → sec → ter**), with ENG audio preferred earliest within the audio group.
- Settings defaults live in code and are merged at startup; the file is auto‑updated to include any new keys.
- Pretty/JSON option file dumps can be toggled via settings; compact logging is **on by default**.

### Fixed
- **Chapters**: end times no longer exceed the next chapter’s start after a global shift.
- **Residual sync**: per‑group residual `--sync 0:<ms>` now applied to **every** subtitle track from that group (no sibling left behind).
- **mkvmerge option handling**: eliminated cases where flags were misinterpreted as file paths in option files.
- **Load Settings**: no longer throws if a mapped UI tag is missing; silently skips unknown tags.

### Backwards compatibility
- Behavior is compatible with prior outputs, with these clarifications:
  - Delays are now **lossless** (positive‑only). Per‑track `--sync` values may differ from earlier runs, but playback alignment is identical and no audio is cropped.
  - Chapters may differ by ≤1 ms due to the non‑overlap guard.
  - Logging is compact by default; enable verbose dumps in settings for deep debugging.

### Settings (new/confirmed keys)
```json
{
  "log_compact": true,
  "log_tail_lines": 0,
  "log_error_tail": 20,
  "log_progress_step": 100,
  "log_show_options_pretty": false,
  "log_show_options_json": false,
  "log_autoscroll": true,

  "rename_chapters": true,
  "snap_chapters": false,
  "snap_mode": "starts",
  "snap_tolerance_ms": 250,

  "first_sub_default": false,
  "signs_sub_default": true,

  "apply_dialog_norm_gain": false
}
```

---

## [1.0] — 2025-08-16
### Summary
Initial GitHub baseline for the GUI port of the prior CLI v20 pipeline. Establishes the Dear PyGui interface, the analyze/merge workflow, and the mkvmerge option‑file strategy.

### Features
- **Dear PyGui** UI with two main workflows:
  - **Analyze** (audio cross‑correlation and optional VideoDiff).
  - **Analyze & Merge** (full pipeline).
- **Batch selection** for Reference (video+chapters) and Secondary/Tertiary inputs.
- **Audio correlation (xcorr)**: chunked correlation + minimum match threshold (%).
- **VideoDiff mode**: single‑pass external tool; captures `ss`/`itsoffset` in seconds; error threshold check (lower is better).
- **Ordering rules**: final track order by priority (**ref → sec → ter**) and type; ENG audio preferred early.
- **Naming conventions**: normalized track names (e.g., `Signs / Songs`), language tagging propagation when known.
- **mkvmerge JSON option file** assembly (argv tokens), including track‑level flags.
- **Temp/output management**: temp job folders per run; default temp under script folder; output folder selection.
- **Logging**: prints commands and tool progress to UI and log file.

### Known limitations (addressed in 1.01)
- Logs could grow to tens of thousands of lines on long merges.
- Negative per‑track delays could crop audio (lossy) instead of shifting positively.
- Chapter end times could overflow the next chapter’s start after shifting.
- Residual subtitle delays from the same source were inconsistently applied across siblings.
- Attachments occasionally received compression flags; some flags could be misread as filenames in malformed option files.
