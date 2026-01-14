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

## 📋 Next Steps (Phase 2)

### Priority 1: libcosmic Integration Research

Before implementing UI, we need to:

1. **Research Latest libcosmic API** (2026-01-14)
   - ✅ Found documentation: [libcosmic Book](https://pop-os.github.io/libcosmic-book/introduction.html)
   - ✅ Repository: [pop-os/libcosmic](https://github.com/pop-os/libcosmic)
   - ⚠️ **Important:** libcosmic is NOT on crates.io - must use git dependency
   - ⚠️ **Requirement:** Rust 1.85+ (currently using 1.75)
   - 🔄 **Action Required:** Verify current libcosmic API patterns

2. **Update Rust Version**
   ```toml
   rust-version = "1.85"  # Update in Cargo.toml
   ```

3. **Add libcosmic Dependency**
   ```toml
   [dependencies]
   libcosmic = { git = "https://github.com/pop-os/libcosmic", branch = "master" }
   ```

### Priority 2: Core Logic Implementation

**Before UI work**, implement core pipeline components in this order:

1. **CommandRunner Enhancement** (`src/core/io/runner.rs`)
   - Implement streaming stdout/stderr capture
   - Add compact logging mode
   - Progress callback system
   - Error tail capture

2. **Track Extraction** (`src/core/extraction/tracks.rs`)
   - Parse `mkvmerge -J` output
   - Implement track extraction with mkvextract
   - Handle A_MS/ACM special cases

3. **Audio Correlation** (`src/core/analysis/audio_corr.rs`)
   - Implement GCC-PHAT correlation (rustfft)
   - Standard cross-correlation (SCC)
   - Chunked analysis with ffmpeg
   - Confidence scoring
   - **Pure Rust** - no Python needed

4. **Options Builder** (`src/core/mux/options_builder.rs`)
   - Build mkvmerge command tokens
   - Delay calculation logic (CRITICAL - preserve exact Python behavior)
   - Track ordering

### Priority 3: UI Implementation (After libcosmic research)

Only after completing core logic and verifying libcosmic API:

1. Create basic application structure
2. Main window layout
3. Manual selection dialog
4. Track widgets

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

- [x] Phase 1: Foundation (Complete)
  - [x] Project structure
  - [x] Core models
  - [x] Configuration
  - [x] Stub modules
  - [x] Build verification
- [ ] Phase 2: Core Logic
  - [ ] CommandRunner enhancement
  - [ ] Track extraction
  - [ ] Audio correlation
  - [ ] Options builder
- [ ] Phase 3: UI Implementation
  - [ ] libcosmic integration
  - [ ] Main window
  - [ ] Dialogs
  - [ ] Track widgets
- [ ] Phase 4: Advanced Features
  - [ ] Subtitle processing
  - [ ] Chapter handling
  - [ ] Correction modes
- [ ] Phase 5: Testing & Polish
  - [ ] End-to-end tests
  - [ ] Performance optimization
  - [ ] Documentation

## 🚀 Getting Started (Development)

```bash
# Clone and switch to rust branch
git checkout claude/rust-rewrite-review-3rmZw

# Build
cargo build

# Run tests
cargo test

# Check code
cargo check
```

---

**Next Session TODO:**
1. Research latest libcosmic API (verify Application trait, message handling)
2. Update Cargo.toml with libcosmic git dependency
3. Implement CommandRunner with streaming I/O
4. Start track extraction implementation
