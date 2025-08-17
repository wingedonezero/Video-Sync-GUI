# Video‑Sync GUI — Technical Design & Operator’s Manual

This document is the **source of truth** for how the tool works, *why* the choices were made, and what guarantees the pipeline provides. Keep it updated whenever behavior changes. All examples and rules below are what the code enforces today.

---

## Goals & Philosophy

- **Lossless, deterministic merges.** Never transcode; only mux. Preserve reference metadata.
- **Positive‑only synchronization (“always add, never subtract”).** We normalize all streams to a **global positive shift** so no track receives a negative offset in practice. (*Details & example below.*)
- **Readable, audit‑friendly logs.** Every job creates a verbose log with a compact **Merge Summary** and the exact `@opts.json` used by `mkvmerge`.
- **Stable mkvmerge option files.** We emit a **tokenized JSON array** (argv) to avoid quoting issues and flag/file ambiguity. Per‑input options always precede the file using **parenthesis grouping**.

---

## File Roles

- **Reference (REF):** Video authority. We feed the **original MKV** to `mkvmerge` (not demuxed), preserving language tags/flags while stripping **track names** from REF only for a clean output.
- **Secondary (SEC):** Source for replacement **English audio** (and possibly subs). Offset is measured **against REF**.
- **Tertiary (TER):** Source for **subtitles** and **attachments** (fonts). Offset is independently measured **against REF**.

---

## Analysis Modes

Two independent analyzers can be selected globally. The pipeline supports analyzing **SEC vs REF** and **TER vs REF** separately; each produces its own delay (in ms).

### 1) Audio Cross‑Correlation (default)

- **Sampling strategy:** Evaluate `N` chunks of `D` seconds each across the **middle 80%** of the timeline to avoid cold opens/silence. Defaults: `N=10`, `D=15`.
- **Per‑chunk result:** For each chunk, compute delay (ms), match confidence (%), and raw floating‑point delay (s).
- **Final decision:** Pick the **most frequent millisecond delay** across chunks. In a tie, choose the candidate with the **highest match** among the tied bins.
- **Reliability check:** If stdev is high or confidences are low, we **pause** and present a summary for confirmation before merging.

Example per‑chunk output line (as shown in logs):

```
Chunk @ 753s -> Delay: +371ms (Match: 54.52%) | Raw: 0.370658s
```

### 2) VideoDiff (perceptual) *(optional)*

- Very fast visual comparer for near‑identical sources.
- We robustly parse the tool’s `[Result]` line and enforce a single sign convention:
  - **Positive delay** means the secondary/tertiary stream is **behind** REF and must be shifted **forward**.
  - **Negative delay** means the stream is **ahead** of REF and would normally move **back**—but see the **positive‑only** rule below.

> If VideoDiff is selected, the computed ms delay still goes through the same **positive‑only normalization** so all `--sync` values applied are non‑negative in the final plan.

---

## Positive‑Only Delay Normalization (“Always Add”)

To keep the working model simple and to ensure **no track starts before time 0**, we normalize the measured delays for all inputs to a **global non‑negative origin**.

**Rule:** Let `Δ_ref = 0`, `Δ_sec = measured_sec_ms`, `Δ_ter = measured_ter_ms` (positive = behind, negative = ahead). Compute:

```
G = max(0, Δ_ref, Δ_sec, Δ_ter)   # global anchor (the *highest*/most positive delay)
δ_ref' = G - Δ_ref
δ_sec' = G - Δ_sec
δ_ter' = G - Δ_ter
```

We then apply **non‑negative syncs** `δ_*'` when building mkvmerge options, so **every stream starts at or after the global start**.

**Worked example:**

- REF video raw  `0 ms` → becomes **`+1085 ms`** (shifted forward)
- SEC audio      `-1085 ms` → becomes **`0 ms`**
- TER audio/subs `-1001 ms` → becomes **`+84 ms`**

This yields a consistent, monotonic plan with only additions while maintaining true A/V alignment.

---

## Chapters

- **Renaming (optional):** Normalize names to `Chapter 01`, `Chapter 02`, … (no language prefix).
- **Time shifting:** Chapters are shifted by the **global positive shift** `G` so visuals remain aligned even when the global origin moves forward.
- **Snap to keyframes (optional):**
  - **Modes:** *Starts only* or *Starts & Ends*.
  - **Tolerance:** configurable (e.g., ±250 ms).
  - If a boundary is within tolerance of a keyframe, we snap; if already within tolerance we leave as‑is; if too far, we log `too_far` and do nothing.

---

## Track Ordering & Defaults

### Final track order (typical layout)

```
[1] REF Video
[2..] SEC English Audio (all)        # exact one audio default = first in final order
[3..] REF Audio (remaining originals)
[4..] TER Subtitles (all)
[5..] SEC Subtitles (all; subject to “swap first 2” rule)
[6..] Other REF tracks (e.g., remaining subs)
[+]  TER Attachments (fonts) appended after streams
```

### Language tags

- Carried through from source whenever present.
- Heuristics may supplement missing tags (e.g., detect `jpn` by filename hints).
- We write `--language 0:<code>` for **every** added stream (video/audio/subs).

### Default flags

- **Audio:** only the **first** audio in the final order gets `--default-track-flag 0:yes` (others `no`).
- **Subtitles:** rules in priority order:
  1) If a track name contains `Signs`, `Songs`, or `Titles` (case‑insensitive), mark **that** as default.
  2) Else, if **no English audio** exists, mark the **first subtitle** default for accessibility.
  3) Else, optional rule: “**first sub in final order default**” can be enabled.
- **Video:** first video is default yes.

### “Swap first two subtitles” (Secondary)

- Optional. If enabled, the first two **secondary** subtitles are swapped (many discs ship `[Signs]` and `[Full]` reversed from desired). The default‑subtitle selection respects this swap.

### Track names

- **Reference track names are stripped** (emptied) for a clean output; new incoming tracks may be named (e.g., `Signs / Songs`).

### Compression & Dialnorm

- Apply `--compression 0:none` to **every** stream (video/audio/subs). **Never** set compression flags on attachments.
- Optional dialnorm removal: when enabled, add `--remove-dialog-normalization-gain 0` to AC‑3/E‑AC‑3 inputs (applied in the option file).

---

## mkvmerge Option File (`@opts.json`)

We emit a **JSON array of CLI tokens** (argv) rather than a structured object. This approach is robust and mirrors exactly what you’d type on the shell, with one crucial rule: **per‑file options immediately precede that file** and each input is wrapped by parentheses so mkvmerge scoping is unambiguous.

Two artifacts are written per job:

- `opts.json` — machine‑readable **token array** consumed by `mkvmerge`.
- `opts.pretty.txt` — human summary (line‑wrapped) included in logs.

**Abridged pretty view example:**

```
--output /path/out.mkv
--chapters /path/chapters_mod.xml
( /path/ref_video.mkv ) --language 0:eng --default-track-flag 0:no --compression 0:none
( /path/sec_audio.truehd ) --language 0:eng --sync 0:84 --default-track-flag 0:yes --compression 0:none
( /path/ter_subs.ass ) --language 0:eng --track-name 0:Signs / Songs --default-track-flag 0:no --compression 0:none
--attach-file /path/font0.ttf
--attach-file /path/font1.ttf
```

We also emit an explicit `--track-order` to lock final layout, and we **never** add compression flags for attachments.

---

## Logging & Artifacts

Every job writes a timestamped log containing:

- **Analysis Summary** with per‑chunk lines and the final conclusion (most‑common ms, best match %).
- **Merge Summary**: a compact section listing final order, languages, defaults, delays (`δ_*'`), track names, attachments, and the exact `--track-order`.
- The **exact options file** (pretty + raw JSON array) for audit/debug.

Job outputs:

```
<output_folder>/<index>.mkv     # final mux
<output_folder>/<index>.log     # job log
<temp_root>/job_<N>_<epoch>/    # demux & analysis workspace
    ref_track_.../sec_track_.../ter_track_...
    *_chapters.xml / *_chapters_mod.xml
    att_*.ttf
    opts.json / opts.pretty.txt
    # plus temp WAV snippets for Audio XCorr
```

---

## Settings (selected)

- `output_folder`: default output dir.
- `analysis_mode`: `"Audio Correlation"` or `"VideoDiff"`.
- `workflow`: `"Analyze & Merge"` or `"Analyze Only"`.
- `scan_chunk_count`, `scan_chunk_duration`: Audio‑XCorr scanning parameters.
- `rename_chapters`: enable normalized names and time shift.
- `snap_mode`: `"off" | "starts" | "starts_and_ends"`; `snap_tolerance_ms`: ± window.
- `match_jpn_secondary` / `match_jpn_tertiary`: if `True`, choose JPN track for analysis; otherwise first audio.
- `swap_subtitle_order`: swap first two SEC subs before default‑sub selection.
- `apply_dialog_norm_gain`: if `True`, remove dialnorm on AC‑3/E‑AC‑3.

---

## Failure Modes & Guarantees

- **Flags treated as files:** avoided by tokenized `@opts.json` and strict per‑file grouping with parentheses.
- **Negative syncs:** eliminated by **positive‑only** normalization.
- **Subtitle default ambiguity:** deterministic rules (Signs/Songs wins; fallback to first sub if no ENG audio).
- **Attachment mishandling:** never apply compression flags to attachments; log each with name and mime.
- **Chapter drift after shifting:** content alignment preserved by shifting all boundaries by `G`, with optional keyframe snapping and `too_far` reporting.

---

## Worked End‑to‑End Example

- **Analysis results:**
  - SEC vs REF: `Δ_sec = -1085 ms`
  - TER vs REF: `Δ_ter = -1001 ms`
  - REF is `0 ms`

- **Global anchor:** `G = max(0, -1085, -1001) = 0` → but if we *choose* a later anchor (e.g., +1085 to avoid any negative), then:

  - `δ_ref' = +1085`
  - `δ_sec' = 0`
  - `δ_ter' = +84`

- **Final plan:** apply those non‑negative syncs in `@opts.json`, write `--track-order`, log **Merge Summary** + **opts.pretty** + raw **opts.json**.

---

## Operator Checklist

1. Choose inputs (REF, SEC, optional TER).
2. Configure settings (analysis mode, chapter rename/snap, swap subs, dialnorm removal).
3. Run **Analyze & Merge**.
4. Inspect **Analysis Summary** and **Merge Summary** in the job log.
5. (If needed) open `opts.pretty.txt` / `opts.json` in the temp dir.
6. Verify final MKV plays with expected defaults and chapter behavior.

---

## Appendix: Implementation Notes

- The GUI/TUI prints **absolute paths** of current work items in batch mode.
- When writing per‑track options, we clone option lists (`list(opts)`) to prevent cross‑track leakage (e.g., a delay meant for one stream appearing on another).
- The code emits **exactly one default audio** (first in order); all other audios default `no`.
- All per‑stream options are scoped immediately before their file token—then we place the file within **parentheses** to lock scope.

---

*End of document.*