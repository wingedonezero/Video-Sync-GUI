# PAL / linear drift correction — disconnected (2026-10-22), to revisit

**State:** analysis still *detects* PAL and linear drift and flags it
(`ctx.pal_drift_flags`, `ctx.linear_drift_flags`). AudioProcessingStep logs
every flagged source (`[Drift] ... correction is disconnected`) and the final
audit reports it as an issue. Nothing corrects it: the track is muxed with its
analysis delay and drifts. The correctors are kept unused in
`vsg_core/correction/pal.py` and `linear.py`. The Options switch
`drift_correction_enabled` ("Enable PAL / linear drift correction") exists,
separate from stepping, but is greyed out and not read by any code path yet.

Come back to this when there are real files to analyse (a PAL disc against a
23.976 release of the same title; a drifting DVD).

## Why it was disconnected

Measured on synthetic jobs with a known answer (10 min of Rosario ep1's real
PCM; Source 2 = a sped-up copy, 300 ms later) and the user's settings
(SCC + peak fit, 10 s windows, 50 % minimum match):

| Case | Result with the old code path |
|---|---|
| PAL, 25/23.976 (41 ms/s) | analysis fails: no window reaches 50 % |
| linear 1 ms/s (1001/1000) | analysis fails |
| linear 0.33 ms/s, FLAC | diagnosed as *stepping* (DBSCAN splits the ramp), rejected, treated as one delay; output drifts to +147 ms at 450 s, unflagged |

Root causes:

1. **Drift smears a window.** Window match on *identical* audio, 10 s windows:
   1.00 at 0 ms/s, 0.80 at 0.04, 0.57 at 0.1, 0.33 at 0.2 (the lossless
   trigger), 0.19 at 1 ms/s. Literature agrees: with drift of 0.1 % or more the
   window must be short or the peak blurs (Dan Ellis, *skewview*, LabROSA).
2. **The detector only sees windows that passed the minimum match**
   (`dense.py` marks `accepted`, `drift_detection.py` uses only accepted
   windows). So at 50 % it is handed almost nothing exactly when drift exists.
   With 5 % (the default before the Feb 2026 dense rework) linear drift *is*
   detected and corrected.
3. **The stepping check runs before the linear check**, so a slow ramp looks
   like clusters.
4. **Corrected delay taken at the early cluster, not at t = 0:** with 5 %,
   corrected tracks sit a constant −10 ms (1 ms/s) / −4 ms (0.33 ms/s) off =
   slope × time of the early cluster. The fitted line's intercept is the right
   start delay.
5. **PAL detection checks Source 1's frame rate** while the fixed slowdown it
   applies fits a sped-up *Source 2*; and it always time-stretches (rubberband),
   which is right only for pitch-corrected PAL audio.

## Facts for the redesign

- The user's Source 1 is always 23.976 (disc or WEB). Other sources are 29.97
  (NTSC DVD; film with pulldown: speed ratio 1) or 25 fps PAL.
- PAL sped-up and native PAL have the **same ratio** against a 23.976 release:
  25/23.976 = 1001/960, the 25 fps one faster. They differ in **pitch**:
  sped-up PAL audio is pitch-raised (+71 cents) or pitch-corrected; native PAL
  is original pitch with the 23.976 release slowed (pitch-lowered or corrected).
  Choose plain resample vs time-stretch by which matches the reference better.
- DVD-style drift is typically 1001/1000 (1 ms/s).
- A lone PAL disc: video cadence (2:2 film vs 50i video) and music tuning tell a
  lot. `Tests/audio_negative_sync/pal_tuning_check.py`: an uncorrected 24→25
  speed-up reads about −24…−29 cents (control-verified). Example: *The Magical
  Legend of the Leprechauns* (1999) PAL DVD = 2:2 film, +3…+7 cents, 170.9 min
  vs the NTSC DVD's listed 170 min → most likely native 25 fps.
- Airbats (US vs JP DVD, ep 1, `delay_map.py`): one flat −499 ms, ±2–3 ms
  jitter, no drift or steps — the "drift between segments" seen once was most
  likely jitter on two different masters.

## Proposed design (not built)

1. Normal analysis stays exactly as it is (delay choice, thresholds).
2. Drift probe only when the normal analysis fails or its windows form a ramp:
   known candidate ratios first — 1, 1001/1000 and inverse, and 1001/960 in the
   direction the frame rates give when one side is 25 fps — each by resample
   and by time-stretch, on Source 2 *for analysis only*; free slope from short
   windows as a last resort.
3. Safety gate: the compensated audio must pass the user's normal 10 s / 50 %
   analysis as a clean uniform delay; otherwise apply nothing and report.
4. Output through the audio finisher: exact ratio + start delay from the
   compensated analysis (t = 0), 24-bit, user's stepping labels; connect the
   `drift_correction_enabled` switch; every flagged source processed.

## Test bench (Tests/audio_negative_sync/)

- `drift_synthetic.py` — `make`, `run --repo WT --case {linear,pal_s2,pal_s1,linear_slow}`,
  `measure`; env `WINDOW_S`, `MIN_MATCH`, `CORR_METHOD`, `JOB_SUFFIX`.
- `drift_match_curve.py` — window match vs drift rate on identical audio.
- `delay_map.py` — delay over time with 4 s windows on the GPU (device 0,
  12 GiB cap, clean teardown).
- `pal_tuning_check.py` — music tuning of a lone PAL disc.
