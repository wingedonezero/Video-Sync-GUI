# Video/Audio Sync & Merge — PySide6 Edition

A focused desktop tool to **analyze A/V timing** and perform a **lossless MKV remux** with predictable, auditable behavior.  
The app discovers delays, applies a **positive‑only global shift** (so no content gets trimmed), handles chapters and subtitles, and writes a mkvmerge options file you can inspect and replay.

> **Scope of this README**  
> This document describes the *baseline* application — the exact code you shared (before any experimental “expert/advanced repair” features). It is intentionally exhaustive so a new contributor can understand end‑to‑end behavior and implementation details.

---

## Table of Contents

- [Key Ideas](#key-ideas)
- [Architecture](#architecture)
- [Job Lifecycle](#job-lifecycle)
- [Delay Discovery Engines](#delay-discovery-engines)
  - [Audio Cross‑Correlation (deep dive)](#audio-cross-correlation-deep-dive)
  - [VideoDiff](#videodiff)
- [Positive‑Only Timing Model](#positive-only-timing-model)
- [Merge Planning](#merge-planning)
  - [Profile‑Driven (Merge Plan)](#profile-driven-merge-plan)
  - [Manual Selection](#manual-selection)
- [Subtitles](#subtitles)
- [Chapters](#chapters)
- [Attachments](#attachments)
- [mkvmerge Options File](#mkvmerge-options-file)
- [Temporary Files, Outputs, Logs](#temporary-files-outputs-logs)
- [GUI Overview](#gui-overview)
- [Configuration Reference](#configuration-reference)
- [Dependencies](#dependencies)
- [Run It](#run-it)
- [Troubleshooting](#troubleshooting)
- [Developer Notes](#developer-notes)
- [Design Invariants & Edge Cases](#design-invariants--edge-cases)
- [Performance Notes](#performance-notes)
- [Known Limitations](#known-limitations)
- [Appendix A: Log Line Guide](#appendix-a-log-line-guide)
- [Appendix B: Demux Extension Map](#appendix-b-demux-extension-map)
- [Appendix C: Configuration Keys (Table)](#appendix-c-configuration-keys-table)

---

## Key Ideas

- **Lossless by design:** the pipeline never applies negative per‑track delays that could discard leading content. We transform all timings into a **non‑negative** scheme via a global shift.
- **Deterministic & auditable:** we construct the mkvmerge command as a token array and persist it (`opts.json`). You can read, diff, and replay it.
- **Separation of concerns:** analysis, planning, extraction, subtitles, chapters, and merging are isolated but connected through explicit data structures.
- **Language‑aware analysis (optional):** reference/target audio stream selection can prefer a specific language tag (e.g., `jpn`, `eng`) to improve correlation robustness.

---

## Architecture

```
repo-root/
├─ main.py                      # App entry point
├─ vsg_core/                    # Headless engine
│  ├─ analysis.py               # Delay discovery (Audio XCorr, VideoDiff)
│  ├─ config.py                 # Settings load/save, defaults, dir creation
│  ├─ job_discovery.py          # Single-file & folder batch discovery
│  ├─ mkv_utils.py              # mkvmerge/mkvextract helpers, demux, chapters
│  ├─ pipeline.py               # Orchestration of a full job
│  ├─ process.py                # Command runner with compact logging
│  └─ subtitle_utils.py         # SRT→ASS, rescale, font-size multiply
└─ vsg_qt/                      # PySide6 GUI
   ├─ main_window.py            # Main window, file pickers, log, actions
   ├─ worker.py                 # Threaded job runner (no UI freeze)
   ├─ manual_selection_dialog.py# Drag/drop track picker + flags
   ├─ options_dialog.py         # Settings tabs & Merge Profile editor
   └─ track_widget.py           # Per-track widget with toggles
```

**Key modules**

- `vsg_core.process.CommandRunner` — canonical way to run external processes with uniform logging, progress throttling, error tails.
- `vsg_core.analysis` — two delay engines:
  - **Audio cross‑correlation** (librosa + scipy) with chunked extraction via ffmpeg.
  - **VideoDiff** integration (external tool), with error bounds.
- `vsg_core.pipeline.JobPipeline` — the orchestrator. Calls analysis, converts delays into positive‑only residuals, builds extraction + mkvmerge plans, executes merge, writes artifacts.
- `vsg_core.mkv_utils` — inspects MKVs (`mkvmerge -J`), extracts tracks (`mkvextract` + ffmpeg for special cases), processes chapters (XML), and attaches files.
- `vsg_core.subtitle_utils` — SRT→ASS conversion, ASS PlayRes rescale, font size multiplication (style‑aware, line‑by‑line safe).

---

## Job Lifecycle

Processing one *Reference* file with optional *Secondary* and *Tertiary* files:

1. **Analysis**
   - For each Secondary/Tertiary, compute delay vs Reference using selected engine.
   - Log per‑chunk results and final “determined” delay.

2. **Merge Planning**
   - Convert raw delays to a **positive‑only** scheme (see below).
   - Build a track plan:
     - **Merge Plan mode** uses the JSON‑like rule set in settings.
     - **Manual Selection** mode uses the user’s drag/drop layout.

3. **Extraction**
   - Demux only those tracks that appear in the final plan. Special handling for `A_MS/ACM` (attempt copy, else decode to PCM with correct bit depth).

4. **Subtitles (optional per track)**
   - Convert SRT→ASS, rescale PlayRes to match video, multiply text size.

5. **Chapters**
   - Optional rename to “Chapter NN”.
   - Shift all `ChapterTimeStart/End` by the **global shift**.
   - Optional **snap** starts (and optionally ends) to keyframes within a threshold.

6. **Merge Execution**
   - Create `opts.json` (mkvmerge token array) and (optionally) a pretty dump.
   - Run mkvmerge with `@opts.json`.

7. **Cleanup**
   - On success (or on analyze‑only), remove the temp job directory.
   - Logs are written next to the output MKV (or in the chosen output folder).

---

## Delay Discovery Engines

### Audio Cross‑Correlation (deep dive)

**Objective:** Estimate relative delay (ms) between the Reference audio stream and a target (Secondary/Tertiary) stream.

Even when languages differ, many mixes share music/SFX transients. By correlating short segments that avoid long silences, we locate a robust lag.

#### Stream selection (language‑aware)

- Inspect `mkvmerge -J` JSON and enumerate `tracks` of type `audio`.
- If the user provided a language code (e.g., `analysis_lang_sec="jpn"`), pick the **first audio** whose `properties.language` matches.
- Otherwise, use the **first** audio track.
- Indexes map to `ffmpeg -map 0:a:<index>` for extraction.

> For best robustness, prefer **like‑for‑like** (e.g., JPN vs JPN) when available.

#### Window extraction

For each scan point `tᵢ`, extract **mono, 48 kHz** WAV windows from both files:

```bash
ffmpeg -y -v error -ss <tᵢ> -i <file> -map 0:a:<idx> -t <dur> -vn \
       -acodec pcm_s16le -ar 48000 -ac 1 <out.wav>
```

- Default duration `dur` = **15s** (configurable).
- Conservative logging: the exact command line is mirrored to the GUI log.

#### Scan schedule

- Determine program duration `D` from `ffprobe` (format duration).
- Defaults:
  - `scan_chunk_count = 10`
  - `scan_chunk_duration = 15`
  - We analyze a band `[0.10*D, 0.90*D)` and distribute windows evenly (skip early logos and late credits to avoid silence).

This balances robustness with I/O/runtime.

#### DSP steps

We load WAVs (mono) with librosa, preserving native rate (48 kHz). Then normalize to z‑scores to remove gain bias:

```python
x = (x - mean(x)) / (std(x) + 1e-9)
y = (y - mean(y)) / (std(y) + 1e-9)
```

Compute **full discrete cross‑correlation** (scipy), then find the peak lag:

```python
c = correlate(x, y, mode='full', method='auto')
k* = argmax(c) - (len(y) - 1)     # lag in samples (y vs x)
τ  = k* / fs                       # seconds
delay_ms = round(1000 * τ)
```

We also compute a **match/confidence** heuristic:

```python
norm = sqrt( sum(x^2) * sum(y^2) )
match_pct = 100 * (max(|c|) / (norm + 1e-9))
```

This is a normalized peak height — higher is “sharper” alignment. It is not a probability.

##### Pre‑whitening / DC removal

The z‑score step behaves like a simple pre‑whitening/normalization, reducing the impact of level shifts and DC offsets so that edge energy (transients) drives the peak.

##### Windowing considerations

- 15s windows capture multiple transients; longer windows (20–30s) increase robustness at the cost of time.  
- If matches are weak, increase duration or adjust language selection.

#### Aggregating results across windows

1. Drop windows with `match_pct <= min_match_pct` (default **5.0**).  
2. Compute the **mode** (most frequent) delay among remaining windows.  
3. From the modal group, pick the window with **max match %**. That tuple `(delay_ms, match%)` is the **determined** delay.

This favors **consistency** over any single window’s outlier result.

#### Practical tuning

| Symptom | What to try |
|---|---|
| Low match% overall | Increase `scan_chunk_duration` to 20–30s; ensure language selection compares similar mixes (e.g., JPN vs JPN). |
| Two clusters of delays | Baseline uses one global delay; confirm with **Analyze Only** and consider whether underlying media truly has a splice (outside baseline scope). |
| Slow analysis | Reduce `scan_chunk_count`; shrink scan band if needed. |

---

### VideoDiff

If `analysis_mode="VideoDiff"`:

- Execute external `videodiff` with `(ref, target)` and parse the last `[Result]` line.
- Extract either `ss:` or `itsoffset:` seconds and `error:` value.
- If kind is `ss`, invert sign for our delay semantics.
- Enforce that `error ∈ [videodiff_error_min, videodiff_error_max]`; otherwise reject result.

Use this when audio mixes are too divergent for correlation (e.g., commentary tracks).

---

## Positive‑Only Timing Model

**Problem:** `mkvmerge --sync` with negative values can drop leading content.

**Solution:** Convert raw delays to **non‑negative residuals** by applying a global shift equal to the absolute most negative delay.

Let raw delays (ms) be:
```
ref = 0
sec = -1001
ter = -1000
```

1. **Global shift**: `global_shift = -min(ref, sec, ter) = 1001`
2. **Residuals**:
   - `ref_resid = ref + global_shift = 1001`
   - `sec_resid = sec + global_shift = 0`
   - `ter_resid = ter + global_shift = 1`
3. **Merge sync flags** (per input group): `--sync 0:<residual_ms>`
4. **Chapters**: shift all timestamps by `+global_shift` so chapters align with delayed streams.

This guarantees that **no input** is asked to start before t=0 in mkvmerge, eliminating trimming.

---

## Merge Planning

After delays are converted, the planner builds a final list of **(track, flags)** entries and a `--track-order` to match GUI order.

### Profile‑Driven (Merge Plan)

A prioritized list of rules (Settings → Merge Plan) defines what to include. Each rule:

- `source`: `REF` | `SEC` | `TER`
- `type`: `Video` | `Audio` | `Subtitles`
- `lang`: CSV or `any` (match against `properties.language`)
- `exclude_langs`: CSV (omit these even if `lang=any`)
- `enabled`: bool
- `is_default`: bool (first match of this type becomes the default track)
- `is_forced_display`: bool (subs)
- `swap_first_two`: bool (subs; swap first two matches)
- `apply_track_name`: bool (pass the input’s `track_name` to output)
- `rescale`: bool (ASS/SSA only; rewrite PlayRes to video)

**Global codec exclusions** (`exclude_codecs`) filter *all* matches whose codec id contains any excluded token (e.g., `ac3`, `dts`, `pcm`).

**Default logic**

- The **first video** is implicitly default.  
- Exactly one **audio** and one **subtitles** track can be marked default via flags.

**Per‑track mkvmerge arguments** (generated in order):

```
--language 0:<lang>
--track-name 0:<name>                 # if apply_track_name and input had a name
--sync 0:<global_shift + role_residual>
--default-track-flag 0:<yes/no>
--forced-display-flag 0:yes           # if is_forced_display
--compression 0:none
--remove-dialog-normalization-gain 0  # if enabled and codec is AC3/E-AC3
( <extracted-file-path> )
```

Finally we add attachments (if any) and `--track-order <inputIdx0>:0,<inputIdx1>:0,...`.

### Manual Selection

Instead of rules, the user drags tracks into **Final Output**:

- Reorder entries to match desired output.
- Per‑entry toggles: Default (A/V/S), Forced (subs), Keep Name, Convert to ASS (SRT), Rescale (ASS/SSA), Size Multiplier (subs).

**Batch auto‑apply:** If enabled, and the **shape signature** (counts of [source × type]) of the next file matches the previous, automatically carry over the layout.

All subsequent stages (extraction, chapters, merge) are identical to the rule‑based plan.

---

## Subtitles

- **SRT → ASS** (optional): via ffmpeg; if output exists, we replace the path.  
- **Rescale PlayRes** (ASS/SSA only): probe reference video width/height via ffprobe and rewrite `PlayResX/PlayResY` if they differ.  
- **Font size multiplier** (ASS/SSA only): parse `Style:` lines and multiply the font size value, keeping other fields intact. Safe parsing avoids corrupting the file.

---

## Chapters

- **Rename** (optional): clear `ChapterDisplay` and write “Chapter NN”.  
- **Shift timestamps**: add `global_shift` (ms → ns) to both `ChapterTimeStart` and `ChapterTimeEnd`.  
- **Snap to keyframes** (optional): probe keyframes via ffprobe and, for starts (and optionally ends), move within `snap_threshold_ms` according to mode (`previous` or `nearest`).  
- **Normalize ends**: ensure each chapter has a valid end; cap ends to next chapter’s start; guarantee strictly increasing intervals.

All chapter edits are written to a temporary XML file and passed to mkvmerge via `--chapters`.

---

## Attachments

If the Tertiary file contains attachments (fonts, images), we extract and `--attach-file` them to the output. These are input‑agnostic artifacts and do not interact with sync timing.

---

## mkvmerge Options File

We emit tokens as JSON (`opts.json`) and run:

```
mkvmerge @<opts.json>
```

Optionally we also write a pretty text dump (`opts.pretty.txt`) for human inspection:

```
--output "<out.mkv>" \
  --chapters "<chapters.xml>" \
  --language 0:jpn --sync 0:1001 --default-track-flag 0:yes --compression 0:none ( "<ref_video.h264>" ) \
  ...
```

This makes the merge **reproducible** and easy to debug.

---

## Temporary Files, Outputs, Logs

Each job creates a unique temp dir: `temp_root/job_<ref-stem>_<epoch>/` with:

- `ref_track_*`, `sec_track_*`, `ter_track_*`: demuxed streams
- `_chapters_modified.xml`: edited chapters
- `opts.json` (+ optional `opts.pretty.txt`): mkvmerge args
- `wav_*`: short analysis windows for audio correlation
- `att_*`: attachments from TER if present

**Output:** `<output_folder>/<ReferenceFileName>.mkv` (same filename as Reference)  
**Run log:** `<output_folder>/<ReferenceFileName>.log`

Compact logging shows *throttled* progress and prints the tail of stderr on error for signal‑to‑noise.

---

## GUI Overview

- **Inputs**: Reference, Secondary, Tertiary (files or directories).
- **Modes**:
  - **Merge Plan** (profile rules)
  - **Manual Selection** (drag/drop final list; optional auto‑apply across batch)
- **Actions**:
  - **Analyze Only** → Compute and display delays (no merge).
  - **Analyze & Merge** → Full pipeline.
- **Settings Tabs**:
  - Storage: output folder, temp root, optional VideoDiff path
  - Analysis: engine choice, chunk count/duration, min match %, VideoDiff error bounds, language prefs (REF/SEC/TER)
  - Chapters: rename, snap mode/threshold, starts‑only toggle
  - Merge Behavior: remove dialog normalization gain, codec blacklist, disable track statistics tags
  - Logging: compact mode, autoscroll, progress step %, error tail lines, pretty/json options dump
  - Merge Plan: rule editor with priority ordering

---

## Configuration Reference

Settings are persisted to `settings.json`. Missing keys are auto‑added with defaults.

- **Storage & Tools**
  - `output_folder` (str) — default `sync_output/` under repo root
  - `temp_root` (str) — default `temp_work/` under repo root
  - `videodiff_path` (str) — blank uses PATH

- **Analysis**
  - `analysis_mode` (str) — `"Audio Correlation"` | `"VideoDiff"`
  - `scan_chunk_count` (int) — default **10**
  - `scan_chunk_duration` (int, seconds) — default **15**
  - `min_match_pct` (float) — default **5.0**
  - `analysis_lang_ref` / `analysis_lang_sec` / `analysis_lang_ter` (str, optional ISO like `jpn`, `eng`)
  - `videodiff_error_min` / `videodiff_error_max` (float) — bounds for VideoDiff acceptance

- **Workflow**
  - `merge_mode` (str) — `"plan"` | `"manual"`

- **Chapters**
  - `rename_chapters` (bool)
  - `snap_chapters` (bool)
  - `snap_mode` (str) — `"previous"` | `"nearest"`
  - `snap_threshold_ms` (int) — default **250**
  - `snap_starts_only` (bool) — only snap chapter starts

- **Merge Behavior**
  - `apply_dialog_norm_gain` (bool) — remove dialnorm for AC3/E‑AC3
  - `exclude_codecs` (str) — comma list (e.g., `"ac3, dts, pcm"`)
  - `disable_track_statistics_tags` (bool)
  - `merge_profile` (list[rule]) — see Merge Plan

- **Logging**
  - `log_compact` (bool) — compact stdout
  - `log_autoscroll` (bool) — GUI behavior
  - `log_progress_step` (int %) — progress throttling (e.g., 20 → 0/20/40/60/80/100)
  - `log_error_tail` (int lines) — tail lines printed on error
  - `log_tail_lines` (int lines) — tail lines printed on success
  - `log_show_options_pretty` / `log_show_options_json` (bool)

- **Archival**
  - `archive_logs` (bool) — after batch, zip per‑file logs and delete the originals

---

## Dependencies

- **Python 3.9+**
- **MKVToolNix**: `mkvmerge`, `mkvextract`
- **FFmpeg**: `ffmpeg`, `ffprobe`
- **VideoDiff** (optional): if using that mode
- Python packages: `PySide6`, `librosa`, `numpy`, `scipy`

Ensure binaries are on `PATH` (or set explicit paths in Settings).

---

## Run It

```bash
python main.py
```

1. Select Reference (and optional Secondary/Tertiary). Files or matching folders.
2. Choose **Analyze Only** to validate delays, or **Analyze & Merge** to produce the final MKV.
3. Watch the log for:
   - Per‑chunk XCorr lines and final delays
   - Positive‑only **global shift**
   - Chapter processing summary
   - mkvmerge options file path
   - Success path for the output file

---

## Troubleshooting

- **Tool not found** — make sure `mkvmerge`, `mkvextract`, `ffmpeg`, `ffprobe` are installed and on `PATH`.  
- **XCorr unstable/low confidence** — increase `scan_chunk_duration` and/or `scan_chunk_count`; ensure language selection targets comparable mixes (JPN vs JPN, ENG vs ENG).  
- **Defaults/forced flags not what you expected** — In **Merge Plan**, check rule ordering and flags; in **Manual** mode, adjust the final list toggles.  
- **Chapters misaligned** — Verify `global_shift` in logs equals the shift applied to chapter XML; if snapping is on, try increasing `snap_threshold_ms` or switch `snap_mode`.  
- **mkvmerge failure** — Open `opts.json`, replay via terminal, and examine stderr; the app also prints the error tail.  

---

## Developer Notes

- **Demux strategy**: `mkvextract` for general tracks; for `A_MS/ACM` we first try stream copy with ffmpeg, else decode to PCM using a bit‑depth‑aware codec (`pcm_s16le`, `pcm_s24le`, `pcm_s32le`, `pcm_f64le`).  
- **Language selection** (analysis only) is independent from merge inclusion rules.  
- **Track ordering** is fully deterministic: we append inputs in the exact GUI/plan order and then emit a matching `--track-order`.  
- **Logging style** balances signal/noise; compact mode prints progress and only a tail of verbose output on success/failure.

---

## Design Invariants & Edge Cases

- **No negative `--sync`** is ever passed to mkvmerge; all per‑input `--sync` values are ≥ 0 after applying the global shift.
- **Reference video** dictates chapter rescale and subtitle PlayRes.
- **Manual layout auto‑apply** is only used when the **shape signature** (counts of `[source × type]`) matches the prior job to prevent accidental mismatches.
- **Codec exclusions** are substring checks against `codec_id` lowercased (e.g., `a_ac3`, `a_dts`, `a_pcm`).
- **Chapters normalization** ensures strictly increasing intervals and prevents open‑ended atoms from overlapping into the next.

---

## Performance Notes

- XCorr windowing is the main cost. Defaults (`10 × 15s`) trade speed vs. robustness.  
- SSD churn is minimized by deleting temp job directories on success.  
- For faster previews, reduce `scan_chunk_count` and/or `scan_chunk_duration` — then confirm with a second run if needed.

---

## Known Limitations

- Baseline engine uses a **single global delay** per Secondary/Tertiary. It does not splice or model time‑varying drift (that would be an “advanced repair” feature outside this README’s scope).  
- XCorr can be confused by long uniform ambiences; tuning the window schedule usually fixes it.  
- VideoDiff requires a separate binary and is subject to its error metric semantics.

---

## Appendix A: Log Line Guide

Examples you’ll see in the GUI log:

```
$ ffprobe -v error -select_streams v:0 -show_entries format=duration -of csv=p=0 "ref.mkv"
Chunk @1278s -> Delay -1001 ms (Match 95.28%)
Secondary delay determined: -1001 ms
[Delay] Raw delays (ms): ref=0, sec=-1001, ter=-1000
[Delay] Applying lossless global shift: +1001 ms
[Chapters] Renamed chapters to "Chapter NN".
[Chapters] Shifted all timestamps by +1001 ms.
[Chapters] Snap result: moved=3, on_kf=5, too_far=1 (kfs=1234, mode=previous, thr=250ms, starts_only=True)
mkvmerge options file written to: temp_work/job_ref_.../opts.json
[SUCCESS] Output file created: sync_output/RefTitle.mkv
```

---

## Appendix B: Demux Extension Map

| Track type | codec_id contains       | Demux extension |
|---|---|---|
| video | `V_MPEGH/ISO/HEVC` | `.h265` |
|  | `V_MPEG4/ISO/AVC` | `.h264` |
|  | `V_MPEG1/2` | `.mpg` |
|  | `V_VP9` | `.vp9` |
|  | `V_AV1` | `.av1` |
|  | *(else)* | `.bin` |
| audio | `A_TRUEHD` | `.thd` |
|  | `A_EAC3` | `.eac3` |
|  | `A_AC3` | `.ac3` |
|  | `A_DTS` | `.dts` |
|  | `A_AAC` | `.aac` |
|  | `A_FLAC` | `.flac` |
|  | `A_OPUS` | `.opus` |
|  | `A_VORBIS` | `.ogg` |
|  | `A_PCM` | `.wav` |
|  | *(else)* | `.bin` |
| subs | `S_TEXT/ASS` | `.ass` |
|  | `S_TEXT/SSA` | `.ssa` |
|  | `S_TEXT/UTF8` | `.srt` |
|  | `S_HDMV/PGS` | `.sup` |
|  | `S_VOBSUB` | `.sub` |
|  | *(else)* | `.sub` |

Special case: `A_MS/ACM` → attempt stream copy; if refused, decode to PCM with bit‑depth‑aware codec.

---

## Appendix C: Configuration Keys (Table)

| Key | Type | Default | Notes |
|---|---|---|---|
| `output_folder` | str | `sync_output` | Output target for merged MKV & job logs |
| `temp_root` | str | `temp_work` | Per‑job scratch directory root |
| `videodiff_path` | str | `""` | If blank, use PATH |
| `analysis_mode` | str | `Audio Correlation` | or `VideoDiff` |
| `scan_chunk_count` | int | `10` | Number of windows for XCorr |
| `scan_chunk_duration` | int | `15` | Seconds per window |
| `min_match_pct` | float | `5.0` | Discard XCorr results below this |
| `analysis_lang_ref` | str | `""` | ISO (`jpn`, `eng`) or blank for first stream |
| `analysis_lang_sec` | str | `""` | Same as above |
| `analysis_lang_ter` | str | `""` | Same as above |
| `videodiff_error_min` | float | `0.0` | Reject if error < min |
| `videodiff_error_max` | float | `100.0` | Reject if error > max |
| `merge_mode` | str | `plan` | or `manual` |
| `rename_chapters` | bool | `false` | Rename to `Chapter NN` |
| `snap_chapters` | bool | `false` | Enable keyframe snapping |
| `snap_mode` | str | `previous` | or `nearest` |
| `snap_threshold_ms` | int | `250` | Max move distance |
| `snap_starts_only` | bool | `true` | Only snap starts |
| `apply_dialog_norm_gain` | bool | `false` | Remove dialnorm for AC3/E‑AC3 |
| `disable_track_statistics_tags` | bool | `false` | mkvmerge flag |
| `exclude_codecs` | str | `""` | CSV blacklist (`ac3,dts,pcm`) |
| `merge_profile` | list | *(see defaults)* | Rule list, priority‑ordered |
| `log_compact` | bool | `true` | Compact command runner logs |
| `log_autoscroll` | bool | `true` | GUI behavior |
| `log_progress_step` | int | `20` | % step for progress lines |
| `log_error_tail` | int | `20` | stderr tail lines on error |
| `log_tail_lines` | int | `0` | stdout tail on success |
| `log_show_options_pretty` | bool | `false` | Dump pretty opts |
| `log_show_options_json` | bool | `false` | Dump raw JSON opts |
| `archive_logs` | bool | `true` | Zip logs after batch |

---

**License**  
This project wraps external tools; respect their licenses. The GUI/engine code is released under the project’s chosen license (add a LICENSE file if needed).
