# Core Architecture (Detailed)

This document describes the **core engine** of Video-Sync-GUI (vsg_core). It explains what each
module is for, what changes were made during modularization, and the key invariants to keep the
system correct. This is the detailed version, mirroring the full breakdown provided in discussion.

---

## Top-level entry

- **`main.py`**
  - Unchanged app entry point that launches the Qt UI (legacy window for now).

---

## vsg_core (runtime / engine)

### `pipeline.py`
**Purpose**
- Thin façade used by the UI/worker.
- Discovers tools, sets up per-job logging, and delegates real work to the orchestrator.
- Public API unchanged (`run_job` returns dict with `status`, `output`, `delay_sec`, `delay_ter`, `name`, `error`).

**Changes**
- Rewritten to be lean.
- Discovers tools (ffmpeg, ffprobe, mkvmerge, mkvextract, optional videodiff).
- Creates per-job temp dir for mkvmerge `@opts.json`.
- Calls orchestrator, then executes mkvmerge with built tokens.
- Preserves exact result contract expected by UI/worker.

**Invariant**
- Must run mkvmerge while referenced files still exist (see Temp/Cleanup section).

---

### Orchestrator

#### `orchestrator/pipeline.py`
**Purpose**
- Coordinates all modular steps.
- Passes a Context object through each step.

**Changes**
- Introduced Context model.
- Defines step order: `Analysis → Extract → Subtitles → Chapters → Attachments → Mux`.
- Returns populated Context.

#### `orchestrator/steps/context.py`
**Purpose**
- Dataclass carrying state across steps: settings, tool paths, dirs, inputs, results.

#### `orchestrator/steps/analysis_step.py`
**Purpose**
- Runs Audio Correlation or VideoDiff to determine delays.
- Computes global shift.

**Changes**
- Audio mode: selects stream by language (from config).
- Scans chunks, computes correlation, picks best by mode+confidence.
- VideoDiff mode: parses result line, validates error bounds, converts seconds to ms.
- Global shift: `global_shift_ms = -min_delay if min_delay < 0 else 0`.

**Invariant**
- Behavior identical to old pipeline.

#### `orchestrator/steps/extract_step.py`
**Purpose**
- Extracts tracks chosen in manual layout.

**Changes**
- Uses mkvextract/ffmpeg (PCM fallback for A_MS/ACM).
- Converts manual layout dicts into typed Track models.
- Guardrails for missing or unextractable tracks.

#### `orchestrator/steps/subtitles_step.py`
**Purpose**
- Applies subtitle transforms.

**Changes**
- Uses helpers in `subtitles/*`.
- Converts SRT→ASS, rescales ASS PlayRes, multiplies font size.

#### `orchestrator/steps/chapters_step.py`
**Purpose**
- Extracts and modifies chapters XML.

**Changes**
- Renames, shifts by global delay, snaps to keyframes, normalizes end-times.
- Uses `chapters/process.py` pipeline.

#### `orchestrator/steps/attachments_step.py`
**Purpose**
- Extracts TER attachments.

#### `orchestrator/steps/mux_step.py`
**Purpose**
- Builds mkvmerge tokens (no execution).

**Changes**
- Delegates all token construction to `mux/options_builder.py`.

---

## Extraction utilities

### `extraction/tracks.py`
**Purpose**
- Parse mkvmerge JSON and extract streams.

**Changes**
- `get_stream_info(mkv)` for JSON.
- Extracts with mkvextract, fallback with ffmpeg for ACM codecs.
- Returns dicts with metadata + path.

### `extraction/attachments.py`
**Purpose**
- Extract attachments with mkvextract.

---

## Subtitle utilities

- **`subtitles/convert.py`** — SRT→ASS with ffmpeg.
- **`subtitles/rescale.py`** — Rewrite PlayResX/PlayResY in ASS/SSA.
- **`subtitles/style.py`** — Inline ASS font size multiplier.

---

## Chapters utilities

- **`chapters/keyframes.py`** — Find keyframe PTS with ffprobe.
- **`chapters/process.py`** — Full pipeline: extract, rename, shift, snap, normalize.

---

## Mux options builder

**File:** `mux/options_builder.py`

**Purpose**
- Translate MergePlan into mkvmerge tokens.

**Rules**
- `--chapters <xml>` if present.
- `--disable-track-statistics-tags` if enabled.
- Defaults: first video, first default audio, first default subtitle.
- Forced subtitle: only one gets `--forced-display-flag yes`.
- Dialog normalization removal if AC3/E-AC3 and enabled.
- **Delays** = `global_shift + per-role delay`.
- Compression disabled.
- Track order preserved.

---

## Analysis engines

- **`analysis/audio_corr.py`**
  - Runs correlation over chunks.
  - Selects audio track by language (or first).
  - Picks best delay (mode + match%).

- **`analysis/videodiff.py`**
  - Runs videodiff tool, parses result.
  - Validates error against thresholds.
  - Converts seconds to ms.

---

## Process wrapper

- **`io/runner.py`**
  - Runs external commands, compacts logs, returns stdout.

---

## Data models

- **`models/enums.py`** — enums: TrackType, SourceRole, AnalysisMode, SnapMode.
- **`models/media.py`** — StreamProps, Track, Attachment.
- **`models/jobs.py`** — JobSpec, Delays, PlanItem, MergePlan, JobResult.
- **`models/settings.py`** — Typed AppSettings.
- **`models/converters.py`** — Converts UI layouts into typed models.

---

## Misc utilities

- **`config.py`** — JSON-backed settings.
- **`job_discovery.py`** — Finds jobs from folders/files.

---

# Key correctness points (sanity checklist)

1. **Analysis parity**  
   - Audio correlation matches previous logic.  
   - VideoDiff thresholds preserved.

2. **Global shift**  
   - Always non-destructive: earliest delay shifted to 0.

3. **Per-track delays**  
   - REF = global shift.  
   - SEC = global shift + sec delay.  
   - TER = global shift + ter delay.

4. **Default/forced flags**  
   - First video default.  
   - One default audio + subtitle.  
   - One forced subtitle.

5. **Subtitles**  
   - Convert/rescale/scale only if requested.

6. **Chapters**  
   - Extract, shift, rename, snap, normalize.

7. **Attachments**  
   - TER only.

8. **mkvmerge tokens**  
   - Centralized builder, all flags preserved.

---

# Temp/cleanup invariant

Artifacts referenced in mkvmerge tokens must exist until after mkvmerge runs.

Options:
- Delay orchestrator cleanup until after mkvmerge.
- Or write persistent artifacts to JobPipeline’s temp dir.

---

# Current status

- ✅ Stable JobPipeline API.  
- ✅ Orchestrator + steps modularized.  
- ✅ Analysis parity confirmed by logs.  
- ✅ Extraction, subtitles, chapters, attachments modular.  
- ✅ Pure mkvmerge builder.  
- ✅ Models ensure clarity.  
- ✅ Single process runner.  

