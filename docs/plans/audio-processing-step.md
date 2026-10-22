# Plan: Audio Processing step (in progress — steps 1–3 built, step 4 deferred, see §11)

Date: 2026-10-21. Steps 1–2 merged to `main` (9a701efa); strict decoding (5d3108fe) and
step 3 on `claude/video-sync-audio-processing-88a59f`.
Research behind it: `~/Desktop/Makemkv/Tests/audio_negative_sync/` (harness, codec
research, `flac_tests/`).

## 1. Goal

Every lossless audio track ends up as **FLAC with its delay baked into the samples**:

- negative delays are cut;
- positive delays get exact digital silence;
- the end is optionally trimmed to the video end.

That means:

- mkvmerge gets `--sync 0:0` for these tracks;
- the audio is aligned to the video both inside the MKV and as an extracted file;
- every kept sample is bit-identical to the source;
- every added or removed sample is logged and tagged.

All audio work happens in **one step**, so there is one place to look and one rule set.

Lossy and object-audio tracks (AC-3, E-AC-3, DTS core, AAC, Opus, TrueHD Atmos,
DTS:X) are **untouched** and use mkvmerge `--sync` exactly as today.

## 2. Decisions already made

| Topic | Decision |
|---|---|
| Positive delays on baked tracks | Prepend exact digital silence (round-trip proven reversible) |
| Precision | Unrounded analysis delay → nearest whole sample (≤ ½ sample, 0.010 ms @ 48 kHz); residual logged |
| Lossless sources | Convert to FLAC (per-track checkbox as today); tracks already FLAC are handled automatically |
| Source 1 audio | Convert only (bake its container offset so mkvmerge gets 0) — **never trimmed** |
| End trim | Option repurposed: "trim converted tracks to the video end", sample-exact; non-Source-1 only |
| `--stop-after-video-ends` | **Removed** (commit c6a6fef3 gets reverted by this work) |
| FLAC encoder | ffmpeg, `-compression_level 12 -max_prediction_order 12` (stays in the FLAC subset, < 1 % bigger than today's uncapped level 12) |
| Bit depth | Always the source's declared depth (padded 24-bit TrueHD stays 24-bit; FLAC "wasted bits" makes padding ~free) |
| Channel layouts | Any layout allowed; non-FLAC-native ones rely on the WAVEFORMATEXTENSIBLE_CHANNEL_MASK tag → logged; layout + per-channel samples verified after encoding |
| PAL / linear | Own switch, separate from stepping |
| Stepping | Analysis/EDL unchanged; only the final encode moves to the shared finisher |

## 3. What is wrong / scattered today

- **Encoding is inconsistent across paths:**
  - `ConversionStep`: FLAC level 12 (outside the subset).
  - Stepping: default level; 16-bit becomes 24-bit; channel layout guessed by count; encodes each
    segment, then re-encodes the joined file.
  - PAL/linear: default level; delay still rounded via `--sync`.
- **`AudioCorrectionStep` runs only one correction kind per job** (PAL **elif** linear **elif**
  stepping), so a second flagged source is silently skipped.
- **A FLAC request can be lost.** `ConversionStep` skips a source with a pending correction. If that
  correction then doesn't run (elif above, stepping false positive, QA fail), the track is never
  converted, and nothing reports it.
- **One switch gates everything:** `stepping_enabled` gates PAL/linear too.
- **Dead code:** `video_verified/preprocessing.apply_for_bitmap_subtitle` rewrites
  `source_delays_ms` after analysis. It has no callers, but would contradict baked audio if revived.

## 4. New layout

```
Analysis (unchanged: delays + stepping/PAL/linear flags)
→ Extract
→ AudioProcessingStep  ← replaces ConversionStep + AudioCorrectionStep
→ Subtitles (uses stepping EDLs as today) → Chapters → Attachments
→ Mux (baked tracks: --sync 0:0) → final audit
```

### Routes (each audio track gets exactly one, decided and logged up front)

| Route | When | What happens |
|---|---|---|
| **A. Correction** | source flagged for stepping (stepping on) or PAL/linear (drift switch on) — every flagged source, not just the first kind | Corrector does its work; its single output encode also bakes the delay + end trim via the shared finisher. If the corrector decides nothing is needed (no transitions / QA fail), the track **falls through to B or C**. |
| **B. FLAC** | per-track "convert to FLAC" ticked, or the track is already FLAC; and eligible (§6) | One ffmpeg pass: decode → cut start / prepend silence → trim end → encode FLAC → verify (§5.4) |
| **C. Untouched** | everything else | As today: extracted file + mkvmerge `--sync <rounded ms>` |

A verification failure on A or B keeps the original track on route C and is reported loudly
(same policy as today's FLAC conversion).

## 5. Shared finisher (used by routes A and B)

The finisher executes an **edit plan**: an ordered list of `take(source a..b)` (optionally with a
stretch filter for drift correction) and `silence(n samples)`, followed by an optional end trim.
It runs as **one streaming ffmpeg pass** (`atrim` per take, `anullsrc`+`atrim` per silence,
`concat`), then the FLAC encode, and is verified sample-for-sample against the plan. Proven
bit-exact on TrueHD 5.1 24-bit, 2026-10-21: three takes + a silence insert, 2,829,360 samples
identical, `flac -t` pass.

- **Route B:** `[silence n]` + `take(n_cut .. end)` → end trim.
- **Stepping:** the EDL → `take / silence / take …` → end trim.
- **PAL/linear:** `take(all, stretch)` → bake + end trim.

No full-track arrays are needed for the final output. Arrays stay in analysis only.

### 5.1 Delay → samples (exact integer arithmetic)

- **Track delay in ns:**
  - Source 1 audio: container offset from `mkvmerge -J` `minimum_timestamp` (ns) + raw global shift.
  - Other sources: `raw_source_delays_ms[source]` (already includes the raw global shift).
  - Stepping: the EDL's first-segment `delay_raw` (as today) + Source 1's audio container offset
    (today passed to mkvmerge; now baked).
- `n = round_half_away(|delay_ns| × rate / 1e9)`.
  - Negative: drop `n` samples.
  - Positive: prepend `n` zero samples.
- Residual (logged) = `n × 1e9 / rate − |delay_ns|`, at most ½ sample.

### 5.2 End trim (route B for non-Source-1 tracks, route A; only when the option is on)

- **Video end** = Source 1's last frame time + its last frame interval, from the real-timestamp
  `FrameTable` (ffms2 index, already on this branch; cached in `ctx.frame_tables` and reused by
  subtitles). Container timestamps are whole ms, so the video end is known to ±0.5 ms; log it.
- Output samples kept = `round(video_end × rate)`; anything after is dropped. Logged.

### 5.3 Encode

- **Command:**
  `ffmpeg -i <source> -map 0:a:N -af "<atrim=start_sample=n | adelay=nS:all=1>,atrim=end_sample=M" -c:a flac -compression_level 12 -max_prediction_order 12 <bit-depth args> -metadata <tags> out.flac`
- **Bit depth:** match the source (`-sample_fmt s16` for 16-bit, `-bits_per_raw_sample 24` for
  24-bit).
- **Channel layout:** the decoder's; never overridden or guessed.
- **Output:** written to a file (not a pipe), so STREAMINFO total + MD5 are written.
- **Decode source:** the extracted file for PCM/TrueHD/DTS-HD MA/MLP/FLAC. If a codec's extracted
  file proves unreliable (as TTA's was), decode from the source container instead.
- **Tags** (Vorbis comments; mkvmerge carries them into the MKV — proven):
  - `VSG_DELAY_MS=<raw>`
  - `VSG_SILENCE_SAMPLES_ADDED=<n>`
  - `VSG_SAMPLES_TRIMMED_START=<n>`
  - `VSG_SAMPLES_TRIMMED_END=<m>`
  - `VSG_SOURCE_CODEC=<codec id>`

### 5.4 Verify (before the track is accepted)

- **Format:** sample rate, channel count, declared bit depth and channel layout equal the source.
- **Samples:** decoded output == `zeros(n_added)` + source samples `[n_cut : n_cut + kept]`,
  compared as s32. Streamed through two ffmpeg pipes in chunks (no full-track RAM).
- **Header:** STREAMINFO total samples == decoded count; STREAMINFO MD5 == MD5 of the decoded
  samples in FLAC's canonical form (computed in Python, no extra tool).
- **Subset:** prediction order ≤ 12 at ≤ 48 kHz is guaranteed by the encoder args; block size and
  partition order are within limits (measured).
- **Non-native layout:** log "layout X stored via channel-mask tag; players that ignore the tag
  will play it as <FLAC default for N channels>".
- **Route A** (corrections alter the audio by design): format + layout + the expected sample count
  from the EDL / stretch; for stepping, decoded output == the assembled PCM.

### 5.5 Log block (per track)

```
[AudioProcessing] Source 2 audio track 1 (A_TRUEHD 5.1(side) 48 kHz 24-bit) -> route B (FLAC)
  delay: raw -10.834789 ms (mkvmerge would have used -11 ms)
  start: cut 520 samples (10.833333 ms), residual -0.001456 ms
  end:   video end 1531.029 ms (Source 1 frame table) -> trimmed 412,800 samples (8.600 s)
  out:   73,489,200 samples, 5.1(side) native layout, 24-bit, subset OK
  verify: samples identical to source[520:73489720]; STREAMINFO total + MD5 OK
  tags:  VSG_DELAY_MS=-10.834789 VSG_SAMPLES_TRIMMED_START=520 VSG_SAMPLES_TRIMMED_END=412800
  mux:   --sync 0:0 (delay baked)
```

## 6. Eligibility for route B

- **Allowed:** PCM integer (8/16/24-bit), TrueHD (not Atmos), DTS-HD MA (not DTS:X), MLP (new),
  FLAC (auto).
- **Excluded, logged with the reason:**
  - TrueHD Atmos, DTS:X (object audio)
  - lossy DTS profiles
  - float PCM (FLAC is integer-only)
  - 32-bit integer PCM (until tested)
  - more than 8 channels
  - tracks ffprobe can't read
- **Unknown channel layout** (ffprobe reports none — common for PCM in MKV): use FLAC's default for
  that channel count, which is also how players read the source PCM; logged.

## 7. Stepping integration (route A)

- Analysis, edit list, QA check and the subtitle use of `stepping_edls` are **unchanged**.
- Final per-track output no longer assembles in memory: the EDL is converted to an **edit plan**
  (§5) and executed by the finisher in one streaming pass. No per-segment FLACs, no concat
  re-encode, no full-track RAM (a 130-min 7.1 track would be ~12 GB as int32). The in-memory
  arrays remain for analysis, silence/boundary detection and the mono QA check.
  - encodes at the source bit depth, with the decoder's layout (no count-based guess).
  - applies the end trim when the option is on.
- `swap_in_corrected_track` sets `delay_baked=True` (replaces `is_pre_aligned`). Source 1's audio
  container offset and the whole-ms global shift are baked too, so mkvmerge gets 0.

**As built (step 3, 2026-10-21):**
- `correction/stepping/edit_plan.py` turns the EDL into finisher ops; the mono QA track and the
  real encode both use it. Parity with the old assembler is tested on random EDLs.
- Starting delay = first segment + Source 1 audio container offset + whole-ms global shift,
  always applied to the nearest sample. (Old: a positive start ≤ 10 ms was skipped, and the
  global shift never reached stepping tracks.)
- Between segments the old rule is kept: increases > 10 ms insert silence, any decrease cuts,
  increases ≤ 10 ms are ignored and logged ("note and monitor").
- Lossy (float-decoded) tracks → 24-bit FLAC, verified against the decode truncated to 24 bits
  (measured: that is what ffmpeg's FLAC encoder does). Object audio keeps only its bed (logged).
- Per-segment drift correction was dead code (`drift_rate_ms_s` never set since `c05dcb61`) and
  is removed; stepping plans hold only takes and silence, verified exactly.
- New tag `VSG_EDIT_PLAN` on every finished FLAC (e.g. `T448-96000 S24000 T96000-192000 T204000-`).
- A stepping source with no verified EDL (no transitions, QA failure) no longer fails the job:
  its tracks take route B/C, and a QA failure is reported as a high-severity stepping issue.

## 8. PAL / linear integration (route A)

**Superseded (2026-10-22):** PAL / linear correction is disconnected and kept for later; see
[drift-correction.md](drift-correction.md). Only the separate switch (`drift_correction_enabled`,
greyed out) was added. The items below are the original plan.

- **New setting:** `drift_correction_enabled` (PAL + linear), separate from `stepping_enabled`.
  Check whether drift *detection* in analysis also needs to follow it; today detection runs
  regardless and only the correction is gated.
- **Single encode per track:** their ffmpeg command appends the delay bake + end trim to the stretch
  filter and uses the shared encoder args.
- **Verify:** format, layout and sample count.
- **Every flagged source is processed** (no elif).

## 9. Mux, audits, validation, UI

- **Options builder:**
  - `delay_baked` → `--sync 0:0`;
  - remove `--stop-after-video-ends`;
  - single delay function, shared with the auditors.
- **Auditors:**
  - `AudioSyncAuditor`: baked tracks are expected at 0 (report the bake summary); the model for
    unbaked PCM/FLAC is fixed (PCM 40 ms packets, FLAC block size) so the false mismatch goes.
  - `FlacConversionAuditor` → `AudioProcessingAuditor`: routes, bakes, layout notes, fall-backs.
  - `AudioDurationAuditor`: wording for the new trim meaning.
- **`StepValidator.validate_audio_processing`:** every audio track has exactly one recorded route
  outcome. This replaces `validate_conversion` / `validate_correction`.
- **UI:**
  - per-track "Convert to FLAC" unchanged;
  - trim checkbox → "Trim converted audio to the video end (sample-exact)";
  - new "PAL / linear drift correction" checkbox beside stepping.

## 10. Files

| Change | Files |
|---|---|
| New | `vsg_core/audio_processing/` (`samples.py` delay/trim math, `encoder.py` ffmpeg FLAC args + tags, `verify.py` streaming comparator + MD5, `routes.py` eligibility + routing); `vsg_core/models/audio_processing.py` (result dataclasses shared with the auditor); `vsg_core/orchestrator/steps/audio_processing_step.py`; `postprocess/auditors/audio_processing.py` |
| Changed | `orchestrator/pipeline.py`, `orchestrator/validation.py`, `orchestrator/steps/context.py`, `models/jobs.py` (`delay_baked`), `models/settings.py`, `mux/options_builder.py`, `postprocess/auditors/{audio_sync,audio_duration,base}.py`, `postprocess/final_auditor.py`, `correction/stepping/{audio_assembly,run}.py`, `correction/{pal,linear}.py`, `vsg_qt/options_dialog/tabs.py`, `CLAUDE.md`, `docs/README.md` |
| Removed | `orchestrator/steps/conversion_step.py` and `audio_correction_step.py` (logic moves into the new step), `apply_for_bitmap_subtitle` (dead), stepping's `_encode_flac` + concat path, `is_pre_aligned` |

## 11. Order of work (one commit each, each tested before the next)

1. *(done)* **Finisher core:** `samples.py` + `encoder.py` + `verify.py`, unit tests (math edge cases, tag
   building) + real-sample tests in `Tests/`.
2. *(done)* **Step with routes B + C:**
   - replaces `ConversionStep`;
   - mux `delay_baked` → 0, remove `--stop-after-video-ends`;
   - auditor + validator + trim option wording.

   At this point FLAC conversion is exact. Stepping/PAL/linear still run through the old
   `AudioCorrectionStep`, temporarily called from inside the new step.
3. **Stepping onto the finisher:** route A, the bit-depth/layout/compression/single-encode fixes,
   end trim, `delay_baked`. *(built, see §7 "As built")*
4. *(changed)* **PAL/linear:** disconnected with a note ([drift-correction.md](drift-correction.md)); the
   separate switch exists (greyed out); stepping alone drives the correction phase.
5. **Cleanup:** dead code, `CLAUDE.md` job flow, `docs/README.md`.

## 12. Validation plan

- **Unit tests:**
  - sample maths: exact integers, rounding ties, 44.1/48/96/192 kHz, positive / negative / zero
    delay, trim with and without;
  - route decisions;
  - eligibility;
  - tag round-trip.
- **Real-sample harness** (`Tests/audio_negative_sync/`):
  - **Sources:** TrueHD 5.1/7.1, DTS-HD MA 5.1/6.1/7.1/96 kHz, BD PCM 16/24 stereo/5.1, DVD
    LPCM, app-made FLAC, foreign FLAC.
  - **Cases:** each at delays −1001/−517/−10.8/0/+10.8/+517 ms, with and without trim.
  - **Checks on the final MKV:**
    - first block at 0;
    - decoded == expected (zeros + source slice);
    - layout;
    - `flac -t` of the extracted track (test-only use of the reference tool);
    - tags present.
- **Channel-layout test set:**
  - **Sources:** synthetic per-channel tones (each channel a different frequency) for every disc
    layout (1.0, 2.0, 2.1, 3.0, 3.0(back), 3.1, 4.0, quad, 4.1, 5.0, 5.0(side), 5.1, 5.1(side),
    6.0, 6.1, 7.0, 7.1, 7.1(wide)).
  - **Path:** encoded as PCM, and via TrueHD/DTS where ffmpeg can encode them, then run through
    the whole pipeline.
  - **Checks:** each speaker's tone lands on the right labelled channel; native vs tagged is logged
    correctly.
- **Stepping regression:** a known stepping job (e.g. the Saikyou Onmyouji ep6 case). The corrected
  track must decode sample-identical to the old implementation's output, apart from the bit-depth
  fix (and end trim if on).
- **App jobs:** Delicious in Dungeon (Source 1 PCM converted, Source 2 E-AC-3 untouched,
  −11011 ms); a TrueHD secondary-source job with a negative delay; a positive-delay job; with and
  without trim.

## 13. Risks

- **Behaviour change** for converted tracks:
  - they now start at 0, with silence for positive delays;
  - they are trimmed exactly when the option is on;
  - lossy tracks are no longer trimmed at all (the flag is removed).
- **Time:** the verification decode is as expensive as today's MD5 check; stepping gets faster (one
  encode instead of many).
- **Non-native channel layouts** depend on the tag being read by the player (logged per track).
- **Trust in ffmpeg's lossless decoders** (TrueHD/MLP, DTS-HD MA): the same trust the current
  conversion has; DTS MA matched the official reference checksum in research.
- **Converted vs unconverted tracks** in one file can differ by ≤ 0.5 ms relative to each other
  (exact vs whole-ms). Inaudible, but documented.

## 14. Answers to the open questions (2026-10-21)

1. **Tags:** keep all five (`VSG_DELAY_MS`, `VSG_SILENCE_SAMPLES_ADDED`,
   `VSG_SAMPLES_TRIMMED_START`, `VSG_SAMPLES_TRIMMED_END`, `VSG_SOURCE_CODEC`). Always write them,
   with 0 when nothing was done, so every processed track describes itself the same way.
2. **Already-FLAC tracks:** re-encoded only when something changes (cut, silence or trim).
   Otherwise untouched.
3. **32-bit integer PCM:** excluded (logged; stays PCM with mkvmerge handling). Revisit if one ever
   shows up.
4. **Drift detection:** always runs in analysis. Only PAL/linear *correction* follows the new switch.
