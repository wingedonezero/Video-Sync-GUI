# Rust Rewrite Progress

> **Branch:** `claude/rust-rewrite-review-3rmZw`
> **Status:** Foundation Phase Complete ✅
> **Last Updated:** 2026-01-14

## Project Overview

This is the Rust rewrite of Video-Sync-GUI, transforming the Python/PySide6 implementation into a native Rust application for:
- **Single binary distribution** (no Python dependency hell)
- **Better performance** for audio/video processing
- **Strong type safety** at compile time
- **Cross-platform support** via libcosmic (Linux, Windows, macOS)

## ✅ Phase 1: Foundation - COMPLETED

### Project Structure Created

```
video-sync-gui/
├── Cargo.toml              ✅ Complete with dependencies
├── src/
│   ├── main.rs             ✅ Binary entry point
│   ├── lib.rs              ✅ Library exports
│   └── core/               ✅ Core modules
│       ├── mod.rs
│       ├── config.rs       ✅ Complete with JSON persistence
│       └── models/         ✅ All models implemented
│           ├── mod.rs
│           ├── enums.rs    ✅ TrackType, AnalysisMode, etc.
│           ├── media.rs    ✅ StreamProps, Track
│           ├── jobs.rs     ✅ Delays, JobSpec, PlanItem, MergePlan
│           ├── settings.rs ✅ Placeholder
│           ├── converters.rs ✅ Language normalization, extension mapping
│           └── results.rs  ✅ Error types
```

### ✅ Implemented Components

1. **Core Models** (`src/core/models/`)
   - ✅ `TrackType` enum (Video, Audio, Subtitles)
   - ✅ `StreamProps` - Complete mkvmerge JSON property mapping
   - ✅ `Track` - Track representation with display formatting
   - ✅ `Delays` - Positive-only timing model implementation
   - ✅ `JobSpec` - Job specifications
   - ✅ `PlanItem` - Complete track plan with all flags
   - ✅ `MergePlan` - Merge plan with delays
   - ✅ Language code normalization (2-letter → 3-letter)
   - ✅ Codec ID to file extension mapping
   - ✅ Error types (`CoreError`, `PipelineError`)

2. **Configuration** (`src/core/config.rs`)
   - ✅ `AppConfig` struct with all Python settings
   - ✅ JSON serialization/deserialization
   - ✅ Load/save functionality
   - ✅ Default values matching Python implementation
   - ✅ Directory creation

3. **IO Runner** (`src/core/io/runner.rs`)
   - ✅ Basic `CommandRunner` structure
   - ✅ Process execution skeleton
   - ⏳ TODO: Logging callbacks, compact mode

### ✅ Stub Modules Created

All module files created with proper structure:
- `analysis/` - Audio correlation, VideoDiff, drift detection, source separation
- `extraction/` - Track and attachment extraction
- `correction/` - Linear, PAL, stepping correction
- `subtitles/` - Convert, rescale, style engine, timing
- `chapters/` - Processing, keyframe snapping
- `mux/` - mkvmerge options builder
- `orchestrator/` - Pipeline orchestration and steps
- `postprocess/` - Final auditing and finalization
- `pipeline_components/` - Utilities
- `job_layouts/` - Job discovery and management

### ✅ Dependencies Added

**Core Dependencies:**
- `serde` + `serde_json` - Serialization
- `tokio` - Async runtime (for libcosmic)
- `rustfft` - FFT operations (audio correlation)
- `ndarray` - N-dimensional arrays
- `hound` - WAV file I/O
- `tempfile` - Temporary directories
- `tracing` + `tracing-subscriber` - Logging
- `anyhow` + `thiserror` - Error handling
- `shellexpand` - Path expansion
- `shell-words` - Command quoting
- `quick-xml` - XML processing (chapters)
- `chrono` - Time handling

**Note:** libcosmic dependency commented out until UI implementation begins (requires Rust 1.85+)

### ✅ Build Status

```bash
$ cargo check
✅ Finished `dev` profile [unoptimized + debuginfo] target(s) in 12.84s
```

**Zero errors, zero warnings!** 🎉

### ✅ Tests

All model tests passing:
- Track type parsing and display
- Audio channels display formatting
- Track display strings
- Delay computation with global shift
- Positive-only timing model
- Language code normalization
- Extension mapping for codecs

## ✅ Phase 2: Core Logic - COMPLETE!

### Part 1: CommandRunner & Track Extraction ✅
- ✅ **CommandRunner** (411 lines) - Streaming I/O, progress callbacks, compact logging
- ✅ **Track Extraction** (306 lines) - mkvmerge -J parsing, extraction, A_MS/ACM handling

### Part 2: Audio Correlation & Options Builder ✅
- ✅ **Audio Correlation** (411 lines) - GCC-PHAT, SCC, chunked analysis, pure Rust
- ✅ **Options Builder** (346 lines) - mkvmerge tokenization, critical delay calculation

### Part 3: Chapters & Subtitles ✅ (JUST COMPLETED!)
- ✅ **Chapter Processing** (515 lines)
  - XML parsing with quick-xml
  - Timestamp shifting (nanosecond precision)
  - Keyframe snapping (previous/nearest modes)
  - Chapter renaming & normalization
- ✅ **Keyframe Detection** (60 lines) - ffprobe integration
- ✅ **Subtitle Conversion** (91 lines) - SRT→ASS via FFmpeg
- ✅ **Subtitle Rescaling** (178 lines) - PlayRes adjustment to video resolution
- ✅ **Font Size Multiplication** (118 lines) - ASS/SSA style scaling
- ✅ **Subtitle Timing** (305 lines) - Three-phase timing fixes (overlap, duration)
- ✅ **Style Engine** (76 lines) - Stub for advanced style operations

**Total New Code:** ~2,060 lines of Rust

## 📊 Test Status
- ✅ **33 tests passing** (up from 28)
- ✅ New tests for:
  - Chapter timestamp parsing/formatting
  - Keyframe snapping (previous/nearest modes)
  - Subtitle rescaling (PlayRes)
  - Font size multiplication
  - Subtitle timing (ASS timestamp parsing)

## 📋 Next Steps (Phase 3)

### Priority 1: Pipeline Orchestration

Now that all core components are implemented, tie them together:

1. **Orchestrator** (`src/core/orchestrator/pipeline.rs`)
   - Implement Context struct to pass state between steps
   - Implement step-based execution:
     - AnalysisStep → Extract delays
     - ExtractStep → Extract tracks
     - SubtitlesStep → Apply subtitle transforms
     - ChaptersStep → Process chapters
     - MuxStep → Build and execute mkvmerge command
   - Add validation between steps

2. **Pipeline Steps** (`src/core/orchestrator/steps/`)
   - `context.rs` - Context struct with all state
   - `analysis_step.rs` - Run audio correlation
   - `extract_step.rs` - Extract tracks from sources
   - `subtitles_step.rs` - Convert, rescale, timing fixes
   - `chapters_step.rs` - Extract, shift, snap chapters
   - `mux_step.rs` - Build opts.json and run mkvmerge

### Priority 2: Integration Testing

Create end-to-end tests:
- Mock job with test files
- Verify pipeline execution
- Validate output structure

### Priority 3: UI Implementation (libcosmic)

After orchestrator is working:

1. Research latest libcosmic API (Rust 1.85+ required)
2. Create basic application structure
3. Main window layout
4. Manual selection dialog
5. Track widgets

## 📚 References

### Documentation Used

- [libcosmic Book](https://pop-os.github.io/libcosmic-book/introduction.html)
- [libcosmic API Docs](https://pop-os.github.io/libcosmic/cosmic/)
- [pop-os/libcosmic GitHub](https://github.com/pop-os/libcosmic)

### Implementation Plan

See `IMPLEMENTATION_PLAN.md` in the Rust-Rewrite branch for the complete roadmap.

### Python Reference

Original Python implementation in `vsg_core/` and `vsg_qt/` directories.

## 🎯 Critical Rules (from Implementation Plan)

### BEFORE implementing ANY dependency:
1. ✅ Use web search to find LATEST documentation
2. ✅ Verify crate versions on crates.io
3. ⚠️ libcosmic changes frequently - ALWAYS verify current API

### Architecture Rules:
- ✅ Maintain separation of `core/` and `ui/` directories
- ✅ Preserve orchestrator pattern with Context passing
- ✅ Match log format exactly: `"[TIMESTAMP] message"`

### What NOT to Do:
- ❌ Don't add new features during rewrite
- ❌ Don't modify output formats
- ❌ Don't implement Python dependencies yet (only for demucs later)

## 🔧 Build Commands

```bash
# Check compilation
cargo check

# Run tests
cargo test

# Build release
cargo build --release

# Run application (stub)
cargo run
```

## 📊 Progress Tracking

- [x] **Phase 1: Foundation** (Complete)
  - [x] Project structure
  - [x] Core models (jobs, media, enums, results)
  - [x] Configuration system
  - [x] Stub modules for all components
  - [x] Build verification (21 tests passing)

- [x] **Phase 2: Core Logic** (Complete - 2026-01-14)
  - [x] CommandRunner enhancement (streaming I/O, callbacks)
  - [x] Track extraction (mkvmerge JSON, mkvextract)
  - [x] Audio correlation (GCC-PHAT, SCC - pure Rust!)
  - [x] Options builder (delay calculation, track ordering)
  - [x] Chapter processing (XML, keyframes, snapping)
  - [x] Subtitle processing (convert, rescale, timing, style)

- [ ] **Phase 3: Pipeline Orchestration** (Next)
  - [ ] Context struct
  - [ ] Pipeline steps (analysis, extract, subtitles, chapters, mux)
  - [ ] Step validation
  - [ ] Error handling & recovery

- [ ] **Phase 4: UI Implementation** (After orchestrator)
  - [ ] libcosmic integration (Rust 1.85+)
  - [ ] Main window
  - [ ] Dialogs (options, job queue, manual selection)
  - [ ] Track widgets

- [ ] **Phase 5: Advanced Features**
  - [ ] Correction modes (linear, PAL, stepping)
  - [ ] Drift detection
  - [ ] Source separation (Python bridge - optional)
  - [ ] Advanced subtitle sync modes

- [ ] **Phase 6: Testing & Polish**
  - [ ] End-to-end integration tests
  - [ ] Performance optimization
  - [ ] Documentation
  - [ ] Release builds

## 🚀 Getting Started (Development)

```bash
# Clone and switch to Rust rewrite branch
git checkout Rust-Rewrite

# Build
cargo build

# Run tests (33 tests passing!)
cargo test

# Check code
cargo check

# Build optimized release
cargo build --release
```

---

## 📈 Statistics

**Total Lines of Rust Code:** ~5,000 lines
**Test Coverage:** 33 unit tests
**Build Time:** ~30-40 seconds
**Dependencies:** 14 crates (no Python required for core logic!)

---

**Next Session TODO:**
1. Implement orchestrator Context struct
2. Create pipeline steps (analysis, extract, subtitles, chapters, mux)
3. Add step validation
4. Create integration test with mock files
