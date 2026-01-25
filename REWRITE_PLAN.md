# Video-Sync-GUI Rewrite Plan

## AI Rules (Must Follow)

1. **Discuss Before Changes** - No implementations without approval
2. **Libs Discussed As Needed** - Research replacements/alternatives together
3. **Research, Don't Assume** - Especially for Rust, consult official docs
4. **Latest Lib Versions** - Use latest stable, discuss issues first
5. **Rewrite for Quality** - Same features, better architecture, no single points of failure

---

## Technology Stack

- **Language**: Rust (core) + C++ (UI)
- **UI Framework**: Qt6 with C++ (native widgets, cross-platform)
- **FFI Bridge**: CXX crate (type-safe Rust ↔ C++ interop)
- **Config Format**: TOML (section-level atomic updates, human-readable with comments)
- **Merge Tool**: mkvmerge (preserve existing JSON options format exactly)
- **Build System**: Cargo workspace + CMake (Qt built via Rust build.rs)

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
│   ├── vsg_bridge/               # CXX bridge (Rust ↔ C++ FFI)
│   │   ├── src/
│   │   │   └── lib.rs            # FFI definitions + implementations
│   │   ├── build.rs              # CXX code generation
│   │   └── Cargo.toml            # crate-type = ["staticlib"]
│   └── vsg_app/                  # App launcher (builds Qt via CMake)
│       ├── src/
│       │   └── main.rs           # Exec's the Qt binary
│       ├── build.rs              # Runs CMake to build Qt UI
│       └── Cargo.toml
├── qt_ui/                        # Qt6 C++ UI
│   ├── CMakeLists.txt            # Qt build configuration
│   ├── main.cpp                  # Application entry point
│   ├── bridge/
│   │   └── vsg_bridge.hpp        # C++ wrapper for Rust FFI
│   ├── main_window/
│   │   ├── window.cpp/hpp        # Main window UI
│   │   └── controller.cpp/hpp    # Main window logic
│   ├── add_job_dialog/
│   │   └── ui.cpp/hpp            # Add job dialog
│   ├── job_queue_dialog/
│   │   ├── ui.cpp/hpp            # Job queue UI
│   │   └── logic.cpp/hpp         # Job queue logic
│   ├── manual_selection_dialog/
│   │   ├── ui.cpp/hpp            # Manual selection UI
│   │   └── logic.cpp/hpp         # Track selection logic
│   ├── track_widget/
│   │   ├── ui.cpp/hpp            # Reusable track widget
│   │   └── logic.cpp/hpp         # Track display logic
│   ├── track_settings_dialog/
│   │   ├── ui.cpp/hpp            # Per-track settings
│   │   └── logic.cpp/hpp         # Settings logic
│   └── options_dialog/
│       ├── ui.cpp/hpp            # App settings dialog
│       └── logic.cpp/hpp         # Settings persistence
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
| Project Setup | [X] | Cargo workspace, crates, Qt + CMake build |
| Models + Enums | [X] | Data types: TrackType, AnalysisMode, Track, JobSpec, etc. |
| Config System | [X] | TOML settings with section-level atomic updates |
| Logging | [X] | Per-job loggers, compact mode, file + GUI callback output |
| CXX Bridge | [X] | Rust ↔ C++ FFI with type-safe bindings |
| UI Shell | [X] | Qt main window, dialogs, log display, run button |
| Orchestrator | [X] | Main pipeline coordinator (trait, context, state, runner) |
| Step: Analyze | [X] | Audio analysis with JobLogger integration |
| Step: Extract | [X] | Stub - pass through, no extraction |
| Step: Mux | [X] | mkvmerge options builder + execution |
| Job Discovery | [X] | Bridge integration for discovering jobs from sources |
| Track Scanning | [X] | mkvmerge -J integration for reading track info |
| Job Layouts | [P] | Copy/paste track layouts (save/load TBD) |

---

## Architecture Principles

### Separation of Concerns (3 Layers)

```
┌─────────────────────────────────────────────────────────────┐
│  Qt UI Layer (qt_ui/)                                       │
│  - C++ Qt6 widgets and dialogs                              │
│  - Presentation + UI logic in same layer                    │
│  - Calls Rust via CXX bridge for backend operations         │
├─────────────────────────────────────────────────────────────┤
│  CXX Bridge (vsg_bridge/)                                   │
│  - Type-safe FFI between Rust and C++                       │
│  - Exposes vsg_core functions to C++                        │
│  - Handles data type conversions                            │
│  - Message queue for async log delivery                     │
├─────────────────────────────────────────────────────────────┤
│  Core/Backend (vsg_core/)                                   │
│  - All business logic in pure Rust                          │
│  - No UI dependencies                                       │
│  - Could run headless/CLI                                   │
└─────────────────────────────────────────────────────────────┘
```

### Qt UI Component Pattern

Each dialog/window follows this structure:
```
component/
├── ui.cpp/hpp      # QDialog/QWidget subclass, builds UI, connects signals
└── logic.cpp/hpp   # Business logic, data handling, bridge calls
```

**Bridge Access**: C++ code uses `VsgBridge::` wrapper functions that call into
the CXX-generated FFI. When bridge is unavailable (`VSG_HAS_BRIDGE` not defined),
stub implementations provide fallback behavior.

### CXX Bridge Pattern

```rust
// In vsg_bridge/src/lib.rs
#[cxx::bridge(namespace = "vsg")]
mod ffi {
    // Types shared between Rust and C++
    struct AnalysisResult {
        source_path: String,
        delay_ms: f64,
        confidence: f64,
        success: bool,
    }

    // Functions callable from C++
    extern "Rust" {
        fn bridge_run_analysis(source_paths: &[String]) -> Vec<AnalysisResult>;
        fn bridge_scan_file(path: &str) -> MediaFileInfo;
        fn bridge_log(message: &str);
        fn bridge_poll_log_message() -> String;
    }
}
```

### Orchestrator Pattern
```
Main Orchestrator
    ├── Step: Analyze (with JobLogger for per-job logging)
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
- Reports progress via callbacks / JobLogger

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

---

## Build System

### How It Works

1. `cargo build -p vsg_app` triggers the build
2. `vsg_bridge` compiles first (CXX generates headers, outputs `libvsg_bridge.a`)
3. `vsg_app/build.rs` runs CMake with paths to:
   - `libvsg_bridge.a` (Rust static library)
   - CXX-generated headers
4. CMake builds the Qt binary, linking against `libvsg_bridge.a`
5. Qt binary is copied to `target/{debug,release}/video-sync-gui-qt`
6. `vsg_app` Rust binary exec's the Qt binary

### Build Commands

```bash
# Full build
cargo build --release -p vsg_app

# Run
./target/release/video-sync-gui

# Alternative: Direct CMake (for Qt-only development)
cd qt_ui
cmake -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
```

---

## Qt UI Implementation Status

| Component | UI | Logic | Bridge | Status |
|-----------|-----|-------|--------|--------|
| MainWindow | [X] | [X] | [X] | Working - log display, run button |
| AddJobDialog | [X] | [X] | [X] | Working - source inputs, job discovery |
| JobQueueDialog | [X] | [X] | [X] | Working - table, reorder, configure jobs |
| ManualSelectionDialog | [X] | [X] | [X] | Working - track selection, drag-drop |
| TrackWidget | [X] | [X] | - | Working - reusable track display |
| TrackSettingsDialog | [X] | [X] | - | Working - per-track configuration |
| OptionsDialog | [X] | [X] | [X] | Working - app settings |
| StyleEditorDialog | [ ] | [ ] | - | Not started (complex - video preview) |

### Bridge Functions Implemented

| Function | Purpose | Status |
|----------|---------|--------|
| `bridge_run_analysis` | Run audio analysis with JobLogger | [X] |
| `bridge_scan_file` | Scan media file with mkvmerge -J | [X] |
| `bridge_discover_jobs` | Discover jobs from source paths | [X] |
| `bridge_log` | Log message to Rust logger | [X] |
| `bridge_poll_log_message` | Poll log queue for GUI display | [X] |
| `bridge_load_settings` | Load app settings | [X] |
| `bridge_save_settings` | Save app settings | [X] |

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
- **GUI display**: Stream to log panel via message queue
- **Per-job logs**: JobLogger creates separate log files per job

### GUI Integration
```rust
// In bridge: create JobLogger with GUI callback
let gui_callback: GuiLogCallback = Arc::new(|msg| {
    bridge_log(&msg);  // Queues message for C++ polling
});
let logger = JobLogger::new(&job_name, &logs_dir, config, Some(gui_callback))?;
```

```cpp
// In Qt: poll for log messages
void MainWindow::pollLogMessages() {
    while (true) {
        auto msg = VsgBridge::pollLogMessage();
        if (msg.isEmpty()) break;
        appendToLogPanel(msg);
    }
}
```

---

## mkvmerge JSON Options

**Note**: Preserve the exact JSON format from original implementation. This took significant effort to get right and is the best approach for mkvmerge integration.

Reference: `Reference Only original/vsg_core/mux/options_builder.py`

---

## Code Standards

### Naming Conventions
- Rust files: `snake_case.rs`
- C++ files: `snake_case.cpp/hpp`
- Rust types: `PascalCase`
- C++ classes: `PascalCase`
- Functions/Methods: `snake_case` (Rust), `camelCase` (C++)
- Constants: `SCREAMING_SNAKE_CASE`

### Module Structure (Rust)
Each module follows consistent layout:
```
module/
  mod.rs       # Public API only (pub use re-exports)
  types.rs     # Structs/enums for this module
  errors.rs    # Module-specific errors (if needed)
  [impl].rs    # Implementation files
```

### Component Structure (C++ Qt)
```
component/
  ui.cpp/hpp       # QWidget/QDialog with UI construction
  logic.cpp/hpp    # Business logic separate from UI
```

### Dependency Rules
```
qt_ui ──────► vsg_bridge     ✓ (UI calls bridge)
vsg_bridge ──► vsg_core      ✓ (Bridge uses core)
vsg_core ────► vsg_bridge    ✗ (Core CANNOT use bridge)
vsg_core ────► qt_ui         ✗ (Core CANNOT use UI)

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
| [X] | `audio_corr.py` | Audio cross-correlation | Core sync logic, integrated with JobLogger |
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
| [X] | `steps/analysis_step.py` | Analyze step | Full implementation with JobLogger |
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
| [X] | `job_discovery.py` | Find/match source files | Integrated via bridge |
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

### CXX Bridge (`vsg_bridge/`)
| Status | Function | Purpose | Notes |
|--------|----------|---------|-------|
| [X] | `bridge_run_analysis` | Run audio analysis | Returns AnalysisResult vec |
| [X] | `bridge_scan_file` | Scan media with mkvmerge -J | Returns MediaFileInfo |
| [X] | `bridge_discover_jobs` | Discover jobs from paths | Returns DiscoveredJob vec |
| [X] | `bridge_log` | Log to Rust logger | Queue for GUI polling |
| [X] | `bridge_poll_log_message` | Poll log queue | For Qt log panel |
| [X] | `bridge_load_settings` | Load TOML settings | Returns BridgeSettings |
| [X] | `bridge_save_settings` | Save settings | Atomic write |

---

### Qt UI Layer (`qt_ui/`)
| Status | Component | Purpose | Notes |
|--------|-----------|---------|-------|
| [X] | `main_window/` | Main window | Log panel, run button |
| [X] | `add_job_dialog/` | Add job dialog | Source inputs, browse, job discovery |
| [X] | `job_queue_dialog/` | Job queue | Table, reorder, configure, copy/paste |
| [X] | `manual_selection_dialog/` | Track selection | Source lists, final list, drag-drop |
| [X] | `track_widget/` | Track widget | Reusable component |
| [X] | `track_settings_dialog/` | Track settings | Per-track config popup |
| [X] | `options_dialog/` | App settings | Path config, logging options |
| [ ] | `style_editor_dialog/` | Style editor | Video preview - complex, deferred |

---

## Implementation Order

### Phase 1: Foundation + MVP ✓ COMPLETE
1. ✓ Project setup (Cargo workspace, crates)
2. ✓ Models + Enums (basic types)
3. ✓ Config system (load/save with atomic writes)
4. ✓ Logging infrastructure
5. ✓ CXX bridge setup
6. ✓ Qt UI shell (all major dialogs)
7. ✓ Orchestrator skeleton + stub steps
8. ✓ Mux step (mkvmerge JSON builder)
9. ✓ Analysis step with JobLogger
10. ✓ Job discovery + track scanning via bridge

### Phase 2: Core Features (Current)
- [ ] Audio correction steps (linear, PAL, stepping)
- [ ] Extraction step (tracks, attachments)
- [ ] Job layout persistence (save/load to JSON)
- [ ] Full job processing pipeline

### Phase 3: Full Features
- [ ] Subtitle processing + OCR
- [ ] Post-processing auditors
- [ ] Style editor with video preview
- [ ] All remaining features from Python original

---

## Session Notes

- **2025-01-24**: Initial plan created from Reference Only original analysis
- **2025-01-24**: Decided on Rust + Slint stack, defined MVP scope
- **2025-01-24**: Project setup complete - Cargo workspace, vsg_core lib
- **2025-01-24**: Models, Config, Logging, Orchestrator modules complete
- **2025-01-25**: Evaluated Slint vs Qt, decided to try Qt for native feel
- **2025-01-25**: Created Qt + CXX migration plan
- **2025-01-25**: Ported all dialogs to Qt/C++ (MainWindow, AddJob, JobQueue, ManualSelection, TrackSettings, Options)
- **2025-01-25**: Wired up CXX bridge - job discovery, track scanning, analysis with JobLogger
- **2025-01-25**: Fixed build system - vsg_app builds Qt via CMake, links vsg_bridge.a
- **2025-01-25**: Implemented copy/paste track layout in JobQueueDialog
- **2025-01-25**: Updated plan to reflect Qt/C++ implementation (was Slint)

---

## Key Differences from Slint Approach

| Aspect | Slint Approach | Qt/C++ Approach |
|--------|----------------|-----------------|
| UI Definition | `.slint` markup files | C++ code with Qt widgets |
| Logic Layer | Rust controllers | C++ logic classes |
| FFI | Slint's Rust bindings | CXX crate (type-safe) |
| Build | Slint compiler in build.rs | CMake called from build.rs |
| Styling | Slint theme.slint | Qt stylesheets / native |
| Dialogs | Slint components | QDialog subclasses |
| Binary | Single Rust executable | Rust launcher + Qt binary |

### Why Qt?

1. **Native look & feel** - Uses platform widgets
2. **Mature ecosystem** - Well-documented, stable
3. **Complex widgets** - Tables, trees, drag-drop work out of box
4. **Video playback** - QMediaPlayer for future style editor
5. **C++ familiarity** - Many developers know Qt
6. **Cross-platform** - Same codebase works on Linux/Windows/macOS
