# Video/Audio Sync & Merge (PySide6) — Deep Technical Documentation

> **Repository root:** `wingedonezero-video-sync-gui/`  
> **Edition:** Manual-Selection + Analysis-first pipeline, no legacy auto-merge plan  
> **Primary targets:** Windows / Linux (macOS workable with matching toolchain)  
> **License:** (fill in for your repo)

This document is intentionally **exhaustive**. It explains *what each module does*, *how the pipeline flows*, the *math behind analysis*, *mkvmerge tokenization*, the *UI behaviors/guardrails*, and the *exact configuration knobs*. It is written so that another developer or another AI can fully understand and extend the system safely.

---

## 0) TL;DR architecture

```
[Qt UI]
  ├─ MainWindow (inputs, settings, run)
  ├─ ManualSelectionDialog (pick tracks; per-track options)
  └─ OptionsDialog (persisted settings)

[Worker thread]
  └─ JobWorker (runs jobs in background; emits log/progress/status)

[Core]
  ├─ JobPipeline (orchestrates analysis → extraction → subtitle transforms → mkvmerge)
  ├─ analysis.py (Audio cross-correlation or VideoDiff wrapper)
  ├─ mkv_utils.py (track discovery/extraction, attachments, chapters processing + snapping)
  ├─ subtitle_utils.py (SRT→ASS, ASS/SSA rescale, font-size multiplier)
  ├─ job_discovery.py (single file vs. batch discovery)
  ├─ config.py (defaults + persistence)
  └─ process.py (CommandRunner: runs external tools, streamed logging)
```

**Key design choices:**

- **Manual layout is the only merge strategy.** There is no legacy “merge plan” inference. You explicitly pick the tracks and their per‑track options.  
- **Analysis-first**: We compute secondary/tertiary delays **before** extraction/merge. A global non‑destructive shift eliminates negative offsets.
- **Safety guardrails**:  
  - UI disables **SEC/TER video** from being added (REF video only).  
  - Exactly one **Default** per type (audio / subtitles); at most one **Forced** subtitles.  
  - SRT→ASS toggle is only enabled for actual SRT inputs.
- **Copy layout (“Auto‑apply”)**: The previous layout is auto‑applied to subsequent files **only when the track signature matches** (non‑strict or strict). No on-disk persistence—applies within the current batch session.

---

## 1) Directory layout

```
wingedonezero-video-sync-gui/
├── main.py                                # Qt entry point
├── vsg_core/
│   ├── __init__.py
│   ├── analysis.py                        # Audio correlation + VideoDiff
│   ├── config.py                          # AppConfig with defaults + persistence
│   ├── job_discovery.py                   # Single file or batch (dir) discovery
│   ├── mkv_utils.py                       # mkvmerge/ffprobe helpers; chapters
│   ├── pipeline.py                        # JobPipeline orchestration
│   ├── process.py                         # CommandRunner process wrapper
│   └── subtitle_utils.py                  # SRT→ASS, rescale, font scaling
└── vsg_qt/
    ├── __init__.py
    ├── main_window.py                     # Main UI: inputs, run, log, options
    ├── manual_selection_dialog.py         # Track picker + per-track “Settings…”
    ├── options_dialog.py                  # Settings tabs
    ├── track_settings_dialog.py           # (popup editor; mirrors TrackWidget menu)
    ├── track_widget.py                    # Per-track inline UI widget
    └── worker.py                          # QRunnable and signals
```

---

## 2) External toolchain & Python deps

### Tools (must be in PATH unless overridden)
- **ffmpeg / ffprobe** (recent; audio extraction, subtitle conversion, video probe)
- **MKVToolNix**: `mkvmerge`, `mkvextract` (track/attachment extraction & final mux)
- **videodiff** *(optional)*: for VideoDiff analysis mode

### Python
- `PySide6` (Qt UI)
- `numpy`, `scipy`, `librosa` (audio correlation)
- Standard library only elsewhere

**Version guidance:** recent stable versions of ffmpeg/MKVToolNix recommended. `librosa` should be reasonably up-to-date to avoid audio I/O quirks.

---

## 3) Configuration (`vsg_core/config.py`)

`AppConfig` loads/saves `settings.json` at repo root and guarantees required folders exist.

### Defaults snapshot

```jsonc
{
  "last_ref_path": "",
  "last_sec_path": "",
  "last_ter_path": "",
  "output_folder": "<repo>/sync_output",
  "temp_root": "<repo>/temp_work",
  "videodiff_path": "",
  "analysis_mode": "Audio Correlation",
  "analysis_lang_ref": "",
  "analysis_lang_sec": "",
  "analysis_lang_ter": "",
  "scan_chunk_count": 10,
  "scan_chunk_duration": 15,
  "min_match_pct": 5.0,
  "videodiff_error_min": 0.0,
  "videodiff_error_max": 100.0,
  "rename_chapters": false,
  "apply_dialog_norm_gain": false,
  "snap_chapters": false,
  "snap_mode": "previous",
  "snap_threshold_ms": 250,
  "snap_starts_only": true,
  "log_compact": true,
  "log_autoscroll": true,
  "log_error_tail": 20,
  "log_tail_lines": 0,
  "log_progress_step": 20,
  "log_show_options_pretty": false,
  "log_show_options_json": false,
  "disable_track_statistics_tags": false,
  "archive_logs": true,
  "auto_apply_strict": false
}
```

**Folders created:** `output_folder`, `temp_root`

All settings are surfaced in **OptionsDialog** except historical debug toggles that are log-only.

---

## 4) Job discovery (`vsg_core/job_discovery.py`)

### Modes
- **Single-file mode**: `ref` must be a file. `sec`/`ter` may be files (optional).  
  → One job: `{ref, sec?, ter?}`

- **Batch mode**: `ref` is a directory. `sec`/`ter` must be directories or empty.  
  → For each `*.mkv|*.mp4|*.m4v` in `ref`, we form a job only if a same‑named file exists in `sec` and/or `ter` directories.  
  → Jobs like `{ref: ".../A.mkv", sec: ".../A.mkv", ter: ".../A.mkv"}`

**Notes:** No errors if zero matches; UI reports “No Jobs Found”.

---

## 5) UI: Main window (`vsg_qt/main_window.py`)

### Key surfaces
- **Inputs**: Reference / Secondary / Tertiary (file or directory).  
- **Manual Selection Behavior**:  
  - *Auto-apply this layout…* (copy previous layout)  
  - *Strict match (type + lang + codec)* for signatures
- **Actions**: “Analyze Only”, “Analyze & Merge”
- **Status/Progress**: per-job + overall
- **Results**: last job’s Secondary/Tertiary delays
- **Log**: streaming, monospace; autoscroll

### Auto-apply (“Copy layout”) — how it works

We compute a **track signature** for the current file set:

- **Non‑strict**: multiset of `"{SOURCE}_{TYPE}"` (e.g., `REF_video`, `SEC_audio`, `TER_subtitles`, …).  
- **Strict**: multiset of `"{SOURCE}_{TYPE}_{lang}_{codec_id}"` (lang lowercased; codec_id lowercased).

If the new signature matches the previous job’s signature, we **materialize** the previous layout by *order within (source,type)*. Example:

- Previous layout chose: first `REF_video`, second `SEC_audio`, first `SEC_subtitles`, …  
- Current file has 1 REF video, 2 SEC audios, 2 SEC subs → we map by positional order per (source,type).

> **Safety:** The previous layout is stored **in memory only**, stripped to an *abstract template* (no track IDs, no filenames): `{source, type, is_default, is_forced_display, apply_track_name, convert_to_ass, rescale, size_multiplier}`. This prevents cross‑file ID leakage.

If signatures differ, we open the **ManualSelectionDialog** (see §6).

### Batch + archiving

- For batch runs, output folder is `output_folder/<ref_dir_name>`.
- If **Archive logs** is checked, all `*.log` files in the batch output directory are zipped into `<ref_dir_name>.zip` and individual `.log` files are removed.

---

## 6) Manual track selection dialog (`vsg_qt/manual_selection_dialog.py`)

### Layout

- **Left**: a single scroll column containing three groups in order: **Reference Tracks**, **Secondary Tracks**, **Tertiary Tracks**. Each group is a `QListWidget` with one item per track. Items show compact info:

  ```
  [A-2] A_EAC3 (eng) '5.1'
  [S-3] S_TEXT/UTF8 (eng) 'Closed Captions'
  [V-0] V_MPEG4/ISO/AVC (und) 'Main video'
  ```

  (`A|S|V` = Audio|Subs|Video, the number is the mkvmerge `id`, language and track name included.)

- **Right**: **Final Output (Drag to reorder)** — the list you build by double‑clicking or drag‑dropping from the left.

### Guardrails enforced in UI

- **No Secondary/Tertiary video**: SEC/TER video items are greyed out and not draggable/selectable. Only **REF** video can appear in output.  
  Rationale: avoid accidental replacement of reference video; multiple video streams are not supported in current mux logic.

- **Exactly one Default per type**: If you mark a different audio/subs item as Default, any previous Default of the same type is automatically cleared.

- **At most one Forced subtitles**: If you set a second “Forced”, the older one is cleared.

- **SRT→ASS toggle only for SRT**: The “Convert SRT → ASS” option is enabled only when `codec_id` is `S_TEXT/UTF8`.

### Per-track options (visible via **Settings…** button on each chosen output item)

The menu mirrors hidden state controls used by the pipeline:

- **Default** (all types)
- **(Subs)** Forced display
- **(Subs)** Convert SRT → ASS
- **(Subs)** Rescale to video resolution (sets `PlayResX/Y` to match the REF video)
- **(Subs)** Size multiplier (0.1× … 5.0×). Implemented as style `Fontsize` multiplier in ASS/SSA (see §9).
- **Keep original track name**

All toggles update the item’s **badges** and **summary** line in real time:

- ⭐ Default, 📌 Forced, 📏 Rescale, 🔤 Size≠1.0×, “Convert to ASS”, “Keep Name”

### Keyboard helpers

- `Ctrl+Up/Down`: move selected item
- `Ctrl+D`: make Default for this type
- `Ctrl+F`: toggle Forced (subs only)
- `Del`: remove item

### Accepting the dialog

We **normalize** the final list before returning:

- Enforce one Default (audio) and one Default (subs) if missing; clear extras.
- Enforce at most one Forced (subs).

The dialog returns a `manual_layout` list with merged **track data + options**, e.g.:

```json
{
  "source": "SEC",
  "id": 2,
  "type": "audio",
  "codec_id": "A_EAC3",
  "lang": "eng",
  "name": "5.1",
  "path": null,                  // filled later by extraction
  "is_default": true,
  "is_forced_display": false,
  "apply_track_name": true,
  "convert_to_ass": false,
  "rescale": false,
  "size_multiplier": 1.0
}
```

The **ID** is the mkvmerge `id` in the *source container*, *not* the index within our final list.

---

## 7) Worker threading (`vsg_qt/worker.py`)

`JobWorker` runs on a `QThreadPool`:

- Emits:
  - **log** (string): streamed lines from the pipeline/commands
  - **progress** (float 0..1): coarse phase progress
  - **status** (string): user‑friendly status per job
  - **finished_job** (dict): result `{status, name, delay_sec, delay_ter, output?}`
  - **finished_all** (list): all job results

No UI blocking while analysis/extraction/muxing run.

---

## 8) Pipeline (`vsg_core/pipeline.py`)

### Overview

A **Job** is `{ref, sec?, ter?, manual_layout?}`. The pipeline runs:

1. **Tool discovery** — `ffmpeg`, `ffprobe`, `mkvmerge`, `mkvextract` (*required*), `videodiff` (*optional unless mode=VideoDiff*).
2. **Analysis phase** — compute delays vs. REF for sec/ter using selected **Analysis Mode**.
3. **(If Analyze Only)** — stop and return delays.
4. **(If Merge)** —
   - Compute **global shift** to eliminate negative offsets.
   - **Extract** the exact tracks from the manual layout.
   - **Subtitle transforms** (convert SRT→ASS, rescale, font size multiply).
   - Extract **attachments** (from TER) and **process chapters** (from REF).
   - **Build mkvmerge tokens** and run mux.
   - Write a per‑job `.log` file under the output directory.

Each job runs in a unique `temp_work/job_<stem>_<epoch>/` which is removed on success.

### Detailed phases

#### 8.1 Analysis (`_run_analysis`)

- **Modes**:
  - **Audio Correlation**: chunked cross‑correlation (see §10).  
  - **VideoDiff**: delegate to external tool; we parse `[Result]` line with either `itsoffset:` or `ss:` and an **error metric**. `ss` values are inverted (semantics differ). We require `error` to be within `[videodiff_error_min, videodiff_error_max]`.

- **Language pinning** (optional): You can request a specific language code for REF/SEC/TER analysis audio. We probe `mkvmerge -J` and choose the first audio track matching the language, or the first audio if no exact match.

- **Outputs**: `delay_sec` and/or `delay_ter` in **milliseconds** (may be negative).

##### 8.1.1 Global shift

We gather present delays `{0 (REF), delay_sec?, delay_ter?}` and compute:

```
min_delay = min(present_delays)
global_shift = -min_delay if min_delay < 0 else 0
```

This ensures no track ends up with a negative `--sync` offset.

**Example**:
- REF=0 ms, SEC = -200 ms, TER = +350 ms  
- `min_delay = -200`, so `global_shift = +200`  
- Effective per‑track sync (mkvmerge `--sync`):
  - REF: +200
  - SEC: -200 + 200 = 0
  - TER: +350 + 200 = 550

We also shift **chapters** by `+global_shift` (see §12) to keep chapter starts aligned with the shifted timeline.

#### 8.2 Extraction (`mkv_utils.extract_tracks`)

Given the manual layout (with **mkvmerge track IDs** per source), we extract only those tracks. Extraction rules:

- Non‑PCM **A_MS/ACM** edge-case is handled:
  1. Attempt `ffmpeg -c:a copy` to a `.wav` container (fast path). If the decoder refuses stream copy,  
  2. **Fallback** to PCM encode with the **best PCM depth** inferred from `audio_bits_per_sample`:
     - `>=64 → pcm_f64le`, `>=32 → pcm_s32le`, `>=24 → pcm_s24le`, else `pcm_s16le`.

- **Other codecs**: We use `mkvextract tracks` for subs/video/audio. Output extension is derived from codec id; unknowns use a neutral extension.

Each extracted track gets a record:

```json
{
  "id": 3,
  "type": "subtitles",
  "lang": "eng",
  "name": "Closed Captions",
  "codec_id": "S_TEXT/UTF8",
  "source": "SEC",
  "path": "/temp/job_X/SEC_track_<stem>_3.srt"
}
```

We form a map `{SOURCE}_{id} → record` to later attach per‑track options from the manual layout.

#### 8.3 Plan building (`_build_plan_from_manual_layout`)

We merge the **extracted record** with the **UI options** (rule):

- `is_default`, `is_forced_display`, `apply_track_name`
- Subtitle-only: `convert_to_ass`, `rescale`, `size_multiplier`

#### 8.4 Subtitle transforms (`vsg_core/subtitle_utils.py`)

For each plan item of type **subtitles**:
- **Convert SRT→ASS** (ffmpeg) if requested (and only for SRT). Path is updated to the `.ass` file.
- **Rescale** ASS/SSA to REF video resolution: we probe REF via `ffprobe` and rewrite `PlayResX/PlayResY`. If the subtitle lacks PlayRes tags, we log and skip.
- **Size multiplier**: see §9 for robust parsing and rewrite of `Style: ... ,Fontsize, ...` lines.

#### 8.5 Attachments & chapters (`mkv_utils.extract_attachments`, `process_chapters`)

- **Attachments** (fonts, etc.) are extracted **from Tertiary** (if present) and added to the final mux via `--attach-file` (you can attach any set; this code uses TER by convention).

- **Chapters** are extracted from **Reference** and processed:
  - Optional **rename** to “Chapter NN”.
  - **Shift** all timestamps by `+global_shift` (if any).
  - Optional **snap to keyframes** (see §12.2).
  - **Normalize** end times to be ≥ start and not overlap the next chapter (see §12.3).
  - Output to `*_chapters_modified.xml` and pass to mkvmerge via `--chapters`.

#### 8.6 mkvmerge tokenization (`_build_mkvmerge_tokens`)

We generate a JSON options file that mkvmerge reads as `@opts.json`. For **each track** in the final order:

- `--language 0:<lang>`  
- `--track-name 0:<name>` *(if “Keep Name”)*  
- `--sync 0:<delay_ms>` where `<delay_ms> = global_shift + (secondary_ms|tertiary_ms)` or just `global_shift` for REF
- `--default-track-flag 0:(yes|no)` per **Default** rules (first REF video OR selected audio/subs)
- `--forced-display-flag 0:yes` (subs only, if “Forced”)
- `--compression 0:none`
- (Optional) `--remove-dialog-normalization-gain 0` for AC3/E‑AC3 if enabled in settings
- Wrap the source with parentheses: `( <extracted_path> )`

Track order is explicit via `--track-order "0:0,1:0,2:0,..."` where indices are positional across our list.

**Global flags**:
- `--chapters <modified.xml>` (if produced)
- `--disable-track-statistics-tags` (if enabled)
- `--attach-file <path>` for each attachment

We then write tokens as JSON to `temp/job_X/opts.json` (and an optional “pretty view” with one token per line) and run:

```
mkvmerge @/abs/path/to/opts.json
```

On success we log `Output file created: <output_dir>/<ref_filename>`.

---

## 9) Subtitle style scaling details (`subtitle_utils.py`)

### 9.1 Convert SRT → ASS
- Implemented with `ffmpeg -i in.srt out.ass`.  
- If `out.ass` fails to materialize, we keep original `.srt` and log a warning.

### 9.2 Rescale to video resolution
- We probe REF video width/height with `ffprobe`, then rewrite `PlayResX:` and `PlayResY:` exact values within the ASS/SSA header.  
- If `PlayResX/Y` tags are absent, we log “no tags” and skip (we do not inject a brand-new header to avoid header corruption).

### 9.3 Font size multiplier
We read the ASS/SSA file (`utf-8-sig` to absorb BOM if any), then **line-by-line** transform:

- Lines beginning with `Style:` have CSV fields; the 3rd numeric field is **Fontsize**.
- We multiply that value and recompose the line, preserving all other fields.  
- This avoids brittle regexes that can corrupt styles or comments.

**Edge cases**:
- If no `Style:` lines are found, we log a warning and do nothing.
- We round to nearest integer to avoid fractional sizes that some renderers treat oddly.

---

## 10) Audio correlation math (`vsg_core/analysis.py`)

We compute **delay** of `target` vs `reference` using **normalized cross‑correlation** on several short chunks (default: 10 chunks × 15s).

### Steps per chunk
1. **Extract** mono 48 kHz WAV from each source with `ffmpeg` (`-ac 1 -ar 48000`). We pick specific audio streams by language if requested; otherwise first audio.  
2. **Load** with librosa (no resample; `sr=None`, mono already ensured).  
3. **Normalize** both chunks to zero mean and unit variance:
   \[ x' = \frac{x - \mu_x}{\sigma_x + \epsilon} \]
4. **Correlate** (scipy.signal.correlate, `mode='full'`):
   - Find `lag_samples = argmax(corr) - (len(sec) - 1)`
   - Convert to seconds: `lag_s = lag_samples / sample_rate`  
   - Convert to ms: `delay_ms = round(lag_s * 1000)`
5. **Match %**: peak correlation normalized by energy:
   \[ \text{match}(\%) = \frac{\max |corr|}{\sqrt{\sum x^2 \sum y^2} + \epsilon} \times 100 \]

### Choosing the “best” delay (`_best_from_results`)
- Filter out low‑confidence chunks: `match > min_match_pct` (default 5%).
- Tally the most frequent **delay_ms** among valid chunks.
- Among chunks with that winning delay, pick the one with highest **match %**.

We prefer **consistency across time** plus **strength** over a single high peak that might be spurious.

---

## 11) VideoDiff mode (`analysis.run_videodiff`)

- We run the `videodiff` executable (from `videodiff_path` setting or PATH) as:
  ```
  videodiff <ref> <target>
  ```
- We scan lines backwards for the last `[Result]` line and parse either:
  - `itsoffset: ±X.XXXs error: Y.YY` → `delay_ms = round(seconds * 1000)`
  - `ss: ±X.XXXs error: Y.YY` → same but **inverted** (`ss` semantics differ), so `delay_ms = -round(seconds * 1000)`
- We log the result and **reject** if `error` is outside `[videodiff_error_min, videodiff_error_max]`.

---

## 12) Chapters processing (`mkv_utils.process_chapters`)

### 12.1 Shift & rename

- Extract chapters XML from **REF** via `mkvextract chapters -`.  
- Optional **rename** to “Chapter NN” by rewriting all `ChapterDisplay` nodes.  
- **Shift** all `ChapterTimeStart` and `ChapterTimeEnd` nodes by `+global_shift` (if nonzero).

### 12.2 Snap to keyframes (optional)

- Probe keyframes from the **video** (`ffprobe -show_entries packet=pts_time,flags`) and collect timestamps where `flags` contain `K`.
- For each chapter timestamp to be snapped (starts only by default), we choose:
  - **Mode `previous`**: the greatest keyframe ≤ timestamp.
  - **Mode `nearest`**: the keyframe with minimal absolute distance.
- Apply only if the absolute difference ≤ `snap_threshold_ms` (default **250 ms**). Otherwise we log `too_far` and keep original.
- We track counts: `moved`, `on_kf`, `too_far` and report a concise summary.

### 12.3 Normalize end times

We ensure each chapter’s **end time** exists and:
- ≥ start + 1 ns  
- ≤ next chapter’s start (if any)

This avoids overlapping/degenerate chapter ranges.

---

## 13) Command execution & logging (`vsg_core/process.py`)

`CommandRunner.run(cmd, tool_paths)`:

- **Resolves** the first token (`cmd[0]`) against `tool_paths` override or falls back to raw name (PATH).
- **Streams** stdout+stderr (merged) line-by-line to the log callback.
- **Compact mode** (default): remembers a tail buffer instead of dumping all lines.  
  - Detects `Progress: NN%` lines and emits only on **step changes** (default every 20%).  
  - On failure, prints last **N** lines (`log_error_tail`, default 20).  
  - On success, can optionally print `log_tail_lines` lines of last stdout if configured.
- **Return**: full captured stdout on return code `0`, else `None`.

This is particularly helpful with **mkvmerge**, which emits frequent `Progress: N%` lines.

---

## 14) mkvmerge token examples

Given a final plan:
```
0: REF video (default)
1: SEC audio (default)
2: TER subtitles (forced, keep name, rescale, 1.25x)
```

With computed `global_shift=+200`, `secondary_ms=-200`, `tertiary_ms=+350`:

- REF video: `--sync 0:+200`, `--default-track-flag 0:yes`
- SEC audio: `--sync 0:0`, `--default-track-flag 0:yes`
- TER subs:  `--sync 0:+550`, `--default-track-flag 0:yes` (if it was the only subs), `--forced-display-flag 0:yes`, `--track-name 0:'Original Name'`, `--compression 0:none`

Global:
- `--chapters /path/to/<ref>_chapters_modified.xml`
- `--disable-track-statistics-tags` (if enabled)
- `--attach-file /path/to/TER_att_...ttf` (fonts, etc.)
- `--track-order "0:0,1:0,2:0"`

Tokens are written to JSON as a flat list and invoked via `mkvmerge @opts.json`.

---

## 15) UI guardrails echoed in pipeline

The UI prevents adding SEC/TER video. As an extra safety net, the pipeline prints warnings if video from non‑REF appears in the plan (shouldn’t happen) or if no REF video exists (audio‑only mux is allowed but you’ll see a log warning).

---

## 16) Result objects

Each job yields a dict like:

```json
{
  "status": "Merged",                // or "Analyzed" or "Failed"
  "output": "/.../ref_name.mkv",     // when merged
  "delay_sec": -12,                  // millis (or null)
  "delay_ter": 487,                  // millis (or null)
  "name": "ref_name.mkv"
}
```

The main window shows **Secondary Delay** and **Tertiary Delay** from the last job.

---

## 17) End-to-end recipes

### 17.1 Analyze only (find A/V delay numbers)

1. Select **Reference** and **Secondary** files. (Tertiary optional.)  
2. Click **Analyze Only**.  
3. Read **Secondary Delay** / **Tertiary Delay** in the Results panel.  
4. Use these numbers in other tools if you don’t need a merged file.

### 17.2 Single merge, hand-pick tracks

1. Select **Reference** = REF.mkv; **Secondary** = SEC.mkv; **Tertiary** = TER.mkv (optional).  
2. Click **Analyze & Merge** → Manual Selection dialog opens.  
3. From **REF**, drag the video you want (usually the only video).  
4. From **SEC/TER**, drag desired audio/subtitles.  
5. For subs: open **Settings…** and set *Default/Forced/Rescale/Size* as needed; use *Convert SRT→ASS* for SRT.  
6. Click **OK**.  
7. Pipeline runs; result at `<output_folder>/REF.mkv`.

### 17.3 Batch with “Copy layout”

1. Set **Reference** to a folder (e.g., `Show.S01/WEB`); set **Secondary/Tertiary** to parallel folders with same file names.  
2. Check **Auto‑apply this layout** (and optionally **Strict match**).  
3. Click **Analyze & Merge**.  
4. For the **first file**, the Manual Selection dialog appears—build your layout; click OK.  
5. For subsequent files with matching signature, the previous layout is **auto‑applied** silently (log will say so). For mismatches, the dialog opens again.  
6. Outputs are in `output_folder/WEB/<filename>.mkv`.  
7. When batch finishes, a zip of job logs is produced if **Archive logs** was enabled.

---

## 18) Troubleshooting & FAQs

### I only see a small “match %” in audio correlation. Is that bad?
Not necessarily. Some sources are noisy (music, effects, different mixes) so absolute numbers vary. The algorithm looks for **consistency** across chunks and then picks the **strongest** among the most frequent delay. Raise `scan_chunk_count` or chunk duration to improve confidence.

### VideoDiff error is out of bounds
Widen the allowed range in **Settings → Analysis**. Or switch to **Audio Correlation** if video content alignment is poor (e.g., different encodes).

### My SRT doesn’t rescale
Rescaling applies to **ASS/SSA** only (renderer needs PlayRes tags). Convert SRT→ASS first and then rescale.

### I can’t drag SEC video
By design. We only allow REF video in the final mux to prevent accidental video swaps.

### My A_MS/ACM audio failed to copy
We attempt stream copy; if the decoder refuses, we **encode to PCM** at a sensible bit depth. Check the log for “Stream copy refused… Falling back to pcm_…”.

### Chapters overlap after shifting
The normalizer guarantees end times won’t overlap the next start and are at least start+1ns. If you see weirdness, check the log for “[Chapters] Normalized …” messages.

---

## 19) Extending the system

- **Add fourth source**: The signature and dialog would need an extra group; pipeline would need a new delay computation and delay bucket.  
- **Per‑track filters/encoders**: Insert a processing pass between extraction and mux tokenization.  
- **Video preview & seeking**: Non‑trivial (decode in UI thread or separate preview worker); out of scope for this edition.  
- **Persist named layouts**: Current design intentionally keeps layout in memory only to avoid misapplies; you could add a saved template with an explicit file count hash or signature to mitigate danger.

---

## 20) Rationale & safety notes

- **Global shift** preserves the original relative timing while avoiding negative `--sync` values (which can be awkward in some tool flows) and aligns chapters to the new zero.  
- **UI guardrails** prevent accidental muxing mistakes that are hard to notice until playback.  
- **ASS/SSA edits** are done with minimal rewriting to avoid header damage; we **never** regenerate the entire ASS header from scratch.  
- **Compact logging** keeps logs readable while preserving essential tails on error.

---

## 21) Developer quickstart

```
python3 -m venv .venv
. .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install PySide6 numpy scipy librosa

# Ensure tools in PATH: ffmpeg, ffprobe, mkvmerge, mkvextract
python main.py
```

**Settings** → verify `Output Directory` and `Temporary Directory`. If using VideoDiff, point to its executable.

---

## 22) Known limitations

- No in-app **media preview/seek**—the focus is on analysis+merge, not manual timeline spotting.  
- Track‑level operations only—no content‑aware subtitle fixing beyond scaling/resolution.  
- Requires matching **file names** across folders for batch discovery.

---

## 23) Glossary

- **REF/SEC/TER**: Reference / Secondary / Tertiary sources.  
- **Default** (mkvmerge): Player’s preferred track of that type.  
- **Forced (subs)**: Mark track as “forced display” flag.  
- **PlayRes**: Logical render resolution in ASS/SSA styles.  
- **A_MS/ACM**: Microsoft ACM containerized audio; some variants resist stream copy.  
- **Global shift**: Non‑destructive offset applied to all tracks so no negative sync remains.  
- **Signature**: Multiset used to detect whether the previous layout can be auto‑applied to a new file.

---

## 24) Example log excerpt (annotated)

```
[12:00:01] === Starting Job: Episode.S01E01.mkv ===
[12:00:01] --- Analysis Phase ---
[12:00:01] Analyzing Secondary file (Audio Correlation)...
[12:00:02] Selected streams for analysis: REF (lang='first', index=0), SEC (lang='first', index=0)
[12:00:12] Chunk @96s -> Delay -192 ms (Match 14.22%)
...
[12:00:18] Secondary delay determined: -200 ms
[12:00:18] --- Merge Planning Phase ---
[12:00:18] [Delay] Raw delays (ms): ref=0, sec=-200, ter=350
[12:00:18] [Delay] Applying lossless global shift: +200 ms
[12:00:18] --- Extraction Phase ---
[12:00:19] Manual selection: preparing to extract 1 REF, 1 SEC, 1 TER tracks.
[12:00:19] mkvextract "..."
[12:00:19] [SubConvert] Converting subs.srt to ASS format...
[12:00:21] [Rescale] Rescaling subs.ass from 1280x720 to 1920x1080.
[12:00:21] [Font Size] Modified 1 style definition(s).
[12:00:22] Chapters XML written to: ..._chapters_modified.xml
[12:00:22] --- Merge Execution Phase ---
[12:00:22] mkvmerge @/temp/job/opts.json
[12:00:23] Progress: 20%
[12:00:24] Progress: 40%
[12:00:26] Progress: 100%
[12:00:26] [SUCCESS] Output file created: /output/Episode.S01E01.mkv
[12:00:26] === Job Finished ===
```

---

## 25) Appendix: settings → behavior matrix

| Setting | Where | Effect |
|---|---|---|
| `analysis_mode` | Options → Analysis | “Audio Correlation” or “VideoDiff” |
| `scan_chunk_count`, `scan_chunk_duration` | Options → Analysis | #chunks × seconds used by audio correlation |
| `min_match_pct` | Options → Analysis | Filters correlation chunks before voting |
| `videodiff_error_min/max` | Options → Analysis | Reject VideoDiff results outside this error band |
| `analysis_lang_ref/sec/ter` | Options → Analysis | Language pin for picking specific audio streams for analysis |
| `rename_chapters` | Options → Chapters | Renames to “Chapter NN” |
| `snap_chapters` + `snap_mode` + `snap_threshold_ms` + `snap_starts_only` | Options → Chapters | Keyframe snapping behavior |
| `apply_dialog_norm_gain` | Options → Merge Behavior | Strip dialog normalization gain for AC3/EAC3 |
| `disable_track_statistics_tags` | Options → Merge Behavior | Add mkvmerge global flag |
| `log_compact`, `log_autoscroll`, `log_progress_step`, `log_error_tail` | Options → Logging | Control UI log behavior & how much tail to show on error |
| `output_folder`, `temp_root` | Options → Storage | Where results & temp live |
| `archive_logs` | Main window | Batch: zip logs at the end |
| `auto_apply_strict` | Main window | Signature = include language + codec id |

---

## 26) Final notes

- This edition is **intentionally explicit**: the user picks tracks and options. The system then applies reproducible transforms and a transparent mux.  
- When in doubt, check the per-job `.log`. All external calls are logged with timestamps and either pretty progress or error tails.

Happy syncing and muxing! 🎬
