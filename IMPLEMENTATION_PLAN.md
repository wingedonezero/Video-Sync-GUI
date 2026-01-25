# Video-Sync-GUI: Core Pipeline Implementation Plan

## Goals

1. **Data Integrity**: No more mystery data issues - clear ownership, immutable where possible
2. **Clean Architecture**: Each component has a single responsibility
3. **Traceable Data Flow**: Easy to see where delays/context come from and go
4. **Testable**: Each component can be tested in isolation

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Qt UI (C++)                                 │
│  JobQueueDialog → ManualSelectionDialog → "Start Processing" button     │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ bridge_run_job()
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           vsg_bridge (Rust)                              │
│  - Converts C++ types ↔ Rust types                                       │
│  - Creates Context, JobState, Pipeline                                   │
│  - Runs pipeline, reports progress                                       │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           vsg_core Pipeline                              │
│                                                                          │
│  Context (IMMUTABLE during execution)                                    │
│  ├── job_spec: sources, manual_layout                                    │
│  ├── settings: all config                                                │
│  └── paths: work_dir, output_dir                                         │
│                                                                          │
│  JobState (APPEND-ONLY during execution)                                 │
│  ├── analysis: AnalysisOutput     (set by AnalyzeStep)                   │
│  ├── extraction: ExtractOutput    (set by ExtractStep)                   │
│  ├── chapters: ChaptersOutput     (set by ChaptersStep)                  │
│  ├── attachments: AttachmentsOutput (set by AttachmentsStep)             │
│  └── mux: MuxOutput               (set by MuxStep)                       │
│                                                                          │
│  Pipeline executes steps in order:                                       │
│  [Analyze] → [Extract] → [Chapters] → [Attachments] → [Mux]              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Integrity Principles

### 1. Immutable Context
- `Context` is read-only after creation
- Contains: job_spec, settings, paths, logger
- Steps CANNOT modify Context

### 2. Append-Only JobState
- Each step writes to its OWN section (e.g., `state.analysis = Some(...)`)
- Steps CANNOT overwrite another step's output
- All intermediate values are recorded for debugging

### 3. Explicit Data Dependencies
- Each step declares what it reads from JobState
- No hidden state, no global variables
- If a step needs data, it must be in Context or JobState

### 4. Delay Calculation is Centralized
- All delay math happens in ONE place: `DelayCalculator`
- No scattered `+delay` or `-delay` throughout code
- Clear documentation of the delay formula

---

## Directory Structure (Changes in Bold)

```
crates/vsg_core/src/
├── lib.rs
├── config/
│   ├── mod.rs
│   ├── manager.rs
│   └── settings.rs
├── models/
│   ├── mod.rs
│   ├── enums.rs
│   ├── media.rs
│   └── jobs.rs
├── jobs/
│   ├── mod.rs
│   ├── types.rs                    # JobQueueEntry, ManualLayout, etc.
│   ├── discovery.rs                # **REWRITE: Batch folder matching**
│   ├── layout.rs
│   └── queue.rs
├── extraction/                      # **NEW MODULE**
│   ├── mod.rs                      # Public API
│   ├── tracks.rs                   # Track extraction via mkvextract
│   ├── attachments.rs              # Attachment extraction
│   ├── container_info.rs           # Container delay reading
│   └── types.rs                    # ExtractedTrack, ContainerDelays
├── chapters/                        # **NEW MODULE**
│   ├── mod.rs                      # Public API
│   ├── extract.rs                  # Chapter extraction from mkv
│   ├── shift.rs                    # Timestamp shifting
│   ├── normalize.rs                # Dedup, end-time fixing
│   └── types.rs                    # Chapter, ChapterList
├── mux/
│   ├── mod.rs
│   ├── options_builder.rs          # **REWRITE: Use manual_layout**
│   ├── delay_calculator.rs         # **NEW: Centralized delay logic**
│   └── plan_builder.rs             # **NEW: Build MergePlan from layout**
├── orchestrator/
│   ├── mod.rs
│   ├── pipeline.rs
│   ├── step.rs
│   ├── types.rs                    # Context, JobState, outputs
│   ├── errors.rs
│   └── steps/
│       ├── mod.rs
│       ├── analyze.rs              # Existing (working)
│       ├── extract.rs              # **REWRITE: Real extraction**
│       ├── chapters.rs             # **NEW**
│       ├── attachments.rs          # **NEW**
│       └── mux.rs                  # **REWRITE: Use plan_builder**
├── analysis/                       # Existing (working)
│   └── ...
└── logging/                        # Existing (working)
    └── ...

crates/vsg_bridge/src/
└── lib.rs                          # **ADD: bridge_run_job()**

qt_ui/
└── job_queue_dialog/
    └── controller.cpp              # **WIRE: Start Processing button**
```

---

## Phase 1: Core Pipeline (Run a Real Job)

### 1.1 Job Discovery - `jobs/discovery.rs`

**Purpose**: Find and match files from source paths

**Input**:
```rust
pub struct DiscoveryInput {
    /// "Source 1" -> path (file or directory)
    pub sources: HashMap<String, PathBuf>,
}
```

**Output**:
```rust
pub struct DiscoveredJob {
    pub id: String,
    pub name: String,
    pub sources: HashMap<String, PathBuf>,  // Resolved file paths
}
```

**Logic**:
```
If Source 1 is a FILE:
  → Single job mode
  → Match files in Source 2/3 directories by filename

If Source 1 is a DIRECTORY:
  → Batch mode
  → Scan for video files (.mkv, .mp4, .m4v)
  → For each file in Source 1, find matches in Source 2/3 dirs
  → Create one job per matched set

Remux-only mode:
  → Source 1 only, no Source 2 required
  → Creates single job for remuxing without sync
```

**Validation**:
- Source 1 must exist
- All resolved paths must exist
- Warn if Source 2/3 files not found (but allow remux-only)

---

### 1.2 Extraction Module - `extraction/`

**Purpose**: Extract tracks from MKV files and read container info

#### 1.2.1 Container Info - `extraction/container_info.rs`

**Purpose**: Read container delays (minimum_timestamp) from tracks

```rust
/// Container timing information for a source file
pub struct ContainerInfo {
    /// Source key ("Source 1", "Source 2", etc.)
    pub source_key: String,
    /// Path to the source file
    pub source_path: PathBuf,
    /// Track ID -> container delay in milliseconds
    pub track_delays_ms: HashMap<usize, i64>,
    /// Video track's container delay (used as reference)
    pub video_delay_ms: i64,
}

impl ContainerInfo {
    /// Read container info from a file using mkvmerge -J
    pub fn from_file(source_key: &str, path: &Path) -> Result<Self, ExtractionError>;

    /// Get the relative delay for an audio track (audio_delay - video_delay)
    /// This preserves the internal sync of Source 1
    pub fn relative_audio_delay(&self, track_id: usize) -> i64;
}
```

**How container delays work**:
```
Container delay = minimum_timestamp / 1,000,000 (ns to ms)

For Source 1:
  - Video delay is the REFERENCE (timeline starts here)
  - Audio relative delay = audio_delay - video_delay
  - This PRESERVES the original Source 1 internal sync

For Source 2/3:
  - Container delays are NOT used (correlation already accounts for them)
  - Only correlation delay + global shift applied
```

#### 1.2.2 Track Extraction - `extraction/tracks.rs`

**Purpose**: Extract specific tracks from MKV files

```rust
pub struct ExtractRequest {
    pub source_path: PathBuf,
    pub track_id: usize,
    pub output_dir: PathBuf,
}

pub struct ExtractedTrack {
    pub source_key: String,
    pub track_id: usize,
    pub extracted_path: PathBuf,
    pub codec_id: String,
}

/// Extract tracks using mkvextract
pub fn extract_tracks(
    requests: &[ExtractRequest],
    logger: &JobLogger,
) -> Result<Vec<ExtractedTrack>, ExtractionError>;
```

**Implementation**:
- Use `mkvextract tracks <file> <id>:<output>`
- Handle special codecs (A_MS/ACM needs ffmpeg conversion)
- Verify output files exist and aren't empty
- Return detailed errors if extraction fails

#### 1.2.3 Attachment Extraction - `extraction/attachments.rs`

```rust
pub struct ExtractedAttachment {
    pub source_key: String,
    pub attachment_id: usize,
    pub extracted_path: PathBuf,
    pub mime_type: String,
}

/// Extract attachments (fonts) from MKV file
pub fn extract_attachments(
    source_path: &Path,
    output_dir: &Path,
    logger: &JobLogger,
) -> Result<Vec<ExtractedAttachment>, ExtractionError>;
```

---

### 1.3 Extract Step - `orchestrator/steps/extract.rs`

**Purpose**: Orchestrate extraction of all tracks needed for the job

**Reads from Context**:
- `ctx.job_spec.sources` - source file paths
- `ctx.job_spec.manual_layout` - which tracks to extract
- `ctx.work_dir` - where to extract to

**Writes to JobState**:
```rust
pub struct ExtractOutput {
    /// Source key -> ContainerInfo
    pub container_info: HashMap<String, ContainerInfo>,
    /// Track key ("Source 1:0", "Source 2:1") -> extracted path
    pub extracted_tracks: HashMap<String, PathBuf>,
    /// List of extracted attachment paths
    pub attachments: Vec<PathBuf>,
}
```

**Logic**:
```
1. Read container info from ALL sources (need for delay calculation)
2. Determine which tracks need extraction:
   - Audio tracks that need correction → extract
   - Subtitles that need processing → extract
   - Video → use source directly (no extraction needed)
   - Audio without correction → use source directly
3. Extract required tracks to work_dir
4. Extract attachments from selected sources
5. Record all paths in ExtractOutput
```

**Note**: For MVP, we can use source files directly (no extraction) and only read container info. Track extraction is only needed for audio correction, which we're stubbing.

---

### 1.4 Chapters Module - `chapters/`

**Purpose**: Extract, shift, and normalize chapters

#### 1.4.1 Types - `chapters/types.rs`

```rust
/// A single chapter entry
#[derive(Debug, Clone)]
pub struct Chapter {
    pub uid: Option<u64>,
    pub start_ns: i64,      // Nanoseconds
    pub end_ns: Option<i64>,
    pub names: Vec<(String, String)>,  // (language, name)
}

/// A list of chapters
#[derive(Debug, Clone)]
pub struct ChapterList {
    pub chapters: Vec<Chapter>,
}

impl ChapterList {
    /// Parse from Matroska XML format
    pub fn from_xml(xml: &str) -> Result<Self, ChapterError>;

    /// Serialize to Matroska XML format
    pub fn to_xml(&self) -> String;

    /// Apply a time shift to all chapters
    pub fn shift(&mut self, shift_ms: i64);

    /// Normalize: fix end times, deduplicate
    pub fn normalize(&mut self);

    /// Rename chapters to "Chapter 01", "Chapter 02", etc.
    pub fn rename_sequential(&mut self);
}
```

#### 1.4.2 Extract - `chapters/extract.rs`

```rust
/// Extract chapters from MKV file
pub fn extract_chapters(
    source_path: &Path,
    logger: &JobLogger,
) -> Result<Option<ChapterList>, ChapterError>;
```

**Implementation**:
- Run `mkvextract chapters <file>` (outputs to stdout)
- Parse XML into ChapterList
- Return None if no chapters

#### 1.4.3 Shift - `chapters/shift.rs`

```rust
impl ChapterList {
    /// Shift all chapter timestamps by given milliseconds
    pub fn shift(&mut self, shift_ms: i64) {
        let shift_ns = shift_ms * 1_000_000;
        for chapter in &mut self.chapters {
            chapter.start_ns = (chapter.start_ns + shift_ns).max(0);
            if let Some(ref mut end) = chapter.end_ns {
                *end = (*end + shift_ns).max(0);
            }
        }
    }
}
```

#### 1.4.4 Normalize - `chapters/normalize.rs`

```rust
impl ChapterList {
    /// Normalize chapters: fix end times, remove duplicates
    pub fn normalize(&mut self) {
        // 1. Sort by start time
        self.chapters.sort_by_key(|c| c.start_ns);

        // 2. Remove duplicates (same start time within 100ms)
        self.chapters.dedup_by(|a, b| {
            (a.start_ns - b.start_ns).abs() < 100_000_000 // 100ms
        });

        // 3. Fix end times (set to next chapter's start, or +1s for last)
        for i in 0..self.chapters.len() {
            let next_start = if i + 1 < self.chapters.len() {
                self.chapters[i + 1].start_ns
            } else {
                self.chapters[i].start_ns + 1_000_000_000 // +1 second
            };
            self.chapters[i].end_ns = Some(next_start);
        }
    }
}
```

---

### 1.5 Chapters Step - `orchestrator/steps/chapters.rs`

**Purpose**: Extract and process chapters from Source 1

**Reads from Context**:
- `ctx.primary_source()` - Source 1 path
- `ctx.settings.chapters` - rename, snap settings

**Reads from JobState**:
- `state.analysis.delays.global_shift_ms` - shift to apply

**Writes to JobState**:
```rust
pub struct ChaptersOutput {
    pub chapters_xml: Option<PathBuf>,
    pub chapter_count: usize,
    pub shifted: bool,
    pub snapped: bool,
}
```

**Logic**:
```
1. Extract chapters from Source 1
2. If no chapters → return early (non-fatal)
3. Apply global_shift_ms to all timestamps
4. Normalize (dedup, fix end times)
5. Optional: rename to sequential
6. Optional: snap to keyframes (future)
7. Write XML to work_dir/chapters.xml
8. Record in ChaptersOutput
```

---

### 1.6 Attachments Step - `orchestrator/steps/attachments.rs`

**Purpose**: Extract fonts from selected sources

**Reads from Context**:
- `ctx.job_spec.manual_layout.attachment_sources` - which sources to extract from
- `ctx.job_spec.sources` - source paths

**Writes to JobState**:
```rust
pub struct AttachmentsOutput {
    pub attachments: Vec<PathBuf>,
    pub source_counts: HashMap<String, usize>,  // How many from each source
}
```

**Logic**:
```
1. For each source in attachment_sources:
   a. Extract attachments to work_dir/attachments/
   b. Track which source each came from
2. Collect all attachment paths
3. Record in AttachmentsOutput
```

---

### 1.7 Delay Calculator - `mux/delay_calculator.rs`

**Purpose**: SINGLE SOURCE OF TRUTH for delay calculations

```rust
/// Inputs needed for delay calculation
pub struct DelayInputs<'a> {
    pub track: &'a FinalTrackEntry,
    pub delays: &'a Delays,
    pub container_info: &'a HashMap<String, ContainerInfo>,
}

/// Calculate the effective delay for a track in the merge
pub fn calculate_effective_delay(inputs: &DelayInputs) -> i64 {
    let track = inputs.track;
    let delays = inputs.delays;
    let source_key = &track.source_key;

    match (&track.track_type, source_key.as_str()) {
        // Source 1 VIDEO: global shift only (video defines timeline)
        (TrackType::Video, "Source 1") => {
            delays.global_shift_ms
        }

        // Source 1 AUDIO: container delay + global shift
        // This preserves Source 1's internal A/V sync
        (TrackType::Audio, "Source 1") => {
            let container = inputs.container_info.get("Source 1");
            let relative_delay = container
                .map(|c| c.relative_audio_delay(track.track_id))
                .unwrap_or(0);
            relative_delay + delays.global_shift_ms
        }

        // Source 1 SUBTITLES: just global shift (no container delay)
        (TrackType::Subtitles, "Source 1") => {
            delays.global_shift_ms
        }

        // Other sources AUDIO/VIDEO: correlation delay (already includes global shift)
        (TrackType::Audio | TrackType::Video, _) => {
            delays.source_delays_ms.get(source_key).copied().unwrap_or(0)
        }

        // Other sources SUBTITLES: same as audio
        (TrackType::Subtitles, _) => {
            // Check if stepping-adjusted (delay embedded in file)
            // For now, just use source delay
            delays.source_delays_ms.get(source_key).copied().unwrap_or(0)
        }
    }
}
```

**Documentation in code**:
```rust
/// # Delay Calculation Rules
///
/// ## Source 1 (Reference)
/// - Video: global_shift only (defines the timeline)
/// - Audio: relative_container_delay + global_shift
///   - relative = audio_container_delay - video_container_delay
///   - This preserves Source 1's original internal sync
/// - Subtitles: global_shift only
///
/// ## Source 2/3 (Synced sources)
/// - All tracks: source_delays_ms[source_key]
///   - Already includes: correlation_delay + global_shift
///   - Container delays from Source 2/3 are NOT used
///     (correlation already accounts for them)
///
/// ## Global Shift
/// - Calculated during analysis
/// - Makes all delays non-negative
/// - Applied to ALL tracks to maintain relative sync
```

---

### 1.8 Plan Builder - `mux/plan_builder.rs`

**Purpose**: Build MergePlan from ManualLayout + JobState

```rust
pub struct PlanBuilder<'a> {
    ctx: &'a Context,
    state: &'a JobState,
}

impl<'a> PlanBuilder<'a> {
    pub fn new(ctx: &'a Context, state: &'a JobState) -> Self {
        Self { ctx, state }
    }

    /// Build the complete merge plan
    pub fn build(&self) -> Result<MergePlan, PlanError> {
        let layout = self.ctx.job_spec.manual_layout.as_ref()
            .ok_or(PlanError::NoLayout)?;

        let delays = self.state.delays()
            .ok_or(PlanError::NoAnalysis)?;

        let container_info = self.state.extract.as_ref()
            .map(|e| &e.container_info)
            .unwrap_or(&HashMap::new());

        let mut items = Vec::new();

        for entry in &layout.final_tracks {
            let plan_item = self.build_plan_item(entry, delays, container_info)?;
            items.push(plan_item);
        }

        let mut plan = MergePlan::new(items, delays.clone());

        // Add chapters
        if let Some(ref chapters) = self.state.chapters {
            plan.chapters_xml = chapters.chapters_xml.clone();
        }

        // Add attachments
        if let Some(ref attachments) = self.state.attachments {
            plan.attachments = attachments.attachments.clone();
        }

        Ok(plan)
    }

    fn build_plan_item(
        &self,
        entry: &FinalTrackEntry,
        delays: &Delays,
        container_info: &HashMap<String, ContainerInfo>,
    ) -> Result<PlanItem, PlanError> {
        // Get source path
        let source_path = self.ctx.job_spec.sources.get(&entry.source_key)
            .ok_or_else(|| PlanError::MissingSource(entry.source_key.clone()))?;

        // Create track
        let track = Track::new(
            &entry.source_key,
            entry.track_id,
            entry.track_type,
            StreamProps::default(), // Will be filled from scan
        );

        // Calculate delay
        let delay_inputs = DelayInputs {
            track: entry,
            delays,
            container_info,
        };
        let delay_ms = calculate_effective_delay(&delay_inputs);

        // Build plan item
        let mut item = PlanItem::new(track, source_path.clone())
            .with_delay(delay_ms)
            .with_default(entry.config.is_default);

        item.is_forced_display = entry.config.is_forced;

        if let Some(ref name) = entry.config.custom_name {
            item.custom_name = name.clone();
        }
        if let Some(ref lang) = entry.config.custom_lang {
            item.custom_lang = lang.clone();
        }

        Ok(item)
    }
}
```

---

### 1.9 Mux Step Rewrite - `orchestrator/steps/mux.rs`

**Changes**:
- Use `PlanBuilder` instead of stub
- Remove hardcoded track creation
- Log delay calculations for debugging

```rust
impl PipelineStep for MuxStep {
    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.section("Building Merge Plan");

        // Build plan from layout
        let builder = PlanBuilder::new(ctx, state);
        let plan = builder.build()
            .map_err(|e| StepError::invalid_input(format!("Failed to build plan: {}", e)))?;

        // Log plan details
        ctx.logger.info(&format!("Tracks: {}", plan.items.len()));
        for (i, item) in plan.items.iter().enumerate() {
            ctx.logger.debug(&format!(
                "  [{}] {} {} from {} (delay: {}ms)",
                i,
                item.track.track_type,
                item.track.id,
                item.track.source,
                item.container_delay_ms
            ));
        }

        if let Some(ref chapters) = plan.chapters_xml {
            ctx.logger.info(&format!("Chapters: {}", chapters.display()));
        }
        ctx.logger.info(&format!("Attachments: {}", plan.attachments.len()));

        // Build output path and mkvmerge command
        let output_path = self.output_path(ctx);
        let builder = MkvmergeOptionsBuilder::new(&plan, &ctx.settings, &output_path);
        let tokens = builder.build();

        // Execute
        ctx.logger.section("Executing mkvmerge");
        let exit_code = self.run_mkvmerge(ctx, &tokens, &output_path)?;

        // Record results
        state.mux = Some(MuxOutput {
            output_path: output_path.clone(),
            exit_code,
            command: format!("{} {}", self.mkvmerge_cmd(), tokens.join(" ")),
        });
        state.merge_plan = Some(plan);

        ctx.logger.success(&format!("Output: {}", output_path.display()));
        Ok(StepOutcome::Success)
    }
}
```

---

### 1.10 Bridge: Run Job - `vsg_bridge/src/lib.rs`

**Add new function**:

```rust
/// Job specification for bridge
#[derive(Debug, Clone)]
struct BridgeJobSpec {
    id: String,
    name: String,
    sources: Vec<BridgeSource>,  // [("Source 1", "/path"), ...]
    layout: BridgeLayout,
}

#[derive(Debug, Clone)]
struct BridgeSource {
    key: String,
    path: String,
}

#[derive(Debug, Clone)]
struct BridgeLayout {
    final_tracks: Vec<BridgeTrackEntry>,
    attachment_sources: Vec<String>,
}

#[derive(Debug, Clone)]
struct BridgeTrackEntry {
    track_id: i32,
    source_key: String,
    track_type: String,
    is_default: bool,
    is_forced: bool,
    custom_name: String,
    custom_lang: String,
}

/// Result of running a job
#[derive(Debug, Clone)]
struct JobRunResult {
    success: bool,
    output_path: String,
    error_message: String,
}

extern "Rust" {
    // ... existing functions ...

    /// Run a configured job through the pipeline
    fn bridge_run_job(job: &BridgeJobSpec) -> JobRunResult;
}

fn bridge_run_job(job: &BridgeJobSpec) -> ffi::JobRunResult {
    // 1. Convert BridgeJobSpec → JobSpec
    // 2. Load settings
    // 3. Create Context with work_dir, output_dir
    // 4. Create JobState
    // 5. Create Pipeline with steps: [Analyze, Extract, Chapters, Attachments, Mux]
    // 6. Run pipeline with progress callbacks
    // 7. Return result
}
```

---

### 1.11 Qt: Wire Button - `qt_ui/job_queue_dialog/controller.cpp`

**Change**:
```cpp
void JobQueueController::startProcessing() {
    auto jobs = getConfiguredJobs();
    if (jobs.empty()) {
        showWarning("No configured jobs to process");
        return;
    }

    // Disable UI during processing
    setProcessingState(true);

    for (const auto& job : jobs) {
        updateStatus(job.id, "Processing");

        // Convert to bridge format
        vsg::BridgeJobSpec spec = convertToSpec(job);

        // Run job
        auto result = vsg::bridge_run_job(spec);

        if (result.success) {
            updateStatus(job.id, "Complete");
            log(QString("✓ %1 → %2").arg(job.name).arg(result.output_path));
        } else {
            updateStatus(job.id, "Error");
            log(QString("✗ %1: %2").arg(job.name).arg(result.error_message));
        }
    }

    setProcessingState(false);
}
```

---

## Phase 2: Chapters & Attachments

Already covered in Phase 1 design. Implementation order:
1. `chapters/` module with types, extract, shift, normalize
2. `ChaptersStep` in orchestrator
3. `extraction/attachments.rs`
4. `AttachmentsStep` in orchestrator

---

## Implementation Checklist

### Phase 1: Core Pipeline

| Task | File(s) | Status |
|------|---------|--------|
| Job Discovery rewrite | `jobs/discovery.rs` | [ ] |
| Container info reading | `extraction/container_info.rs` | [ ] |
| Extraction types | `extraction/types.rs` | [ ] |
| Track extraction | `extraction/tracks.rs` | [ ] |
| Extract step rewrite | `orchestrator/steps/extract.rs` | [ ] |
| Delay calculator | `mux/delay_calculator.rs` | [ ] |
| Plan builder | `mux/plan_builder.rs` | [ ] |
| Mux step rewrite | `orchestrator/steps/mux.rs` | [ ] |
| Bridge run_job | `vsg_bridge/src/lib.rs` | [ ] |
| Qt wire button | `qt_ui/job_queue_dialog/controller.cpp` | [ ] |

### Phase 2: Chapters & Attachments

| Task | File(s) | Status |
|------|---------|--------|
| Chapter types | `chapters/types.rs` | [ ] |
| Chapter extraction | `chapters/extract.rs` | [ ] |
| Chapter shift | `chapters/shift.rs` | [ ] |
| Chapter normalize | `chapters/normalize.rs` | [ ] |
| Chapters step | `orchestrator/steps/chapters.rs` | [ ] |
| Attachment extraction | `extraction/attachments.rs` | [ ] |
| Attachments step | `orchestrator/steps/attachments.rs` | [ ] |

---

## Testing Strategy

### Unit Tests
- `delay_calculator`: Test all delay scenarios
- `ChapterList`: Parse, shift, normalize, serialize
- `ContainerInfo`: Parse mkvmerge JSON
- `PlanBuilder`: Build plans from various layouts

### Integration Tests
- Create test MKV files with known delays
- Run full pipeline
- Verify output has correct sync

### Manual Testing
- Run with real files
- Check mkvmerge command output
- Verify output file plays correctly

---

## Data Flow Diagram

```
User selects files
        │
        ▼
┌─────────────────┐
│  Job Discovery  │ → Creates JobQueueEntry with sources
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Manual Selection│ → User configures ManualLayout
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Start Process  │ → Creates JobSpec from entry + layout
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                        PIPELINE                              │
│                                                              │
│  ┌──────────┐   Delays    ┌──────────┐  ContainerInfo       │
│  │ Analyze  │────────────▶│ Extract  │──────────────┐       │
│  └──────────┘              └──────────┘              │       │
│       │                         │                    │       │
│       │ global_shift_ms         │ container_info     │       │
│       ▼                         ▼                    ▼       │
│  ┌──────────┐              ┌────────────┐    ┌────────────┐  │
│  │ Chapters │              │Attachments │    │    Mux     │  │
│  │ (shift)  │              │ (extract)  │    │  (merge)   │  │
│  └────┬─────┘              └─────┬──────┘    └────────────┘  │
│       │                          │                  ▲        │
│       │ chapters_xml             │ attachments      │        │
│       └──────────────────────────┴──────────────────┘        │
│                                                              │
│                     PlanBuilder                              │
│                         │                                    │
│                         ▼                                    │
│                   DelayCalculator                            │
│                         │                                    │
│                         ▼                                    │
│                    MergePlan                                 │
│                         │                                    │
│                         ▼                                    │
│                MkvmergeOptionsBuilder                        │
│                         │                                    │
│                         ▼                                    │
│                     mkvmerge                                 │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
                    Output .mkv file
```

---

## Notes

1. **MVP Simplification**: For initial implementation, we can skip actual track extraction and use source files directly. Only container info reading is essential.

2. **Error Handling**: Each step should provide detailed errors that help debugging. Include file paths, track IDs, and what operation failed.

3. **Logging**: Log all delay calculations with the formula used. This makes debugging sync issues easy.

4. **Future**: Audio correction, subtitle processing, and OCR can be added as additional steps without changing the core architecture.
