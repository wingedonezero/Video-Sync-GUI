# Plan: the app cuts passthrough audio itself (built 2026-10-25, uncommitted — see §21)

Date: 2026-10-25. Follows `audio-processing-step.md` (FLAC route, built).
Research and proof: `~/Desktop/Makemkv/Tests/audio_negative_sync/` — `CUT-SAFETY-2026-10-25.md`
(this plan's evidence), `codec_research/STRATEGY-2026-10-20.md` (per-codec rules),
`harness/` (`rawparse.py`, `prep_core.py`: the prototype to port).

## 1. Goal

Audio that keeps its codec (lossy, Atmos, DTS:X, and lossless tracks not converted to FLAC) is
today muxed as extracted, with mkvmerge `--sync` doing any negative cut, and **nothing trims its
end**. The 2026-10-25 Dungeon job shows the result: the WEB E-AC-3 runs **65.4 s past the video**.

New: the app makes every cut on these tracks itself, on the codec's own frame boundaries, and
mkvmerge only ever gets `--sync ≥ 0` for them.

- **Start:** drop whole frames before the delay point, exactly as mkvmerge does today, but
  checked, and starting on a frame that can actually start a decoder.
- **End:** when "trim audio to the video end" is on (not Source 1), drop whole frames after it.
- **Never** insert silence or frames into a lossy stream, never re-encode, never cut inside a frame.

A frame can't be split without re-encoding, so up to one frame of audio is still missing at the
start (32 ms for AC-3, 29 ms in the Dungeon job), and the codec's warm-up after any cut stays.
Both are what mkvmerge gives today.

## 2. What the research established

| Question | Answer (evidence in `CUT-SAFETY-2026-10-25.md`) |
|---|---|
| Does MKVToolNix-Mod cut audio differently from 103.0? | No: every audio and cutting source file is byte-identical to 103.0 |
| How does mkvmerge cut? | Drops whole packets whose shifted time is < 0, by time only, no codec check (`generic_packetizer.cpp` `add_packet2`) |
| Is that safe? | AC-3, E-AC-3 (frame + dependents = one packet), AAC, DTS lossy/MA: **yes**. TrueHD/Atmos: **no** (keeps up to 127 undecodable AUs, first one flagged key frame). DTS Express: **no** (source only). Vorbis: 9.33 ms early with lacing |
| Does our cut equal mkvmerge's? | Yes: Dungeon E-AC-3 −11011 ms, our cut + `--sync +29` = mkvmerge's cut, frame for frame (time, size, adler32, key) |
| End trim result | Dungeon: 2,044 frames dropped, ends 7.5 ms after the video (< 1 frame) |
| Does the FFmpeg fork change any of this? | No: all 10-20 decode experiments identical on the fork |
| Can a strict decode catch a bad start? | **No** (DTS ramp-in, TrueHD off a major sync, mkvmerge's TrueHD cut all exit 0). Checks must be packet-level |

## 3. Routes after this change

`AudioRouteStr` gains one value:

| Route | Who | mkvmerge gets |
|---|---|---|
| `corrected` | stepping (unchanged) | `--sync 0` |
| `flac` | lossless + FLAC requested (unchanged) | `--sync 0` |
| **`passthrough`** (new) | every other track in a supported codec | `--sync r`, r ≥ 0 |
| `untouched` | unsupported codec, or the passthrough cut failed | `--sync` as today (logged loudly) |

A `passthrough` track with nothing to cut (positive delay, no end trim) gets the same `--sync` as
today and its file is not rewritten; it still goes through the post-mux check (§7).

## 4. Per codec

The first kept unit must be an **entry unit**: one a decoder can start on, and that mkvmerge
times correctly when the file starts there.

| Codec | Unit (= mkvmerge packet) | Entry unit | End cut after | Phase |
|---|---|---|---|---|
| AC-3 | syncframe (32 ms @48k) | any | any unit | 1 |
| E-AC-3 (incl. BD 7.1 core+dependent, JOC) | independent frame + its dependents | independent substream 0 (or AC-3 core) | any unit | 1 |
| TrueHD / MLP (incl. Atmos) | access unit (0.83 ms) | **major sync** (every ≤ 128 AUs) | any AU | 1 |
| DTS core / ES / 96-24 / HRA / MA / DTS:X | core + its EXSS | core sync, never a lone EXSS | after the EXSS | 1 |
| DTS-HD MA coreless | EXSS | EXSS whose XLL starts with its sync | whole packet | 1 |
| DTS Express (LBR) | EXSS | packet carrying LBR **DECODERINIT** | whole packet | 1 (new rule; needs a sample) |
| AAC (ADTS) | frame (21.3 ms @48k) | any ADTS frame | any frame | 1 |
| Opus (Ogg) | packet | sample-exact via Ogg pre-skip + 80 ms pre-roll, end granule | sample | 2 |
| Vorbis | packet | packet, muxed with `--disable-lacing` | packet | 2 |
| MP2 / MP3 | frame (LAME frame counts) | any frame | any frame | 2 |
| anything else | — | — | — | `untouched` |

Streams the parser refuses (prototype list): garbage at the start, independent E-AC-3 substreams
> 0, sample-rate changes mid-stream, a TrueHD file not starting on a major sync, truncated
units mid-stream. Refused → `untouched`, with the reason in the log.

## 5. Planning a cut (exact integer arithmetic)

- **Unit map:** port `harness/rawparse.py` (mkvmerge's packet rules from the 103.0 source, header
  walk only, no tool run; matched mkvmerge on every accepted track of the 448-track sweep).
  Each unit: byte position, size, sample count, entry flag. Unit k starts at
  t_k = (samples before k) / rate, as an exact fraction.
- **Delay d:** the unrounded delay the FLAC route already uses (`_baked_delay_ms`).
- **Start:** k = first entry unit with t_k + d ≥ 0. Residual r = llround_ms(t_k + d) → `--sync r`.
  For d ≥ 0: k = 0, r = llround_ms(d).
- **End** (switch on, not Source 1): m = last unit with t_m + d < video end, where the video end is
  `_output_video_end_ms` (Source 1's real frame timestamps, as the FLAC route). Audio then runs
  past the video by less than one unit and never stops short.
- **Write:** byte slice `raw[pos_k : pos_m + size_m]` to a new file next to the extraction.

Difference from today: mkvmerge rounds d to whole ms *before* cutting; we round once, after
(t_k + d). Kept audio is then within 0.5 ms of exact instead of up to 1 ms. On 48 kHz AC-3 /
E-AC-3 t_k is a whole ms, so the blocks are identical to today's (Dungeon: r = 29 both ways).

## 6. Pre-mux check (before the cut file replaces the extraction)

1. Re-parse the cut file from byte 0 with the same rules: first unit is an entry unit, units
   contiguous, last unit complete, count and sizes equal the plan.
2. sha256 of the cut file equals sha256 of `raw[pos_k : end]`.

Any failure → `untouched` with today's mkvmerge `--sync` (§9).

## 7. Post-mux check (packet level, on the final MKV)

For each `passthrough` track, from `ffprobe -show_packets -show_data_hash` (laced blocks are
split into frames by the demuxer):

- **V1** first packet is an entry unit, at exactly r ms; TrueHD: key flag set and a major sync.
- **V2** packet count = m − k + 1; payload hashes equal source units k..m. With
  `--remove-dialog-normalization-gain` mkvmerge rewrites the dialnorm field of AC-3 / E-AC-3 /
  TrueHD units, so V2 compares sizes and hashes with that field masked, or sizes only (to decide).
- **V3** every packet time within 1 ms of t_j + d.
- **V4** (end trimmed) the last packet ends at or after the video end, by less than one unit.

Not decode-based: a strict decode passes every bad start this check exists for.
This replaces `AudioSyncAuditor`'s codec-table prediction for `passthrough` tracks (that table
is wrong for PCM/FLAC/TrueHD/DTS variants anyway); `AudioDurationAuditor` expects trimmed
passthrough tracks to end within one unit past the video end.

## 8. Log block per track

```
[AudioProcessing] Source 2 audio track 2 (A_EAC3) -> passthrough: whole frames cut, codec kept
  delay:  raw -11010.834586 ms (mkvmerge would have used -11011 ms)
  start:  dropped 345 units (11040.000 ms); first kept unit at +29.165 ms -> --sync +29
  end:    dropped 2044 units (65408.000 ms); ends 7.500 ms after the video end
  verify: 47844 units re-parsed, sha256 OK; mkvmerge gets --sync +29
```

## 9. Failure handling

Any parse refusal, plan error or pre-mux check failure keeps the extracted file and today's
mkvmerge `--sync`, reported as a warning in the final report (as FLAC failures are). A post-mux
check failure is an audit issue. For TrueHD Atmos the fallback means mkvmerge's broken start —
the warning says so.

## 10. Mux

New `PlanItem.mux_sync_ms: int | None` set by the step for `passthrough` tracks; the options builder
uses it when set (same place as `delay_baked`). Phase 2 adds `--disable-lacing` for Vorbis/Opus.

## 11. Files

| File | Change |
|---|---|
| `vsg_core/audio_processing/frames.py` (new) | unit map per codec (port of `rawparse.py`), typed dataclasses |
| `vsg_core/audio_processing/frame_cut.py` (new) | plan, slice, pre-mux re-parse check |
| `vsg_core/orchestrator/steps/audio_processing_step.py` | `passthrough` route |
| `vsg_core/models/audio_processing.py` | route value, unit counts / residual / overrun fields |
| `vsg_core/models/jobs.py` | `PlanItem.mux_sync_ms` |
| `vsg_core/mux/options_builder.py` | use `mux_sync_ms` |
| `vsg_core/postprocess/auditors/` | packet-level check; duration auditor rule |
| `tests/` | parser and planner unit tests (synthetic frames per codec) |
| `docs/README.md` §8.2a | document the route |

## 12. Order of work (one commit each, each tested before the next)

1. Frame parser + unit tests; harness sweep (448 tracks) re-run against the ported module.
2. Planner + slicer + pre-mux check; Dungeon E-AC-3 replay through the module.
3. Step route + `mux_sync_ms` + log block, behind the existing trim switch for the end.
4. Post-mux packet check, auditor changes.
5. Phase 2: Opus pre-skip, Vorbis no-lacing, MP2/MP3.

## 13. Validation plan

- **Dungeon ep 1** re-run: E-AC-3 frames identical to today's job for the start; end trimmed
  (2,044 frames, +7.5 ms); every other track identical.
- **Harness sweep** (`harness/run_harness.py`, 448 tracks × 13 cases) through the app module:
  equal to mkvmerge's own cut on every accepted track.
- **Real jobs**: a DVD AC-3 job, a BD job with TrueHD *not* converted (start must land on a major
  sync, V1 key flag), a DTS-HD MA job not converted, a positive-delay job (nothing cut, same
  `--sync`), Source 1 tracks (never end-trimmed).
- **Gaps** (no real sample): TrueHD Atmos, E-AC-3 7.1/JOC, DTS:X, DTS Express, HE-AAC.

## 14. Risks

- **Parser vs mkvmerge drift.** The parser copies mkvmerge's packet rules; a future MKVToolNix-Mod
  change to audio packetizing would need the sweep re-run. Mitigated by the pre-mux re-parse and
  the post-mux packet check, which compare against what mkvmerge actually wrote.
- **Untested formats** (Atmos, DTS:X, Express): rules from source/spec only.
- **Dialnorm removal** changes payload bytes (§7 V2).
- **Out of scope, noted:** raw extraction drops a non-Source-1 track's own start offset (e.g. the
  +1 ms Opus in Dungeon Source 3); today's behaviour, unchanged here.

## 15. Decisions (2026-10-25)

1. **End rule:** keep every unit that *starts* before the video end. Overrun < one unit (§16).
2. **Switch:** the existing "trim audio to the video end" option covers passthrough tracks too.
3. **Rounding:** r = llround_ms(t_k + d) from the unrounded delay, whole ms (§16).
4. **Scope:** every format in §4 before this ships (the phase column is build order only), with
   the codec-specific rules of §17.
5. **DTS Express:** in scope, with its own entry rule (§17); needs a real sample before shipping.
6. **Dialnorm:** the app does the edit itself before the mux, byte-identical to mkvmerge's (§18).

## 16. End overrun and rounding

The last kept unit starts before the video end, so the audio runs past it by less than one unit:

| Codec | Unit | Worst overrun |
|---|---|---|
| TrueHD / MLP | 40 samples @48k | < 0.83 ms |
| DTS core (disc) | 512 samples @48k | < 10.7 ms |
| AAC-LC | 1024 @48k | < 21.3 ms |
| MP2 / MP3 | 1152 @48k / @44.1k | < 24 / 26.1 ms |
| AC-3, E-AC-3 | 1536 @48k (E-AC-3 can use 256–768) | < 32 ms |
| DTS-CD 14-bit | 1024 @44.1k | < 23.2 ms |
| HE-AAC, DTS-HD MA coreless | 2048 @48k | < 42.7 ms |
| AC-3 @32 kHz | 1536 @32k | < 48 ms |
| DTS Express | 4096 @48k | < 85.3 ms |
| Opus | sample-exact (end granule) | 0 |

Rounding: Matroska stores times in whole ms (with video). Today the app rounds the delay to a whole
ms and mkvmerge then rounds each block's time; with §5 the residual is rounded and each block's
time again. For 48 kHz AC-3/E-AC-3 block times are whole ms, so only one rounding happens either
way. For units that aren't whole ms (AAC, DTS, TrueHD, 44.1 kHz) a block can be up to ~0.83 ms
off.

**Decision (2026-10-25): keep the whole-ms residual r.** Per-frame exact times (a decimal-ms
`--sync` in MKVToolNix-Mod, or a timestamp file) were considered and dropped. The file only keeps
whole-ms times, and a raw extraction keeps none, so the only delay that survives
extract → remux is the first block's whole ms (`minimum_timestamp`). With r whole, the output is
exactly what a remux of the extracted track at that offset gives, so the timing is stable across
round trips. Finer per-frame times would be lost, and changed by up to 1 ms, on the first remux.
The sub-ms remainder (≤ 0.5 ms) is below the file's own 1 ms resolution. Only the FLAC route
can carry sub-ms precision, and it survives extraction because the delay is in the samples.

## 17. Codec-specific rules beyond "whole units"

Cutting here is what mkvmerge does and what a player does on a seek: whole units are dropped,
nothing inside a kept unit changes. The only thing lost is decoder state from dropped units; every
format below has defined restart points for exactly that.

- **TrueHD / Atmos:** start on a major sync. At a major sync every substream restarts, including
  the 16-channel Atmos presentation (FFmpeg checks `nonrestart_substr` for all substreams).
  Keep the slice contiguous: HDMI/MAT passthrough pads from the `input_timing` difference between
  consecutive AUs. **Never edit dialnorm on TrueHD**: Doom9 reports that eac3to's TrueHD dialnorm
  edit breaks Atmos (the app passes the option only for AC-3/E-AC-3 today; keep it that way).
- **E-AC-3 / JOC (Atmos in DD+):** keep each independent frame with its dependent frames (the JOC
  and object metadata ride in the last dependent substream when there is one). JOC interpolates its
  matrix from the previous frame, so the first frame after a start cut is approximate, as after any
  seek (spec reading; no sample).
- **DTS-HD MA / DTS:X:** keep core + EXSS together; DTS:X data is inside the XLL frame of the same
  packet. After a start cut the lossless output takes 1–30 frames to become bit-exact (core
  history), the same as mkvmerge's cut today. Real sample available: Detective Dee BD DTS:X 7.1
  (FFmpeg fork `samples/dtsx/`, 30 s).
- **DTS Express (LBR):** a different codec in a DTS-HD wrapper, no core. Its packets are 4096
  samples, and only some carry a *decoder-init* header (like a key frame); the others can't start a
  decoder. mkvmerge counts the packets before the first init as 0 samples (reading of its source),
  so a cut that starts on a non-init packet is mis-timed as well as undecodable. Rule: walk forward
  to the first init packet.
- **E-AC-3 additional independent substreams** (substream id > 0): mkvmerge already mis-times them;
  refuse (`untouched`) and log.

## 18. Dialnorm removal done by the app

mkvmerge's `--remove-dialog-normalization-gain` is a fixed header edit (MKVToolNix source):

- **AC-3 / E-AC-3:** set `dialnorm` (and `dialnorm2` for dual mono) to 31 (no attenuation), recompute
  CRC1 (AC-3 only) and CRC2; if CRC2 would equal the sync word, set the `crcrsv` bit and recompute.
- **DTS core:** 4-bit field to 0 (no header-CRC update in mkvmerge; check what to do when the
  header CRC is present). **DTS EXSS:** 5-bit field to 0, recompute the EXSS header CRC.
- **TrueHD:** 2.0/5.1/7.1 dialnorm fields in each major sync to 31, recompute the major-sync
  checksum. Not used (§17).

The app does the same edit on the cut file before the mux and stops passing the option to
mkvmerge. Then the MKV holds exactly the bytes of our file, and the post-mux V2 check is exact.
Proof before use: our edited units must be byte-identical to mkvmerge's own output with the
option, on every AC-3/E-AC-3 sample. Whether the E-AC-3 dialnorm edit is safe for JOC Atmos is
untested (same caution as TrueHD).

## 19. Other ways to get sample-exact lossy tracks (not in this plan)

- **Lossless kept, lossy re-made from it:** some groups edit the lossless track sample-exactly and
  re-encode the lossy track from it. That only works when a lossless track of the same mix
  exists. Your rule (keep lossless; keep lossy only when there is no lossless) means a kept lossy
  track never has one, so this doesn't apply. It is also a new lossy generation, and FFmpeg's
  AC-3 encoder never uses short blocks (worse on transients than Dolby's).
- **Lossless → edit → re-encode to TrueHD:** lossless either way, but loses Atmos objects
  (FFmpeg decodes only up to the 7.1 presentation) and FFmpeg's TrueHD encoder is experimental.
  The FLAC route already gives a sample-exact lossless result for non-Atmos tracks.

## 20. Samples still needed

TrueHD Atmos, E-AC-3 JOC (Atmos), E-AC-3 7.1 (core + dependent) and 1/2/3-block, DTS Express,
HE-AAC, real MP2/MP3. Available: Detective Dee DTS:X, FFmpeg sample archive (DTS variants, AAC,
MP3, Opus, Vorbis), the library (AC-3, E-AC-3 5.1/2.0, TrueHD 5.1/2.0, PCM).

## 21. Build status (2026-10-25)

Built on `claude/audio-work-status-53134d`, not committed:

- `vsg_core/audio_processing/frames.py`, `passthrough.py`, `dialnorm.py`, `ogg_opus.py`;
  `passthrough` route in `AudioProcessingStep`; `PlanItem.mux_sync_ms / dialnorm_removed /
  mux_disable_lacing`; options builder; `AudioPassthroughAuditor`; duration auditor rule;
  trim option relabelled "Trim audio to the video end".
- Before replacing the extraction, the cut file is re-parsed against the plan, compared with the
  source (sha256, or byte-by-byte outside the dialnorm/CRC fields), and must be identified by
  `mkvmerge -J` exactly like the extraction.
- Not cut by the app (today's mkvmerge path, logged): Vorbis (cut by mkvmerge, warned about for
  negative delays: laced, FFmpeg places it 9.33 ms early),
  DTS Express streams with sync-only packets (none seen yet), ALAC/TTA/WavPack, float and 20-bit PCM.

Validation (`Tests/audio_negative_sync/`):

- `app_frames_sweep.py`: parser == mkvmerge's packetisation on 250/250 accepted tracks (AC-3 32,
  E-AC-3 27, DTS 59, TrueHD 11, MLP 4, AAC 86, MP2/MP3 31); 3 refusals (MP3 rate changes, a DTS
  cut starting on an orphan extension).
- `dialnorm_parity.py`: the app's dialnorm edit is byte-identical to mkvmerge's on 28 AC-3/E-AC-3
  files (DVD, BD, WEB, 7.1, dual mono).
- `app_cut_sweep.py`: 1773 cases pass against mkvmerge's own cut (same blocks, first block at r,
  times within 0.95 ms); TrueHD: mkvmerge's own cut kept 2–126 undecodable AUs before ours.
- Dungeon ep 1 job (`dungeon_passthrough/`): E-AC-3 frames identical in bytes and times to the
  10-25 job's first 47,844; 2,044 frames past the video end dropped, ends 7 ms after it; all
  audits pass.
- `pytest tests/`: 292 passed (18 new in `tests/test_passthrough_cuts.py`).

Format gaps after checking the FFmpeg sample sets (2026-10-25):

- **Tested since:** E-AC-3 JOC Atmos 7.1 (`fate-suite/eac3/the_great_wall_7.1.eac3`) and E-AC-3
  7.1 core + dependent (`A-codecs/AC3/eac3/7_pt_1.eac3`, HD DVD `7_pt_1_sample.evo`): all cut cases
  pass. DTS:X (BD, Detective Dee, `FFmpeg/samples/dtsx/`): all cut cases pass. HE-AAC / HEv2:
  34 conformance and real files in the AAC set, all pass.
- **TrueHD Atmos and DTS Express:** tested on real samples since (below).

DTS Express, tested 2026-10-25 on FFmpeg trac #6559 (`DTS_EXPRESS_256_5.1.dtshd`, 5.1, 18.9 s;
`Tests/audio_negative_sync/dts_express_check.py`): every packet carries a decoder-init header;
the app's 221 packets == mkvmerge's (positions, sizes, times); all 6 cut cases give
mkvmerge-identical blocks; the cut decode lines up with the uncut decode at exactly the expected
sample (parametric codec: it settles to about -40 dB of the signal after two packets, never
bit-identical, the same for mkvmerge's own cut). Rule: an Express packet is an entry unit only
with a decoder-init header; a stream with sync-only packets is refused (mkvmerge's timing of those
is unverified).

TrueHD Atmos 7.1, tested 2026-10-25 on a real UHD (Resident Evil: Apocalypse, Disc-Remuxer +
MKVToolNix-Mod rip, first 180 s; `Tests/audio_negative_sync/atmos_check.py`): major syncs are
irregular on this disc (1 to 128 AUs apart), which the parser follows. All 6 cut cases pass on the
TrueHD Atmos, AC-3, DTS-HD MA and DTS tracks of the title. mkvmerge's own cut kept 35 to 98
undecodable AUs before ours. Every cut starts on a major sync; mkvmerge still identifies
"TrueHD Atmos" and ffprobe "Dolby TrueHD + Dolby Atmos"; the fork's strict decode (which requires
every substream, the Atmos presentation included, to restart at a major sync) passes with no
message; the decoded 7.1 bed is bit-identical to the uncut decode from the same sample.

The Atmos objects themselves, decoded with truehdd (presentation 3 -> Dolby Atmos master file set;
built from the user's copy in Tests/Disc-Remuxer/inputs/sources/truehdd;
`Tests/audio_negative_sync/atmos_truehdd_check.py`):

- `truehdd verify`: the uncut and every cut stream are CONFORMANT (Blu-ray / HD DVD valid).
- Object audio (LFE bed + 11 objects, 24-bit) of the cut is bit-identical to the uncut decode from
  the cut point.
- Object metadata: the first object metadata in the cut arrives 30.5 ms after its start (the
  stream repeats the full object state periodically); that state equals the uncut stream's at the
  same moment, and all 1,658 later events are identical after the shift. Before it, a renderer has
  no positions yet, exactly as after a seek; mkvmerge's own cut decodes to the same metadata.
- truehdd's `verify` and decoder, like FFmpeg, silently skip the undecodable AUs mkvmerge's own cut
  leaves at the start, so neither catches that start; the packet check does.

Decisions 2026-10-26 before commit:

- **Lacing stays on.** `--disable-lacing` is global in mkvmerge, so it was dropped; an Opus
  passthrough track logs a warning (FFmpeg decodes variable-size Opus packets in a lace slightly
  differently), as does a Vorbis track with a negative delay (laced, a cut Vorbis plays 9.33 ms early
  in FFmpeg). The user rarely muxes either.
- **Preserved originals are cut too.** The original kept beside a stepping-corrected track goes
  through the same passthrough cut (result flagged `preserved_original`, label suffix
  "(preserved original)"), so mkvmerge never cuts audio itself, e.g. a TrueHD Atmos original.
- Start offsets of non-Source-1 tracks lost at extraction don't matter: their delay comes from
  correlating the extracted audio itself.
- **Everything reaches the final audit.** `AudioPassthroughAuditor` reports, as warnings in the
  batch report: refused cuts (muxed with mkvmerge `--sync` as before), the Opus lacing caveat, a
  Vorbis track mkvmerge cuts, and any codec the app doesn't cut whose delay is negative.
- GUI: the FLAC checkbox tooltips say what happens to a track left unticked (kept in its codec,
  cut in whole frames) and that FLAC keeps only TrueHD's top mix; the dialnorm option says the app
  makes the edit itself and never on TrueHD; the trim option is "Trim audio to the video end".

Full-length film and review (2026-10-26):

- Resident Evil: Apocalypse UHD, 93.8 min: TrueHD Atmos (6.75 M access units) cut, written and
  checked in 9 s, 355 MB private memory (the rest of the RSS is the mapped file); DTS-HD MA 15 s;
  AC-3 with the dialnorm edit 5-7 s (61 s before the numpy CRCs). The final audit extracts only the
  rewritten tracks plus every cut track's frame times with mkvextract (~45 s on 47 GB), instead of
  mkvinfo -s (2 min, 638 MB of text in memory).
- Code review fixes: the old sync audit skips tracks cut in their codec (it read an Opus pre-skip as
  a sync delay); a failed FLAC conversion or stepping correction keeps the original in its codec
  through the passthrough cut, never mkvmerge's; the first-frame check allows the file's own
  timestamp rounding; the missing-frame-table warning says no audio is trimmed.
