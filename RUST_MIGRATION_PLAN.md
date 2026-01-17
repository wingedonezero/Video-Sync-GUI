# Video-Sync-GUI: Rust Migration Master Plan

> **Document Purpose**: This is the authoritative reference for migrating Video-Sync-GUI from Python to Rust. It must be consulted and updated by any AI or developer working on this migration.
>
> **Last Updated**: 2026-01-16
> **Migration Status**: Phase 8 Rust Complete - **Python Integration NOT Started**
>
> **New Plan (2026-01-16)**: Build the **core shell first** (orchestrator, pipeline, workers, config, UI wiring) with **embedded Python** for anything not yet ported. Leaf/algorithm modules will be integrated **after** the core shell is runnable.

---

## 🚨 Current State Summary

### Quick Start for New Chats (Read First)
- **Active Rust crate**: `vsg_core_rs/` at repo root (this is where all new work goes).
- **Reference snapshot**: `rust/vsg_core_rs/` is **read-only** for comparison.
- **Phase 9 focus**: Build the core shell first (orchestrator/worker/config/UI wiring), embed Python for unported modules, then migrate leaf modules.

### What We Have
| Component | Status | Location |
|-----------|--------|----------|
| **Rust implementations (active)** | ✅ Written & tested | `vsg_core_rs/src/` (4,291 lines) |
| **Rust reference snapshot** | ✅ Reference only | `rust/vsg_core_rs/` |
| **Python implementations** | ✅ Still working | `python/vsg_core/` (12,978 lines) |
| **Python → Rust bridge** | ❌ **DOES NOT EXIST** | Should be `python/vsg_core/_rust_bridge/` |

**Reference note**: `rust/vsg_core_rs/` is a snapshot for comparison only. Active Rust work happens in `vsg_core_rs/`.

### What This Means
- **Rust code exists but is UNUSED** - Python doesn't import `vsg_core_rs`
- **Both implementations work independently** - Parallel development
- **No performance benefit yet** - Still running pure Python
- **Phase 9 is the critical "tie-in" phase** - Must create integration layer

### Immediate Action Required
1. Establish Rust **core shell** layout (orchestrator, pipeline, workers, config, UI wiring)
2. Embed Python for any unported modules to keep behavior intact
3. Build Rust library: `cd vsg_core_rs && maturin develop --release`
4. Create `python/vsg_core/_rust_bridge/` modules (as needed for parity checks)
5. Test Python ↔ Rust parity **after** core shell is runnable

---

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Migration Philosophy](#2-migration-philosophy)
3. [What Stays in Python](#3-what-stays-in-python)
4. [Build and Distribution Strategy](#4-build-and-distribution-strategy)
5. [Architecture After Migration](#5-architecture-after-migration)
6. [Migration Phases](#6-migration-phases)
7. [Phase 1: Core Data Types](#phase-1-core-data-types)
8. [Phase 2: Audio Correlation Engine](#phase-2-audio-correlation-engine)
9. [Phase 3: Drift Detection](#phase-3-drift-detection)
10. [Phase 4: Audio Correction](#phase-4-audio-correction)
11. [Phase 5: Subtitle Processing Core](#phase-5-subtitle-processing-core)
12. [Phase 6: Frame Utilities](#phase-6-frame-utilities)
13. [Phase 7: Extraction Layer](#phase-7-extraction-layer)
14. [Phase 8: Mux Options Builder](#phase-8-mux-options-builder)
15. [Phase 9: Core Shell + Embedded Python](#phase-9-core-shell--embedded-python)
16. [Phase 10: UI Migration](#phase-10-ui-migration)
17. [Critical Preservation Requirements](#critical-preservation-requirements)
18. [Testing Strategy](#testing-strategy)
19. [Completion Tracking](#completion-tracking)
20. [Instructions for AI Assistants](#instructions-for-ai-assistants)

---

## 1. Project Overview

### Current State
- **Codebase Size**: ~22,000 lines Python across 133 modules
- **Packages**: `vsg_core` (backend, 92 modules) + `vsg_qt` (UI, 41 modules)
- **Architecture**: Orchestrator pattern with modular pipeline steps
- **Known Issues**: Memory management with numpy arrays, worker thread crashes with complex configurations

### Migration Goals
1. **Stability**: Eliminate Python memory management issues (numpy arrays, GIL, worker threads)
2. **Performance**: Leverage Rust's zero-cost abstractions and true parallelism
3. **Maintainability**: Strong typing prevents class of bugs that plague complex Python
4. **Incremental**: App must work completely throughout migration

### What This Migration Is NOT
- NOT a rewrite from scratch (preserve logic and behaviors)
- NOT changing how logging works
- NOT changing mkvmerge JSON handling
- NOT adding new features during migration

---

## 2. Migration Philosophy

### Principle 1: Core-Shell-First Migration (Updated)
Start with the **orchestrator + worker + config + UI wiring** so the app is runnable end-to-end, even if many steps are still Python-backed. This ensures:
- The UI and job lifecycle can be tested early
- Logging, progress, and pipeline behavior are validated up front
- Python-backed modules remain available via embedding or bridges

### Principle 2: Bottom-Up Module Migration (Still Applies)
Once the core shell is runnable, migrate leaf modules in dependency order. This ensures:
- Each Rust module can be tested independently
- The core shell remains stable while internals are replaced
- No circular dependency issues

### Principle 3: Preserve All Behaviors
Every special case, threshold, and edge case handling must be preserved exactly. The migration document includes specific notes about what must not change.

### Principle 4: Small, Testable Steps
Each phase produces a working system. Never break functionality for more than one phase.

### Principle 5: Hybrid Operation (Expanded)
During migration, **Rust owns the orchestration shell** while **Python remains embedded** for functionality not yet ported. Rust handles:
- Pipeline orchestration
- Worker lifecycle & logging
- Config and job models
Python continues to handle:
- Legacy leaf modules and external tool wrappers
- pysubs2, videotimestamps, and model-dependent code

---

## 3. What Stays in Python

These components will remain in Python for the foreseeable future:

| Component | Reason |
|-----------|--------|
| `videotimestamps` library | No Rust equivalent exists |
| `pysubs2` library + subtitle processing | No Rust equivalent exists for full ASS/SSA/SRT parsing and manipulation |
| Source separation models | PyTorch/ONNX ecosystem, already subprocess-isolated |
| Qt UI (`python/vsg_qt/*`) | Migrated last; PyO3 FFI works well |
| External tool calls | Already subprocess-based (ffmpeg, mkvmerge, etc.) |

---

## 4. Build and Distribution Strategy

### How Rust Integrates with Current Setup

Your current setup uses:
- `python/.venv/` — Python virtual environment
- `python/run.sh` — Activates venv, sets ROCm env, runs `python main.py`
- `python/setup_env.sh` — Creates venv, installs Python dependencies
- `Cargo.toml` at repo root — Rust workspace (active crate: `vsg_core_rs/`)

The Rust library will be built with **maturin** and installed into the same venv:

```
┌─────────────────────────────────────────────────────────────┐
│                    Project Directory                         │
├─────────────────────────────────────────────────────────────┤
│  python/run.sh              → Unchanged (runs python main.py) │
│  python/setup_env.sh        → Add Rust build step             │
│  python/main.py             → Unchanged                       │
│  python/requirements.txt    → Unchanged                       │
│                                                              │
│  python/.venv/                                               │
│  └── lib/python3.13/site-packages/                           │
│      ├── vsg_core_rs.cpython-313-x86_64-linux-gnu.so  ←NEW  │
│      ├── numpy/                                              │
│      ├── scipy/                                              │
│      └── ... (other packages)                                │
│                                                              │
│  vsg_core_rs/       ←NEW (Rust source)                   │
│  ├── Cargo.toml                                              │
│  ├── pyproject.toml  (maturin config)                        │
│  └── src/                                                    │
│      ├── lib.rs                                              │
│      └── ...                                                 │
│                                                              │
│  python/vsg_core/          (Python - calls into Rust)          │
│  python/vsg_qt/            (Python UI)                         │
└─────────────────────────────────────────────────────────────┘
```

### Maturin Setup

Create `vsg_core_rs/pyproject.toml`:
```toml
[build-system]
requires = ["maturin>=1.7,<2.0"]
build-backend = "maturin"

[project]
name = "vsg_core_rs"
version = "0.1.0"
requires-python = ">=3.10"
classifiers = [
    "Programming Language :: Rust",
    "Programming Language :: Python :: Implementation :: CPython",
]

[tool.maturin]
features = ["pyo3/extension-module"]
python-source = "python"  # Optional: for Python stubs
module-name = "vsg_core_rs"
```

### Build Commands

**Development** (installs into active venv):
```bash
cd vsg_core_rs
maturin develop --release
```

**Production wheel** (for distribution):
```bash
cd vsg_core_rs
maturin build --release
# Output: target/wheels/vsg_core_rs-0.1.0-cp313-cp313-linux_x86_64.whl
```

### Updated python/setup_env.sh

Add to `full_setup()` after Python dependencies are installed:

```bash
# Step 4: Build Rust components
echo -e "${YELLOW}[4/4] Building Rust components...${NC}"

# Check for Rust toolchain
if ! command -v cargo &> /dev/null; then
    echo -e "${YELLOW}Rust not found. Installing via rustup...${NC}"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
fi

# Ensure maturin is installed
venv_pip install maturin

# Build and install Rust library
RUST_PROJECT_DIR="$PROJECT_DIR/../vsg_core_rs"
if [ -d "$RUST_PROJECT_DIR" ]; then
    cd "$RUST_PROJECT_DIR"
    maturin develop --release
    cd "$PROJECT_DIR"
    echo -e "${GREEN}✓ Rust components built${NC}"
else
    echo -e "${YELLOW}No Rust components found (vsg_core_rs/ not present)${NC}"
fi
```

### What Goes Where After Build

| Location | Contents |
|----------|----------|
| `vsg_core_rs/target/` | Rust build artifacts (not distributed) |
| `vsg_core_rs/target/wheels/` | Wheel files if using `maturin build` |
| `python/.venv/lib/python3.13/site-packages/vsg_core_rs*.so` | Installed native module |

### Distribution Options

1. **Development/Local**: Use `maturin develop` — builds and installs directly into venv
2. **Wheel Distribution**: Use `maturin build` — creates `.whl` file users can `pip install`
3. **Source Distribution**: Ship `vsg_core_rs/` source, users run `maturin develop`

**Recommended for your project**: Option 3 (source distribution) since:
- Users already run `python/setup_env.sh`
- Rust compilation handles platform differences automatically
- No need to build wheels for every platform

### python/run.sh and python/setup_env.sh Stay Mostly Unchanged

- `python/run.sh` — No changes needed. It activates venv and runs `python main.py`. The Rust library is already in the venv's site-packages.
- `python/setup_env.sh` — Add the Rust build step shown above. Everything else stays the same.

### GPU Environment

Your ROCm environment detection in `python/run.sh` stays exactly as-is. The Rust library doesn't need GPU access directly — source separation (which uses GPU) stays in Python via `audio-separator`.

---

## 5. Architecture After Migration

```
┌─────────────────────────────────────────────────────────────────┐
│                     Python Layer (Thin)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   vsg_qt    │  │ Orchestrator│  │  videotimestamps (lib)  │  │
│  │  (PySide6)  │  │  (pipeline) │  │  source_separation      │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘  │
│         │                │                      │                │
└─────────┼────────────────┼──────────────────────┼────────────────┘
          │                │                      │
          │         PyO3 Bindings                 │
          │                │                      │
┌─────────┼────────────────┼──────────────────────┼────────────────┐
│         ▼                ▼                      ▼                │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    vsg_core_rs (Rust)                       │ │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐            │ │
│  │  │   models   │  │  analysis  │  │ correction │            │ │
│  │  │  (types)   │  │ (correlate)│  │ (stepping) │            │ │
│  │  └────────────┘  └────────────┘  └────────────┘            │ │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐            │ │
│  │  │ subtitles  │  │    mux     │  │ extraction │            │ │
│  │  │  (sync)    │  │ (options)  │  │  (tracks)  │            │ │
│  │  └────────────┘  └────────────┘  └────────────┘            │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                         Rust Layer                               │
└──────────────────────────────────────────────────────────────────┘
```

---

## 5.1. Current Integration Status

> ⚠️ **CRITICAL**: This section documents what exists vs. what's missing.

### What EXISTS (Rust Side)

```
vsg_core_rs/src/
├── lib.rs                    ✅ PyO3 module with all exports
├── models/                   ✅ All data types (enums, media, jobs, settings)
├── analysis/
│   ├── correlation.rs        ✅ GCC-PHAT, SCC, SCOT, Whitened methods
│   ├── delay_selection.rs    ✅ All 4 selection modes
│   └── drift_detection.rs    ✅ DBSCAN, PAL/linear diagnosis
├── correction/
│   ├── edl.rs               ✅ EDL segment generation
│   ├── linear.rs            ✅ Tempo ratio calculation
│   ├── pal.rs               ✅ PAL constants
│   └── utils.rs             ✅ Buffer alignment, silence detection
├── subtitles/
│   └── frame_utils.rs       ✅ 3 frame conversion modes
├── extraction/
│   └── tracks.rs            ✅ Container delay calculation
├── chapters/
│   └── timestamps.rs        ✅ Nanosecond timestamp manipulation
└── mux/
    └── delay_calculator.rs  ✅ Track delay rules + sync tokens
```

### What's MISSING (Python Integration)

```
python/vsg_core/
├── _rust_bridge/            ❌ DOES NOT EXIST - needs creation
│   ├── __init__.py
│   ├── analysis.py          ❌ Would wrap vsg_core_rs.analyze_audio_correlation
│   ├── correction.py        ❌ Would wrap vsg_core_rs correction functions
│   ├── extraction.py        ❌ Would wrap vsg_core_rs extraction functions
│   ├── chapters.py          ❌ Would wrap vsg_core_rs chapter functions
│   ├── mux.py               ❌ Would wrap vsg_core_rs.calculate_mux_delay
│   └── frame_utils.py       ❌ Would wrap vsg_core_rs frame utilities
│
├── orchestrator/steps/      ❌ Still uses pure Python implementations
│   ├── analysis_step.py     ❌ Calls python/vsg_core/analysis/audio_corr.py (Python)
│   ├── extract_step.py      ❌ Calls python/vsg_core/extraction/tracks.py (Python)
│   └── ...                  ❌ All steps use Python, not Rust
```

### Why This Matters

1. **Rust code is tested but unused** - We have 4,000+ lines of Rust that aren't being called
2. **Python implementation still runs** - All actual processing uses Python code
3. **No performance benefit yet** - Until integration, we don't get Rust's speed
4. **Parallel development risk** - If Python code changes, Rust may diverge

### Integration Priority

| Priority | Bridge Module | Rust Functions | Python Replacement |
|----------|---------------|----------------|-------------------|
| 1 | `_rust_bridge/analysis.py` | `analyze_audio_correlation`, `diagnose_drift` | `audio_corr.py`, `drift_detection.py` |
| 2 | `_rust_bridge/mux.py` | `calculate_mux_delay`, `build_mkvmerge_sync_token` | `options_builder.py` |
| 3 | `_rust_bridge/extraction.py` | `calculate_container_delay`, `add_container_delays_to_json` | `tracks.py` |
| 4 | `_rust_bridge/chapters.py` | `shift_chapter_timestamp`, `format_chapter_timestamp` | `process.py` |
| 5 | `_rust_bridge/frame_utils.py` | 6 frame conversion functions | `frame_utils.py` |
| 6 | `_rust_bridge/correction.py` | EDL generation, tempo ratios | `stepping.py`, `linear.py` |

---

## 6. Migration Phases

> ⚠️ **Note**: Phases 1-8 have Rust implementations, but Python integration is NOT complete.
> The codebase currently has parallel implementations (Python + Rust) that are not connected.

| Phase | Component | Est. Files | Priority | Rust Status | Python Integration |
|-------|-----------|------------|----------|-------------|-------------------|
| 1 | Core Data Types | 6 | CRITICAL | ✅ Complete | ❌ Not integrated |
| 2 | Audio Correlation | 1 | CRITICAL | ✅ Complete | ❌ Not integrated |
| 3 | Drift Detection | 1 | HIGH | ✅ Complete | ❌ Not integrated |
| 4 | Audio Correction | 3 | HIGH | ✅ Complete | ❌ Not integrated |
| 5 | Subtitle Core | 0 | N/A | N/A | **STAYS IN PYTHON** (pysubs2) |
| 6 | Frame Utilities | 1 (partial) | MEDIUM | ✅ Complete | ❌ Not integrated |
| 7 | Extraction Layer | 3 | MEDIUM | ✅ Complete | ❌ Not integrated |
| 8 | Mux Options | 1 | MEDIUM | ✅ Complete | ❌ Not integrated |
| **9** | **Core Shell + Embedded Python** | 8+ | **CRITICAL** | N/A | **CURRENT PHASE** |
| 10 | UI Migration | 41 | LAST | Not started | Future |

### What "Complete" Means for Phases 1-8
- ✅ **Rust code written** in `vsg_core_rs/src/`
- ✅ **PyO3 bindings defined** for Python interop
- ✅ **Unit tests pass** in Rust
- ❌ **Python does NOT call Rust yet** - this is Phase 9

---

## Phase 1: Core Data Types

### Status: [x] Completed (2026-01-16)

### Files to Migrate
```
python/vsg_core/models/enums.py        →  src/models/enums.rs
python/vsg_core/models/media.py        →  src/models/media.rs
python/vsg_core/models/results.py      →  src/models/results.rs
python/vsg_core/models/jobs.py         →  src/models/jobs.rs
python/vsg_core/models/settings.py     →  src/models/settings.rs
python/vsg_core/models/converters.py   →  src/models/converters.rs
```

### Rust Crate Structure
```
vsg_core_rs/
├── Cargo.toml
├── src/
│   ├── lib.rs
│   └── models/
│       ├── mod.rs
│       ├── enums.rs
│       ├── media.rs
│       ├── results.rs
│       ├── jobs.rs
│       ├── settings.rs
│       └── converters.rs
```

### Step 1.1: Create Cargo Workspace
```toml
# Cargo.toml
[package]
name = "vsg_core_rs"
version = "0.1.0"
edition = "2021"
rust-version = "1.74"  # Required by pyo3 0.27+

[lib]
name = "vsg_core_rs"
crate-type = ["cdylib", "rlib"]

[dependencies]
pyo3 = { version = "0.27", features = ["extension-module"] }
numpy = "0.27"  # PyO3 numpy bindings (NOT Python numpy)
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
```

### Step 1.2: Enums (enums.rs)

**CRITICAL PRESERVATION**: Enum values must match Python exactly for serialization.

```rust
// src/models/enums.rs
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

#[pyclass]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum TrackType {
    Video,
    Audio,
    Subtitles,
}

#[pyclass]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum AnalysisMode {
    Audio,
    Video,
}

#[pyclass]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum SnapMode {
    Previous,
    Nearest,
}

#[pyclass]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum StepStatus {
    Pending,
    Running,
    Success,
    Skipped,
    Failed,
}

#[pyclass]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum CorrectionVerdict {
    Uniform,
    Stepped,
    Failed,
}
```

### Step 1.3: Media Types (media.rs)

```rust
// src/models/media.rs
use pyo3::prelude::*;
use std::path::PathBuf;
use super::enums::TrackType;

#[pyclass]
#[derive(Clone, Debug)]
pub struct StreamProps {
    #[pyo3(get, set)]
    pub codec_id: String,
    #[pyo3(get, set)]
    pub language: Option<String>,
    #[pyo3(get, set)]
    pub track_name: Option<String>,
    #[pyo3(get, set)]
    pub audio_channels: Option<u32>,
    #[pyo3(get, set)]
    pub audio_sampling_frequency: Option<u32>,
}

#[pyclass]
#[derive(Clone, Debug)]
pub struct Track {
    #[pyo3(get, set)]
    pub id: u32,
    #[pyo3(get, set)]
    pub track_type: TrackType,
    #[pyo3(get, set)]
    pub props: StreamProps,
    #[pyo3(get, set)]
    pub container_delay_ms: i32,  // CRITICAL: Must be i32, not u32 (can be negative)
}
```

### Step 1.4: Jobs Types (jobs.rs)

**CRITICAL PRESERVATION**:
- `source_delays_ms` uses `i32` (rounded for mkvmerge)
- `raw_source_delays_ms` uses `f64` (unrounded for VideoTimestamps precision)
- Both dicts must have identical keys

```rust
// src/models/jobs.rs
use pyo3::prelude::*;
use std::collections::HashMap;
use std::path::PathBuf;

#[pyclass]
#[derive(Clone, Debug, Default)]
pub struct Delays {
    /// Rounded delays for mkvmerge (integer milliseconds)
    #[pyo3(get, set)]
    pub source_delays_ms: HashMap<String, i32>,

    /// Raw delays for VideoTimestamps (float milliseconds)
    /// CRITICAL: Must have same keys as source_delays_ms
    #[pyo3(get, set)]
    pub raw_source_delays_ms: HashMap<String, f64>,

    #[pyo3(get, set)]
    pub global_shift_ms: i32,

    #[pyo3(get, set)]
    pub raw_global_shift_ms: f64,
}

#[pyclass]
#[derive(Clone, Debug)]
pub struct PlanItem {
    #[pyo3(get, set)]
    pub source_key: String,
    #[pyo3(get, set)]
    pub track_id: u32,
    #[pyo3(get, set)]
    pub track_type: super::enums::TrackType,
    #[pyo3(get, set)]
    pub file_path: PathBuf,
    #[pyo3(get, set)]
    pub container_delay_ms: i32,

    // State flags - determine delay application
    #[pyo3(get, set)]
    pub is_preserved: bool,      // Original track kept
    #[pyo3(get, set)]
    pub is_corrected: bool,      // Underwent correction
    #[pyo3(get, set)]
    pub stepping_adjusted: bool, // Delay baked in (return 0)
    #[pyo3(get, set)]
    pub frame_adjusted: bool,    // Delay baked in (return 0)
    #[pyo3(get, set)]
    pub is_generated: bool,      // Created by style filtering
    #[pyo3(get, set)]
    pub generated_source_track_id: Option<u32>,
    #[pyo3(get, set)]
    pub generated_source_path: Option<PathBuf>,
}
```

### Step 1.5: Python Bindings

```rust
// src/lib.rs
use pyo3::prelude::*;

mod models;

#[pymodule]
fn vsg_core_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    // Enums
    m.add_class::<models::enums::TrackType>()?;
    m.add_class::<models::enums::AnalysisMode>()?;
    m.add_class::<models::enums::SnapMode>()?;
    m.add_class::<models::enums::StepStatus>()?;
    m.add_class::<models::enums::CorrectionVerdict>()?;

    // Media
    m.add_class::<models::media::StreamProps>()?;
    m.add_class::<models::media::Track>()?;

    // Jobs
    m.add_class::<models::jobs::Delays>()?;
    m.add_class::<models::jobs::PlanItem>()?;

    Ok(())
}
```

### Testing Checkpoint 1
- [ ] Build Rust library with `maturin develop`
- [ ] Import in Python: `from vsg_core_rs import TrackType, Delays, PlanItem`
- [ ] Verify enum values match Python originals
- [ ] Verify Delays can round-trip through JSON
- [ ] Run existing Python tests with Rust types substituted

---

## Phase 2: Audio Correlation Engine

### Status: [x] Completed (2026-01-16)

### Files to Migrate
```
python/vsg_core/analysis/audio_corr.py  →  src/analysis/correlation.rs
```

### Dependencies
- Phase 1 (data types)
- Rust crates: `rustfft`, `ndarray`, `rayon`

### Step 2.1: Add Dependencies
```toml
# Cargo.toml additions
[dependencies]
rustfft = "6.4"
ndarray = { version = "0.17", features = ["rayon"] }
rayon = "1.11"
num-complex = "0.4"
```

### Step 2.2: Core Correlation Algorithms

**CRITICAL PRESERVATION - GCC-PHAT Algorithm**:
```rust
// src/analysis/correlation.rs

/// GCC-PHAT (Generalized Cross-Correlation with Phase Transform)
///
/// CRITICAL: This must match Python implementation exactly:
/// - FFT size = len(ref) + len(tgt) - 1
/// - Phase normalization: G / (|G| + 1e-9)
/// - Lag calculation: k - n if k > n/2 else k
/// - Delay in ms: (lag_samples / sr) * 1000.0
pub fn gcc_phat(
    ref_chunk: &[f32],
    tgt_chunk: &[f32],
    sample_rate: u32,
) -> (f64, f64) {
    let n = ref_chunk.len() + tgt_chunk.len() - 1;

    // FFT of both signals
    let mut planner = FftPlanner::new();
    let fft = planner.plan_fft_forward(n);
    let ifft = planner.plan_fft_inverse(n);

    // ... (full implementation)

    // CRITICAL: Normalization epsilon must be 1e-9
    let g_phat: Vec<Complex<f64>> = g.iter()
        .map(|&x| x / (x.norm() + 1e-9))
        .collect();

    // ... (lag calculation)

    let lag_samples = if k > n / 2 { k as i64 - n as i64 } else { k as i64 };
    let delay_ms = (lag_samples as f64 / sample_rate as f64) * 1000.0;
    let confidence = normalize_peak_confidence(&r_phat, k);

    (delay_ms, confidence)
}
```

### Step 2.3: Correlation Methods Enum

**CRITICAL**: All 7 methods must be supported:
1. Phase Correlation (GCC-PHAT) - Primary
2. Standard Correlation (SCC)
3. GCC-SCOT
4. GCC Whitened
5. Onset Detection (requires librosa - keep in Python)
6. DTW (requires librosa - keep in Python)
7. Spectrogram Correlation (requires librosa - keep in Python)

Methods 5-7 require librosa; implement as Python fallback.

### Step 2.4: Chunk Processing with Rayon

```rust
/// Process all chunks in parallel
///
/// CRITICAL PRESERVATION:
/// - Scan range: 5% to 95% of duration (configurable)
/// - Chunk duration: 15 seconds (configurable)
/// - min_match_pct: 5% default
pub fn run_correlation(
    ref_audio: &[f32],
    tgt_audio: &[f32],
    sample_rate: u32,
    config: &CorrelationConfig,
) -> CorrelationResult {
    let chunks: Vec<ChunkInfo> = calculate_chunks(
        ref_audio.len(),
        sample_rate,
        config.chunk_duration_s,
        config.scan_start_pct,  // Default: 5.0
        config.scan_end_pct,    // Default: 95.0
    );

    // CRITICAL: Parallel processing with rayon
    let results: Vec<ChunkResult> = chunks
        .par_iter()
        .map(|chunk| process_chunk(ref_audio, tgt_audio, chunk, sample_rate, config))
        .collect();

    // Delay selection
    select_final_delay(&results, config.delay_selection_mode)
}
```

### Step 2.5: Delay Selection Modes

**CRITICAL PRESERVATION - All 4 modes**:

```rust
pub enum DelaySelectionMode {
    MostCommon,      // Mode of rounded delays
    ModeClustered,   // Most common ±1ms cluster
    Average,         // Mean of raw delays
    FirstStable,     // First N consecutive with same delay
}

/// CRITICAL: First Stable logic
/// - Groups consecutive chunks by delay (±1ms tolerance)
/// - Returns average of RAW delays in first stable group
/// - Then rounds for final integer delay
fn select_first_stable(
    results: &[ChunkResult],
    min_chunks: usize,      // Default: 3
    skip_unstable: bool,    // Default: true
) -> (i32, f64) {
    // ... implementation matching Python exactly
}
```

### Step 2.6: PyO3 Bindings

```rust
#[pyfunction]
#[pyo3(signature = (ref_audio, tgt_audio, sample_rate, method="gcc_phat", chunk_duration_s=15.0, min_match_pct=5.0, delay_selection_mode="most_common", scan_start_pct=5.0, scan_end_pct=95.0))]
fn analyze_audio_correlation(
    py: Python,
    ref_audio: PyReadonlyArrayDyn<f32>,
    tgt_audio: PyReadonlyArrayDyn<f32>,
    sample_rate: u32,
    method: &str,
    chunk_duration_s: f64,
    min_match_pct: f64,
    delay_selection_mode: &str,
    scan_start_pct: f64,
    scan_end_pct: f64,
) -> PyResult<PyObject> {
    // Release GIL during computation
    py.allow_threads(|| {
        let ref_slice = ref_audio.as_slice()?;
        let tgt_slice = tgt_audio.as_slice()?;

        // ... correlation logic
    })
}
```

### Testing Checkpoint 2
- [ ] Unit tests for GCC-PHAT match Python output (within 0.001ms)
- [ ] Unit tests for SCC match Python output
- [ ] Parallel chunk processing produces same results as sequential
- [ ] All 4 delay selection modes match Python behavior
- [ ] Integration test: Replace Python audio_corr with Rust, run full job
- [ ] Memory usage: Verify no leaks after 10 consecutive analyses

---

## Phase 3: Drift Detection

### Status: [x] Complete

### Files to Migrate
```
python/vsg_core/analysis/drift_detection.py  →  src/analysis/drift_detection.rs
```

### Dependencies
- Phase 1, Phase 2
- Rust crates: `linfa-clustering` (DBSCAN)

### Step 3.1: DBSCAN Clustering

**CRITICAL PRESERVATION**:
- eps (epsilon): Default from config
- min_samples: Default from config
- Clusters consecutive chunks with similar delays

```rust
use linfa::prelude::*;
use linfa_clustering::Dbscan;

pub fn diagnose_audio_issue(
    chunk_results: &[ChunkResult],
    config: &DriftConfig,
) -> AudioDiagnosis {
    let accepted: Vec<_> = chunk_results
        .iter()
        .filter(|c| c.accepted)
        .collect();

    if accepted.len() < config.min_accepted_chunks {
        return AudioDiagnosis::InsufficientData;
    }

    let delays: Array2<f64> = /* extract delays as 2D array */;

    let clusters = Dbscan::params(config.min_samples)
        .tolerance(config.eps)
        .transform(&delays)?;

    // Analyze cluster transitions
    analyze_clusters(&clusters, &accepted)
}
```

### Step 3.2: Diagnosis Types

```rust
#[pyclass]
#[derive(Clone, Debug)]
pub enum AudioDiagnosis {
    Uniform,           // Single constant delay
    Stepping,          // Discrete jumps (>50ms between clusters)
    PalDrift,          // Gradual ~3% slower (25fps PAL)
    LinearDrift,       // Consistent acceleration/deceleration
    InsufficientData,  // Not enough accepted chunks
}
```

### Step 3.3: PAL Detection

**CRITICAL PRESERVATION**:
- PAL = ~25.0 fps ±0.1
- Expected drift: 40.88 ms/s
- Tempo ratio for correction: (24000/1001) / 25.0 = 0.95904

```rust
fn detect_pal_drift(
    clusters: &[ClusterInfo],
    duration_s: f64,
) -> bool {
    // Check if drift rate matches PAL characteristics
    let expected_drift_ms_per_s = 40.88;
    let measured_drift = calculate_drift_rate(clusters);

    (measured_drift - expected_drift_ms_per_s).abs() < 5.0  // ±5ms/s tolerance
}
```

### Testing Checkpoint 3
- [ ] DBSCAN produces same cluster assignments as sklearn
- [ ] Diagnosis matches Python for known stepping audio
- [ ] Diagnosis matches Python for known PAL drift audio
- [ ] Integration: Run with Phase 2, verify end-to-end diagnosis

---

## Phase 4: Audio Correction

### Status: [x] Complete

### Files to Migrate
```
python/vsg_core/correction/stepping.py  →  src/correction/stepping.rs
python/vsg_core/correction/linear.py    →  src/correction/linear.rs
python/vsg_core/correction/pal.py       →  src/correction/pal.rs
```

### Dependencies
- Phases 1-3
- External: rubberband CLI (keep as subprocess)
- Rust crates: `hound` (WAV I/O), `rubato` (resampling)

### Step 4.1: Stepping Correction

**CRITICAL PRESERVATION**:

```rust
/// Audio segment for EDL (Edit Decision List)
#[pyclass]
#[derive(Clone, Debug)]
pub struct AudioSegment {
    #[pyo3(get)]
    pub start_s: f64,
    #[pyo3(get)]
    pub end_s: f64,
    #[pyo3(get)]
    pub delay_ms: i32,
    #[pyo3(get)]
    pub delay_raw: f64,
    #[pyo3(get)]
    pub drift_rate_ms_s: f64,
}
```

**CRITICAL - Buffer Alignment**:
```rust
/// CRITICAL: Opus and certain codecs produce unaligned output
/// Must trim to multiple of element_size (4 bytes for f32)
fn align_buffer(data: &[u8], element_size: usize) -> &[u8] {
    let aligned_len = (data.len() / element_size) * element_size;
    let trimmed = data.len() - aligned_len;
    if trimmed > 0 {
        // Log trimmed bytes for diagnostics
        log::debug!("Trimmed {} unaligned bytes", trimmed);
    }
    &data[..aligned_len]
}
```

**CRITICAL - Silence Detection**:
```rust
/// CRITICAL: Use std < 100.0 threshold for int32 PCM silence
fn is_silence(samples: &[i32]) -> bool {
    let std_dev = calculate_std(samples);
    std_dev < 100.0
}
```

**CRITICAL - Scan Ranges**:
```rust
/// CRITICAL: Stepping uses 5%-99% scan range
/// (different from main analysis 5%-95%)
const STEPPING_SCAN_START_PCT: f64 = 5.0;
const STEPPING_SCAN_END_PCT: f64 = 99.0;
```

### Step 4.2: Linear Drift Correction

**CRITICAL**: Keep rubberband as subprocess call (quality matters):
```rust
pub fn run_linear_correction(
    input_path: &Path,
    output_path: &Path,
    tempo_ratio: f64,
    engine: LinearCorrectionEngine,
    runner: &CommandRunner,
) -> Result<()> {
    match engine {
        LinearCorrectionEngine::Rubberband => {
            // CRITICAL: High-quality, keep as subprocess
            runner.run(&[
                "rubberband",
                "-t", &tempo_ratio.to_string(),
                input_path.to_str().unwrap(),
                output_path.to_str().unwrap(),
            ])
        }
        LinearCorrectionEngine::Aresample => {
            // FFmpeg aresample filter
            // ...
        }
        LinearCorrectionEngine::Atempo => {
            // FFmpeg atempo filter (fast, lower quality)
            // ...
        }
    }
}
```

### Step 4.3: PAL Correction

**CRITICAL PRESERVATION**:
```rust
/// CRITICAL: Exact PAL tempo ratio
const PAL_TEMPO_RATIO: f64 = (24000.0 / 1001.0) / 25.0;  // 0.95904...

/// CRITICAL: FLAC output has NO container delay (must be reset to 0)
pub fn run_pal_correction(
    input_path: &Path,
    output_path: &Path,
    runner: &CommandRunner,
) -> Result<CorrectionResult> {
    // ... correction logic

    Ok(CorrectionResult {
        output_path: output_path.to_path_buf(),
        container_delay_ms: 0,  // CRITICAL: Always 0 for corrected FLAC
        // ...
    })
}
```

### Testing Checkpoint 4
- [ ] Buffer alignment handles Opus codec output
- [ ] Silence detection matches Python thresholds
- [ ] EDL generation matches Python for known stepping audio
- [ ] PAL tempo ratio is exactly 0.95904...
- [ ] Corrected FLAC has container_delay_ms = 0
- [ ] Integration: Full stepping correction produces identical audio

---

## Phase 5: Subtitle Processing Core

### Status: [N/A] STAYS IN PYTHON

### Migration Decision: NO MIGRATION NEEDED

**Reason**: All subtitle processing relies heavily on `pysubs2`, which has no Rust equivalent. The `pysubs2` library provides:
- Full ASS/SSA/SRT/VTT parsing and manipulation
- Style management with proper color space handling
- Event timing and text manipulation
- Format conversion between subtitle formats

**Files that STAY in Python** (all use pysubs2):
```
python/vsg_core/subtitles/metadata_preserver.py  →  KEEP (uses pysubs2)
python/vsg_core/subtitles/style_engine.py        →  KEEP (uses pysubs2)
python/vsg_core/subtitles/timing.py              →  KEEP (uses pysubs2)
python/vsg_core/subtitles/cleanup.py             →  KEEP (uses pysubs2)
python/vsg_core/subtitles/frame_matching.py      →  KEEP (uses pysubs2)
python/vsg_core/subtitles/rescale.py             →  KEEP (uses pysubs2)
python/vsg_core/subtitles/stepping_adjust.py     →  KEEP (uses pysubs2)
python/vsg_core/subtitles/style_filter.py        →  KEEP (uses pysubs2)
python/vsg_core/subtitles/sync_modes/*.py        →  KEEP (all use pysubs2)
```

### Alternative Considered and Rejected

**Option**: Implement custom ASS parser in Rust
**Rejected because**:
- ASS/SSA format is complex with many edge cases
- pysubs2 handles format conversion (SRT↔ASS↔VTT)
- Aegisub metadata preservation is intricate
- Color space conversions (pysubs2.Color ↔ Qt hex format)
- Would require months of work to reach parity
- High risk of introducing subtitle corruption bugs

### Impact on Architecture

Subtitle processing remains a **Python-only layer** that calls into Rust for:
- Frame/time conversion utilities (Phase 6)
- Video analysis and correlation results

The Python subtitle modules will:
- Use correlation results from Rust
- Use drift detection results from Rust
- Apply delays calculated by Rust
- Keep all subtitle parsing/manipulation in Python with pysubs2

---

## Phase 6: Frame Utilities

### Status: [x] Completed (2026-01-16) - PARTIAL MIGRATION

### Migration Decision: SPLIT - Core utilities to Rust, sync modes stay in Python

**Files to Migrate to Rust** (pure computational logic):
```
python/vsg_core/subtitles/frame_utils.py (partial)  →  src/subtitles/frame_utils.rs
```

**Files to KEEP in Python** (use pysubs2):
```
python/vsg_core/subtitles/frame_sync.py      →  KEEP (re-exports only)
python/vsg_core/subtitles/sync_modes/*.py    →  KEEP (all use pysubs2)
```

### Dependencies
- Phase 1
- Keep `videotimestamps` in Python (no Rust equivalent)

### Step 6.1: Frame Conversion Methods (Migrate to Rust)

**CRITICAL PRESERVATION - Multiple modes**:

```rust
/// MODE 0: Frame START (deterministic)
/// Used for Correlation-Frame-Snap
/// CRITICAL: Uses epsilon (1e-6) for FP protection
pub fn time_to_frame_floor(time_ms: f64, fps: f64) -> u64 {
    let frame_duration = 1000.0 / fps;
    let epsilon = 1e-6;
    ((time_ms + epsilon) / frame_duration).floor() as u64
}

/// MODE 1: Middle of Frame (+0.5 offset)
pub fn time_to_frame_middle(time_ms: f64, fps: f64) -> u64 {
    let frame_duration = 1000.0 / fps;
    ((time_ms / frame_duration) + 0.5).floor() as u64
}

/// Frame to time (inverse)
pub fn frame_to_time(frame: u64, fps: f64) -> f64 {
    let frame_duration = 1000.0 / fps;
    frame as f64 * frame_duration
}
```

### Step 6.2: VFR Handling

**CRITICAL**: VideoTimestamps integration stays in Python.
Rust provides CFR utilities; Python wraps for VFR.

### Step 6.3: Python Integration

The Python subtitle processing modules will call Rust for frame conversion utilities:

```python
# Python: python/vsg_core/subtitles/sync_modes/time_based.py
from vsg_core_rs import time_to_frame_floor, frame_to_time_floor
import pysubs2

def apply_sync(subtitle_path, delay_ms, fps):
    subs = pysubs2.load(subtitle_path)  # Python handles parsing

    # Use Rust for frame conversions (fast, precise)
    for event in subs.events:
        # Python handles subtitle manipulation
        event.start += delay_ms
        event.end += delay_ms

    subs.save(subtitle_path)
```

### What Stays in Python

The following `frame_utils.py` functions **cannot** be migrated (depend on Python libraries):
- `get_vapoursynth_frame_info()` - Requires VapourSynth Python API
- `detect_scene_changes()` - Requires PySceneDetect library
- `extract_frame_as_image()` - Requires VapourSynth + PIL
- `compute_perceptual_hash()` - Requires imagehash library
- `detect_video_fps()` - Uses videotimestamps or ffprobe subprocess
- `get_vfr_timestamps()` - Requires videotimestamps library

### Testing Checkpoint 6
- [ ] Frame conversions match Python for all modes
- [ ] Epsilon protection prevents FP drift issues
- [ ] Round-trip frame→time→frame is stable
- [ ] Python subtitle sync modes can call Rust utilities

---

## Phase 7: Extraction Layer

### Status: [x] Completed (2026-01-16)

### Files to Migrate
```
python/vsg_core/extraction/tracks.py       →  src/extraction/tracks.rs
python/vsg_core/extraction/attachments.py  →  src/extraction/attachments.rs
python/vsg_core/chapters/process.py        →  src/chapters/process.rs
```

### Dependencies
- Phase 1
- Keep mkvmerge/ffprobe as subprocess calls

### Step 7.1: mkvmerge JSON Parsing

**CRITICAL PRESERVATION**:

```rust
/// Parse mkvmerge -J output
///
/// CRITICAL: minimum_timestamp is in NANOSECONDS
/// CRITICAL: Use round() not truncate for container_delay_ms
pub fn parse_mkvmerge_json(json_str: &str) -> Result<StreamInfo> {
    let info: MkvmergeInfo = serde_json::from_str(json_str)?;

    for track in &mut info.tracks {
        if matches!(track.track_type, TrackType::Audio | TrackType::Video) {
            let min_ts_ns = track.properties.minimum_timestamp.unwrap_or(0);
            // CRITICAL: Nanoseconds to milliseconds with proper rounding
            track.container_delay_ms = (min_ts_ns as f64 / 1_000_000.0).round() as i32;
        } else {
            // Subtitles don't have meaningful container delays
            track.container_delay_ms = 0;
        }
    }

    Ok(info)
}
```

### Step 7.2: Chapter Processing

**CRITICAL PRESERVATION**:
- Chapters must be shifted by global_shift_ms
- Chapter snapping to keyframes (optional feature)
- XML format must be preserved exactly

### Testing Checkpoint 7
- [ ] mkvmerge JSON parsing matches Python exactly
- [ ] Container delays calculated correctly (nanoseconds → ms)
- [ ] Negative delays handled with round() not int()
- [ ] Chapter XML round-trips without modification

---

## Phase 8: Mux Options Builder

### Status: [✓] Completed

### Files to Migrate
```
python/vsg_core/mux/options_builder.py  →  src/mux/options_builder.rs
```

### Dependencies
- Phases 1, 7

### Step 8.1: Options Builder

**CRITICAL PRESERVATION - Delay Rules**:

```rust
/// Calculate final delay for a track
///
/// CRITICAL RULES:
/// - Source 1 AUDIO: container_delay + global_shift
/// - Source 1 VIDEO: ONLY global_shift (IGNORE container delay)
/// - Other Sources: correlation_delay (already includes global_shift)
/// - stepping_adjusted=true: Return 0 (delay baked in)
/// - frame_adjusted=true: Return 0 (delay baked in)
pub fn calculate_track_delay(
    item: &PlanItem,
    delays: &Delays,
    global_shift: i32,
) -> i32 {
    // Subtitles with baked-in timing
    if item.stepping_adjusted || item.frame_adjusted {
        return 0;
    }

    if item.source_key == "Source 1" {
        match item.track_type {
            TrackType::Video => {
                // CRITICAL: Video ignores container delay
                global_shift
            }
            TrackType::Audio => {
                // CRITICAL: Use round() for negative values
                let container = (item.container_delay_ms as f64).round() as i32;
                container + global_shift
            }
            _ => 0,
        }
    } else {
        // Other sources use correlation delay
        delays.source_delays_ms
            .get(&item.source_key)
            .copied()
            .unwrap_or(0)
    }
}
```

**CRITICAL - Token Format**:
```rust
/// Build mkvmerge command tokens
///
/// CRITICAL: Delays are signed format: "+500" or "-500"
pub fn build_sync_token(track_idx: u32, delay_ms: i32) -> Vec<String> {
    vec![
        "--sync".to_string(),
        format!("{}:{:+}", track_idx, delay_ms),  // Note: {:+} for signed
    ]
}
```

### Step 8.2: JSON Output

**CRITICAL PRESERVATION**:
```rust
/// Write options to JSON file
///
/// CRITICAL: ensure_ascii=false equivalent (UTF-8 characters allowed)
/// CRITICAL: Single-line JSON array (no formatting in file)
pub fn write_options_file(tokens: &[String], path: &Path) -> Result<()> {
    let json = serde_json::to_string(tokens)?;  // No pretty-print
    std::fs::write(path, json)?;
    Ok(())
}
```

### Testing Checkpoint 8
- [✓] Delay calculation matches Python for all track types
- [✓] Signed delay format correct (+500, -500)
- [✓] JSON output matches Python exactly
- [✓] UTF-8 track names preserved in JSON

---

## Phase 9: Core Shell + Embedded Python

### Status: [ ] Not Started

> ⚠️ **CRITICAL MISSING PIECE**: Phases 1-8 implemented Rust code, but Python does NOT call it yet.
> The Rust and Python implementations exist in parallel. This phase establishes the **runnable core shell** first, then integrates modules.

### Current State
- **Rust code exists**: `vsg_core_rs/src/` with all Phase 1-8 implementations
- **Python code unchanged**: `python/vsg_core/` still uses pure Python implementations
- **No integration**: Zero Python files import from `vsg_core_rs`

### Phase 9A: Core Shell First (Required)

Deliver a **runnable Rust shell** that mirrors Python structure 1:1. Stubs are acceptable as long as the layout matches.

```
vsg_core_rs/src/
├── orchestrator/            # Rust pipeline orchestration
├── pipeline/                # Job pipeline coordination
├── pipeline_components/     # Logging, result audit, output writer
├── workers/                 # Worker lifecycle + threading
├── config/                  # Settings, defaults, persistence
└── ui_bridge/               # Hooks for UI <-> core (if needed)
```

### Phase 9B: Embedded Python + Bridges

**Primary rule**: If a Rust module is not ready, call the Python implementation directly via embedding.
Bridges remain useful for parity testing and gradual switchover.

Create wrapper modules that bridge Python → Rust. These go in `python/vsg_core/` and provide 1:1 naming with existing Python APIs:

```
python/vsg_core/
├── _rust_bridge/                    ← NEW: Integration layer
│   ├── __init__.py
│   ├── analysis.py                  ← Wraps vsg_core_rs analysis functions
│   ├── correction.py                ← Wraps vsg_core_rs correction functions
│   ├── extraction.py                ← Wraps vsg_core_rs extraction functions
│   ├── chapters.py                  ← Wraps vsg_core_rs chapter functions
│   ├── mux.py                       ← Wraps vsg_core_rs mux functions
│   └── frame_utils.py               ← Wraps vsg_core_rs frame utilities
```

**Integration Pattern** (keeps Python API stable):

```python
# python/vsg_core/_rust_bridge/analysis.py
"""
Bridge module: Provides same API as python/vsg_core/analysis/audio_corr.py
but delegates to Rust implementation.
"""
try:
    from vsg_core_rs import (
        analyze_audio_correlation as _rust_correlate,
        CorrelationMethod,
        DelaySelectionMode,
    )
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False

def run_correlation(ref_audio, tgt_audio, sample_rate, method="gcc_phat", **kwargs):
    """
    1:1 API match with existing Python implementation.
    Delegates to Rust when available.
    """
    if RUST_AVAILABLE:
        return _rust_correlate(ref_audio, tgt_audio, sample_rate, method, **kwargs)
    else:
        # Fallback to pure Python (for testing/comparison)
        from vsg_core.analysis.audio_corr import run_correlation as _py_correlate
        return _py_correlate(ref_audio, tgt_audio, sample_rate, method, **kwargs)
```

### Phase 9C: Integration Testing

**Step-by-step validation** to ensure Rust produces identical results:

| Test | Python Module | Rust Bridge | Validation |
|------|---------------|-------------|------------|
| 1 | `analysis/audio_corr.py` | `_rust_bridge/analysis.py` | Same delay ±0.1ms, same confidence |
| 2 | `analysis/drift_detection.py` | `_rust_bridge/analysis.py` | Same diagnosis enum |
| 3 | `correction/stepping.py` | `_rust_bridge/correction.py` | Same EDL segments |
| 4 | `correction/linear.py` | `_rust_bridge/correction.py` | Same tempo ratio |
| 5 | `extraction/tracks.py` | `_rust_bridge/extraction.py` | Same container delays |
| 6 | `chapters/process.py` | `_rust_bridge/chapters.py` | Same shifted timestamps |
| 7 | `mux/options_builder.py` | `_rust_bridge/mux.py` | Same mkvmerge tokens |
| 8 | `subtitles/frame_utils.py` | `_rust_bridge/frame_utils.py` | Same frame numbers |

### Phase 9D: Real-World Testing

```
Test Files Required:
├── stepping_audio/           ← Audio with known stepping issues
├── pal_drift_audio/          ← PAL framerate drift samples
├── linear_drift_audio/       ← Linear drift samples
├── complex_subtitles/        ← ASS/SSA with styles
└── vfr_video/                ← Variable framerate test files
```

**Validation Process**:
1. Run full pipeline with pure Python
2. Run full pipeline with Rust bridge
3. Compare outputs byte-for-byte (muxed file)
4. Compare intermediate results (delays, EDL, tokens)

### Phase 9E: Switchover

Once testing passes:
1. Update orchestrator steps to use `_rust_bridge` modules
2. Keep Python implementations for fallback/comparison
3. Add `USE_RUST=true` environment variable for gradual rollout

### Files to Create

```
vsg_core_rs/src/orchestrator/
vsg_core_rs/src/pipeline/
vsg_core_rs/src/pipeline_components/
vsg_core_rs/src/workers/
vsg_core_rs/src/config/
vsg_core_rs/src/ui_bridge/
python/vsg_core/_rust_bridge/__init__.py
python/vsg_core/_rust_bridge/analysis.py
python/vsg_core/_rust_bridge/correction.py
python/vsg_core/_rust_bridge/extraction.py
python/vsg_core/_rust_bridge/chapters.py
python/vsg_core/_rust_bridge/mux.py
python/vsg_core/_rust_bridge/frame_utils.py
tests/integration/test_rust_python_parity.py
```

### Files to Modify

```
python/vsg_core/orchestrator/steps/analysis_step.py     →  Import from _rust_bridge
python/vsg_core/orchestrator/steps/extract_step.py      →  Import from _rust_bridge
python/vsg_core/orchestrator/steps/audio_correction_step.py  →  Import from _rust_bridge
python/vsg_core/orchestrator/steps/chapters_step.py     →  Import from _rust_bridge
python/vsg_core/orchestrator/steps/mux_step.py          →  Import from _rust_bridge
```

### Testing Checkpoint 9
- [ ] Core shell compiles with stubbed steps
- [ ] Build `vsg_core_rs` with `maturin develop`
- [ ] Embedded Python calls succeed for unported modules
- [ ] All bridge modules import successfully
- [ ] Unit tests: Rust output matches Python for each function
- [ ] Integration test: Full pipeline produces identical output
- [ ] Real-world test: Process known test files successfully
- [ ] No regressions in existing Python-only workflow

---

## Phase 10: UI Migration

### Status: [ ] Not Started (LAST - After Phase 9 Complete)

### Current Strategy (Hybrid)
1. **Keep PySide6 UI** for now (`python/vsg_qt/`)
2. **Use PyO3 FFI** to call Rust backend via `vsg_core_rs`
3. Benefit: UI continues working while backend transitions to Rust

### Future Strategy (Full Rust GUI)

Once Phase 9 integration is stable and tested, migrate to a Rust-native GUI:

| Framework | Pros | Cons |
|-----------|------|------|
| **libcosmic** (System76) | Native look, Iced-based, good for Linux | Linux-focused, newer ecosystem |
| **Slint** | Declarative, cross-platform, good tooling | Commercial license for some uses |
| **egui** | Immediate mode, simple, pure Rust | Less native look |
| **Tauri** | Web technologies (HTML/CSS/JS) | Still uses web renderer |
| **iced** | Elm-like architecture, pure Rust | Still maturing |

### Migration Path

```
Current State:
├── python/vsg_qt/ (PySide6 Python)
└── vsg_core_rs/ (Rust library)

Phase 9 Complete:
├── python/vsg_qt/ (PySide6 Python) ─→ calls ─→ vsg_core_rs/
└── python/vsg_core/ (Python orchestration) ─→ calls ─→ vsg_core_rs/

Phase 10 Complete:
├── vsg_gui/ (Rust GUI - libcosmic/slint/egui)
└── vsg_core_rs/ (Rust library - direct calls, no FFI)
```

### 1:1 Naming Convention

To ensure nothing is missed during migration, maintain identical naming:

| Python (vsg_qt) | Rust GUI (vsg_gui) |
|-----------------|-------------------|
| `main_window/window.py` | `main_window/window.rs` |
| `main_window/controller.py` | `main_window/controller.rs` |
| `job_queue_dialog/*.py` | `job_queue_dialog/*.rs` |
| `add_job_dialog/*.py` | `add_job_dialog/*.rs` |
| `options_dialog/*.py` | `options_dialog/*.rs` |
| ... | ... |

### Files (41 modules to eventually migrate)
All modules in `python/vsg_qt/` - migrate last after Phase 9 is stable and tested.

---

## Critical Preservation Requirements

### 1. Logging System

**DO NOT CHANGE**:
- Timestamp format: `[HH:MM:SS]` prepended to all messages
- Message prefixes: `[ERROR]`, `[WARNING]`, `[INFO]`, `[DEBUG]`, `[FATAL]`, `[!]`
- Section markers: `--- Section Name ---`
- Progress format: `Progress: N%`
- Error tailing: `[stderr/tail]` with configurable line count
- Log file encoding: UTF-8

**Implementation**:
```rust
// Rust logging must emit strings compatible with Python callback
pub fn format_log_message(level: LogLevel, msg: &str) -> String {
    let prefix = match level {
        LogLevel::Error => "[ERROR]",
        LogLevel::Warning => "[WARNING]",
        LogLevel::Info => "[INFO]",
        LogLevel::Debug => "[DEBUG]",
        LogLevel::Fatal => "[FATAL]",
    };
    format!("{} {}", prefix, msg)
}
```

### 2. mkvmerge JSON Handling

**DO NOT CHANGE**:
- JSON parsing from `mkvmerge -J`
- `minimum_timestamp` in nanoseconds → milliseconds conversion
- `round()` not `int()` for negative values
- `ensure_ascii=False` for output (UTF-8)
- Single-line JSON array format for options file

### 3. Numerical Thresholds

**DO NOT CHANGE** (unless explicitly requested):

| Threshold | Value | Location |
|-----------|-------|----------|
| GCC-PHAT epsilon | 1e-9 | audio_corr |
| Silence std threshold | 100.0 | stepping |
| Frame epsilon | 1e-6 | frame_utils |
| PAL tempo ratio | 0.95904... | pal.py |
| Default scan start | 5% | audio_corr |
| Default scan end | 95% | audio_corr |
| Stepping scan end | 99% | stepping |
| Default chunk duration | 15s | audio_corr |
| Min match percent | 5% | audio_corr |
| Confidence ratio min | 5.0 | stepping |

### 4. Data Structure Invariants

**MUST MAINTAIN**:
- `source_delays_ms` and `raw_source_delays_ms` have identical keys
- `container_delay_ms` is `i32` (can be negative)
- State flags (`stepping_adjusted`, `frame_adjusted`) determine delay application

### 5. Platform Compatibility

**MUST SUPPORT**:
- Linux (primary)
- Windows (secondary)
- GPU detection (CUDA, ROCm, MPS)

---

## Testing Strategy

### Unit Tests (Per Phase)
Each phase includes specific test checkpoints. All must pass before proceeding.

### Integration Tests
After each phase:
1. Run full pipeline on test files
2. Compare output to Python-only baseline
3. Verify byte-identical muxed output (when possible)

### Regression Tests
Maintain test suite with:
- Known stepping audio files
- Known PAL drift files
- Complex subtitle timing
- Edge case configs (different delay modes, source separation)

### Memory Testing
After Phase 2:
- Run 10 consecutive analyses
- Monitor memory usage
- Verify no leaks (Rust should eliminate numpy issues)

---

## Completion Tracking

> ⚠️ **Important Clarification**: "Rust Complete" means the Rust code is written and unit-tested.
> It does **NOT** mean Python is calling Rust. Python integration is tracked separately.

### Phase Status

| Phase | Rust Code | Python Integration | Started | Completed | Notes |
|-------|-----------|-------------------|---------|-----------|-------|
| 1 | ✅ Complete | ❌ Not started | 2026-01-16 | 2026-01-16 | Core data types in Rust |
| 2 | ✅ Complete | ❌ Not started | 2026-01-16 | 2026-01-16 | Audio correlation in Rust |
| 3 | ✅ Complete | ❌ Not started | 2026-01-16 | 2026-01-16 | Drift detection in Rust |
| 4 | ✅ Complete | ❌ Not started | 2026-01-16 | 2026-01-16 | Audio correction in Rust |
| 5 | N/A | N/A | - | 2026-01-16 | STAYS IN PYTHON (pysubs2) |
| 6 | ✅ Complete | ❌ Not started | 2026-01-16 | 2026-01-16 | Frame utils in Rust (partial) |
| 7 | ✅ Complete | ❌ Not started | 2026-01-16 | 2026-01-16 | Extraction/chapters in Rust |
| 8 | ✅ Complete | ❌ Not started | 2026-01-16 | 2026-01-16 | Mux delay calc in Rust |
| **9** | N/A | ❌ **CURRENT** | - | - | **Core Shell + Embedded Python** |
| 10 | ❌ Not started | ❌ Not started | - | - | Future GUI migration |

### What's Actually Running

| Component | Currently Uses | Should Use After Phase 9 |
|-----------|---------------|-------------------------|
| Audio correlation | `python/vsg_core/analysis/audio_corr.py` (Python) | `vsg_core_rs.analyze_audio_correlation` (Rust) |
| Drift detection | `python/vsg_core/analysis/drift_detection.py` (Python) | `vsg_core_rs.diagnose_drift` (Rust) |
| Container delays | `python/vsg_core/extraction/tracks.py` (Python) | `vsg_core_rs.calculate_container_delay` (Rust) |
| Mux delay calc | `python/vsg_core/mux/options_builder.py` (Python) | `vsg_core_rs.calculate_mux_delay` (Rust) |
| Frame conversions | `python/vsg_core/subtitles/frame_utils.py` (Python) | `vsg_core_rs.time_to_frame_*` (Rust) |
| Chapter timestamps | `python/vsg_core/chapters/process.py` (Python) | `vsg_core_rs.shift_chapter_timestamp` (Rust) |

### Integration Gap Identified

| Date | Issue | Impact |
|------|-------|--------|
| 2026-01-16 | **Python integration layer missing** | All phases 1-8 have Rust code but Python doesn't call it |
| 2026-01-16 | **No `_rust_bridge` modules exist** | Orchestrator steps use pure Python implementations |
| 2026-01-16 | **Parallel development created two implementations** | Both work, neither talks to the other |

### Next Steps (Phase 9)

1. [ ] Define Rust core shell folder structure (matching Python layout)
2. [ ] Implement orchestrator + worker lifecycle with stubbed steps
3. [ ] Embed Python modules for unported functionality
4. [ ] Build `vsg_core_rs` with `maturin develop` and verify imports work
5. [ ] Create `python/vsg_core/_rust_bridge/__init__.py`
6. [ ] Create bridge modules one at a time, test each
7. [ ] Run full pipeline comparison tests
8. [ ] Validate output matches pure Python version

### Checkpoint Log

| Date | Phase | Checkpoint | Result | Notes |
|------|-------|------------|--------|-------|
| 2026-01-16 | 1 | Build with maturin | PASS | Successfully compiled with PyO3 0.27 |
| 2026-01-16 | 1 | Python imports | PASS | All types importable from vsg_core_rs |
| 2026-01-16 | 1 | Enum values | PASS | Enums match Python expectations |
| 2026-01-16 | 1 | Type instantiation | PASS | All types can be created and used from Python |
| 2026-01-16 | 1 | Converter functions | PASS | nanoseconds_to_ms, round_delay_ms work correctly |
| 2026-01-16 | 2 | Build correlation engine | PASS | All algorithms compile successfully |
| 2026-01-16 | 2 | GCC-PHAT implementation | PASS | Epsilon 1e-9, lag calculation matches Python |
| 2026-01-16 | 2 | SCC/SCOT/Whitened | PASS | All correlation methods implemented |
| 2026-01-16 | 2 | Delay selection modes | PASS | All 4 modes (MostCommon, Clustered, Average, FirstStable) |
| 2026-01-16 | 2 | Parallel processing | PASS | Rayon-based chunk processing |
| 2026-01-16 | 2 | PyO3 bindings | PASS | analyze_audio_correlation function exposed |
| 2026-01-16 | 3 | Build drift detection | PASS | Custom DBSCAN implementation compiles successfully |
| 2026-01-16 | 3 | DBSCAN clustering | PASS | 1D DBSCAN with eps=20ms, min_samples=2 |
| 2026-01-16 | 3 | PAL drift detection | PASS | 25fps ±0.1, 40.9ms/s drift ±5ms tolerance |
| 2026-01-16 | 3 | Linear drift detection | PASS | R² thresholds, codec-aware slope detection |
| 2026-01-16 | 3 | Quality validation | PASS | Strict/normal/lenient modes, cluster filtering |
| 2026-01-16 | 4 | Build correction modules | PASS | EDL, linear, PAL, utils modules compile |
| 2026-01-16 | 4 | EDL generation | PASS | AudioSegment struct, generate_edl_from_correlation with filtering |
| 2026-01-16 | 4 | Linear tempo ratio | PASS | Formula: 1000/(1000+drift_rate), rubberband/aresample/atempo |
| 2026-01-16 | 4 | PAL tempo ratio | PASS | Constant: 0.95904, drift rate: 40.9 ms/s |
| 2026-01-16 | 4 | Buffer alignment | PASS | align_buffer for Opus, element_size=4 bytes |
| 2026-01-16 | 4 | Silence detection | PASS | is_silence with std < 100.0 for int32 PCM |
| 2026-01-16 | 4 | Unit tests | PASS | 31 tests passed, all Phase 4 logic verified |
| 2026-01-16 | 5 | Migration decision | N/A | Phase 5 stays in Python - pysubs2 has no Rust equivalent |
| 2026-01-16 | 6 | Build frame utilities | PASS | Created src/subtitles/frame_utils.rs with all conversion modes |
| 2026-01-16 | 6 | MODE 0 implementation | PASS | time_to_frame_floor, frame_to_time_floor with epsilon 1e-6 |
| 2026-01-16 | 6 | MODE 1 implementation | PASS | time_to_frame_middle, frame_to_time_middle with Python banker's rounding |
| 2026-01-16 | 6 | MODE 2 implementation | PASS | time_to_frame_aegisub, frame_to_time_aegisub with centisecond rounding |
| 2026-01-16 | 6 | Rust unit tests | PASS | 13 tests passed, all modes verified |
| 2026-01-16 | 6 | Python integration | PASS | All functions match Python implementation exactly |
| 2026-01-16 | 6 | PyO3 bindings | PASS | All 6 functions callable from Python |
| 2026-01-16 | 7 | Build extraction module | PASS | Created src/extraction/tracks.rs with container delay calculation |
| 2026-01-16 | 7 | Container delay formula | PASS | round(ns / 1_000_000) - uses round() not int() for negatives |
| 2026-01-16 | 7 | mkvmerge JSON parsing | PASS | add_container_delays_to_json processes tracks correctly |
| 2026-01-16 | 7 | Subtitle delay handling | PASS | Subtitles always get container_delay_ms = 0 |
| 2026-01-16 | 7 | Build chapters module | PASS | Created src/chapters/timestamps.rs with nanosecond precision |
| 2026-01-16 | 7 | Timestamp shifting | PASS | shift_timestamp_ns with clamping to 0 |
| 2026-01-16 | 7 | Timestamp formatting | PASS | format_ns/parse_ns for HH:MM:SS.nnnnnnnnn format |
| 2026-01-16 | 7 | Rust unit tests | PASS | 26 new tests passed (extraction + chapters) |
| 2026-01-16 | 7 | Python integration | PASS | All 5 functions work correctly from Python |
| 2026-01-16 | 7 | PyO3 bindings | PASS | Container delay, JSON processing, chapter timestamps |
| 2026-01-16 | 8 | Build mux module | PASS | Created src/mux/delay_calculator.rs |
| 2026-01-16 | 8 | Delay calculation rules | PASS | Source 1 video/audio, stepping/frame-adjusted, other sources |
| 2026-01-16 | 8 | Source 1 video logic | PASS | Only global_shift applied (container delay ignored) |
| 2026-01-16 | 8 | Source 1 audio logic | PASS | container_delay + global_shift |
| 2026-01-16 | 8 | Stepping-adjusted logic | PASS | Returns 0 (delay baked into subtitle file) |
| 2026-01-16 | 8 | Frame-adjusted logic | PASS | Returns 0 (delay baked into subtitle file) |
| 2026-01-16 | 8 | Sync token building | PASS | build_sync_token with signed format (+500, -500, +0) |
| 2026-01-16 | 8 | Rust unit tests | PASS | 15 new tests passed covering all delay scenarios |
| 2026-01-16 | 8 | Python integration | PASS | All delay calculations and token building work from Python |
| 2026-01-16 | 8 | PyO3 bindings | PASS | calculate_mux_delay, build_mkvmerge_sync_token |

---

## Instructions for AI Assistants

### MANDATORY RULES

1. **Read this document first** before making any migration changes.

2. **Do not deviate** from the plan without discussing with the user first. If you believe a different approach is better, explain why and get approval.

3. **Preserve all behaviors** listed in Critical Preservation Requirements. These took significant time to get right.

4. **Update this document** after completing each phase or making significant additions:
   - Mark phases complete in Completion Tracking
   - Add notes about any discoveries or changes
   - Log test results in Checkpoint Log

5. **Small, testable steps**. Never break functionality for more than one phase. The app must work throughout migration.

6. **Do not change logging**. The logging system is purposeful and must remain compatible.

7. **Do not change mkvmerge JSON handling**. This was extensively tested and debugged.

8. **Test before proceeding**. Each phase has testing checkpoints. All must pass before moving to the next phase.

9. **When in doubt, ask**. If something is unclear or seems wrong, discuss with the user before implementing.

10. **Core shell first**: Do not skip orchestrator/worker/config/UI wiring. Leaf modules only move after the shell is runnable.

11. **Embed Python early**: If a Rust module is not ready, call the Python implementation directly via embedding. Do not re-implement logic "just to make it compile."

12. **1:1 Layout Requirement**: Rust directories must mirror Python structure 1:1 (names, nesting). Placeholder modules are acceptable, but the layout must match.

13. **Documentation parity**: Python code uses detailed notes about what sections do and why; Rust code must include equivalent inline notes (where appropriate) so humans and AI can understand intent and constraints.

14. **Formatting discipline**: Do not introduce sloppy formatting. Follow existing code standards and keep formatting consistent with the surrounding codebase.

### Document Maintenance

When working on this migration:

```markdown
### Session: [DATE]
**Phase**: [N]
**Work Done**:
- Item 1
- Item 2

**Test Results**:
- Checkpoint X: PASS/FAIL
- Notes...

**Changes to Plan**:
- None / Description of changes

**Next Steps**:
- ...
```

Add this to the Checkpoint Log section.

### Code Review Checklist

Before marking any phase complete:
- [ ] All listed files migrated
- [ ] All testing checkpoints pass
- [ ] No regressions in existing functionality
- [ ] Memory usage stable (no leaks)
- [ ] Logging output unchanged
- [ ] mkvmerge JSON handling unchanged
- [ ] Document updated with completion status

---

## Appendix A: Rust Crate Recommendations

> **Last verified**: 2026-01-16

| Purpose | Crate | Version | Notes |
|---------|-------|---------|-------|
| FFT | `rustfft` | 6.4.1 | Fast, pure Rust, SIMD-accelerated |
| Arrays | `ndarray` | 0.17.1 | numpy-like, with rayon support |
| Parallelism | `rayon` | 1.11.0 | Easy data parallelism |
| Python bindings | `pyo3` | 0.27.1 | Mature, requires Rust 1.74+ |
| NumPy interop | `numpy` | 0.27.0 | PyO3 crate for numpy arrays (NOT Python numpy) |
| JSON | `serde_json` | 1.0 | Standard |
| WAV I/O | `hound` | 3.5 | Simple, reliable |
| Resampling | `rubato` | 0.15 | High quality |
| Clustering | `linfa-clustering` | 0.8.1 | DBSCAN support |
| XML | `quick-xml` | 0.37 | Fast XML parsing |
| Logging | `log` + `env_logger` | 0.4 / 0.11 | Standard |
| Complex numbers | `num-complex` | 0.4 | For FFT operations |

### Crate Clarifications

**`numpy` crate**: This is the [Rust crate from crates.io](https://crates.io/crates/numpy) that provides PyO3 bindings for NumPy's C-API. It allows Rust to receive and return numpy arrays from Python with zero-copy when possible. This is NOT Python's numpy - it's the Rust interop layer.

**Source separation**: The `audio-separator` Python package provides access to PyTorch/ONNX models (Demucs, Roformer, MDX-Net, etc.). This stays in Python because:
1. It's already subprocess-isolated in the current codebase
2. The models are PyTorch/ONNX which have mature Python ecosystems
3. No equivalent Rust libraries exist for these specific models

## Appendix B: File Inventory

### vsg_core (92 modules)
<details>
<summary>Click to expand full list</summary>

```
python/vsg_core/
├── __init__.py
├── config.py
├── job_discovery.py
├── pipeline.py
├── models/
│   ├── __init__.py
│   ├── enums.py
│   ├── media.py
│   ├── jobs.py
│   ├── results.py
│   ├── settings.py
│   └── converters.py
├── system/
│   └── gpu_env.py
├── io/
│   └── runner.py
├── analysis/
│   ├── __init__.py
│   ├── audio_corr.py
│   ├── drift_detection.py
│   ├── source_separation.py
│   └── videodiff.py
├── extraction/
│   ├── __init__.py
│   ├── tracks.py
│   └── attachments.py
├── correction/
│   ├── __init__.py
│   ├── stepping.py
│   ├── linear.py
│   └── pal.py
├── subtitles/
│   ├── __init__.py
│   ├── frame_utils.py
│   ├── frame_sync.py
│   ├── frame_matching.py
│   ├── metadata_preserver.py
│   ├── style_engine.py
│   ├── timing.py
│   ├── cleanup.py
│   ├── convert.py
│   ├── ocr.py
│   ├── rescale.py
│   ├── style.py
│   ├── style_filter.py
│   ├── checkpoint_selection.py
│   ├── stepping_adjust.py
│   └── sync_modes/
│       ├── __init__.py
│       ├── time_based.py
│       ├── correlation_frame_snap.py
│       ├── correlation_guided_frame_anchor.py
│       ├── subtitle_anchored_frame_snap.py
│       ├── duration_align.py
│       └── timebase_frame_locked_timestamps.py
├── chapters/
│   ├── __init__.py
│   ├── process.py
│   └── keyframes.py
├── mux/
│   ├── __init__.py
│   └── options_builder.py
├── job_layouts/
│   ├── __init__.py
│   ├── manager.py
│   ├── signature.py
│   ├── persistence.py
│   └── validation.py
├── orchestrator/
│   ├── __init__.py
│   ├── pipeline.py
│   ├── validation.py
│   └── steps/
│       ├── __init__.py
│       ├── context.py
│       ├── analysis_step.py
│       ├── extract_step.py
│       ├── audio_correction_step.py
│       ├── subtitles_step.py
│       ├── chapters_step.py
│       ├── attachments_step.py
│       └── mux_step.py
├── pipeline_components/
│   ├── __init__.py
│   ├── tool_validator.py
│   ├── log_manager.py
│   ├── output_writer.py
│   ├── result_auditor.py
│   ├── sync_planner.py
│   └── sync_executor.py
└── postprocess/
    ├── __init__.py
    ├── finalizer.py
    ├── final_auditor.py
    ├── chapter_backup.py
    └── auditors/
        └── [17 auditor modules]
```
</details>

### vsg_qt (41 modules)
<details>
<summary>Click to expand full list</summary>

```
python/vsg_qt/
├── __init__.py
├── main_window/
│   ├── __init__.py
│   ├── window.py
│   └── controller.py
├── worker/
│   ├── __init__.py
│   ├── runner.py
│   └── signals.py
├── job_queue_dialog/
├── add_job_dialog/
├── options_dialog/
├── manual_selection_dialog/
├── track_widget/
├── track_settings_dialog/
├── style_editor_dialog/
├── generated_track_dialog/
├── sync_exclusion_dialog/
├── resample_dialog/
└── [other dialog modules]
```
</details>

---

*End of Migration Plan Document*
