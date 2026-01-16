# Video-Sync-GUI: Rust Migration Master Plan

> **Document Purpose**: This is the authoritative reference for migrating Video-Sync-GUI from Python to Rust. It must be consulted and updated by any AI or developer working on this migration.
>
> **Last Updated**: 2026-01-16
> **Migration Status**: Planning Phase

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
15. [Phase 9: Pipeline Orchestration](#phase-9-pipeline-orchestration)
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

### Principle 1: Bottom-Up Migration
Start with modules that have **zero internal dependencies**, work upward. This ensures:
- Each Rust module can be tested independently
- Python orchestration continues working with Rust components via PyO3
- No circular dependency issues

### Principle 2: Preserve All Behaviors
Every special case, threshold, and edge case handling must be preserved exactly. The migration document includes specific notes about what must not change.

### Principle 3: Small, Testable Steps
Each phase produces a working system. Never break functionality for more than one phase.

### Principle 4: Hybrid Operation
During migration, Python calls Rust via PyO3 bindings. Rust handles compute-heavy work; Python handles orchestration and UI.

---

## 3. What Stays in Python

These components will remain in Python for the foreseeable future:

| Component | Reason |
|-----------|--------|
| `videotimestamps` library | No Rust equivalent exists |
| Source separation models | PyTorch/ONNX ecosystem, already subprocess-isolated |
| Qt UI (`vsg_qt/*`) | Migrated last; PyO3 FFI works well |
| External tool calls | Already subprocess-based (ffmpeg, mkvmerge, etc.) |

---

## 4. Build and Distribution Strategy

### How Rust Integrates with Current Setup

Your current setup uses:
- `.venv/` — Python virtual environment
- `run.sh` — Activates venv, sets ROCm env, runs `python main.py`
- `setup_env.sh` — Creates venv, installs Python dependencies

The Rust library will be built with **maturin** and installed into the same venv:

```
┌─────────────────────────────────────────────────────────────┐
│                    Project Directory                         │
├─────────────────────────────────────────────────────────────┤
│  run.sh              → Unchanged (runs python main.py)       │
│  setup_env.sh        → Add Rust build step                   │
│  main.py             → Unchanged                             │
│  requirements.txt    → Unchanged                             │
│                                                              │
│  .venv/                                                      │
│  └── lib/python3.13/site-packages/                          │
│      ├── vsg_core_rs.cpython-313-x86_64-linux-gnu.so  ←NEW  │
│      ├── numpy/                                              │
│      ├── scipy/                                              │
│      └── ... (other packages)                                │
│                                                              │
│  vsg_core_rs/        ←NEW (Rust source)                      │
│  ├── Cargo.toml                                              │
│  ├── pyproject.toml  (maturin config)                        │
│  └── src/                                                    │
│      ├── lib.rs                                              │
│      └── ...                                                 │
│                                                              │
│  vsg_core/           (Python - calls into Rust)              │
│  vsg_qt/             (Python UI)                             │
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

### Updated setup_env.sh

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
if [ -d "$PROJECT_DIR/vsg_core_rs" ]; then
    cd "$PROJECT_DIR/vsg_core_rs"
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
| `.venv/lib/python3.13/site-packages/vsg_core_rs*.so` | Installed native module |

### Distribution Options

1. **Development/Local**: Use `maturin develop` — builds and installs directly into venv
2. **Wheel Distribution**: Use `maturin build` — creates `.whl` file users can `pip install`
3. **Source Distribution**: Ship `vsg_core_rs/` source, users run `maturin develop`

**Recommended for your project**: Option 3 (source distribution) since:
- Users already run `setup_env.sh`
- Rust compilation handles platform differences automatically
- No need to build wheels for every platform

### run.sh and setup_env.sh Stay Mostly Unchanged

- `run.sh` — No changes needed. It activates venv and runs `python main.py`. The Rust library is already in the venv's site-packages.
- `setup_env.sh` — Add the Rust build step shown above. Everything else stays the same.

### GPU Environment

Your ROCm environment detection in `run.sh` stays exactly as-is. The Rust library doesn't need GPU access directly — source separation (which uses GPU) stays in Python via `audio-separator`.

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

## 6. Migration Phases

| Phase | Component | Est. Files | Priority | Dependencies |
|-------|-----------|------------|----------|--------------|
| 1 | Core Data Types | 6 | CRITICAL | None |
| 2 | Audio Correlation | 1 | CRITICAL | Phase 1 |
| 3 | Drift Detection | 1 | HIGH | Phase 1, 2 |
| 4 | Audio Correction | 3 | HIGH | Phase 1, 2, 3 |
| 5 | Subtitle Core | 4 | MEDIUM | Phase 1 |
| 6 | Frame Utilities | 2 | MEDIUM | Phase 1, 5 |
| 7 | Extraction Layer | 3 | MEDIUM | Phase 1 |
| 8 | Mux Options | 1 | MEDIUM | Phase 1, 7 |
| 9 | Pipeline Orchestration | 8 | LOW | All above |
| 10 | UI Migration | 41 | LAST | All above |

---

## Phase 1: Core Data Types

### Status: [ ] Not Started

### Files to Migrate
```
vsg_core/models/enums.py        →  src/models/enums.rs
vsg_core/models/media.py        →  src/models/media.rs
vsg_core/models/results.py      →  src/models/results.rs
vsg_core/models/jobs.py         →  src/models/jobs.rs
vsg_core/models/settings.py     →  src/models/settings.rs
vsg_core/models/converters.py   →  src/models/converters.rs
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

### Status: [ ] Not Started

### Files to Migrate
```
vsg_core/analysis/audio_corr.py  →  src/analysis/correlation.rs
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

### Status: [ ] Not Started

### Files to Migrate
```
vsg_core/analysis/drift_detection.py  →  src/analysis/drift_detection.rs
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

### Status: [ ] Not Started

### Files to Migrate
```
vsg_core/correction/stepping.py  →  src/correction/stepping.rs
vsg_core/correction/linear.py    →  src/correction/linear.rs
vsg_core/correction/pal.py       →  src/correction/pal.rs
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

### Status: [ ] Not Started

### Files to Migrate
```
vsg_core/subtitles/metadata_preserver.py  →  src/subtitles/metadata.rs
vsg_core/subtitles/style_engine.py        →  src/subtitles/styles.rs
vsg_core/subtitles/timing.py              →  src/subtitles/timing.rs
vsg_core/subtitles/cleanup.py             →  src/subtitles/cleanup.rs
```

### Dependencies
- Phase 1
- Rust crates: `ass_parser` or custom ASS/SSA parser

### Step 5.1: Subtitle Format Support

**CRITICAL PRESERVATION**:
- Supported: `.ass`, `.ssa`, `.srt`, `.vtt`
- Unsupported (skip): PGS, VOB bitmap subtitles

### Step 5.2: ASS Parser

If no suitable Rust crate exists, implement custom parser preserving:
- All style attributes
- Script info section
- Aegisub project garbage (comments)
- Event timing precision (centiseconds)

### Testing Checkpoint 5
- [ ] Parse and re-serialize ASS without data loss
- [ ] Style attributes round-trip correctly
- [ ] Timing precision maintained (centisecond level)

---

## Phase 6: Frame Utilities

### Status: [ ] Not Started

### Files to Migrate
```
vsg_core/subtitles/frame_utils.py  →  src/subtitles/frame_utils.rs
vsg_core/subtitles/frame_sync.py   →  src/subtitles/frame_sync.rs
```

### Dependencies
- Phases 1, 5
- Keep `videotimestamps` in Python (no Rust equivalent)

### Step 6.1: Frame Conversion Methods

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

### Testing Checkpoint 6
- [ ] Frame conversions match Python for all modes
- [ ] Epsilon protection prevents FP drift issues
- [ ] Round-trip frame→time→frame is stable

---

## Phase 7: Extraction Layer

### Status: [ ] Not Started

### Files to Migrate
```
vsg_core/extraction/tracks.py       →  src/extraction/tracks.rs
vsg_core/extraction/attachments.py  →  src/extraction/attachments.rs
vsg_core/chapters/process.py        →  src/chapters/process.rs
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

### Status: [ ] Not Started

### Files to Migrate
```
vsg_core/mux/options_builder.py  →  src/mux/options_builder.rs
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
- [ ] Delay calculation matches Python for all track types
- [ ] Signed delay format correct (+500, -500)
- [ ] JSON output matches Python exactly
- [ ] UTF-8 track names preserved in JSON

---

## Phase 9: Pipeline Orchestration

### Status: [ ] Not Started

### Files to Migrate
```
vsg_core/orchestrator/steps/context.py           →  Keep in Python (thin wrapper)
vsg_core/orchestrator/steps/analysis_step.py     →  Keep in Python (calls Rust)
vsg_core/orchestrator/steps/extract_step.py      →  Keep in Python
vsg_core/orchestrator/steps/audio_correction_step.py  →  Keep in Python
vsg_core/orchestrator/steps/subtitles_step.py    →  Keep in Python
vsg_core/orchestrator/steps/chapters_step.py     →  Keep in Python
vsg_core/orchestrator/steps/mux_step.py          →  Keep in Python
vsg_core/orchestrator/pipeline.py                →  Keep in Python
```

### Migration Strategy
Keep orchestration in Python. Steps call into Rust for heavy computation:

```python
# analysis_step.py (Python)
from vsg_core_rs import analyze_audio_correlation, diagnose_drift

class AnalysisStep:
    def run(self, ctx, runner):
        # Decode audio (Python/FFmpeg)
        ref_pcm = self._decode_audio(...)
        tgt_pcm = self._decode_audio(...)

        # RUST: Heavy correlation
        result = analyze_audio_correlation(
            ref_pcm, tgt_pcm,
            sample_rate=48000,
            method=ctx.config['correlation_method'],
            # ...
        )

        # RUST: Drift detection
        diagnosis = diagnose_drift(result['chunks'])

        # Python: Update context
        ctx.delays = Delays(...)
```

### Testing Checkpoint 9
- [ ] Full pipeline runs with Rust components
- [ ] All step validations pass
- [ ] Output identical to pure-Python version

---

## Phase 10: UI Migration

### Status: [ ] Not Started (LAST)

### Strategy
1. Keep PySide6 UI
2. Use PyO3 FFI to call Rust backend
3. Optionally: Future migration to Tauri/egui

### Files
All 41 modules in `vsg_qt/` - migrate last after all backend is stable.

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

### Phase Status

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| 1 | [ ] | - | - | |
| 2 | [ ] | - | - | |
| 3 | [ ] | - | - | |
| 4 | [ ] | - | - | |
| 5 | [ ] | - | - | |
| 6 | [ ] | - | - | |
| 7 | [ ] | - | - | |
| 8 | [ ] | - | - | |
| 9 | [ ] | - | - | |
| 10 | [ ] | - | - | |

### Checkpoint Log

| Date | Phase | Checkpoint | Result | Notes |
|------|-------|------------|--------|-------|
| | | | | |

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
vsg_core/
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
vsg_qt/
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
