//! Job-related data structures (specs, plans, results).

use std::collections::HashMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use super::enums::JobStatus;
use super::media::Track;

/// Specification for a sync/merge job.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct JobSpec {
    /// Map of source names to file paths (e.g., "Source 1" -> "/path/to/file.mkv").
    pub sources: HashMap<String, PathBuf>,
    /// Optional manual track layout override.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub manual_layout: Option<Vec<HashMap<String, serde_json::Value>>>,
    /// Sources to extract attachments from (e.g., ["Source 1", "Source 2"]).
    /// If empty, defaults to Source 1 only.
    #[serde(default)]
    pub attachment_sources: Vec<String>,
}

impl JobSpec {
    /// Create a new job spec with the given sources.
    pub fn new(sources: HashMap<String, PathBuf>) -> Self {
        Self {
            sources,
            manual_layout: None,
            attachment_sources: Vec::new(),
        }
    }

    /// Create a job spec for two sources (common case).
    pub fn two_sources(source1: PathBuf, source2: PathBuf) -> Self {
        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), source1);
        sources.insert("Source 2".to_string(), source2);
        Self::new(sources)
    }
}

/// Calculated sync delays between sources.
///
/// # Delay Storage
///
/// Delays are stored in two forms:
/// - `raw_source_delays_ms` / `source_delays_ms`: Final delays WITH global_shift applied
/// - `pre_shift_delays_ms`: Original delays WITHOUT global_shift (for debugging/logging)
///
/// The `raw_source_delays_ms` values are what get applied to tracks in mkvmerge.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Delays {
    /// Rounded delays per source in milliseconds (WITH global_shift applied).
    #[serde(default)]
    pub source_delays_ms: HashMap<String, i64>,
    /// Raw (unrounded) delays per source for precision (WITH global_shift applied).
    #[serde(default)]
    pub raw_source_delays_ms: HashMap<String, f64>,
    /// Original delays BEFORE global shift (for logging/debugging).
    #[serde(default)]
    pub pre_shift_delays_ms: HashMap<String, f64>,
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
    pub fn set_delay(&mut self, source: impl Into<String>, raw_ms: f64) {
        let source = source.into();
        // Store in both pre-shift and current (will be shifted later)
        self.pre_shift_delays_ms.insert(source.clone(), raw_ms);
        self.raw_source_delays_ms.insert(source.clone(), raw_ms);
        self.source_delays_ms.insert(source, raw_ms.round() as i64);
    }

    /// Get the final delay for a source (with global shift applied).
    pub fn get_final_delay(&self, source: &str) -> Option<f64> {
        self.raw_source_delays_ms.get(source).copied()
    }

    /// Get the pre-shift delay for a source (without global shift).
    pub fn get_pre_shift_delay(&self, source: &str) -> Option<f64> {
        self.pre_shift_delays_ms.get(source).copied()
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
    pub delays: Option<HashMap<String, i64>>,
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
    pub fn analyzed(name: impl Into<String>, delays: HashMap<String, i64>) -> Self {
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
        assert!(spec.sources.contains_key("Source 1"));
        assert!(spec.sources.contains_key("Source 2"));
    }

    #[test]
    fn delays_set_and_round() {
        let mut delays = Delays::new();
        delays.set_delay("Source 2", -178.555);
        assert_eq!(delays.source_delays_ms.get("Source 2"), Some(&-179));
        assert_eq!(delays.raw_source_delays_ms.get("Source 2"), Some(&-178.555));
    }

    #[test]
    fn job_result_serializes() {
        let result = JobResult::failed("test_job", "Something went wrong");
        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("\"status\":\"Failed\""));
        assert!(json.contains("\"error\":\"Something went wrong\""));
    }
}
