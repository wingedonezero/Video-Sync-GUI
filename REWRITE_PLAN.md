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
- **Config Format**: TOML (section-level atomic updates, human-readable with comments)
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
│       │   ├── windows/          # Per-window Rust logic
│       │   │   ├── main_window.rs
│       │   │   ├── job_queue.rs
│       │   │   ├── track_settings.rs
│       │   │   └── ...
│       │   └── common/           # Shared UI logic (reused across windows)
│       ├── slint/                # .slint files (presentation only)
│       │   ├── windows/          # Window definitions
│       │   │   ├── main_window.slint
│       │   │   ├── job_queue.slint
│       │   │   └── ...
│       │   ├── components/       # Reusable widgets
│       │   │   ├── log_panel.slint
│       │   │   ├── track_widget.slint
│       │   │   └── ...
│       │   └── theme.slint       # Shared colors, fonts, spacing
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
│   └── settings.toml             # App settings (TOML format)
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
| Models + Enums | [X] | Data types: TrackType, AnalysisMode, Track, JobSpec, etc. |
| Config System | [X] | TOML settings with section-level atomic updates |
| Logging | [X] | Per-job loggers, compact mode, file + GUI callback output |
| UI Shell | [P] | Main window, file inputs, log display, run button |
| Orchestrator | [X] | Main pipeline coordinator (trait, context, state, runner) |
| Step: Analyze | [X] | Stub - pass through with zero delays |
| Step: Extract | [X] | Stub - pass through, no extraction |
| Step: Mux | [X] | mkvmerge options builder + execution |
| Job Layouts | [ ] | Save/load track configurations |

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
1. Read `settings.toml` from `.config/`
2. Validate all values against schema
3. Apply defaults for missing keys (via serde `#[serde(default)]`)
4. Write cleaned config back (if changes made)

### At Runtime
- Section-level atomic updates (only changed section rewritten)
- Uses `toml_edit` to preserve comments and formatting
- Write to temp file, then atomic rename

### Format
- TOML for human-readability and comment support
- Sections: paths, logging, analysis, chapters, postprocess

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
| [X] | `enums.py` | TrackType, AnalysisMode, SnapMode | Rust enums with serde |
| [X] | `media.py` | Track, StreamProps, Attachment | Structs with validation |
| [X] | `settings.py` | AppSettings config model | Moved to config module |
| [X] | `jobs.py` | JobSpec, Delays, MergePlan, JobResult | Immutable structs |
| [ ] | `converters.py` | Type conversions | Trait impls (From/Into) |
| [ ] | `results.py` | Result types | Result<T, E> patterns |

---

### Configuration (`config/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [X] | `config.py` | Settings persistence | TOML format, section-level atomic updates, validation on load |

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
| [X] | `options_builder.py` | mkvmerge command builder | Builds command-line tokens, handles delays |

---

### Orchestrator (`orchestrator/`)
| Status | Original | Purpose | Notes |
|--------|----------|---------|-------|
| [X] | `pipeline.py` | Main orchestrator | Pipeline runner with step coordination |
| [X] | `validation.py` | Step validation | Built into PipelineStep trait |
| [X] | `steps/context.py` | Shared context | Context + JobState structs |
| [X] | `steps/analysis_step.py` | Analyze step | Stub implementation |
| [X] | `steps/extract_step.py` | Extract step | Stub implementation |
| [ ] | `steps/audio_correction_step.py` | Correction step | |
| [ ] | `steps/subtitles_step.py` | Subtitles step | |
| [ ] | `steps/chapters_step.py` | Chapters step | |
| [ ] | `steps/attachments_step.py` | Attachments step | |
| [X] | `steps/mux_step.py` | Mux step | mkvmerge options builder |

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
| [X] | (new) | Structured logging | tracing + per-job loggers, compact mode, file + GUI callback |

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
- **2025-01-24**: Models module complete - enums, media types, job types
- **2025-01-24**: Config module complete - TOML format with section-level atomic updates
- **2025-01-24**: Logging module complete - tracing integration, per-job loggers with file + GUI callback, compact mode
- **2025-01-24**: Orchestrator base complete - PipelineStep trait, Context, JobState, Pipeline runner, error chain
- **2025-01-24**: Pipeline steps complete - Analyze (stub), Extract (stub), Mux with mkvmerge options builder
- **2025-01-25**: Added comprehensive UI Dialog Implementation Plan with factories and component specs

---

## UI Dialog Implementation Plan

### Overview

This section details the implementation plan for all UI dialogs needed for the job processing workflow. The goal is to implement all dialogs with proper structure, stubbing those not immediately needed while ensuring the critical path (job creation → queue → processing) works end-to-end.

### Dialog Priority Tiers

**Tier 1 - Critical Path (Must Work):**
- AddJobDialog - Entry point for creating jobs
- JobQueueDialog - Queue management and job launch
- ManualSelectionDialog - Track selection and configuration
- TrackWidget - Reusable track display component

**Tier 2 - Important (Functional with Stubs):**
- TrackSettingsDialog - Per-track configuration popup
- SourceSettingsDialog - Correlation settings per source

**Tier 3 - Stub Only (Placeholder UI):**
- StyleEditorDialog - Video preview + style editing (complex)
- GeneratedTrackDialog - Style filtering for generated tracks
- SyncExclusionDialog - Frame sync style exclusions

---

### Directory Structure

```
crates/vsg_ui/
├── src/
│   ├── main.rs
│   ├── ui.rs                          # Slint module exports
│   ├── windows/
│   │   ├── mod.rs                     # Window module exports
│   │   ├── main_window.rs             # Main window logic
│   │   ├── settings_window.rs         # Settings window logic
│   │   ├── add_job_dialog.rs          # Add job dialog logic
│   │   ├── job_queue_dialog.rs        # Job queue dialog logic
│   │   ├── manual_selection_dialog.rs # Manual selection logic
│   │   └── track_settings_dialog.rs   # Track settings logic
│   ├── components/
│   │   ├── mod.rs                     # Component exports
│   │   ├── track_widget.rs            # TrackWidget logic controller
│   │   └── source_list.rs             # Source list logic
│   └── common/
│       ├── mod.rs                     # Common UI utilities
│       ├── dialog_factory.rs          # Dialog creation factories
│       └── track_helpers.rs           # Track display helpers
├── slint/
│   ├── app.slint                      # App-level component
│   ├── theme.slint                    # Shared colors/fonts
│   ├── windows/
│   │   ├── main_window.slint
│   │   ├── settings_window.slint
│   │   ├── add_job_dialog.slint
│   │   ├── job_queue_dialog.slint
│   │   ├── manual_selection_dialog.slint
│   │   └── track_settings_dialog.slint
│   └── components/
│       ├── source_input.slint
│       ├── track_widget.slint
│       ├── track_list.slint
│       ├── source_group.slint
│       └── attachment_selector.slint
└── Cargo.toml
```

---

### Factory Patterns

#### 1. Dialog Factory (`common/dialog_factory.rs`)

```rust
//! Dialog creation and lifecycle management.
//!
//! Provides consistent patterns for creating, configuring, and
//! running modal/modeless dialogs.

use slint::ComponentHandle;
use std::sync::Arc;

/// Result of a dialog interaction
pub enum DialogResult<T> {
    /// User accepted with data
    Accepted(T),
    /// User cancelled
    Cancelled,
}

/// Factory for creating dialogs with consistent setup
pub struct DialogFactory;

impl DialogFactory {
    /// Create and configure AddJobDialog
    pub fn create_add_job_dialog(
        initial_paths: Option<Vec<String>>,
    ) -> Result<AddJobDialog, slint::PlatformError> {
        let dialog = AddJobDialog::new()?;

        // Pre-populate if paths provided (e.g., from drag-drop)
        if let Some(paths) = initial_paths {
            populate_source_inputs(&dialog, paths);
        } else {
            // Default: 2 empty source inputs
            dialog.set_source_count(2);
        }

        Ok(dialog)
    }

    /// Create and configure JobQueueDialog
    pub fn create_job_queue_dialog(
        jobs: Vec<JobData>,
        layout_manager: Arc<JobLayoutManager>,
    ) -> Result<JobQueueDialog, slint::PlatformError> {
        let dialog = JobQueueDialog::new()?;
        populate_job_table(&dialog, jobs);
        // Store layout_manager for clipboard operations
        Ok(dialog)
    }

    /// Create and configure ManualSelectionDialog
    pub fn create_manual_selection_dialog(
        track_info: TrackInfo,
        previous_layout: Option<ManualLayout>,
    ) -> Result<ManualSelectionDialog, slint::PlatformError> {
        let dialog = ManualSelectionDialog::new()?;
        populate_source_lists(&dialog, &track_info);

        if let Some(layout) = previous_layout {
            prepopulate_final_list(&dialog, layout);
        }

        Ok(dialog)
    }

    /// Create TrackSettingsDialog for a specific track type
    pub fn create_track_settings_dialog(
        track_type: TrackType,
        codec_id: &str,
        current_config: TrackConfig,
    ) -> Result<TrackSettingsDialog, slint::PlatformError> {
        let dialog = TrackSettingsDialog::new()?;
        configure_for_track_type(&dialog, track_type, codec_id);
        apply_current_values(&dialog, current_config);
        Ok(dialog)
    }
}

/// Helper to run a dialog modally and get result
pub async fn run_modal<T, D, F>(dialog: D, extract_result: F) -> DialogResult<T>
where
    D: ComponentHandle,
    F: FnOnce(&D) -> T,
{
    // Show dialog and wait for close
    dialog.show().ok();
    // ... blocking wait for dialog close ...
    // Check accept/cancel state and return result
    todo!()
}
```

#### 2. Track Widget Factory (`components/track_widget.rs`)

```rust
//! TrackWidget component logic controller.
//!
//! Creates and manages individual track display widgets
//! with their badges, controls, and configuration state.

use slint::{Model, SharedString, VecModel};
use std::rc::Rc;
use vsg_core::models::{Track, TrackType};

/// Data needed to display a track widget
#[derive(Clone, Debug)]
pub struct TrackDisplayData {
    /// Summary line (e.g., "English, AAC 5.1, 48kHz")
    pub summary: String,
    /// Source label (e.g., "Source 2")
    pub source_label: String,
    /// Badge text (e.g., "🎯 Default | 🔧 Modified")
    pub badges: String,
    /// Track type for conditional controls
    pub track_type: TrackType,
    /// Codec for subtitle-specific features
    pub codec_id: String,
    /// Available sources for sync dropdown
    pub sync_sources: Vec<String>,
    /// Current sync target
    pub sync_to_source: String,
    /// Flag states
    pub is_default: bool,
    pub is_forced: bool,
    pub has_custom_name: bool,
    /// Subtitle-specific
    pub perform_ocr: bool,
    pub convert_to_ass: bool,
    pub rescale: bool,
    pub size_multiplier: f32,
    /// Style editing state
    pub has_style_edits: bool,
}

/// Factory for creating TrackWidget display data
pub struct TrackWidgetFactory;

impl TrackWidgetFactory {
    /// Create display data from a Track and configuration
    pub fn create_display_data(
        track: &Track,
        config: &TrackConfig,
        available_sources: &[String],
    ) -> TrackDisplayData {
        TrackDisplayData {
            summary: Self::build_summary(track),
            source_label: track.source.clone(),
            badges: Self::build_badges(track, config),
            track_type: track.track_type,
            codec_id: track.codec_id.clone().unwrap_or_default(),
            sync_sources: available_sources.to_vec(),
            sync_to_source: config.sync_to_source.clone().unwrap_or_default(),
            is_default: config.is_default,
            is_forced: config.is_forced,
            has_custom_name: config.custom_name.is_some(),
            perform_ocr: config.perform_ocr,
            convert_to_ass: config.convert_to_ass,
            rescale: config.rescale,
            size_multiplier: config.size_multiplier,
            has_style_edits: config.style_patch.is_some(),
        }
    }

    /// Build the summary text for a track
    fn build_summary(track: &Track) -> String {
        let mut parts = vec![];

        // Language
        if let Some(lang) = &track.language {
            parts.push(Self::language_display(lang));
        }

        // Codec info
        if let Some(codec) = &track.codec_id {
            parts.push(Self::codec_display(codec));
        }

        // Type-specific info
        match track.track_type {
            TrackType::Audio => {
                if let Some(channels) = track.channels {
                    parts.push(Self::channel_layout(channels));
                }
            }
            TrackType::Video => {
                if let Some(res) = &track.resolution {
                    parts.push(res.clone());
                }
            }
            TrackType::Subtitles => {
                // Nothing extra for subtitles
            }
        }

        parts.join(", ")
    }

    /// Build badge string for a track
    fn build_badges(track: &Track, config: &TrackConfig) -> String {
        let mut badges = vec![];

        if config.is_default {
            badges.push("🎯 Default");
        }
        if config.is_forced {
            badges.push("⚡ Forced");
        }
        if config.custom_name.is_some() {
            badges.push("✏️ Named");
        }
        if config.perform_ocr {
            badges.push("🔤 OCR");
        }
        if config.style_patch.is_some() {
            badges.push("🎨 Styled");
        }
        if track.is_generated {
            badges.push("🔗 Generated");
        }

        badges.join(" | ")
    }

    fn language_display(code: &str) -> String {
        // Map language codes to display names
        match code {
            "eng" => "English".to_string(),
            "jpn" => "Japanese".to_string(),
            "spa" => "Spanish".to_string(),
            "und" => "Undetermined".to_string(),
            _ => code.to_uppercase(),
        }
    }

    fn codec_display(codec_id: &str) -> String {
        match codec_id {
            "A_AAC" | "A_AAC-2" => "AAC".to_string(),
            "A_AC3" => "AC3".to_string(),
            "A_DTS" => "DTS".to_string(),
            "A_FLAC" => "FLAC".to_string(),
            "A_OPUS" => "Opus".to_string(),
            "S_TEXT/ASS" => "ASS".to_string(),
            "S_TEXT/UTF8" => "SRT".to_string(),
            "S_HDMV/PGS" => "PGS".to_string(),
            "S_VOBSUB" => "VobSub".to_string(),
            _ => codec_id.to_string(),
        }
    }

    fn channel_layout(channels: u8) -> String {
        match channels {
            1 => "Mono".to_string(),
            2 => "Stereo".to_string(),
            6 => "5.1".to_string(),
            8 => "7.1".to_string(),
            _ => format!("{} ch", channels),
        }
    }
}

/// Track configuration state
#[derive(Clone, Debug, Default)]
pub struct TrackConfig {
    pub sync_to_source: Option<String>,
    pub is_default: bool,
    pub is_forced: bool,
    pub custom_name: Option<String>,
    pub custom_lang: Option<String>,
    pub perform_ocr: bool,
    pub convert_to_ass: bool,
    pub rescale: bool,
    pub size_multiplier: f32,
    pub style_patch: Option<StylePatch>,
    pub font_replacements: Option<FontReplacements>,
    pub sync_exclusion_styles: Vec<String>,
    pub sync_exclusion_mode: String,
}
```

---

### Component Specifications

#### 1. AddJobDialog

**Purpose:** Add source files and discover jobs from them.

**Slint Structure:**
```slint
// slint/windows/add_job_dialog.slint
import { VerticalBox, HorizontalBox, Button, ScrollView, LineEdit } from "std-widgets.slint";
import { SourceInput } from "../components/source_input.slint";

export struct SourceInputData {
    index: int,
    path: string,
    is_reference: bool,
}

export component AddJobDialog inherits Dialog {
    title: "Add Job(s) to Queue";
    min-width: 700px;
    min-height: 300px;

    // Data
    in-out property <[SourceInputData]> sources: [];
    in-out property <string> error-message: "";

    // Callbacks
    callback add-source();
    callback remove-source(int);
    callback browse-source(int);
    callback source-path-changed(int, string);
    callback find-and-add-jobs();
    callback cancel();

    VerticalBox {
        padding: 12px;
        spacing: 8px;

        // Scrollable source inputs area
        ScrollView {
            vertical-stretch: 1;

            VerticalBox {
                spacing: 4px;

                for source[idx] in sources: SourceInput {
                    label: source.is-reference
                        ? "Source \{source.index} (Reference):"
                        : "Source \{source.index}:";
                    path: source.path;
                    browse-clicked => { browse-source(idx); }
                    path-changed(p) => { source-path-changed(idx, p); }
                }
            }
        }

        // Add source button
        Button {
            text: "Add Another Source";
            clicked => { add-source(); }
        }

        // Error message (if any)
        if error-message != "": Text {
            text: error-message;
            color: #cc0000;
        }

        // Dialog buttons
        HorizontalBox {
            alignment: end;
            spacing: 8px;

            Button {
                text: "Cancel";
                clicked => { cancel(); }
            }
            Button {
                text: "Find & Add Jobs";
                primary: true;
                clicked => { find-and-add-jobs(); }
            }
        }
    }
}
```

**Rust Logic (`windows/add_job_dialog.rs`):**
```rust
//! Add Job Dialog logic controller.

use slint::{ComponentHandle, Model, VecModel};
use std::rc::Rc;
use std::path::PathBuf;

/// Set up all callbacks for AddJobDialog
pub fn setup_add_job_dialog(dialog: &AddJobDialog) {
    setup_source_management(dialog);
    setup_browse_buttons(dialog);
    setup_find_jobs(dialog);
}

fn setup_source_management(dialog: &AddJobDialog) {
    let dialog_weak = dialog.as_weak();

    dialog.on_add_source(move || {
        if let Some(d) = dialog_weak.upgrade() {
            let sources = d.get_sources();
            let model = sources.as_any().downcast_ref::<VecModel<SourceInputData>>().unwrap();
            let new_idx = model.row_count() as i32 + 1;
            model.push(SourceInputData {
                index: new_idx,
                path: "".into(),
                is_reference: false,
            });
        }
    });

    // Similar for remove_source...
}

fn setup_browse_buttons(dialog: &AddJobDialog) {
    let dialog_weak = dialog.as_weak();

    dialog.on_browse_source(move |idx| {
        if let Some(d) = dialog_weak.upgrade() {
            if let Some(path) = pick_video_file("Select Source") {
                // Update source at index
                update_source_path(&d, idx as usize, path);
            }
        }
    });
}

fn setup_find_jobs(dialog: &AddJobDialog) {
    let dialog_weak = dialog.as_weak();

    dialog.on_find_and_add_jobs(move || {
        if let Some(d) = dialog_weak.upgrade() {
            // Collect paths
            let sources = collect_source_paths(&d);

            // Validate
            if sources.get("Source 1").map(|s| s.is_empty()).unwrap_or(true) {
                d.set_error_message("Source 1 (Reference) cannot be empty.".into());
                return;
            }

            // Call job discovery
            match discover_jobs(&sources) {
                Ok(jobs) if jobs.is_empty() => {
                    d.set_error_message(
                        "No matching jobs could be discovered from the provided paths.".into()
                    );
                }
                Ok(jobs) => {
                    // Store discovered jobs and close dialog
                    // Parent will retrieve via get_discovered_jobs()
                    d.set_discovered_jobs(jobs);
                    d.hide().ok();
                }
                Err(e) => {
                    d.set_error_message(format!("Error: {}", e).into());
                }
            }
        }
    });
}
```

#### 2. JobQueueDialog

**Purpose:** Display and manage the job queue, launch processing.

**Slint Structure:**
```slint
// slint/windows/job_queue_dialog.slint
import { VerticalBox, HorizontalBox, Button, StandardListView, StandardTableView } from "std-widgets.slint";

export struct JobRowData {
    name: string,
    source1: string,
    source2: string,
    source3: string,
    status: string,  // "Pending", "Configured", "Processing", "Complete", "Error"
    is_configured: bool,
}

export component JobQueueDialog inherits Dialog {
    title: "Job Queue";
    min-width: 1200px;
    min-height: 600px;

    // Data
    in-out property <[JobRowData]> jobs: [];
    in-out property <[int]> selected-rows: [];
    in-out property <bool> has-clipboard: false;

    // Callbacks
    callback add-jobs();
    callback remove-selected();
    callback move-up();
    callback move-down();
    callback configure-job(int);  // row index
    callback copy-layout(int);
    callback paste-layout();
    callback start-processing();
    callback cancel();

    // Drop handling
    callback files-dropped([string]);

    VerticalBox {
        padding: 12px;
        spacing: 8px;

        // Job table
        StandardTableView {
            columns: [
                { title: "Job Name", width: 200px },
                { title: "Source 1", width: 250px },
                { title: "Source 2", width: 250px },
                { title: "Source 3", width: 200px },
                { title: "Status", width: 100px },
            ];
            rows: jobs.length;
            // ... cell content callback

            row-double-clicked(row) => { configure-job(row); }
            // Context menu handled in Rust
        }

        // Action buttons
        HorizontalBox {
            spacing: 8px;

            Button {
                text: "Add Job(s)...";
                clicked => { add-jobs(); }
            }

            Rectangle { horizontal-stretch: 1; }

            Button {
                text: "Move Up";
                clicked => { move-up(); }
            }
            Button {
                text: "Move Down";
                clicked => { move-down(); }
            }
            Button {
                text: "Remove Selected";
                clicked => { remove-selected(); }
            }
        }

        // Dialog buttons
        HorizontalBox {
            alignment: end;
            spacing: 8px;

            Button {
                text: "Cancel";
                clicked => { cancel(); }
            }
            Button {
                text: "Start Processing Queue";
                primary: true;
                clicked => { start-processing(); }
            }
        }
    }
}
```

#### 3. ManualSelectionDialog

**Purpose:** Configure final track layout by selecting from sources.

**Slint Structure:**
```slint
// slint/windows/manual_selection_dialog.slint
import { VerticalBox, HorizontalBox, Button, ScrollView, GroupBox, CheckBox } from "std-widgets.slint";
import { SourceGroup } from "../components/source_group.slint";
import { TrackList } from "../components/track_list.slint";

export struct TrackItemData {
    id: int,
    track-type: string,  // "video", "audio", "subtitles"
    summary: string,
    source: string,
    badges: string,
    is-blocked: bool,  // e.g., video from non-reference source
}

export struct SourceGroupData {
    source-key: string,
    title: string,
    tracks: [TrackItemData],
}

export component ManualSelectionDialog inherits Dialog {
    title: "Manual Track Selection";
    min-width: 1200px;
    min-height: 700px;

    // Data
    in-out property <[SourceGroupData]> source-groups: [];
    in-out property <[TrackItemData]> final-tracks: [];
    in-out property <[TrackItemData]> external-tracks: [];
    in-out property <bool> show-external-group: false;
    in-out property <string> info-message: "";

    // Attachment sources
    in-out property <[string]> available-attachment-sources: [];
    in-out property <[bool]> attachment-source-checked: [];

    // Callbacks
    callback track-double-clicked(int, string);  // track-id, source-key
    callback add-external-subtitles();
    callback open-source-settings(string);  // source-key
    callback final-track-moved(int, int);  // from-idx, to-idx
    callback final-track-removed(int);
    callback open-track-settings(int);  // track-id in final list
    callback open-style-editor(int);
    callback accept();
    callback cancel();

    VerticalBox {
        padding: 12px;
        spacing: 8px;

        // Info message
        if info-message != "": Text {
            text: info-message;
            color: #228b22;
            font-weight: bold;
        }

        // Main content - two panes
        HorizontalBox {
            vertical-stretch: 1;
            spacing: 12px;

            // Left pane - Source tracks
            VerticalBox {
                horizontal-stretch: 1;

                ScrollView {
                    vertical-stretch: 1;

                    VerticalBox {
                        spacing: 8px;

                        for group in source-groups: SourceGroup {
                            title: group.title;
                            tracks: group.tracks;

                            track-double-clicked(id) => {
                                track-double-clicked(id, group.source-key);
                            }
                            configure-correlation => {
                                open-source-settings(group.source-key);
                            }
                        }

                        // External subtitles group
                        if show-external-group: SourceGroup {
                            title: "External Subtitles";
                            tracks: external-tracks;
                            track-double-clicked(id) => {
                                track-double-clicked(id, "External");
                            }
                        }
                    }
                }

                Button {
                    text: "Add External Subtitle(s)...";
                    clicked => { add-external-subtitles(); }
                }
            }

            // Right pane - Final output
            VerticalBox {
                horizontal-stretch: 2;

                GroupBox {
                    title: "Final Output (Drag to reorder)";
                    vertical-stretch: 1;

                    TrackList {
                        tracks: final-tracks;
                        reorderable: true;

                        track-moved(from, to) => { final-track-moved(from, to); }
                        track-removed(idx) => { final-track-removed(idx); }
                        settings-clicked(id) => { open-track-settings(id); }
                        style-editor-clicked(id) => { open-style-editor(id); }
                    }
                }

                // Attachments
                GroupBox {
                    title: "Attachments";

                    HorizontalBox {
                        spacing: 8px;

                        Text { text: "Include attachments from:"; }

                        for source[idx] in available-attachment-sources: CheckBox {
                            text: source;
                            checked: attachment-source-checked[idx];
                            toggled => {
                                // Update attachment selection
                            }
                        }
                    }
                }
            }
        }

        // Dialog buttons
        HorizontalBox {
            alignment: end;
            spacing: 8px;

            Button {
                text: "Cancel";
                clicked => { cancel(); }
            }
            Button {
                text: "OK";
                primary: true;
                clicked => { accept(); }
            }
        }
    }
}
```

#### 4. TrackWidget Component

**Purpose:** Reusable track display with controls.

**Slint Structure:**
```slint
// slint/components/track_widget.slint
import { HorizontalBox, VerticalBox, CheckBox, ComboBox, Button } from "std-widgets.slint";

export component TrackWidget inherits Rectangle {
    in property <string> summary;
    in property <string> source-label;
    in property <string> badges;
    in property <string> track-type;
    in property <[string]> sync-sources;
    in-out property <string> sync-to-source;
    in-out property <bool> is-default;
    in-out property <bool> is-forced;
    in-out property <bool> has-custom-name;

    // Visibility flags for conditional controls
    in property <bool> show-sync-control: track-type != "video";
    in property <bool> show-style-editor: track-type == "subtitles";

    // Callbacks
    callback settings-clicked();
    callback style-editor-clicked();
    callback default-changed(bool);
    callback forced-changed(bool);
    callback sync-source-changed(string);

    min-height: 60px;
    padding: 5px;

    VerticalBox {
        spacing: 4px;

        // Top row: summary + badges + source
        HorizontalBox {
            Text {
                text: summary;
                font-weight: bold;
                horizontal-stretch: 1;
            }

            if badges != "": Text {
                text: badges;
                color: #e0a800;
                font-weight: bold;
            }

            Text {
                text: source-label;
                color: #666666;
            }
        }

        // Bottom row: controls
        HorizontalBox {
            spacing: 8px;
            alignment: end;

            if show-sync-control: HorizontalBox {
                spacing: 4px;
                Text { text: "Sync to:"; vertical-alignment: center; }
                ComboBox {
                    model: sync-sources;
                    current-value <=> sync-to-source;
                    selected(val) => { sync-source-changed(val); }
                }
            }

            CheckBox {
                text: "Default";
                checked <=> is-default;
                toggled => { default-changed(self.checked); }
            }

            CheckBox {
                text: "Forced";
                checked <=> is-forced;
                toggled => { forced-changed(self.checked); }
            }

            if show-style-editor: Button {
                text: "Style Editor...";
                clicked => { style-editor-clicked(); }
            }

            Button {
                text: "Settings...";
                clicked => { settings-clicked(); }
            }
        }
    }
}
```

#### 5. TrackSettingsDialog

**Purpose:** Per-track configuration popup.

**Slint Structure:**
```slint
// slint/windows/track_settings_dialog.slint
import { VerticalBox, HorizontalBox, Button, GroupBox, ComboBox, LineEdit, CheckBox, SpinBox } from "std-widgets.slint";

export component TrackSettingsDialog inherits Dialog {
    title: "Track Settings";
    min-width: 400px;

    // Track info
    in property <string> track-type;  // "audio", "subtitles", "video"
    in property <string> codec-id;

    // Language settings
    in-out property <[string]> language-options: [];
    in-out property <string> selected-language;

    // Custom name
    in-out property <string> custom-name;

    // Subtitle-specific options
    in-out property <bool> perform-ocr;
    in-out property <bool> convert-to-ass;
    in-out property <bool> rescale;
    in-out property <float> size-multiplier: 1.0;

    // Visibility
    property <bool> show-subtitle-options: track-type == "subtitles";
    property <bool> show-ocr-option: codec-id == "S_HDMV/PGS" || codec-id == "S_VOBSUB";
    property <bool> show-sync-exclusion: codec-id == "S_TEXT/ASS" || codec-id == "S_TEXT/SSA";

    // Callbacks
    callback configure-sync-exclusion();
    callback accept();
    callback cancel();

    VerticalBox {
        padding: 12px;
        spacing: 8px;

        // Language section
        GroupBox {
            title: "Language Settings";

            HorizontalBox {
                spacing: 8px;
                Text { text: "Language:"; vertical-alignment: center; }
                ComboBox {
                    model: language-options;
                    current-value <=> selected-language;
                    horizontal-stretch: 1;
                }
            }
        }

        // Track name section
        GroupBox {
            title: "Track Name";

            HorizontalBox {
                spacing: 8px;
                Text { text: "Custom Name:"; vertical-alignment: center; }
                LineEdit {
                    text <=> custom-name;
                    horizontal-stretch: 1;
                }
            }
        }

        // Subtitle options (conditional)
        if show-subtitle-options: GroupBox {
            title: "Subtitle Options";

            VerticalBox {
                spacing: 4px;

                if show-ocr-option: CheckBox {
                    text: "Perform OCR";
                    checked <=> perform-ocr;
                }

                CheckBox {
                    text: "Convert to ASS (SRT only)";
                    checked <=> convert-to-ass;
                }

                CheckBox {
                    text: "Rescale to video resolution";
                    checked <=> rescale;
                }

                HorizontalBox {
                    spacing: 8px;
                    Text { text: "Size multiplier:"; vertical-alignment: center; }
                    SpinBox {
                        value: size-multiplier * 100;
                        minimum: 10;
                        maximum: 1000;
                        // Note: Slint SpinBox is integer, we'll convert in Rust
                    }
                    Text { text: "%"; vertical-alignment: center; }
                }

                if show-sync-exclusion: Button {
                    text: "Configure Frame Sync Exclusions...";
                    clicked => { configure-sync-exclusion(); }
                }
            }
        }

        // Dialog buttons
        HorizontalBox {
            alignment: end;
            spacing: 8px;

            Button {
                text: "Cancel";
                clicked => { cancel(); }
            }
            Button {
                text: "OK";
                primary: true;
                clicked => { accept(); }
            }
        }
    }
}
```

---

### Stub Dialogs (Tier 3 - Placeholder Only)

These dialogs will show a placeholder message and close button. Implementation deferred.

#### StyleEditorDialog (Stub)
```slint
export component StyleEditorDialog inherits Dialog {
    title: "Style Editor";
    min-width: 800px;
    min-height: 600px;

    callback close();

    VerticalBox {
        padding: 20px;

        Text {
            text: "🎨 Style Editor";
            font-size: 20px;
            font-weight: bold;
        }

        Text {
            text: "Video preview and subtitle style editing.";
            color: #666666;
        }

        Rectangle {
            vertical-stretch: 1;
            background: #f0f0f0;
            border-radius: 4px;

            Text {
                text: "Style Editor will be implemented in a future phase.\n\nThis includes:\n• Video preview panel\n• Style property editing\n• Font replacement\n• Live preview";
                horizontal-alignment: center;
                vertical-alignment: center;
            }
        }

        HorizontalBox {
            alignment: end;
            Button {
                text: "Close";
                clicked => { close(); }
            }
        }
    }
}
```

#### GeneratedTrackDialog (Stub)
```slint
export component GeneratedTrackDialog inherits Dialog {
    title: "Create Generated Track";
    min-width: 500px;

    callback close();

    VerticalBox {
        padding: 20px;

        Text {
            text: "🔗 Generated Track";
            font-size: 18px;
            font-weight: bold;
        }

        Text {
            text: "Filter styles from source track to create a new track.\n\nNot yet implemented.";
        }

        HorizontalBox {
            alignment: end;
            Button {
                text: "Close";
                clicked => { close(); }
            }
        }
    }
}
```

#### SyncExclusionDialog (Stub)
```slint
export component SyncExclusionDialog inherits Dialog {
    title: "Frame Sync Exclusions";
    min-width: 400px;

    callback close();

    VerticalBox {
        padding: 20px;

        Text {
            text: "⏭️ Sync Exclusions";
            font-size: 18px;
            font-weight: bold;
        }

        Text {
            text: "Configure which subtitle styles to exclude from frame sync.\n\nNot yet implemented.";
        }

        HorizontalBox {
            alignment: end;
            Button {
                text: "Close";
                clicked => { close(); }
            }
        }
    }
}
```

---

### Implementation Checklist

| Dialog | Slint | Rust Logic | Status |
|--------|-------|------------|--------|
| AddJobDialog | [ ] | [ ] | Not started |
| JobQueueDialog | [ ] | [ ] | Not started |
| ManualSelectionDialog | [ ] | [ ] | Not started |
| TrackWidget | [ ] | [ ] | Not started |
| TrackSettingsDialog | [ ] | [ ] | Not started |
| SourceSettingsDialog | [ ] | [ ] | Not started |
| StyleEditorDialog | [ ] | [ ] | Stub only |
| GeneratedTrackDialog | [ ] | [ ] | Stub only |
| SyncExclusionDialog | [ ] | [ ] | Stub only |

---

### Job Layout System

The job layout system enables saving and applying track configurations across similar files.

#### Core Components

```rust
// In vsg_core/src/jobs/layouts/

mod.rs           // Public API
signature.rs     // File signature generation
persistence.rs   // JSON save/load
validation.rs    // Layout compatibility checks
manager.rs       // High-level layout operations

/// Signature for matching similar files
pub struct FileSignature {
    /// Number of each track type per source
    pub track_counts: HashMap<String, TrackCounts>,
    /// Codec IDs per track
    pub codec_signatures: Vec<String>,
    /// Duration ranges
    pub duration_ms: Option<i64>,
}

/// Manager for job layouts
pub struct JobLayoutManager {
    layouts_dir: PathBuf,
}

impl JobLayoutManager {
    /// Save layout for a job
    pub fn save_layout(&self, job_id: &str, layout: &ManualLayout) -> Result<()>;

    /// Find compatible layout for new job
    pub fn find_compatible(&self, signature: &FileSignature) -> Option<ManualLayout>;

    /// Copy layout from one job to another
    pub fn copy_layout(&self, from_job: &str, to_job: &str) -> Result<()>;
}
```

#### Layout JSON Format
```json
{
  "version": 1,
  "created": "2025-01-25T10:00:00Z",
  "signature": {
    "track_counts": {
      "Source 1": { "video": 1, "audio": 2, "subtitles": 3 },
      "Source 2": { "video": 1, "audio": 2, "subtitles": 0 }
    }
  },
  "final_tracks": [
    {
      "source": "Source 1",
      "track_id": 0,
      "track_type": "video",
      "config": {}
    },
    {
      "source": "Source 1",
      "track_id": 1,
      "track_type": "audio",
      "config": {
        "is_default": true,
        "sync_to_source": "Source 1"
      }
    }
  ],
  "attachment_sources": ["Source 1"],
  "source_settings": {}
}
