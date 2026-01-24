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
}

impl JobSpec {
    /// Create a new job spec with the given sources.
    pub fn new(sources: HashMap<String, PathBuf>) -> Self {
        Self {
            sources,
            manual_layout: None,
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
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Delays {
    /// Rounded delays per source in milliseconds.
    #[serde(default)]
    pub source_delays_ms: HashMap<String, i64>,
    /// Raw (unrounded) delays per source for precision.
    #[serde(default)]
    pub raw_source_delays_ms: HashMap<String, f64>,
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

    /// Set delay for a source.
    pub fn set_delay(&mut self, source: impl Into<String>, raw_ms: f64) {
        let source = source.into();
        self.raw_source_delays_ms.insert(source.clone(), raw_ms);
        self.source_delays_ms.insert(source, raw_ms.round() as i64);
    }
}

/// A single item in the merge plan (one track with its processing options).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanItem {
    /// The track to process.
    pub track: Track,
    /// Path to extracted file (if extracted).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub extracted_path: Option<PathBuf>,
    /// Whether this is the default track of its type.
    #[serde(default)]
    pub is_default: bool,
    /// Whether this track has forced display flag.
    #[serde(default)]
    pub is_forced_display: bool,
    /// Container delay to apply in milliseconds.
    #[serde(default)]
    pub container_delay_ms: i64,
    /// Custom language override.
    #[serde(default)]
    pub custom_lang: String,
    /// Custom track name override.
    #[serde(default)]
    pub custom_name: String,
}

impl PlanItem {
    /// Create a new plan item for a track.
    pub fn new(track: Track) -> Self {
        Self {
            track,
            extracted_path: None,
            is_default: false,
            is_forced_display: false,
            container_delay_ms: 0,
            custom_lang: String::new(),
            custom_name: String::new(),
        }
    }

    /// Set as default track.
    pub fn with_default(mut self, is_default: bool) -> Self {
        self.is_default = is_default;
        self
    }

    /// Set container delay.
    pub fn with_delay(mut self, delay_ms: i64) -> Self {
        self.container_delay_ms = delay_ms;
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
