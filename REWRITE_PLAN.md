# Video-Sync-GUI Rewrite Plan

## AI Rules (Must Follow)

1. **Discuss Before Changes** - No implementations without approval
2. **Libs Discussed As Needed** - Research replacements/alternatives together
3. **Research, Don't Assume** - Especially for Rust, consult official docs
4. **Latest Lib Versions** - Use latest stable, discuss issues first
5. **Rewrite for Quality** - Same features, better architecture, no single points of failure

---

## Technology Stack

- **Language**: Rust
- **UI Framework**: Slint (`.slint` markup + Rust logic = natural UI/logic separation)
- **Config Format**: JSON (same as original `settings.json`)
- **Merge Tool**: mkvmerge (preserve existing JSON options format exactly)

---

## Project Structure

```
video-sync-gui/
├── Cargo.toml                    # Workspace root
├── crates/
│   ├── vsg_core/                 # Core library (no UI dependencies)
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── models/           # Data types, enums
│   │   │   ├── config/           # Settings, atomic JSON
│   │   │   ├── orchestrator/     # Main pipeline + steps
│   │   │   ├── analysis/         # Audio correlation, drift
│   │   │   ├── correction/       # PAL, linear, stepping
│   │   │   ├── subtitles/        # Parsing, sync, OCR
│   │   │   ├── extraction/       # Track/attachment extraction
│   │   │   ├── mux/              # mkvmerge options builder
│   │   │   ├── jobs/             # Job discovery, layouts
│   │   │   ├── postprocess/      # Auditors, validation
│   │   │   ├── logging/          # Structured logging
│   │   │   └── common/           # Shared utilities, reusable ops
│   │   └── Cargo.toml
│   └── vsg_ui/                   # Slint UI application
│       ├── src/
│       │   ├── main.rs
│       │   ├── windows/          # Per-window logic
│       │   │   ├── main_window.rs
│       │   │   ├── job_queue.rs
│       │   │   ├── track_settings.rs
│       │   │   └── ...
│       │   └── common/           # Shared UI logic (reused across windows)
│       ├── ui/                   # .slint files (presentation only)
│       │   ├── main_window.slint
│       │   ├── job_queue.slint
│       │   └── ...
│       └── Cargo.toml
└── Reference Only original/      # Python reference code
```

---

## Runtime Directory Structure

All paths relative to binary location:

```
<binary_dir>/
├── video-sync-gui(.exe)
├── .config/
│   └── settings.json             # App settings
├── .logs/                        # Log files
├── .temp/                        # Temporary processing files
└── sync_output/                  # Completed merged files
```

---

## Phase 1: MVP Scope

Goal: Basic working pipeline to test architecture

| Component | Status | Description |
|-----------|--------|-------------|
| Project Setup | [X] | Cargo workspace, crates, Slint build |
| UI Shell | [P] | Main window, file inputs, log display, run button |
| Orchestrator | [ ] | Main pipeline coordinator |
| Step: Analyze | [ ] | Stub - just pass through for now |
| Step: Extract | [ ] | Stub - basic track extraction |
| Step: Mux | [ ] | Build mkvmerge command, execute |
| Config System | [ ] | Load/save settings.json with atomic writes |
| Job Layouts | [ ] | Save/load track configurations |
| Logging | [ ] | Debug levels, compact mode, pretty mkvmerge output |

---

## Architecture Principles

### Separation of Concerns (3 Layers)

```
┌─────────────────────────────────────────────────────────┐
│  UI Presentation (.slint files)                         │
│  - Layout, styling, visual elements                     │
│  - No logic whatsoever                                  │
├─────────────────────────────────────────────────────────┤
│  UI Logic (vsg_ui/src/)                                 │
│  - Window-specific logic (each window has own file)     │
│  - Common UI logic (shared across windows)              │
│  - Calls into vsg_core for backend operations           │
├─────────────────────────────────────────────────────────┤
│  Core/Backend (vsg_core/)                               │
│  - All business logic                                   │
│  - No UI dependencies                                   │
│  - Could run headless/CLI                               │
└─────────────────────────────────────────────────────────┘
```

**UI Layer** (`vsg_ui/`):
- `.slint` files = presentation only (layout, styling)
- Per-window logic files (e.g., `main_window_logic.rs`, `job_queue_logic.rs`)
- `common/` = UI logic reused across multiple windows
- Windows call their logic file OR common if shared

**Core Layer** (`vsg_core/`):
- Pure backend, zero UI dependencies
- Could be used by CLI tool with same code
- All processing, analysis, muxing logic lives here

### Orchestrator Pattern
```
Main Orchestrator
    ├── Step: Analyze (micro-orchestrator for analysis tasks)
    ├── Step: Extract (micro-orchestrator for extraction)
    ├── Step: Correct (micro-orchestrator for audio correction)
    ├── Step: Subtitles (micro-orchestrator for subtitle processing)
    ├── Step: Chapters (micro-orchestrator for chapters)
    ├── Step: Attachments (micro-orchestrator for attachments)
    └── Step: Mux (micro-orchestrator for merge)
```

Each step:
- Orchestrates its own sub-operations
- Stays focused and small
- Validates its inputs/outputs
- Reports progress via callbacks

**Step Trait Contract** (all steps implement):
```rust
trait PipelineStep {
    fn name(&self) -> &str;
    fn validate_input(&self, ctx: &Context) -> Result<()>;
    fn execute(&self, ctx: &mut Context, state: &mut JobState) -> Result<()>;
    fn validate_output(&self, ctx: &Context) -> Result<()>;
}
```

**Error Handling:**
- Errors carry context chain (Job → Step → Operation → Detail)
- Each layer adds info as errors bubble up
- Example: `Job 'movie_xyz' → MuxStep → mkvmerge → exit code 2: "Invalid track"`

### Reusable Operations

**Rule**: If code is used in 2+ places → extract to appropriate `common/` module

**Backend reuse** (`vsg_core/common/`):
- Command execution (ffmpeg, mkvmerge, etc.)
- File I/O utilities
- Time/duration parsing
- Path resolution

**UI reuse** (`vsg_ui/src/common/`):
- Shared dialog behaviors
- Common widget helpers
- Validation display patterns
- Progress/status display logic

### Data Flow
- Unidirectional: data flows one way through pipeline
- Context object carries state between steps
- Steps don't reach back into previous steps

### Job State Manifest (Write-Once Record)

Each job gets a `state.json` that records all calculated values.

**Purpose:**
- Single source of truth for job data
- Prevents accidental overwrites between steps
- Debugging: see exactly what each step calculated
- Audit trail after job completes

**Rules:**
- Steps can ADD new values (write)
- Steps CANNOT overwrite existing values (error if tried)
- Persisted atomically after each write
- Readable by any step

**Implementation:** Typed struct with `Option<T>` fields
- `None` = not set yet
- `Some(value)` = set, cannot change
- Compile-time safety for field names
- Each step's output is its own sub-struct

**File relationships:**
```
job_layout.json  → WHAT to do (track selections, user settings)
state.json       → WHAT HAPPENED (calculated values, paths, results)
mkvmerge.json    → HOW to merge (final mkvmerge command options)
```

**Location:** `.temp/<job_id>/state.json`

**Example structure:**
```json
{
  "job_id": "a1b2c3",
  "created": "2025-01-24T10:30:00Z",
  "analysis": {
    "raw_delay_ms": -178.5555,
    "confidence": 0.94,
    "drift_detected": true
  },
  "extract": {
    "video_track": "...",
    "audio_tracks": ["..."]
  },
  "mux": {
    "output_path": "...",
    "exit_code": 0
  }
}
```

---

## Config System Requirements

### On Load
1. Read `settings.json` from `.config/`
2. Validate all values against schema
3. Remove any invalid/unknown keys
4. Apply defaults for missing keys
5. Write cleaned config back (if changes made)

### At Runtime
- Single-value atomic updates only
- Don't rewrite entire file for one change
- Use file locking to prevent corruption

### Format
- Preserve exact format from original Python app
- Same key names, same structure

---

## Logging Requirements

### Levels
- Error, Warn, Info, Debug, Trace
- Configurable at runtime

### Features
- **Compact mode**: Condensed output option
- **Pretty mkvmerge**: Format mkvmerge options nicely
- **Extract debug**: Detailed extraction logging (for troubleshooting)
- **File logging**: Write to `.logs/` directory
- **UI display**: Stream to log panel in UI

---

## mkvmerge JSON Options

**Note**: Preserve the exact JSON format from original implementation. This took significant effort to get right and is the best approach for mkvmerge integration.

Reference: `Reference Only original/vsg_core/mux/options_builder.py`

---

## Code Standards

### Naming Conventions
- Files: `snake_case.rs`
- Types/Structs/Enums: `PascalCase`
- Functions/Methods: `snake_case`
- Constants: `SCREAMING_SNAKE_CASE`

### Module Structure
Each module follows consistent layout:
```
module/
  mod.rs       # Public API only (pub use re-exports)
  types.rs     # Structs/enums for this module
  errors.rs    # Module-specific errors (if needed)
  [impl].rs    # Implementation files
```

### Dependency Rules (What Can Import What)
```
vsg_ui ──────► vsg_core     ✓ (UI can use core)
vsg_core ────► vsg_ui       ✗ (Core CANNOT use UI)

Within vsg_core:
  orchestrator → steps, models, common  ✓
  steps → models, common, own domain    ✓
  models → common                       ✓
  common → (nothing - leaf module)
```

### File Guidelines
- File > ~500 lines → consider splitting
- Function > ~50 lines → consider breaking down
- `mod.rs` = re-exports only, no implementation

### Testing
- Unit tests: `#[cfg(test)]` block in same file
- Integration tests: `tests/` directory
- Each step should have basic tests

### Comments
- `///` doc comments on public items
- Inline comments explain WHY, not WHAT
- No commented-out code (git has history)

---

## Reference Code Tracking

### Legend
- `[ ]` Not Started
- `[P]` Partial
- `[X]` Implemented

---

### Data Models (`models/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `enums.py` | TrackType, AnalysisMode, SnapMode | Rust enums |
| [ ] | `media.py` | Track, StreamProps, Attachment | Structs with validation |
| [ ] | `settings.py` | AppSettings config model | Serde for JSON |
| [ ] | `jobs.py` | JobSpec, Delays, MergePlan, JobResult | Immutable structs |
| [ ] | `converters.py` | Type conversions | Trait impls (From/Into) |
| [ ] | `results.py` | Result types | Result<T, E> patterns |

---

### Configuration (`config/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `config.py` | Settings persistence | Atomic writes, validation on load |

---

### Analysis (`analysis/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `audio_corr.py` | Audio cross-correlation | Core sync logic |
| [ ] | `drift_detection.py` | DBSCAN for stepping/drift | |
| [ ] | `sync_stability.py` | Delay consistency | Quality metrics |
| [ ] | `videodiff.py` | Frame-based sync | GPU TBD |
| [ ] | `source_separation.py` | Vocal isolation | Heavy DSP |

---

### Audio Correction (`correction/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `linear.py` | Constant drift fix | ffmpeg |
| [ ] | `pal.py` | PAL speed fix | ffmpeg |
| [ ] | `stepping.py` | Stepping pattern fix | EDL timing |

---

### Subtitle Processing (`subtitles/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `data.py` | SubtitleData container | Load once, write once |
| [ ] | `convert.py` | Format conversion | ASS/SRT |
| [ ] | `edit_plan.py` | Edit operations | |
| [ ] | `frame_utils.py` | Frame timing | Precision critical |
| [ ] | `parsers/` | ASS/SRT parsing | |
| [ ] | `writers/` | ASS/SRT writing | |
| [ ] | `operations/` | Style patches, rescaling | |
| [ ] | `ocr/` | OCR subsystem | Tesseract integration |

---

### Extraction (`extraction/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `tracks.py` | Track extraction | ffmpeg/mkvextract |
| [ ] | `attachments.py` | Attachment extraction | Fonts etc |

---

### Muxing (`mux/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `options_builder.py` | mkvmerge command builder | **Preserve JSON format exactly** |

---

### Orchestrator (`orchestrator/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `pipeline.py` | Main orchestrator | Step coordination |
| [ ] | `validation.py` | Step validation | Gates between steps |
| [ ] | `steps/context.py` | Shared context | Passed through pipeline |
| [ ] | `steps/analysis_step.py` | Analyze step | |
| [ ] | `steps/extract_step.py` | Extract step | |
| [ ] | `steps/audio_correction_step.py` | Correction step | |
| [ ] | `steps/subtitles_step.py` | Subtitles step | |
| [ ] | `steps/chapters_step.py` | Chapters step | |
| [ ] | `steps/attachments_step.py` | Attachments step | |
| [ ] | `steps/mux_step.py` | Mux step | |

---

### Job Management (`jobs/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `job_discovery.py` | Find/match source files | |
| [ ] | `job_layouts/manager.py` | Layout API | |
| [ ] | `job_layouts/signature.py` | File signatures | |
| [ ] | `job_layouts/persistence.py` | Save/load JSON | |
| [ ] | `job_layouts/validation.py` | Layout validation | |

---

### Post-Processing (`postprocess/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `final_auditor.py` | Coordinate auditors | |
| [ ] | `finalizer.py` | Output finalization | |
| [ ] | `auditors/*.py` | Individual auditors (18+) | Add as needed |

---

### Logging (`logging/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | (new) | Structured logging | Compact, pretty, debug modes |

---

### Common Utilities (`common/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `io/runner.py` | Command execution | Subprocess handling |
| [ ] | (new) | File utilities | Atomic writes, path helpers |
| [ ] | (new) | Time parsing | Duration, timestamps |

---

### UI Layer (`vsg_ui/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [ ] | `main_window/` | Main window | Slint + controller |
| [ ] | `job_queue_dialog/` | Job queue | |
| [ ] | `track_settings_dialog/` | Track config | |
| [ ] | `options_dialog/` | Settings | |
| [ ] | `style_editor_dialog/` | Style editor | Video preview |
| [ ] | Other dialogs | Various | Add as needed |

---

## Implementation Order

### Phase 1: Foundation + MVP
1. Project setup (Cargo workspace, crates)
2. Models + Enums (basic types)
3. Config system (load/save with atomic writes)
4. Logging infrastructure
5. Orchestrator skeleton + stub steps
6. Mux step (mkvmerge JSON builder)
7. Basic UI shell (file select, run, log display)
8. Job layouts (save/load configurations)

### Phase 2: Core Features
- Analysis step (audio correlation)
- Extract step
- Correction steps

### Phase 3: Full Features
- Subtitle processing + OCR
- Post-processing auditors
- Full UI with all dialogs

---

## Session Notes

- **2025-01-24**: Initial plan created from Reference Only original analysis
- **2025-01-24**: Decided on Rust + Slint stack, defined MVP scope, directory structure, config/logging requirements
- **2025-01-24**: Clarified 3-layer architecture (presentation / UI logic / core), per-window logic files, common modules for reuse
- **2025-01-24**: Added Job State Manifest (write-once record), Step trait contract, error context chains
- **2025-01-24**: Added Code Standards (naming, module structure, dependency rules, file guidelines)
- **2025-01-24**: Project setup complete - Cargo workspace, vsg_core lib, vsg_ui bin with Slint, basic main window
