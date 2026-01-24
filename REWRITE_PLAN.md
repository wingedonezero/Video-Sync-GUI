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
│       │   └── controllers/      # UI logic (calls core, no business logic)
│       ├── ui/                   # .slint files
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
| UI Shell | [ ] | Main window, file inputs, log display, run button |
| Orchestrator | [ ] | Main pipeline coordinator |
| Step: Analyze | [ ] | Stub - just pass through for now |
| Step: Extract | [ ] | Stub - basic track extraction |
| Step: Mux | [ ] | Build mkvmerge command, execute |
| Config System | [ ] | Load/save settings.json with atomic writes |
| Job Layouts | [ ] | Save/load track configurations |
| Logging | [ ] | Debug levels, compact mode, pretty mkvmerge output |

---

## Architecture Principles

### Separation of Concerns
- **UI Layer** (`vsg_ui`): Only handles display and user input
  - `.slint` files define layout/styling
  - Rust controllers call into `vsg_core`, no business logic
  - UI just calls functions, doesn't contain logic

- **Core Layer** (`vsg_core`): All business logic
  - No UI dependencies whatsoever
  - Could run headless/CLI with same core

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

### Reusable Operations
If a function/operation can be reused → extract to `common/` module

Examples:
- Command execution (ffmpeg, mkvmerge, etc.)
- File I/O utilities
- Time/duration parsing
- Path resolution

### Data Flow
- Unidirectional: data flows one way through pipeline
- Context object carries state between steps
- Steps don't reach back into previous steps

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
