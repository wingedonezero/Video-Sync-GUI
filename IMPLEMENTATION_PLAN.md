# Video-Sync-GUI: Rust Rewrite Implementation Plan

> **Document Version:** 1.0
> **Last Updated:** 2026-01-14
> **Status:** Initial Planning Phase

This document serves as the **comprehensive roadmap** for rewriting Video-Sync-GUI from Python to Rust. It contains everything needed to guide development, including architecture decisions, dependency mappings, UI specifications, business logic rules, and progress tracking.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Development Rules for AI/Future Chats](#2-development-rules-for-aifuture-chats)
3. [Architecture Overview](#3-architecture-overview)
4. [Dependency Replacement Matrix](#4-dependency-replacement-matrix)
5. [Python Integration Strategy](#5-python-integration-strategy)
6. [UI Implementation Plan (libcosmic)](#6-ui-implementation-plan-libcosmic)
7. [Core Module Migration Plan](#7-core-module-migration-plan)
8. [Business Logic & Special Cases](#8-business-logic--special-cases)
9. [File Structure & Output Formats](#9-file-structure--output-formats)
10. [Build & Setup Instructions](#10-build--setup-instructions)
11. [Progress Tracking](#11-progress-tracking)

---

## 1. Project Overview

### 1.1 Why Rust?

The Python implementation suffers from:
- **Dependency hell**: venv, uv, and Python version conflicts
- **Fragile environment setup**: Different systems require different configurations
- **Runtime dependency issues**: Libraries like librosa, numba, llvmlite have strict version requirements

**Rust advantages:**
- Single binary distribution (once compiled, it just works)
- No runtime dependency management for users
- Better performance for audio/video processing
- Strong type system catches errors at compile time

### 1.2 Goals

- **Exact feature parity** with Python implementation
- **Identical UI** using libcosmic (Iced-based)
- **Same output formats** (logs, JSON, temp files)
- **Preserve all business logic** and special cases
- **Minimal Python dependency** - only for source separation (demucs/torch), everything else pure Rust

### 1.3 Non-Goals

- Adding new features during rewrite
- Changing the architecture significantly
- Modifying output formats or log structures

---

## 2. Development Rules for AI/Future Chats

### 2.1 CRITICAL: Always Check Latest API Documentation

**Before implementing ANY dependency:**
1. Use web search to find the LATEST documentation
2. Verify crate versions on crates.io
3. Check for breaking changes in recent versions
4. libcosmic changes frequently - ALWAYS verify current API

### 2.2 Code Style & Organization

```
MUST FOLLOW:
- Maintain separation of core/ and ui/ directories
- Each UI window gets its own module
- Use descriptive comments explaining what each section does
- Follow the orchestrator pattern for pipeline execution
- Keep step-based processing (analysis, extraction, correction, mux)
```

### 2.3 Architecture Rules

```
PRESERVE:
- Orchestrator system with Context passing between steps
- Each pipeline step handles one specific task
- PlanItem/MergePlan/Delays model structure
- Log message format: "[TIMESTAMP] message"
- Progress callback system (0.0 to 1.0)
```

### 2.4 When Implementing UI

```
MUST DO:
1. Match Qt layout exactly - same buttons, same positions
2. Each dialog gets its own file
3. Keep UI shell thin, logic in separate controller/logic module
4. Support all keyboard shortcuts from Python version
5. Preserve drag-and-drop functionality
```

### 2.5 When Implementing Core Logic

```
MUST DO:
1. Copy business logic EXACTLY from Python
2. Keep all threshold values and magic numbers
3. Preserve all special case handling
4. Match log output format exactly
5. Keep mkvmerge JSON parsing identical
```

### 2.6 Error Handling

```
MUST DO:
- Provide detailed error messages like Python version
- Include file names, track IDs, codec info in errors
- Never silently fail - always log and propagate
```

---

## 3. Architecture Overview

### 3.1 Directory Structure (Target)

```
video-sync-gui/
├── Cargo.toml
├── build.rs                    # Build script for Python embedding
├── src/
│   ├── main.rs                 # Application entry point
│   ├── lib.rs                  # Library exports
│   │
│   ├── core/                   # vsg_core equivalent
│   │   ├── mod.rs
│   │   ├── config.rs           # AppConfig with all settings
│   │   ├── models/
│   │   │   ├── mod.rs
│   │   │   ├── jobs.rs         # JobSpec, Delays, PlanItem, MergePlan, JobResult
│   │   │   ├── media.rs        # Track, StreamProps, TrackType
│   │   │   ├── settings.rs     # AppSettings
│   │   │   ├── enums.rs        # TrackType enum
│   │   │   ├── converters.rs   # Type converters
│   │   │   └── results.rs      # Result types
│   │   │
│   │   ├── io/
│   │   │   ├── mod.rs
│   │   │   └── runner.rs       # CommandRunner for external processes
│   │   │
│   │   ├── analysis/
│   │   │   ├── mod.rs
│   │   │   ├── audio_corr.rs   # Audio correlation (SCC, GCC-PHAT, etc.)
│   │   │   ├── drift_detection.rs
│   │   │   ├── source_separation.rs  # Python bridge for demucs
│   │   │   └── videodiff.rs
│   │   │
│   │   ├── extraction/
│   │   │   ├── mod.rs
│   │   │   ├── tracks.rs       # mkvextract wrapper
│   │   │   └── attachments.rs  # Font/attachment extraction
│   │   │
│   │   ├── correction/
│   │   │   ├── mod.rs
│   │   │   ├── linear.rs       # Linear drift correction
│   │   │   ├── pal.rs          # PAL speedup correction
│   │   │   └── stepping.rs     # Stepping correction with EDL
│   │   │
│   │   ├── subtitles/
│   │   │   ├── mod.rs
│   │   │   ├── timing.rs       # Overlap/duration fixes
│   │   │   ├── convert.rs      # SRT to ASS conversion
│   │   │   ├── rescale.rs      # Resolution scaling
│   │   │   ├── style.rs        # Style manipulation
│   │   │   ├── style_engine.rs # ASS style parsing/modification
│   │   │   ├── ocr.rs          # Python bridge for OCR
│   │   │   ├── cleanup.rs      # Post-OCR cleanup
│   │   │   ├── frame_matching.rs
│   │   │   ├── frame_sync.rs
│   │   │   ├── frame_utils.rs
│   │   │   ├── metadata_preserver.rs
│   │   │   ├── stepping_adjust.rs
│   │   │   ├── checkpoint_selection.rs
│   │   │   ├── style_filter.rs
│   │   │   └── sync_modes/
│   │   │       ├── mod.rs
│   │   │       ├── time_based.rs
│   │   │       ├── duration_align.rs
│   │   │       ├── correlation_frame_snap.rs
│   │   │       ├── correlation_guided_frame_anchor.rs
│   │   │       ├── subtitle_anchored_frame_snap.rs
│   │   │       └── timebase_frame_locked_timestamps.rs
│   │   │
│   │   ├── chapters/
│   │   │   ├── mod.rs
│   │   │   ├── process.rs      # Chapter extraction/manipulation
│   │   │   └── keyframes.rs    # Keyframe snapping
│   │   │
│   │   ├── mux/
│   │   │   ├── mod.rs
│   │   │   └── options_builder.rs  # mkvmerge command builder
│   │   │
│   │   ├── orchestrator/
│   │   │   ├── mod.rs
│   │   │   ├── pipeline.rs     # Main Orchestrator
│   │   │   ├── validation.rs   # StepValidator
│   │   │   └── steps/
│   │   │       ├── mod.rs
│   │   │       ├── context.rs      # Context struct
│   │   │       ├── analysis_step.rs
│   │   │       ├── extract_step.rs
│   │   │       ├── audio_correction_step.rs
│   │   │       ├── subtitles_step.rs
│   │   │       ├── chapters_step.rs
│   │   │       ├── attachments_step.rs
│   │   │       └── mux_step.rs
│   │   │
│   │   ├── postprocess/
│   │   │   ├── mod.rs
│   │   │   ├── final_auditor.rs
│   │   │   ├── finalizer.rs
│   │   │   ├── chapter_backup.rs
│   │   │   ├── result_auditor.rs
│   │   │   └── auditors/       # All individual auditor modules
│   │   │
│   │   ├── pipeline_components/
│   │   │   ├── mod.rs
│   │   │   ├── log_manager.rs
│   │   │   ├── output_writer.rs
│   │   │   ├── result_auditor.rs
│   │   │   ├── sync_executor.rs
│   │   │   ├── sync_planner.rs
│   │   │   └── tool_validator.rs
│   │   │
│   │   ├── job_layouts/
│   │   │   ├── mod.rs
│   │   │   ├── manager.rs
│   │   │   ├── persistence.rs
│   │   │   ├── signature.rs
│   │   │   └── validation.rs
│   │   │
│   │   └── job_discovery.rs
│   │
│   ├── ui/                     # vsg_qt equivalent (libcosmic)
│   │   ├── mod.rs
│   │   ├── app.rs              # Main application state
│   │   │
│   │   ├── main_window/
│   │   │   ├── mod.rs
│   │   │   ├── view.rs         # UI layout
│   │   │   └── controller.rs   # Event handling
│   │   │
│   │   ├── options_dialog/
│   │   │   ├── mod.rs
│   │   │   ├── view.rs
│   │   │   ├── logic.rs
│   │   │   └── tabs/           # Individual tab modules
│   │   │
│   │   ├── job_queue_dialog/
│   │   │   ├── mod.rs
│   │   │   ├── view.rs
│   │   │   └── logic.rs
│   │   │
│   │   ├── add_job_dialog/
│   │   │   ├── mod.rs
│   │   │   └── view.rs
│   │   │
│   │   ├── manual_selection_dialog/
│   │   │   ├── mod.rs
│   │   │   ├── view.rs
│   │   │   ├── logic.rs
│   │   │   └── widgets.rs      # SourceList, FinalList
│   │   │
│   │   ├── track_settings_dialog/
│   │   │   ├── mod.rs
│   │   │   ├── view.rs
│   │   │   └── logic.rs
│   │   │
│   │   ├── track_widget/
│   │   │   ├── mod.rs
│   │   │   ├── view.rs
│   │   │   ├── logic.rs
│   │   │   └── helpers.rs
│   │   │
│   │   ├── style_editor_dialog/
│   │   │   ├── mod.rs
│   │   │   ├── view.rs
│   │   │   ├── logic.rs
│   │   │   ├── video_widget.rs
│   │   │   └── player_thread.rs
│   │   │
│   │   ├── resample_dialog/
│   │   │   ├── mod.rs
│   │   │   └── view.rs
│   │   │
│   │   ├── generated_track_dialog/
│   │   │   ├── mod.rs
│   │   │   └── view.rs
│   │   │
│   │   ├── sync_exclusion_dialog/
│   │   │   ├── mod.rs
│   │   │   └── view.rs
│   │   │
│   │   └── worker/
│   │       ├── mod.rs
│   │       ├── runner.rs       # Background job execution
│   │       └── signals.rs      # Thread communication
│   │
│   └── python/                 # Python embedding (optional)
│       ├── mod.rs
│       ├── bridge.rs           # PyO3 bridge for source separation
│       └── scripts/
│           └── source_separation.py  # Only Python dependency
│
├── python/                     # Bundled Python 3.13.x
│   └── (embedded python runtime)
│
├── resources/
│   └── (icons, assets)
│
└── tests/
    └── (test modules)
```

### 3.2 Core Architecture Patterns

#### Orchestrator Pattern
```rust
// The pipeline runs steps in sequence with validation
pub struct Orchestrator;

impl Orchestrator {
    pub fn run(&self, ctx: Context) -> Result<Context, PipelineError> {
        let ctx = AnalysisStep::run(ctx)?;
        StepValidator::validate_analysis(&ctx)?;

        if !ctx.and_merge {
            return Ok(ctx);
        }

        let ctx = ExtractStep::run(ctx)?;
        StepValidator::validate_extraction(&ctx)?;

        // ... more steps

        let ctx = MuxStep::run(ctx)?;
        Ok(ctx)
    }
}
```

#### Context Pattern
```rust
// Context carries all state between pipeline steps
pub struct Context {
    pub settings: AppSettings,
    pub settings_dict: HashMap<String, Value>,
    pub tool_paths: HashMap<String, Option<PathBuf>>,
    pub log: Box<dyn Fn(&str) + Send + Sync>,
    pub progress: Box<dyn Fn(f64) + Send + Sync>,
    pub output_dir: PathBuf,
    pub temp_dir: PathBuf,
    pub sources: HashMap<String, PathBuf>,
    pub and_merge: bool,
    pub manual_layout: Vec<HashMap<String, Value>>,
    pub attachment_sources: Vec<String>,

    // Filled during pipeline
    pub delays: Option<Delays>,
    pub extracted_items: Option<Vec<PlanItem>>,
    pub chapters_xml: Option<PathBuf>,
    pub attachments: Option<Vec<PathBuf>>,
    pub segment_flags: HashMap<String, HashMap<String, Value>>,
    pub pal_drift_flags: HashMap<String, HashMap<String, Value>>,
    pub linear_drift_flags: HashMap<String, HashMap<String, Value>>,
    pub source1_audio_container_delay_ms: i64,
    pub container_delays: HashMap<String, HashMap<i32, i64>>,
    pub global_shift_is_required: bool,
    pub sync_mode: String,
    pub stepping_sources: Vec<String>,
    pub stepping_detected_disabled: Vec<String>,
    pub stepping_edls: HashMap<String, Vec<AudioSegment>>,
    pub correlation_snap_no_scenes_fallback: bool,
    pub out_file: Option<PathBuf>,
    pub tokens: Option<Vec<String>>,
}
```

---

## 4. Dependency Replacement Matrix

### 4.1 GUI Framework

| Python | Rust | Notes |
|--------|------|-------|
| PySide6 (Qt6) | **libcosmic** | Iced-based, native Linux, pre-built widgets |

**libcosmic Notes:**
- Built on top of Iced
- Has pre-made widgets for common patterns
- ALWAYS check latest docs before implementing
- Repository: https://github.com/pop-os/libcosmic

### 4.2 Audio Processing

| Python | Rust | Notes |
|--------|------|-------|
| numpy | **ndarray** | N-dimensional arrays |
| scipy.signal | **rustfft** + custom | FFT, correlation, filtering |
| scipy.signal.correlate | Custom impl using rustfft | Cross-correlation |
| scipy.signal.butter | **biquad** or custom | Butterworth filter |

### 4.3 Scientific/DSP

| Python | Rust | Notes |
|--------|------|-------|
| numpy | **ndarray** | Core array operations |
| scipy | **nalgebra** + custom | Linear algebra |
| scikit-learn | **linfa** | Machine learning (DBSCAN clustering) |

### 4.4 Subtitle Processing

| Python | Rust | Notes |
|--------|------|-------|
| pysubs2 | **subparse** or custom | ASS/SSA/SRT parsing |

**Custom subtitle parser needed for:**
- Full ASS/SSA style support
- Metadata preservation
- Raw style block manipulation

### 4.5 Image Processing

| Python | Rust | Notes |
|--------|------|-------|
| Pillow | **image** | Image loading/manipulation |
| imagehash | **img_hash** or custom | Perceptual hashing |
| opencv-python | **opencv-rust** | Frame extraction |

### 4.6 Video/Frame Processing

| Python | Rust | Notes |
|--------|------|-------|
| av (PyAV) | **ffmpeg-next** | FFmpeg bindings |
| VideoTimestamps | Custom impl | VFR timestamp handling |
| ffms2 | **ffms2-rs** | Frame-accurate seeking |
| VapourSynth | **vapoursynth-rs** | High-perf frame access |
| scenedetect | Custom impl | Scene change detection |

### 4.7 Process Execution

| Python | Rust | Notes |
|--------|------|-------|
| subprocess | **std::process::Command** | Built-in |
| shlex | **shell-words** | Command quoting |

### 4.8 JSON/Serialization

| Python | Rust | Notes |
|--------|------|-------|
| json | **serde_json** | JSON parsing |
| dataclasses | **serde** derive | Struct serialization |

### 4.9 File System

| Python | Rust | Notes |
|--------|------|-------|
| pathlib | **std::path::PathBuf** | Path handling |
| tempfile | **tempfile** | Temp directories |

### 4.10 Logging

| Python | Rust | Notes |
|--------|------|-------|
| logging | **tracing** or **log** | Structured logging |

### 4.11 XML Processing

| Python | Rust | Notes |
|--------|------|-------|
| lxml | **quick-xml** or **roxmltree** | XML parsing |

### 4.12 Audio Analysis (Rust Replacements for librosa)

| Python (librosa) | Rust Crate | Notes |
|------------------|------------|-------|
| onset_strength | **aubio-rs** | Bindings to aubio library |
| mfcc | **mfcc** or custom | Mel-frequency cepstral coefficients |
| dtw | **dtw** | Dynamic time warping |
| melspectrogram | **mel-spec** or custom | Use rustfft + mel filterbank |
| power_to_db | Custom | Simple math conversion |

### 4.13 Voice Activity Detection (Rust Replacement for webrtcvad)

| Python | Rust | Notes |
|--------|------|-------|
| webrtcvad | **webrtc-vad** | Rust bindings to same underlying C library |

### 4.14 REQUIRES PYTHON (Embedded) - Minimal

| Library | Purpose | Why Python Required |
|---------|---------|---------------------|
| **demucs** | AI source separation (vocal isolation) | PyTorch model, no Rust equivalent |
| **torch** | Neural network inference for demucs | GPU acceleration |

**Note:** Python embedding is ONLY needed if source separation feature is used. All other audio analysis can be pure Rust.

---

## 5. Python Integration Strategy

### 5.1 Minimal Python Embedding (Source Separation Only)

Python is **ONLY** required for the source separation feature (demucs/torch).
All other functionality can be pure Rust.

**When Python is needed:**
- User enables source separation in settings
- demucs model requires PyTorch for inference

**Location:** `python/` directory in the distribution (optional component)

**Crate:** `pyo3` for Rust-Python interop

### 5.2 Python Bridge Architecture

```rust
// src/python/bridge.rs (only for source separation)
use pyo3::prelude::*;

pub struct SourceSeparationBridge {
    // Lazy-initialized only when source separation is requested
}

impl SourceSeparationBridge {
    pub fn new() -> PyResult<Self> {
        pyo3::prepare_freethreaded_python();
        Ok(Self {})
    }

    pub fn run_source_separation(
        &self,
        ref_audio: &[f32],
        target_audio: &[f32],
        model: &str,
        device: &str,
    ) -> PyResult<(Vec<f32>, Vec<f32>)> {
        Python::with_gil(|py| {
            let script = include_str!("scripts/source_separation.py");
            let module = PyModule::from_code(py, script, "source_separation", "source_separation")?;
            // ... call Python function
        })
    }
}
```

### 5.3 Functions Requiring Python

1. **Source Separation** (demucs) - **ONLY unavoidable Python dependency**
   - `apply_source_separation(ref_pcm, tgt_pcm, sr, config)`
   - Requires torch, demucs packages

### 5.4 Pure Rust Implementations (No Python Needed)

**Audio Correlation:**
- `_find_delay_gcc_phat()` - GCC-PHAT correlation (rustfft)
- `_find_delay_scc()` - Standard cross-correlation (rustfft)
- `_find_delay_gcc_scot()` - GCC-SCOT correlation (rustfft)
- Butterworth/band-pass filtering (biquad crate)

**Audio Analysis (replaces librosa):**
- Onset detection - aubio-rs crate
- MFCC extraction - mfcc crate or custom
- DTW alignment - dtw crate
- Mel spectrogram - rustfft + custom mel filterbank

**Voice Activity Detection (replaces webrtcvad):**
- webrtc-vad crate - Rust bindings to same C library

---

## 6. UI Implementation Plan (libcosmic)

### 6.1 Window Inventory

| Window | Python File | Description |
|--------|-------------|-------------|
| **MainWindow** | `vsg_qt/main_window/` | Main application window |
| **OptionsDialog** | `vsg_qt/options_dialog/` | Settings with 9 tabs |
| **JobQueueDialog** | `vsg_qt/job_queue_dialog/` | Batch job management |
| **AddJobDialog** | `vsg_qt/add_job_dialog/` | Add new jobs |
| **ManualSelectionDialog** | `vsg_qt/manual_selection_dialog/` | Track selection/ordering |
| **TrackSettingsDialog** | `vsg_qt/track_settings_dialog/` | Per-track options |
| **StyleEditorDialog** | `vsg_qt/style_editor_dialog/` | Subtitle style editing with video preview |
| **ResampleDialog** | `vsg_qt/resample_dialog/` | Audio resampling options |
| **GeneratedTrackDialog** | `vsg_qt/generated_track_dialog/` | Style filtering for generated tracks |
| **SyncExclusionDialog** | `vsg_qt/sync_exclusion_dialog/` | Frame sync exclusion config |

### 6.2 MainWindow Layout

```
┌─────────────────────────────────────────────────────────────┐
│ [Settings...] button                                    (top)│
├─────────────────────────────────────────────────────────────┤
│ ┌─ Main Workflow ──────────────────────────────────────────┐│
│ │ [Open Job Queue for Merging...]           (large button) ││
│ │ [x] Archive logs to a zip file on batch completion       ││
│ └──────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│ ┌─ Quick Analysis (Analyze Only) ──────────────────────────┐│
│ │ Source 1 (Reference): [________________] [Browse...]     ││
│ │ Source 2:             [________________] [Browse...]     ││
│ │ Source 3:             [________________] [Browse...]     ││
│ │                                        [Analyze Only]    ││
│ └──────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│ Status: Ready                              [Progress Bar]   │
├─────────────────────────────────────────────────────────────┤
│ ┌─ Latest Job Results ─────────────────────────────────────┐│
│ │ Source 2 Delay: — │ Source 3 Delay: — │ Source 4 Delay: —││
│ └──────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│ ┌─ Log ────────────────────────────────────────────────────┐│
│ │ [Monospace log output with scrolling]                    ││
│ │                                                          ││
│ │                                                          ││
│ └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 6.3 OptionsDialog Tabs

1. **Storage & Tools** - Paths, output folder, temp directory, tool locations
2. **Analysis** - Correlation method, filtering, scan parameters
3. **Stepping Correction** - All stepping settings (silence snap, VAD, transients)
4. **Subtitles** - Sync modes, frame matching, timing options
5. **Chapters** - Chapter processing options
6. **Timing** - Overlap/duration fix settings
7. **Subtitle Cleanup** - OCR cleanup, normalization
8. **Merge Behavior** - Track naming, post-processing
9. **Logging** - Compact mode, tail lines, progress

### 6.4 ManualSelectionDialog Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    [Info Label - contextual messages]                    │
├────────────────────────────────────┬────────────────────────────────────┤
│ LEFT PANE (Scrollable)             │ RIGHT PANE                         │
│                                    │                                    │
│ ┌─ Source 1 (Reference) ─────────┐ │ ┌─ Final Output (Drag to reorder)─┐│
│ │ [Track widgets - expandable]   │ │ │ [TrackWidgets with badges]      ││
│ └────────────────────────────────┘ │ │ - Video, Audio, Subtitles       ││
│                                    │ │ - Drag to reorder               ││
│ ┌─ Source 2 ─────────────────────┐ │ │ - Double-click for settings     ││
│ │ [Track widgets]                │ │ └────────────────────────────────┘│
│ └────────────────────────────────┘ │                                    │
│                                    │ ┌─ Attachments ─────────────────┐ │
│ ┌─ External Subtitles ───────────┐ │ │ Include from: [x]S1 [x]S2 [ ]S3││
│ │ [External sub tracks]          │ │ └────────────────────────────────┘│
│ └────────────────────────────────┘ │                                    │
│                                    │                                    │
│ [Add External Subtitle(s)...]      │                                    │
├────────────────────────────────────┴────────────────────────────────────┤
│                                              [OK] [Cancel]               │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.5 TrackWidget Features

Each track widget displays:
- Track type icon (video/audio/subtitle)
- Codec info
- Language
- Track name (if any)
- Badges: Default, Forced, Corrected, Preserved, Generated, FrameSync

Context menu actions:
- Configure... (track settings)
- Copy Styles / Paste Styles (subtitles)
- Edit Styles... (opens style editor)
- Create Generated Track... (filter styles)
- Remove from final

### 6.6 StyleEditorDialog

```
┌───────────────────────────────────────────────────────────────────────┐
│                        Subtitle Style Editor                          │
├─────────────────────────────────────────┬─────────────────────────────┤
│ VIDEO PREVIEW                           │ STYLE CONTROLS              │
│ ┌─────────────────────────────────────┐ │                             │
│ │                                     │ │ Style: [Dropdown]  [Reset] │
│ │     [Video frame with subs]         │ │                             │
│ │                                     │ │ [Strip Tags] [Resample...] │
│ └─────────────────────────────────────┘ │                             │
│ [Pause] [─────────Seek────────────────] │ ┌─ Style Properties ──────┐│
│                                         │ │ Font Name: [________]   ││
│ ┌─ Subtitle Events ─────────────────┐   │ │ Font Size: [____]       ││
│ │ # | Start | End | Style | Text    │   │ │ Primary:   [Pick...]    ││
│ │ 1 | 00:01 | ... | Main  | Hello   │   │ │ Secondary: [Pick...]    ││
│ │ 2 | 00:05 | ... | Main  | World   │   │ │ Outline:   [Pick...]    ││
│ │ ...                               │   │ │ Shadow:    [Pick...]    ││
│ └───────────────────────────────────┘   │ │ [x] Bold  [ ] Italic    ││
│                                         │ │ Outline: [__] Shadow:[__]││
│                                         │ │ Margins: L[_] R[_] V[_] ││
│                                         │ └─────────────────────────┘│
│                                         │           [OK] [Cancel]    │
└─────────────────────────────────────────┴─────────────────────────────┘
```

### 6.7 libcosmic Implementation Notes

```rust
// IMPORTANT: Always verify latest libcosmic API!
// Example structure (may change):

use cosmic::iced::widget::{button, column, container, row, text, text_input};
use cosmic::widget::{dropdown, scrollable, toggler};
use cosmic::{Application, Command, Element, Theme};

// Each window is a separate Application or a Dialog
pub struct MainWindow {
    config: AppConfig,
    log_output: String,
    progress: f32,
    status: String,
    // ... state fields
}

#[derive(Debug, Clone)]
pub enum Message {
    OpenOptions,
    OpenJobQueue,
    BrowseSource1,
    BrowseSource2,
    BrowseSource3,
    AnalyzeOnly,
    LogMessage(String),
    ProgressUpdate(f32),
    // ... more messages
}

impl Application for MainWindow {
    type Message = Message;
    type Executor = cosmic::executor::Default;
    type Flags = ();

    fn new(_flags: ()) -> (Self, Command<Message>) {
        // Initialize
    }

    fn title(&self) -> String {
        "Video/Audio Sync & Merge".into()
    }

    fn update(&mut self, message: Message) -> Command<Message> {
        match message {
            Message::OpenOptions => {
                // Open options dialog
            }
            // ... handle all messages
        }
    }

    fn view(&self) -> Element<Message> {
        // Build UI tree
    }
}
```

---

## 7. Core Module Migration Plan

### 7.1 Phase 1: Foundation (Implement First)

#### 7.1.1 Models (`src/core/models/`)

```rust
// enums.rs
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum TrackType {
    Video,
    Audio,
    Subtitles,
}

// media.rs
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StreamProps {
    pub codec_id: Option<String>,
    pub lang: Option<String>,
    pub name: Option<String>,
    pub default: bool,
    pub forced: bool,
    pub audio_channels: Option<u8>,
    pub audio_sampling_frequency: Option<u32>,
    // ... all properties from Python
}

#[derive(Debug, Clone)]
pub struct Track {
    pub source: String,
    pub id: i32,
    pub track_type: TrackType,
    pub props: StreamProps,
}

// jobs.rs
#[derive(Debug, Clone)]
pub struct Delays {
    pub source_delays_ms: HashMap<String, i64>,
    pub raw_source_delays_ms: HashMap<String, f64>,
    pub global_shift_ms: i64,
    pub raw_global_shift_ms: f64,
}

#[derive(Debug, Clone)]
pub struct PlanItem {
    pub track: Track,
    pub extracted_path: Option<PathBuf>,
    pub is_default: bool,
    pub is_forced_display: bool,
    pub apply_track_name: bool,
    pub convert_to_ass: bool,
    pub rescale: bool,
    pub size_multiplier: f64,
    pub style_patch: Option<HashMap<String, Value>>,
    pub user_modified_path: Option<PathBuf>,
    pub sync_to: Option<String>,
    pub is_preserved: bool,
    pub is_corrected: bool,
    pub correction_source: Option<String>,
    pub perform_ocr: bool,
    pub perform_ocr_cleanup: bool,
    pub container_delay_ms: i64,
    pub custom_lang: String,
    pub custom_name: String,
    pub aspect_ratio: Option<String>,
    pub stepping_adjusted: bool,
    pub is_generated: bool,
    pub generated_source_track_id: Option<i32>,
    pub generated_source_path: Option<PathBuf>,
    pub generated_filter_mode: String,
    pub generated_filter_styles: Vec<String>,
    pub generated_original_style_list: Vec<String>,
    pub generated_verify_only_lines_removed: bool,
    pub skip_frame_validation: bool,
    pub sync_exclusion_styles: Vec<String>,
    pub sync_exclusion_mode: String,
    pub sync_exclusion_original_style_list: Vec<String>,
}
```

#### 7.1.2 Config (`src/core/config.rs`)

Port ALL settings from Python with:
- Default values
- Type validation
- Migration logic for old settings
- Save/load JSON

#### 7.1.3 IO Runner (`src/core/io/runner.rs`)

```rust
pub struct CommandRunner {
    config: HashMap<String, Value>,
    log_callback: Box<dyn Fn(&str) + Send + Sync>,
}

impl CommandRunner {
    pub fn run(
        &self,
        cmd: &[&str],
        tool_paths: &HashMap<String, Option<PathBuf>>,
        is_binary: bool,
        input_data: Option<&[u8]>,
    ) -> Result<CommandOutput, CommandError> {
        // Execute subprocess
        // Handle compact logging
        // Return stdout
    }
}
```

### 7.2 Phase 2: Extraction & Analysis

#### 7.2.1 Track Extraction (`src/core/extraction/tracks.rs`)

Key functions:
- `get_stream_info()` - Parse mkvmerge -J output
- `get_stream_info_with_delays()` - Include container delays
- `extract_tracks()` - mkvextract with detailed error reporting
- `get_track_info_for_dialog()` - Combined mkvmerge + ffprobe info

#### 7.2.2 Audio Correlation (`src/core/analysis/audio_corr.rs`)

Implement in pure Rust:
- `_find_delay_gcc_phat()` - Phase correlation
- `_find_delay_scc()` - Standard correlation
- `_find_delay_gcc_scot()` - SCOT weighting
- `_apply_bandpass()` - Butterworth filter
- `_apply_lowpass()` - FIR lowpass
- `_normalize_peak_confidence()` - Confidence scoring

Python bridge for:
- `_find_delay_onset()` - librosa onset detection
- `_find_delay_dtw()` - librosa DTW
- `_find_delay_spectrogram()` - librosa mel spectrogram

### 7.3 Phase 3: Correction

#### 7.3.1 Stepping Correction (`src/core/correction/stepping.rs`)

Complex module with:
- `SteppingCorrector` struct
- Binary search for boundaries
- Silence detection (FFmpeg silencedetect)
- VAD protection (Python bridge for webrtcvad)
- Video frame snapping
- EDL generation
- Audio assembly

### 7.4 Phase 4: Subtitles

#### 7.4.1 Subtitle Processing

- Custom ASS/SSA parser (or subparse crate)
- Style manipulation engine
- Timing fixes (overlap, duration)
- Frame-locked timestamps
- Stepping adjustment

### 7.5 Phase 5: Mux & Postprocess

#### 7.5.1 Options Builder (`src/core/mux/options_builder.rs`)

Build mkvmerge command with:
- Track ordering (preserved tracks insertion)
- Delay calculation (CRITICAL logic)
- Language/name settings
- Compression settings
- Attachment handling

#### 7.5.2 Final Auditor

All auditor modules for post-merge validation.

---

## 8. Business Logic & Special Cases

### 8.1 Delay Calculation (CRITICAL)

From `vsg_core/mux/options_builder.py`:

```python
def _effective_delay_ms(self, plan: MergePlan, item: PlanItem) -> int:
    """
    CRITICAL: Video container delays from source MKV should be IGNORED.
    Video defines the timeline and should only get the global shift.

    Source 1 VIDEO: Ignore container delays, only apply global shift
    Source 1 AUDIO: Preserve individual container delays + global shift
    Source 1 SUBTITLES: Use correlation delay (0 for Source 1)
    Other Sources: Use pre-calculated correlation delay
    External Subs: Use delay from sync_to target
    """
```

**PRESERVE THIS LOGIC EXACTLY**

### 8.2 Track Ordering with Preserved Tracks

When stepping correction preserves original audio:
1. Normal tracks first
2. Insert preserved audio AFTER last main audio track
3. Insert preserved subs AFTER last main subtitle track

### 8.3 Stepping Correction Special Cases

1. **Silence Snapping**: Find silence zones in TARGET audio, not reference
2. **Video Snapping**: Validate video snap doesn't exit silence zone
3. **VAD Protection**: Never cut during detected speech
4. **Transient Avoidance**: Avoid cuts near musical attacks

### 8.4 Frame-Locked Timestamps

Order of operations:
1. Frame-align global shift to TARGET video frames
2. Snap each subtitle to TARGET frame boundaries
3. Preserve duration (adjust end with same delta)
4. Safety: If end <= start frame, push to next frame
5. Post-ASS validation after centisecond quantization

### 8.5 Generated Track Validation

When filtering styles:
- Store original style list for validation
- Verify ONLY event lines removed
- Styles and format sections unchanged

### 8.6 Correlation Method Selection

| Method | Implementation | Crate |
|--------|----------------|-------|
| Standard (SCC) | Pure Rust | rustfft |
| GCC-PHAT | Pure Rust | rustfft |
| GCC-SCOT | Pure Rust | rustfft |
| Onset Detection | Pure Rust | aubio-rs |
| DTW | Pure Rust | dtw |
| Spectrogram | Pure Rust | rustfft + custom |

**All correlation methods can be implemented in pure Rust.**

### 8.7 Language Normalization

Convert 2-letter to 3-letter codes:
```
en -> eng, ja -> jpn, jp -> jpn, zh -> zho, etc.
```

### 8.8 Error Reporting Format

Detailed errors with:
- Source identification
- Track ID and name
- Codec info
- File path
- Troubleshooting steps

---

## 9. File Structure & Output Formats

### 9.1 Log Format (PRESERVE EXACTLY)

```
[HH:MM:SS] message text
[HH:MM:SS] $ command with arguments
[HH:MM:SS] Progress: 50%
[HH:MM:SS] [Validation] Step validated successfully.
[HH:MM:SS] [FATAL] Error message
[HH:MM:SS] [WARNING] Warning message
```

### 9.2 Settings JSON Format

File: `settings.json` in script directory

All keys from Python `AppConfig.defaults` must be preserved.

### 9.3 Temp Directory Structure

```
temp_work/
└── orch_{filename}_{timestamp}/
    ├── Source_1_track_{name}_{id}.ext
    ├── Source_2_track_{name}_{id}.ext
    └── ...
```

### 9.4 Output Directory

```
sync_output/
├── {output_filename}.mkv
└── logs/
    ├── {job_name}.log
    └── archive_{timestamp}.zip  (if enabled)
```

### 9.5 mkvmerge JSON Parsing

Use exact same field paths:
- `tracks[].type`
- `tracks[].id`
- `tracks[].properties.codec_id`
- `tracks[].properties.language`
- `tracks[].properties.track_name`
- `tracks[].properties.default_track`
- `tracks[].properties.forced_track`
- `tracks[].properties.minimum_timestamp`
- `tracks[].properties.audio_channels`
- `tracks[].properties.audio_sampling_frequency`
- etc.

---

## 10. Build & Setup Instructions

### 10.1 Prerequisites

```bash
# Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# System dependencies (Ubuntu/Debian)
sudo apt install -y \
    build-essential \
    pkg-config \
    libssl-dev \
    libgtk-3-dev \
    libxkbcommon-dev \
    libwayland-dev \
    libxrandr-dev \
    libxi-dev \
    python3.13-dev \
    ffmpeg \
    mkvtoolnix

# For GPU support (optional)
# NVIDIA: Install CUDA toolkit
# AMD: Install ROCm
```

### 10.2 Building

```bash
# Development build
cargo build

# Release build (optimized)
cargo build --release

# Run tests
cargo test

# Run application
cargo run --release
```

### 10.3 Python Embedding (Optional - Source Separation Only)

Python is only needed if the source separation feature is used.

**If source separation is enabled:**
1. Download Python 3.13.x standalone build
2. Install demucs and torch packages
3. Bundle as optional component

**Without source separation:**
- Pure Rust binary, no Python needed

### 10.4 Distribution

**Minimal distribution (no source separation):**
- Single binary executable
- Resource files (icons)

**Full distribution (with source separation):**
- Single binary executable
- Bundled Python 3.13.x runtime
- demucs/torch packages
- Resource files (icons)

---

## 11. Progress Tracking

### 11.1 Implementation Status

#### Foundation
- [ ] Project structure created
- [ ] Cargo.toml with dependencies
- [ ] Models module
- [ ] Config module
- [ ] IO Runner

#### UI (Phase 1 - Do First)
- [ ] MainWindow view
- [ ] MainWindow controller
- [ ] OptionsDialog with all tabs
- [ ] JobQueueDialog
- [ ] AddJobDialog
- [ ] ManualSelectionDialog
- [ ] TrackWidget
- [ ] TrackSettingsDialog
- [ ] StyleEditorDialog
- [ ] ResampleDialog
- [ ] GeneratedTrackDialog
- [ ] SyncExclusionDialog

#### Core - Extraction
- [ ] mkvmerge JSON parsing
- [ ] Track extraction
- [ ] Attachment extraction
- [ ] ffprobe integration

#### Core - Analysis
- [ ] Audio decoding
- [ ] SCC correlation (rustfft)
- [ ] GCC-PHAT correlation (rustfft)
- [ ] GCC-SCOT correlation (rustfft)
- [ ] Onset detection (aubio-rs)
- [ ] DTW alignment (dtw crate)
- [ ] Mel spectrogram (rustfft + custom)
- [ ] Voice activity detection (webrtc-vad)
- [ ] Drift detection
- [ ] Source separation (Python bridge - optional)

#### Core - Correction
- [ ] Linear drift correction
- [ ] PAL speedup correction
- [ ] Stepping correction
- [ ] EDL generation
- [ ] Audio assembly

#### Core - Subtitles
- [ ] ASS/SSA parser
- [ ] SRT parser
- [ ] Style engine
- [ ] Timing fixes
- [ ] Frame matching
- [ ] All sync modes
- [ ] Stepping adjustment

#### Core - Pipeline
- [ ] Context struct
- [ ] Orchestrator
- [ ] AnalysisStep
- [ ] ExtractStep
- [ ] AudioCorrectionStep
- [ ] SubtitlesStep
- [ ] ChaptersStep
- [ ] AttachmentsStep
- [ ] MuxStep
- [ ] StepValidator

#### Core - Postprocess
- [ ] Final auditor
- [ ] All auditor modules
- [ ] Finalizer

#### Integration
- [ ] Python embedding (optional, for source separation only)
- [ ] End-to-end testing

### 11.2 Notes for Updates

When completing a section, update this document:
1. Mark checkbox as complete: `[x]`
2. Add any implementation notes
3. Document any deviations from plan
4. Update "Last Updated" date at top

---

## Appendix A: Key File References (Main Branch)

For detailed implementation reference, consult these files in the main branch:

| Component | File Path |
|-----------|-----------|
| Config | `vsg_core/config.py` |
| Models | `vsg_core/models/` |
| Orchestrator | `vsg_core/orchestrator/pipeline.py` |
| Context | `vsg_core/orchestrator/steps/context.py` |
| Audio Correlation | `vsg_core/analysis/audio_corr.py` |
| Stepping Correction | `vsg_core/correction/stepping.py` |
| Track Extraction | `vsg_core/extraction/tracks.py` |
| Options Builder | `vsg_core/mux/options_builder.py` |
| Subtitle Timing | `vsg_core/subtitles/timing.py` |
| Frame-Locked Sync | `vsg_core/subtitles/sync_modes/timebase_frame_locked_timestamps.py` |
| Main Window | `vsg_qt/main_window/` |
| Options Dialog | `vsg_qt/options_dialog/` |
| Manual Selection | `vsg_qt/manual_selection_dialog/` |
| Style Editor | `vsg_qt/style_editor_dialog/` |

---

## Appendix B: Critical Constants & Thresholds

Preserve these exact values:

```rust
// Audio processing
const DEFAULT_SAMPLE_RATE: u32 = 48000;
const BUFFER_ALIGNMENT_SIZE: usize = 4; // float32 = 4 bytes

// Correlation confidence
const MIN_CONFIDENCE_RATIO: f64 = 5.0;

// Silence detection
const DEFAULT_SILENCE_THRESHOLD_DB: f64 = -40.0;
const DEFAULT_SILENCE_MIN_DURATION_MS: u64 = 100;

// Subtitle timing
const EMERGENCY_MIN_DURATION_MS: u64 = 100;
const DEFAULT_MIN_DURATION_MS: u64 = 500;
const DEFAULT_MAX_CPS: f64 = 20.0;

// Frame matching
const DEFAULT_HASH_SIZE: u32 = 8;
const DEFAULT_HASH_THRESHOLD: u32 = 5;

// Stepping clustering
const DEFAULT_DBSCAN_EPSILON_MS: f64 = 20.0;
const DEFAULT_DBSCAN_MIN_SAMPLES: usize = 2;
```

---

*End of Implementation Plan Document*
