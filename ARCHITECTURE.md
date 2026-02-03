# Video Sync GUI - Architecture

This document describes the target architecture for the Rust rewrite.

## Overview

Video Sync GUI synchronizes and merges video files by:
1. Analyzing audio to calculate sync delays between sources
2. Extracting selected tracks from each source
3. Applying corrections and transformations
4. Muxing everything into a single output file

## The Three-Layer Model

```
┌─────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR                           │
│                  (orchestrator/pipeline.rs)                 │
│                                                             │
│   • Initializes Context (read-only config)                  │
│   • Creates JobState (mutable accumulator)                  │
│   • Runs steps in sequence                                  │
│   • Handles cancellation                                    │
│   • Reports overall progress                                │
│   • Aggregates errors                                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                         STEPS                               │
│                  (orchestrator/steps/*.rs)                  │
│                                                             │
│   • Micro-orchestrators for one phase of work               │
│   • Extract needed data from Context                        │
│   • Call module functions with typed parameters             │
│   • Store results in JobState                               │
│   • Handle logging and progress reporting                   │
│   • Decide control flow (skip, abort, continue)             │
│                                                             │
│   Rules:                                                    │
│   • NO algorithms or calculations                           │
│   • NO direct file I/O (delegate to modules)                │
│   • Target: 50-150 lines per step                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        MODULES                              │
│        (analysis/, extraction/, chapters/, mux/, etc.)      │
│                                                             │
│   • ALL business logic lives here                           │
│   • Pure functions: Input → Result<Output, Error>           │
│   • Typed input structs, typed output structs               │
│   • No Context or JobState access                           │
│   • May accept logger for detailed progress                 │
│   • Testable without orchestrator infrastructure            │
│                                                             │
│   Examples:                                                 │
│   • analysis::run_correlation(samples, settings) → Delays   │
│   • extraction::probe_file(path) → FileInfo                 │
│   • chapters::shift_chapters(chapters, offset) → Chapters   │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow

```
                    ┌──────────────┐
                    │   JobSpec    │  (what to process)
                    │   Settings   │  (how to process)
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   Context    │  IMMUTABLE
                    │              │  (read-only view of config)
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
         ┌────────┐   ┌────────┐   ┌────────┐
         │ Step 1 │   │ Step 2 │   │ Step N │
         └───┬────┘   └───┬────┘   └───┬────┘
             │            │            │
             │   ┌────────┴────────┐   │
             │   │                 │   │
             ▼   ▼                 ▼   ▼
        ┌─────────────────────────────────┐
        │            JobState             │  MUTABLE
        │                                 │  (accumulates results)
        │  • analysis: Option<Output>     │
        │  • extraction: Option<Output>   │
        │  • chapters: Option<Output>     │
        │  • mux: Option<Output>          │
        │  • merge_plan: Option<Plan>     │
        └─────────────────────────────────┘
```

### Context (Immutable)
- Contains: JobSpec, Settings, paths, logger
- Created once at pipeline start
- Steps read from it, never modify

### JobState (Mutable Accumulator)
- Contains: Results from each step
- Each step adds its output
- Write-once per field (don't overwrite previous step's data)
- Serializable for debugging/recovery

## Crate Structure

```
crates/
├── vsg_core/           # Backend library (no UI dependencies)
│   └── src/
│       ├── lib.rs
│       ├── models/     # Shared data types
│       │   ├── enums.rs
│       │   ├── media.rs
│       │   └── jobs.rs
│       ├── config/     # Settings management
│       ├── analysis/   # MODULE: Audio correlation
│       ├── extraction/ # MODULE: Track extraction
│       ├── chapters/   # MODULE: Chapter processing
│       ├── mux/        # MODULE: mkvmerge command building
│       ├── logging/    # Job logging
│       └── orchestrator/
│           ├── pipeline.rs   # ORCHESTRATOR
│           ├── step.rs       # PipelineStep trait
│           ├── types.rs      # Context, JobState
│           ├── errors.rs     # Error types
│           └── steps/        # STEPS
│               ├── analyze.rs
│               ├── extract.rs
│               ├── chapters.rs
│               └── mux.rs
│
└── vsg_ui/             # GUI application (to be rewritten with GTK/Relm4)
    └── src/
        ├── main.rs
        └── ...
```

## Module Responsibilities

### analysis/
- Audio extraction via FFmpeg
- Cross-correlation algorithms (GCC-PHAT, SCC, etc.)
- Delay selection strategies
- Drift detection

### extraction/
- File probing (mkvmerge -J)
- Track extraction (mkvextract)
- Attachment extraction

### chapters/
- Chapter XML parsing
- Timing shift
- Keyframe snapping
- Chapter renaming

### mux/
- Build mkvmerge options JSON
- Track ordering
- Flag setting (default, forced)

### config/
- Load/save settings.toml
- Section-level updates
- Default value handling

## Step Implementation Pattern

```rust
// Good step: thin wrapper that delegates to module
impl PipelineStep for AnalyzeStep {
    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.section("Analysis");

        // 1. Extract what we need from Context
        let sources = &ctx.job_spec.sources;
        let settings = &ctx.settings.analysis;

        // 2. Call module function (ALL logic is there)
        let result = analysis::analyze_sources(sources, settings, &ctx.logger)?;

        // 3. Store in JobState
        state.analysis = Some(result);

        Ok(StepOutcome::Success)
    }
}
```

```rust
// Bad step: business logic embedded
impl PipelineStep for AnalyzeStep {
    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        // DON'T DO THIS - calculating std_dev here is business logic
        let delays: Vec<f64> = /* ... */;
        let mean = delays.iter().sum::<f64>() / delays.len() as f64;
        let variance = delays.iter().map(|d| (d - mean).powi(2)).sum::<f64>() / delays.len() as f64;
        let std_dev = variance.sqrt();  // This belongs in analysis module!
        // ...
    }
}
```

## Python Reference

The `Reference Only original/` directory contains the complete Python implementation.

### Purpose
- Understand feature requirements and expected behavior
- Compare output/results between implementations
- Reference for edge cases and special handling

### How to Use
1. **Feature understanding**: Read Python code to understand WHAT a feature does
2. **Behavior verification**: Run both implementations, compare results
3. **Edge cases**: Check how Python handles errors, empty input, etc.

### How NOT to Use
- Do NOT copy code structure directly (Python patterns ≠ Rust patterns)
- Do NOT import Python abstractions that don't fit Rust
- Do NOT try to match internal implementation details

### Mapping (Python → Rust)
| Python | Rust |
|--------|------|
| `vsg_core/orchestrator/pipeline.py` | `vsg_core/src/orchestrator/pipeline.rs` |
| `vsg_core/orchestrator/steps/` | `vsg_core/src/orchestrator/steps/` |
| `vsg_core/analysis/` | `vsg_core/src/analysis/` |
| `vsg_core/extraction/` | `vsg_core/src/extraction/` |
| `vsg_core/chapters/` | `vsg_core/src/chapters/` |
| `vsg_core/config.py` | `vsg_core/src/config/` |
| `vsg_qt/` | `vsg_ui/` (to be rewritten) |

## Current Status

This architecture document describes the TARGET state. The current Rust code:
- Has the basic structure in place
- Some steps contain business logic that should move to modules
- UI (`vsg_ui/`) needs rewrite with GTK/Relm4
- Some features are stubbed but not implemented

When working on the codebase:
1. Check if feature has working backend code before adding UI
2. Refactor steps to be thinner when touching them
3. Move calculations from steps into modules
4. Remove code once replaced (don't keep dead code)
