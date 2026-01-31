//! Job-related data structures (specs, plans, results).

use std::collections::HashMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use super::enums::JobStatus;
use super::media::Track;
use super::source_index::SourceIndex;

/// Specification for a sync/merge job.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct JobSpec {
    /// Map of source indices to file paths.
    pub sources: HashMap<SourceIndex, PathBuf>,
    /// Optional manual track layout override (legacy format, will be migrated).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub manual_layout: Option<Vec<HashMap<String, serde_json::Value>>>,
    /// Sources to extract attachments from.
    /// If empty, defaults to Source 1 only.
    #[serde(default)]
    pub attachment_sources: Vec<SourceIndex>,
}

impl JobSpec {
    /// Create a new job spec with the given sources.
    pub fn new(sources: HashMap<SourceIndex, PathBuf>) -> Self {
        Self {
            sources,
            manual_layout: None,
            attachment_sources: Vec::new(),
        }
    }

    /// Create a job spec for two sources (common case).
    pub fn two_sources(source1: PathBuf, source2: PathBuf) -> Self {
        let mut sources = HashMap::new();
        sources.insert(SourceIndex::source1(), source1);
        sources.insert(SourceIndex::source2(), source2);
        Self::new(sources)
    }

    /// Get the source path for a given index.
    pub fn source_path(&self, index: SourceIndex) -> Option<&PathBuf> {
        self.sources.get(&index)
    }

    /// Get Source 1 path (primary source).
    pub fn source1_path(&self) -> Option<&PathBuf> {
        self.source_path(SourceIndex::source1())
    }

    /// Get Source 2 path (secondary source).
    pub fn source2_path(&self) -> Option<&PathBuf> {
        self.source_path(SourceIndex::source2())
    }
}

/// Delay values for a single source.
///
/// Stores multiple representations of the same delay for different purposes:
/// - `delay_ms`: Rounded integer for mkvmerge (final output)
/// - `raw_delay_ms`: Full precision for calculations (WITH global shift)
/// - `pre_shift_delay_ms`: Original value before global shift (for logging)
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct SourceDelay {
    /// Rounded delay in milliseconds (WITH global_shift applied).
    /// This is the value passed to mkvmerge.
    #[serde(default)]
    pub delay_ms: i64,
    /// Raw (unrounded) delay for precision (WITH global_shift applied).
    #[serde(default)]
    pub raw_delay_ms: f64,
    /// Original delay BEFORE global shift (for logging/debugging).
    #[serde(default)]
    pub pre_shift_delay_ms: f64,
}

impl SourceDelay {
    /// Create a new source delay with all values set to the same raw value.
    pub fn new(raw_ms: f64) -> Self {
        Self {
            delay_ms: raw_ms.round() as i64,
            raw_delay_ms: raw_ms,
            pre_shift_delay_ms: raw_ms,
        }
    }

    /// Create a source delay with pre-shift and post-shift values.
    pub fn with_shift(pre_shift_ms: f64, post_shift_ms: f64) -> Self {
        Self {
            delay_ms: post_shift_ms.round() as i64,
            raw_delay_ms: post_shift_ms,
            pre_shift_delay_ms: pre_shift_ms,
        }
    }
}

/// Calculated sync delays between sources.
///
/// # Delay Storage
///
/// Each source has a [`SourceDelay`] containing:
/// - `delay_ms` / `raw_delay_ms`: Final delays WITH global_shift applied
/// - `pre_shift_delay_ms`: Original delays WITHOUT global_shift (for debugging)
///
/// The `raw_delay_ms` values are what get applied to tracks in mkvmerge.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Delays {
    /// Per-source delays indexed by SourceIndex.
    #[serde(default)]
    pub sources: HashMap<SourceIndex, SourceDelay>,
    /// Global shift applied to all tracks (rounded).
    #[serde(default)]
    pub global_shift_ms: i64,
    /// Raw global shift for precision.
    #[serde(default)]
    pub raw_global_shift_ms: f64,
}

impl Delays {
    /// Create empty delays.
    pub fn new() -> Self {
        Self::default()
    }

    /// Set delay for a source (stores the raw delay BEFORE any global shift).
    pub fn set_delay(&mut self, source: SourceIndex, raw_ms: f64) {
        self.sources.insert(source, SourceDelay::new(raw_ms));
    }

    /// Set delay for a source with both pre-shift and post-shift values.
    pub fn set_delay_with_shift(&mut self, source: SourceIndex, pre_shift_ms: f64, post_shift_ms: f64) {
        self.sources.insert(source, SourceDelay::with_shift(pre_shift_ms, post_shift_ms));
    }

    /// Get the source delay entry.
    pub fn get(&self, source: SourceIndex) -> Option<&SourceDelay> {
        self.sources.get(&source)
    }

    /// Get the final delay for a source (with global shift applied).
    pub fn get_final_delay(&self, source: SourceIndex) -> Option<f64> {
        self.sources.get(&source).map(|d| d.raw_delay_ms)
    }

    /// Get the rounded delay for a source (for mkvmerge).
    pub fn get_delay_ms(&self, source: SourceIndex) -> Option<i64> {
        self.sources.get(&source).map(|d| d.delay_ms)
    }

    /// Get the pre-shift delay for a source (without global shift).
    pub fn get_pre_shift_delay(&self, source: SourceIndex) -> Option<f64> {
        self.sources.get(&source).map(|d| d.pre_shift_delay_ms)
    }

    /// Iterate over all source delays.
    pub fn iter(&self) -> impl Iterator<Item = (&SourceIndex, &SourceDelay)> {
        self.sources.iter()
    }

    /// Get the number of sources with delays.
    pub fn len(&self) -> usize {
        self.sources.len()
    }

    /// Check if there are no delays.
    pub fn is_empty(&self) -> bool {
        self.sources.is_empty()
    }
}

/// A single item in the merge plan (one track with its processing options).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanItem {
    /// The track to process.
    pub track: Track,
    /// Path to the source file containing this track.
    pub source_path: PathBuf,
    /// Path to extracted file (if extracted).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub extracted_path: Option<PathBuf>,
    /// Whether this is the default track of its type.
    #[serde(default)]
    pub is_default: bool,
    /// Whether this track has forced display flag.
    #[serde(default)]
    pub is_forced_display: bool,
    /// Container delay to apply in milliseconds (raw f64 for precision).
    /// Only rounded to integer at the final mkvmerge command step.
    #[serde(default)]
    pub container_delay_ms_raw: f64,
    /// Custom language override.
    #[serde(default)]
    pub custom_lang: String,
    /// Custom track name override.
    #[serde(default)]
    pub custom_name: String,

    // === Processing flags ===
    /// Track has been adjusted by stepping correction.
    #[serde(default)]
    pub stepping_adjusted: bool,
    /// Track has been adjusted by frame-level sync.
    #[serde(default)]
    pub frame_adjusted: bool,

    // === Preservation/correction flags ===
    /// Track was preserved from a previous run (not re-processed).
    #[serde(default)]
    pub is_preserved: bool,
    /// Track was corrected from another source.
    #[serde(default)]
    pub is_corrected: bool,
    /// Source used for correction (if is_corrected is true).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub correction_source: Option<String>,

    // === Video-specific options ===
    /// Original aspect ratio to preserve (e.g., "16:9", "109:60").
    #[serde(skip_serializing_if = "Option::is_none")]
    pub aspect_ratio: Option<String>,

    // === User modifications ===
    /// Path to user-modified file (replaces extracted_path when set).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub user_modified_path: Option<PathBuf>,
}

impl PlanItem {
    /// Create a new plan item for a track.
    pub fn new(track: Track, source_path: impl Into<PathBuf>) -> Self {
        Self {
            track,
            source_path: source_path.into(),
            extracted_path: None,
            is_default: false,
            is_forced_display: false,
            container_delay_ms_raw: 0.0,
            custom_lang: String::new(),
            custom_name: String::new(),
            stepping_adjusted: false,
            frame_adjusted: false,
            is_preserved: false,
            is_corrected: false,
            correction_source: None,
            aspect_ratio: None,
            user_modified_path: None,
        }
    }

    /// Set as default track.
    pub fn with_default(mut self, is_default: bool) -> Self {
        self.is_default = is_default;
        self
    }

    /// Set container delay.
    pub fn with_delay(mut self, delay_ms_raw: f64) -> Self {
        self.container_delay_ms_raw = delay_ms_raw;
        self
    }
}

/// Complete plan for merging tracks into output file.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MergePlan {
    /// Tracks to include in merge.
    pub items: Vec<PlanItem>,
    /// Calculated sync delays.
    pub delays: Delays,
    /// Path to chapters XML file (if any).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chapters_xml: Option<PathBuf>,
    /// Paths to attachment files to include.
    #[serde(default)]
    pub attachments: Vec<PathBuf>,
}

impl MergePlan {
    /// Create a new merge plan.
    pub fn new(items: Vec<PlanItem>, delays: Delays) -> Self {
        Self {
            items,
            delays,
            chapters_xml: None,
            attachments: Vec::new(),
        }
    }
}

/// Result of a completed job.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobResult {
    /// Final status.
    pub status: JobStatus,
    /// Job name/identifier.
    pub name: String,
    /// Path to output file (if merged).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output: Option<PathBuf>,
    /// Calculated delays (if analyzed).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub delays: Option<Delays>,
    /// Error message (if failed).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl JobResult {
    /// Create a successful merge result.
    pub fn merged(name: impl Into<String>, output: PathBuf) -> Self {
        Self {
            status: JobStatus::Merged,
            name: name.into(),
            output: Some(output),
            delays: None,
            error: None,
        }
    }

    /// Create an analysis-only result.
    pub fn analyzed(name: impl Into<String>, delays: Delays) -> Self {
        Self {
            status: JobStatus::Analyzed,
            name: name.into(),
            output: None,
            delays: Some(delays),
            error: None,
        }
    }

    /// Create a failed result.
    pub fn failed(name: impl Into<String>, error: impl Into<String>) -> Self {
        Self {
            status: JobStatus::Failed,
            name: name.into(),
            output: None,
            delays: None,
            error: Some(error.into()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn job_spec_two_sources() {
        let spec = JobSpec::two_sources("/path/a.mkv".into(), "/path/b.mkv".into());
        assert_eq!(spec.sources.len(), 2);
        assert!(spec.sources.contains_key(&SourceIndex::source1()));
        assert!(spec.sources.contains_key(&SourceIndex::source2()));
        assert_eq!(spec.source1_path(), Some(&PathBuf::from("/path/a.mkv")));
        assert_eq!(spec.source2_path(), Some(&PathBuf::from("/path/b.mkv")));
    }

    #[test]
    fn delays_set_and_round() {
        let mut delays = Delays::new();
        delays.set_delay(SourceIndex::source2(), -178.555);

        let delay = delays.get(SourceIndex::source2()).unwrap();
        assert_eq!(delay.delay_ms, -179);
        assert_eq!(delay.raw_delay_ms, -178.555);
        assert_eq!(delay.pre_shift_delay_ms, -178.555);
    }

    #[test]
    fn delays_with_shift() {
        let mut delays = Delays::new();
        delays.set_delay_with_shift(SourceIndex::source1(), 100.0, 50.0);

        let delay = delays.get(SourceIndex::source1()).unwrap();
        assert_eq!(delay.delay_ms, 50);
        assert_eq!(delay.raw_delay_ms, 50.0);
        assert_eq!(delay.pre_shift_delay_ms, 100.0);
    }

    #[test]
    fn delays_serialization() {
        let mut delays = Delays::new();
        delays.set_delay(SourceIndex::source1(), 0.0);
        delays.set_delay(SourceIndex::source2(), -178.5);

        let json = serde_json::to_string(&delays).unwrap();
        // SourceIndex serializes as "Source 1", "Source 2"
        assert!(json.contains("Source 1"));
        assert!(json.contains("Source 2"));

        // Round-trip
        let parsed: Delays = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.get_delay_ms(SourceIndex::source2()), Some(-179));
    }

    #[test]
    fn job_result_serializes() {
        let result = JobResult::failed("test_job", "Something went wrong");
        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("\"status\":\"Failed\""));
        assert!(json.contains("\"error\":\"Something went wrong\""));
    }

    #[test]
    fn job_result_analyzed() {
        let mut delays = Delays::new();
        delays.set_delay(SourceIndex::source2(), -100.0);

        let result = JobResult::analyzed("test_job", delays);
        assert_eq!(result.status, JobStatus::Analyzed);
        assert!(result.delays.is_some());

        let d = result.delays.unwrap();
        assert_eq!(d.get_delay_ms(SourceIndex::source2()), Some(-100));
    }
}
