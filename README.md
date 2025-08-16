# Video Sync GUI — v1.0

A purpose-built GUI for **lossless** audio/subtitle alignment and MKV remuxing with a focus on correctness, repeatability, and readable logs. It wraps a proven CLI pipeline into a DearPyGui app and codifies the rules we’ve refined: **accurate delay detection, positive-only (lossless) delay application, clean chapter handling, predictable track ordering & defaults, and safe mkvmerge option assembly**.

This README is intentionally exhaustive so another engineer (or another chat) can understand the whole system end-to-end.

---

## Table of contents
- [Philosophy & goals](#philosophy--goals)
- [Key features](#key-features)
- [Workflows](#workflows)
- [Delay discovery](#delay-discovery)
  - [Audio cross-correlation](#audio-crosscorrelation)
  - [VideoDiff](#videodiff)
  - [Rounding & units](#rounding--units)
  - [Lossless “positive-only” delay scheme](#lossless-positiveonly-delay-scheme)
- [Chapters](#chapters)
  - [Renaming](#renaming)
  - [Time shifting](#time-shifting)
  - [Snap to keyframes (optional)](#snap-to-keyframes-optional)
- [Tracks: ordering, language, defaults, compression](#tracks-ordering-language-defaults-compression)
- [Attachments (fonts)](#attachments-fonts)
- [mkvmerge options file format](#mkvmerge-options-file-format)
- [Temporary/output layout & naming](#temporaryoutput-layout--naming)
- [Logging & settings](#logging--settings)
- [GUI layout & controls](#gui-layout--controls)
- [Configuration file reference](#configuration-file-reference)
- [Dependencies](#dependencies)
- [Known limitations / notes](#known-limitations--notes)
- [Versioning](#versioning)

---

## Philosophy & goals
- **Bit-exact where possible.** No re-encoding; use mkvextract/mkvmerge to demux/remux.  
- **Lossless sync.** Never “cut off” early audio via negative delays; always shift with **positive** delays by moving the global start forward.  
- **Deterministic assembly.** mkvmerge command is written to a JSON option file and logged, with stable ordering and rule-driven defaults.  
- **Readable logs.** Compact by default; rich enough for debugging when needed.  
- **Debuggable temp tree.** Every stage writes to a per-job folder with predictable names.

---

## Key features
- **Two analysis engines**:
  - **Audio cross-correlation** with tunable chunking & minimum match threshold.
  - **VideoDiff** (external tool) for video-based offset + confidence (error) reporting.
- **Lossless delay application**:
  - Converts raw offsets (which may be negative) into a **positive-only** scheme by shifting the global start so the earliest track becomes 0 ms.
  - Applies the proper per-track residuals to **all** media streams and **chapters**.
- **Chapter handling**:
  - Optional **rename** to `Chapter 01`, `Chapter 02`, … (no language prefix).
  - **Time-shift** chapters by the computed global shift.
  - **Optional “snap to keyframes”**: starts-only or starts+ends with tolerance.
- **Track ordering & defaults** (sane playback behavior):
  - Audio defaults only on **first audio in final order** (or per user rule).
  - Subtitles: optional “**make first sub in final order default**”, and special handling for a **“Signs / Songs”** track (can be marked default by rule).
  - Language tags are preserved / propagated; names standardized.
- **Compression & dialog normalization**:
  - `--compression 0:none` applied to **all tracks** except attachments.
  - Optional **`--remove-dialog-normalization-gain`** for supported audio types.
- **Attachments**: fonts collected and attached; attachments **never** get compression flags.
- **mkvmerge option files**:
  - **JSON array of tokens** (argv) built programmatically (the format mkvmerge actually accepts for `@file.json`).
  - A “pretty” companion text is emitted for human review.
- **Storage control**:
  - **Temp root** folder selector with default under the script directory.
  - Output folder selector; persistent across sessions.
- **Compact logs + autoscroll**:
  - One command line per tool + throttled progress; short error tails.
  - Log window auto-scrolls to bottom while jobs run.
- **Per-job artifact logging**:
  - Logs include the **final merge order**, selected delays, chapter adjustments, and the **exact option file** used by mkvmerge.

---

## Workflows
1. **Analyze only**
   - Demux what’s needed for analysis.
   - Run either **Audio XCorr** or **VideoDiff** once.
   - Report offset (ms) and analysis confidence (for VideoDiff: lower error is better; > 100 = reject).

2. **Analyze & Merge**
   - Analyze as above.
   - Compute **positive-only delay plan**.
   - Optionally **shift/rename/snap** chapters.
   - Build mkvmerge **JSON option file** (tokens) respecting all rules.
   - Merge to final MKV with attachments.

> **Tip:** VideoDiff runs **exactly once**; Audio XCorr may work in chunks internally but reports a single best-fit offset. If VideoDiff error > configured max, the job **fails early**.

---

## Delay discovery

### Audio cross-correlation
- Compares audio waveforms from Reference vs. Secondary/Tertiary sources to estimate offset.
- **Settings**:
  - **Chunk size** (sec): analysis stride (bigger = fewer comparisons, smaller = more robust but slower).
  - **Minimum match %**: reject if lower (prevents merging dubious results).
- Produces a raw offset in seconds (can be negative if secondary starts “earlier”).

### VideoDiff
- External tool that compares video frames and prints a final line with **`itsoffset:`** or **`ss:`** in seconds (e.g., `ss: 1.08527`).
- We parse the **last result line** when the program completes.
- **Confidence/error**: lower is better; **> 100** is rejected.
- In logs we record both the raw value and the parsed ms.

### Rounding & units
- Internally we work ms-accurate.  
- **Audio XCorr**: round to the nearest ms (traditional rounding; if the 4th decimal ≥ 5, round up).  
- **VideoDiff**: same rounding of its seconds value to ms.
- mkvmerge accepts sub-ms in some contexts, but our pipeline standardizes on ms for consistency across tools and logs.

### Lossless “positive-only” delay scheme
Negative mkvmerge delays **crop** streams (lossy). We **never** do that.

**Rule**: Identify the most negative offset, call it `N` (e.g., `-1085 ms`).  
- Add `+|N|` to **all** tracks (global shift).  
- Then apply **per-track** residuals so the earliest track lands at `0 ms`.

Example:
- Video (reference): `0 ms` raw → becomes `+1085 ms`.
- Audio A (secondary): `-1085 ms` → becomes `0 ms`.
- Audio B (tertiary): `-1001 ms` → becomes `+84 ms`.

Chapters are shifted by the **global** `+|N|` so they stay aligned to the reference content.

---

## Chapters

### Renaming
If enabled, final chapter names are normalized to **`Chapter 01`**, `Chapter 02`, … (no `en:` prefix).

### Time shifting
Chapters are shifted by the global positive shift so that:
- The **reference video**’s timeline 0 moves to the **new** global start.
- Chapter **content** remains aligned to the same visuals.

### Snap to keyframes (optional)
- Goal: improve seek UX by aligning chapter boundaries to nearby I-frames.
- Modes:
  - **Starts only**
  - **Starts & Ends**
- **Tolerance**: configurable (e.g., ±250 ms).  
  - If a chapter boundary is **within tolerance** of a keyframe, we snap it.
  - If already within tolerance, we leave it as is.
  - If **no nearby keyframe** (or out of tolerance), we **don’t move** it and log “too_far”.
- **Log summary** (compact):
  ```
  [Chapters] Snap result: moved=X, on_kf=Y, too_far=Z (kfs=..., mode=..., thr=...ms)
  ```
- Full per-chapter spam is disabled by default (can be re-enabled for debugging).

> Note: This is optional because some releases prefer untouched chapter times exactly from source.

---

## Tracks: ordering, language, defaults, compression
- **Ordering**
  - We keep deterministic group order: **Reference** → **Secondary** → **Tertiary**.
  - Within groups, order is the demuxed stream order unless user swap options are enabled.
  - **English audio first** in final order when present.

- **Language tags**
  - Carried through from source when available; can be supplemented by heuristics (e.g., “jpn” matching on secondary/tertiary by filename hints).
  - The GUI shows and propagates the language for video, audio, and subtitles.

- **Default track flags**
  - **Audio**: only the **first audio** in final order gets `--default-track-flag yes` (unless user toggles a different rule).
  - **Subtitles**:
    - Optional: “**first sub in final order default**”.
    - **“Signs / Songs”** track: if detected, can be made default per rule (so signs are on by default).
    - If there’s **no English audio**, we mark the **first subtitle** default to aid accessibility.

- **Compression**
  - `--compression 0:none` on **every track** (video/audio/subs) **except attachments**.
  - Attachments don’t support/need compression flags.

- **Dialog normalization (optional)**
  - If enabled, `--remove-dialog-normalization-gain` is applied to supported audio tracks **via the option file** (off by default).

---

## Attachments (fonts)
- All font attachments from sources are collected and re-attached.
- Filenames are preserved; non-ASCII safe paths handled.
- **No** compression flags are applied to attachments.

---

## mkvmerge options file format
We write a **JSON option file** that mkvmerge accepts via `@/path/to/opts.json`.  
**Format**: a **JSON array of command-line tokens** (exact argv), not a structured object.

Example (abridged “pretty” view we log):
```
--output /path/out.mkv
--chapters /path/chapters_mod.xml
( /path/ref_video.avc ) --language 0:eng --default-track-flag 0:no --compression 0:none
( /path/sec_audio.truehd ) --language 0:eng --sync 0:84 --default-track-flag 0:yes --compression 0:none
( /path/ter_subs.ass ) --language 0:eng --track-name 0:Signs / Songs --default-track-flag 0:no --compression 0:none
--attach-file /path/font0.ttf
--attach-file /path/font1.ttf
```

We produce two files per job:
- `opts.json` — the actual **token array** consumed by mkvmerge.
- `opts.pretty.txt` — line-wrapped human summary (what you’ll see in logs if you enable the dump flags).

This solves:
- Over-long shell commands,
- Quoting/escaping issues,
- The “flag looked like a file” failure mode (we validated tokenization thoroughly).

---

## Temporary/output layout & naming
Per job we create:  
`<temp_root>/job_<N>_<epoch>/`
- `ref_track_...` / `sec_track_...` / `ter_track_...` — demuxed streams (extensions match codecs; no symlinks).
- `*_chapters.xml`, `*_chapters_mod.xml` — raw/shifted/snap-processed chapters.
- `att_*.ttf` — attachments written with stable numbering.
- `opts.json`, `opts.pretty.txt` — mkvmerge options.
- Any analysis intermediates (e.g., extracted WAV for XCorr) live here.

Outputs:
- Final MKV: `<output_folder>/<index>.mkv`
- Job log: `<output_folder>/<index>.log`

---

## Logging & settings
**Compact by default**:
- Log only `$ command`, throttled `Progress: N%`, and small tails on error.
- Chapter snap prints a single summary line.
- Option dumps are **off** unless explicitly enabled.

**Autoscroll**: Log window follows new lines when enabled.

### Controlling verbosity (in `settings_gui.json`)
```json
{
  "log_compact": true,
  "log_progress_step": 100,
  "log_tail_lines": 0,
  "log_error_tail": 20,
  "log_show_options_pretty": false,
  "log_show_options_json": false,
  "log_autoscroll": true
}
```

> The app **merges** `settings_gui.json` with in-code defaults at startup and rewrites the file if keys are missing. The **Load Settings** button re-applies the file to the UI safely.

---

## GUI layout & controls

### Inputs
- **Reference**, **Secondary**, **Tertiary** file pickers (video containers).
- Read-only inferred details (languages, streams) are shown when available.

### Menus
- **Storage**
  - **Temp root** (default: `{script_dir}/temp_work/`), auto-created if unset.
  - **Output folder** (persistent).
- **Analysis Settings**
  - **Mode**: Audio XCorr / VideoDiff.
  - **XCorr**:
    - Chunk (sec)
    - Minimum match (%)
  - **VideoDiff**:
    - Path to binary
    - Max error (reject if > threshold)
- **Global**
  - **Rename chapters** to `Chapter NN`.
  - **Snap chapters** (Off / Starts / Starts+Ends) + tolerance (ms).
  - **First sub default** (toggle).
  - **Signs / Songs default** (toggle).
  - **Remove dialog normalization gain** (toggle).
  - **Swap subtitle order** / language match hints (e.g., `jpn` on secondary/tertiary).
  - **Logging options** (checkboxes for autoscroll/compact, optional dumps).

### Action buttons
- **Analyze** — run the chosen analysis only.
- **Analyze & Merge** — full pipeline with positive-only delay plan.

---

## Configuration file reference
Located next to the script: `settings_gui.json` (auto-created/updated).

Common keys (non-exhaustive):
```json
{
  "temp_root": "/path/to/temp_work",
  "output_folder": "/path/to/Output",
  "workflow": "analyze_only | analyze_merge",
  "analysis_mode": "xcorr | videodiff",

  "xcorr_chunk_sec": 8,
  "xcorr_min_match_pct": 75,

  "videodiff_path": "/usr/local/bin/videodiff",
  "videodiff_max_error": 50,

  "rename_chapters": true,
  "snap_chapters": true,
  "snap_mode": "starts|both",
  "snap_tolerance_ms": 250,

  "first_sub_default": true,
  "signs_sub_default": true,

  "apply_dialog_norm_gain": false,

  "log_compact": true,
  "log_progress_step": 100,
  "log_tail_lines": 0,
  "log_error_tail": 20,
  "log_show_options_pretty": false,
  "log_show_options_json": false,
  "log_autoscroll": true
}
```

> Any missing keys are filled from defaults at app start and written back.

---

## Dependencies
- **Python 3.9+** (user tested on 3.13)
- **DearPyGui 2.1.0**
- **MKVToolNix** (`mkvmerge`, `mkvextract`)
- **FFmpeg/ffprobe** (for keyframe & analysis helpers)
- **VideoDiff** (external) if using that analysis mode

Make sure the binaries are in `PATH` or set explicit paths in settings where applicable.

---

## Known limitations / notes
- **MediaInfo “frame rate” on audio**: It’s container framing math (e.g., 1600/1920 samples per frame), **not** a change to the audio sample rate or bitstream. Our pipeline demuxes and remuxes **bit-for-bit**.
- **MediaInfo duplicate “Delay” lines**: different granularities/aliases of the same timing; the authoritative values are the ones we compute & feed into mkvmerge.
- **Precision**: We standardize offsets to **ms**. mkvmerge can accept higher precision in some contexts, but cross-tool consistency & determinism are the priority.
- **Chapter snapping**: optional; if most points are already near keyframes, moving only a few is expected. We log **moved / on_kf / too_far** counts.

---

## Versioning
- Starting point: **v1.0** (this baseline).
- We’ll bump by **+0.01 per change** (1.01, 1.02, …).
- Keep `CHANGELOG.md` updated alongside code.

---

### Why we do things this way (design notes)

- **Positive-only delays**: Negative delays **truncate** early samples. By shifting the global start forward so the earliest stream is at 0 ms, we keep **all data** and maintain perfect sync by adding silence where needed.
- **JSON token option files**: Long, complex merges are brittle on shell lines (quoting, spaces, UTF-8). The JSON argv format is **exactly** what mkvmerge consumes internally and avoids the “flag interpreted as file” class of bugs.
- **Compression disabled**: Some players behave better and we avoid “smart” muxer defaults altering payload; attachments don’t support compression flags anyway.
- **Chapter snapping**: Purely for seek ergonomics; optional because some releases want untouched chapter boundaries.
