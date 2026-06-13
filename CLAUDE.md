# CLAUDE.md

Guidance for Claude Code (and any AI agent) working in this repo. Claude Code
auto-reads this file every session. Keep it accurate and tight — if you notice a
claim here that the code contradicts, fix the file as part of your change.

## What this is

**Video/Audio Sync & Merge** — a PySide6 desktop app that manually syncs and
merges subtitle/audio tracks into MKV files. It is **analysis-first and
manual-only**: it computes track delays (audio cross-correlation or an external
VideoDiff tool), the user explicitly picks which tracks go into the output, then
`mkvmerge` muxes the result. There is no automatic "merge plan" inference.

Two packages: `vsg_core/` (backend engine) and `vsg_qt/` (PySide6 GUI).
Entry point: `main.py` → `vsg_qt.main_window.MainWindow`.

## Commands

- **Set up the environment (first run):** `python3 setup_gui.py` — a standalone
  GUI (run with *system* Python) that builds the `.venv`, installs dependencies,
  and fetches optional GPU / OCR / audio-separator packages and model weights.
  Skip this if `CLAUDE.local.md` says this machine is already set up.
- **Run the app:** `./run.sh` (sets ROCm env vars, activates `.venv`, launches),
  or from inside the venv: `python main.py`.
- **Tests:** `pytest tests/` (single file: `pytest tests/test_pgs_timing.py`).
- **Format:** `ruff format .`
- **Lint (autofix + import sort):** `ruff check --fix .`
- **Type-check:** `pyright`
- **Pre-commit (runs ruff on commit):** install once with `pre-commit install`;
  run on demand with `pre-commit run --all-files`.

Per the gradual-migration policy below, run format/lint on the **files you
touched**, not the whole repo.

## Architecture

### Job flow

`MainController` (`vsg_qt/main_window/`) discovers jobs and hands each to a
`JobWorker` (`vsg_qt/worker/`, a background `QThreadPool` task — nothing blocks
the UI thread). The worker runs the core pipeline:

```
analyze (compute SEC/TER delays) → global shift (remove negative offsets)
→ extract tracks → subtitle transforms → optional audio correction
→ chapters + attachments → mux (mkvmerge) → post-process/validate
```

`CommandRunner` (`vsg_core/io/`) is the single choke point that shells out to
external tools with streamed log/progress callbacks.

### Design invariants (don't break these without explicit approval)

- **Manual track selection only** — no auto-merge inference.
- **Analysis-first** — delays are computed *before* extraction/mux; a global
  *non-destructive* shift eliminates negative offsets.
- **UI guardrails:** REF video only (no SEC/TER video); exactly one Default per
  type (audio/subs); at most one Forced subtitle; SRT→ASS toggle enabled only
  for real SRT inputs.

### `vsg_core/` (backend)

- `analysis/` — audio cross-correlation + VideoDiff delay analysis, stream probing, source separation
- `audit/` — append-only JSON audit trail of timing values at each pipeline step
- `chapters/` — extract / rename / shift chapters, snap to keyframes
- `correction/` — audio timing corrections: linear, PAL (24↔25 fps), stepping (silence-gated segments)
- `extraction/` — extract tracks & attachments from MKV containers
- `io/` — `CommandRunner` (external-tool execution with streamed logging)
- `job_discovery.py` — find single-file or batch jobs; match files by name across folders
- `job_layouts/` — persist / reapply per-file track-layout templates
- `models/` — shared dataclasses & Literal type aliases (see *Type organization*)
- `mux/` — `OptionsBuilder` (generate `mkvmerge` JSON option tokens)
- `orchestrator/` — modular pipeline steps with per-step validation
- `pipeline_components/` — pipeline building blocks (log manager, validators, planners, executors, auditors)
- `pipeline.py` — `JobPipeline`: coordinates one sync job end-to-end
- `postprocess/` — final output validation / audio rebasing
- `reporting/` — batch reports + debug output management
- `subtitles/` — SubtitleData container, ASS/SRT parse+write, sync/stepping/style/font operations, OCR for image subs (VobSub/PGS), CFR/VFR frame timing
- `system/` — GPU/threading environment setup
- `config.py` — `AppConfig`: load/save `settings.json`, path resolution
- `font_manager.py` — font scan/parse (fontTools + fontconfig), replacement tracking
- `favorite_colors.py` — persisted subtitle style color favorites

### `vsg_qt/` (GUI)

`main_window/` (slim `MainWindow` shell + `MainController` logic), `worker/`
(`JobWorker` thread), and feature dialogs: `manual_selection_dialog/` (track
picker), `options_dialog/` (settings), `subtitle_editor/`, `track_settings_dialog/`,
`source_settings_dialog/`, `job_queue_dialog/`, plus resample / OCR-dictionary /
sync-exclusion / report / favorites / font-manager dialogs.

### External binaries (invoked via `vsg_core/io` `CommandRunner`)

`mkvmerge`, `mkvextract`, `ffmpeg`, `ffprobe`, and optionally the external
`videodiff` tool. `VideoTimestamps` (frame/time precision) and VapourSynth are
Python libraries, not subprocesses.

## Environment gotchas

> Machine-specific paths and overrides (venv/model location, "setup already
> done", etc.) live in **`CLAUDE.local.md`** — gitignored, not committed, but
> auto-read if present. Check it for this machine's specifics.

- **Use the project `.venv`** (`run.sh` activates it). User config lives in
  `settings.json` at the repo root and is **gitignored** — it is per-user state,
  not committed.
- **GPU is AMD/ROCm on a dual-GPU box.** All GPU work MUST pin to device 0:
  `main.py` sets `HIP_VISIBLE_DEVICES=0` (via `setdefault`, so explicit overrides
  win) **before** torch/llama load, and subprocesses inherit it. Do not unset it
  — the iGPU SIGSEGVs on first kernel launch.
- **`main.py` sets critical env before any heavy import** (BLAS/OpenMP thread
  caps to 1 to avoid scipy/numpy segfaults in multi-job runs, plus the GPU pin).
  Don't reorder those lines or move imports above them.
- **Pinned deps — don't bump casually** (`pyproject.toml` explains why):
  `PySide6==6.8.2` matches the Debian 13 system Qt (Breeze theme + KIO);
  `av==16.1.0` because 17.x needs `sws_free_context()` absent from Debian
  FFmpeg 7.1.3 (and it's built `--no-binary av` for subtitle-filter support).

## Working agreement (process)

- **Discuss before non-trivial changes.** First: (1) explain the plan,
  (2) list impacted files/functions, (3) call out risks/tradeoffs, (4) get
  explicit approval. Small, local fixes (typos, an obvious bug in the same
  function) are fine — still say what you changed.
- **Work in your worktree, commit to a branch — never touch `main` directly.**
  Make edits in the workspace/worktree you were given (not the main checkout),
  and commit to a branch (it gets merged to `main` afterward). Commit or push
  only when asked.
- **Preserve behavior by default.** If a behavior change is needed, document
  what changes, why, and how it's validated.
- **Refactors keep feature parity** — improve architecture without changing
  external behavior; prefer incremental refactors over big rewrites (unless
  asked); remove single points of failure where feasible.
- **Dependencies are a discussion.** Propose options + tradeoffs; prefer fewer.
  Don't add or bump a library unprompted.
- **Research, don't assume.** When an API/behavior is uncertain, check official
  docs or upstream source. If you can't verify, say so and propose the safest path.
- **No giant diffs (gradual migration).** Format/lint and dict→dataclass
  conversions only in files you're already editing. Never mass-reformat the repo.
- **Validate risky changes** (parsing, timing, IO, concurrency, data
  transforms): add/extend tests or give a concrete validation plan (commands +
  expected output). See `tests/` for the existing timing/subtitle suites
  (PGS/VobSub timing, frame rounding, subtitle data, rescale tags).
- **On finishing:** summarize what changed and why, note any behavior changes,
  and give the format/lint/test commands for the touched files.

## Verification discipline

Habits that catch the class of subtle, long-lived bugs that look like someone
else's fault (a bad rip, a flaky tool) but turn out to be ours:

- **Validate against ground truth, not a model of it.** For timing / parsing /
  IO work, check the *real* output — extract the muxed file, read the actual
  container values — on *real* sample media, not just unit tests or an assumed
  formula. A test that exercises only your own approximation will happily agree
  with your bug.
- **A tolerance or fudge factor to make things "line up" is a red flag.** If a
  change needs a fuzzy margin to pass, the model underneath is probably wrong —
  find the exact invariant instead of widening the band.
- **Isolate before blaming an external tool or the source.** makemkv / mkvmerge
  / ffmpeg / the rip are rarely the actual cause; reproduce against ground truth
  and rule out our own math first.
- **Test the edges and every entry point.** Bugs hide in the few-percent cases
  (boundary/odd values, off-by-one, CFR vs VFR, empty input) and in paths that
  don't inherit the main one's setup (subprocesses, plugins, threads) — not in
  the typical file on the happy path.
- **For a discrete grid (frames, samples, ticks), compute it exactly** with
  integer arithmetic; don't approximate a quantized value with floats.

## Code style — "Rust-like Python" (Python 3.11+)

Explicit, typed, structured. Prioritize correctness, clarity, and
maintainability over cleverness. Tooling is enforced — **Ruff format**
(line length 88, double quotes), **Ruff check** (incl. import sorting), and
**Pyright** (standard mode). Follow `pyproject.toml`; don't hand-format or
bikeshed formatting.

- **Explicit over implicit** — no stringly-typed APIs, no `**kwargs` passthrough soup.
- **Types on ALL functions**, public and private. No `Any` without a comment justifying it.
- **Structs over dicts** — dataclasses, not `Dict[str, Any]`.
- **Fail fast** — validate at boundaries, trust internal code.
- **Readable** — small functions, clear names; comments/docstrings explain
  *why*, not *what*, and only when the intent isn't obvious.

### Dataclasses

- New dataclasses: `@dataclass(slots=True)`.
- Immutable value objects (results, flags, computed data): add `frozen=True`.
- Keep mutable for builders/accumulators (Context, editor state).
- Canonical examples live in `vsg_core/models/`.

### Dict vs dataclass

- **New structured data → dataclass**, never raw dicts.
- **Existing dicts → convert only when you modify that code.** The repo still has
  ~140 legacy `Dict[str, Any]`; migrate gradually, don't sweep.
- **External JSON / tool output** (`mkvmerge -J`, `ffprobe`) → `TypedDict` at the
  parse boundary, convert to a dataclass internally.
- **Validated external input** (config, tool-output parsing that needs coercion)
  → Pydantic v2. Internal domain models & hot paths → stdlib dataclasses.
- **Simple key→value maps** are fine as `dict[str, ConcreteType]`.

### Serialized fields: Literal, not Enum

Fields that serialize to JSON (AppSettings, config) use **Literal type aliases**,
not Enums — JSON-native, no `.value`, type-checked. Shared aliases live in
`vsg_core/models/types.py` (e.g. `TrackTypeStr`, `AnalysisModeStr`, `SnapModeStr`).
All `AppSettings` fields must be JSON-native: `str` / `int` / `float` / `bool` /
`list` / `None`.

### Banned patterns (fix when you're already in that code)

| Bad | Good |
|-----|------|
| `Dict[str, Any]` | dataclass or `TypedDict` |
| `List[Dict[str, Any]]` | `list[SomeDataclass]` |
| `config: dict` | `config: AppSettings` |
| `**kwargs` passthrough | explicit parameters |

### Type organization

- **Shared across 2+ unrelated modules → `vsg_core/models/`**
  (`types.py` aliases, `media.py`, `jobs.py`, `settings.py`, `context_types.py`,
  `converters.py`).
- **Used in one subpackage → keep it local** (e.g.
  `vsg_core/subtitles/data.py`, `vsg_core/subtitles/edit_plan.py`).
- Rule of thumb: if you need to import a type into an *unrelated* module, move it
  to `models/`.

## Reference

- **`docs/README.md`** — exhaustive technical docs (analysis math, mkvmerge
  tokenization, pipeline phases, UI guardrails). Trust the code over its
  directory-tree section, which predates the current package split.
