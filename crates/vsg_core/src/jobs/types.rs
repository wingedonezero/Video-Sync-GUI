//! Job queue types and data structures.

use std::collections::HashMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::models::TrackType;

/// Status of a job in the queue.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum JobQueueStatus {
    /// Job added but not configured (no manual layout).
    #[default]
    Pending,
    /// Job configured with manual layout, ready to process.
    Configured,
    /// Currently being processed.
    Processing,
    /// Completed successfully.
    Complete,
    /// Failed with error.
    Error,
}

impl JobQueueStatus {
    /// Get display string for UI.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "Pending",
            Self::Configured => "Configured",
            Self::Processing => "Processing",
            Self::Complete => "Complete",
            Self::Error => "Error",
        }
    }
}

/// A single job in the queue.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobQueueEntry {
    /// Unique job identifier.
    pub id: String,
    /// Display name (usually derived from primary source filename).
    pub name: String,
    /// Map of source keys to file paths ("Source 1" -> path).
    pub sources: HashMap<String, PathBuf>,
    /// Layout ID for referencing the layout file (MD5 hash of source filenames).
    /// This is calculated from sources and used to find the layout in job_layouts/{id}.json.
    pub layout_id: String,
    /// Current status.
    pub status: JobQueueStatus,
    /// Manual layout if configured (loaded from job_layouts/{layout_id}.json, not persisted here).
    #[serde(skip)]
    pub layout: Option<ManualLayout>,
    /// Error message if status is Error.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_message: Option<String>,
}

impl JobQueueEntry {
    /// Create a new pending job.
    /// The layout_id is automatically calculated from source filenames.
    pub fn new(id: String, name: String, sources: HashMap<String, PathBuf>) -> Self {
        let layout_id = super::generate_layout_id(&sources);
        Self {
            id,
            name,
            sources,
            layout_id,
            status: JobQueueStatus::Pending,
            layout: None,
            error_message: None,
        }
    }

    /// Get truncated source path for display.
    pub fn source_display(&self, key: &str, max_len: usize) -> String {
        self.sources
            .get(key)
            .map(|p| {
                let s = p
                    .file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_else(|| p.to_string_lossy().to_string());
                if s.len() > max_len {
                    format!("...{}", &s[s.len() - max_len + 3..])
                } else {
                    s
                }
            })
            .unwrap_or_default()
    }

    /// Check if job has all required sources.
    pub fn has_required_sources(&self) -> bool {
        self.sources.contains_key("Source 1") && self.sources.contains_key("Source 2")
    }
}

/// User-configured track layout for a job.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManualLayout {
    /// Ordered list of tracks to include in final output.
    pub final_tracks: Vec<FinalTrackEntry>,
    /// Sources to include attachments from.
    pub attachment_sources: Vec<String>,
}

impl ManualLayout {
    /// Create an empty layout.
    pub fn new() -> Self {
        Self {
            final_tracks: Vec::new(),
            attachment_sources: Vec::new(),
        }
    }

    /// Convert to the JSON format expected by JobSpec/MuxStep.
    ///
    /// Returns a Vec of track objects that MuxStep can read. Each track
    /// is a HashMap with keys like "source", "id", "type", "is_default", etc.
    pub fn to_job_spec_format(&self) -> Vec<HashMap<String, serde_json::Value>> {
        self.final_tracks
            .iter()
            .map(|track| {
                let mut map = HashMap::new();

                // Source and track identification
                map.insert("source".to_string(), serde_json::json!(track.source_key));
                map.insert("id".to_string(), serde_json::json!(track.track_id));
                map.insert(
                    "type".to_string(),
                    serde_json::json!(match track.track_type {
                        TrackType::Video => "video",
                        TrackType::Audio => "audio",
                        TrackType::Subtitles => "subtitles",
                    }),
                );

                // Track flags
                map.insert("is_default".to_string(), serde_json::json!(track.config.is_default));
                map.insert(
                    "is_forced_display".to_string(),
                    serde_json::json!(track.config.is_forced_display),
                );

                // Custom overrides (only include if set)
                if let Some(ref name) = track.config.custom_name {
                    map.insert("custom_name".to_string(), serde_json::json!(name));
                }
                if let Some(ref lang) = track.config.custom_lang {
                    map.insert("custom_lang".to_string(), serde_json::json!(lang));
                }

                // Include empty strings for codec/language/name - MuxStep will use defaults
                map.insert("codec".to_string(), serde_json::json!(""));
                map.insert("language".to_string(), serde_json::json!(""));
                map.insert("name".to_string(), serde_json::json!(""));

                map
            })
            .collect()
    }
}

impl Default for ManualLayout {
    fn default() -> Self {
        Self::new()
    }
}

/// A single track entry in the final output list.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FinalTrackEntry {
    /// Track ID within the source file.
    pub track_id: usize,
    /// Source key this track comes from.
    pub source_key: String,
    /// Track type (video, audio, subtitles).
    pub track_type: TrackType,
    /// User configuration for this track.
    pub config: TrackConfig,
    /// Position in user's ordered output list (0-indexed).
    #[serde(default)]
    pub user_order_index: usize,
    /// Position among tracks of same source and type (for robust matching).
    #[serde(default)]
    pub position_in_source_type: usize,
}

impl FinalTrackEntry {
    /// Create a new entry with default config.
    pub fn new(track_id: usize, source_key: String, track_type: TrackType) -> Self {
        Self {
            track_id,
            source_key,
            track_type,
            config: TrackConfig::default(),
            user_order_index: 0,
            position_in_source_type: 0,
        }
    }
}

/// Per-track configuration options.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TrackConfig {
    /// Sync delay target source (for audio/subs from non-reference sources).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sync_to_source: Option<String>,
    /// Set as default track of this type.
    #[serde(default)]
    pub is_default: bool,
    /// Set forced display flag (shows subtitles even when disabled).
    #[serde(default)]
    pub is_forced_display: bool,
    /// Custom track name override.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub custom_name: Option<String>,
    /// Custom language override.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub custom_lang: Option<String>,
    /// Apply original track name from source (vs. custom_name override).
    #[serde(default)]
    pub apply_track_name: bool,
}

/// Wrapper for saved layout files with metadata.
/// This is what gets serialized to disk by LayoutManager.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SavedLayoutData {
    /// Job identifier (MD5 hash of source filenames).
    pub job_id: String,
    /// Source file paths at time of saving.
    pub sources: HashMap<String, PathBuf>,
    /// The actual layout configuration.
    #[serde(flatten)]
    pub layout: ManualLayout,
    /// ISO timestamp when layout was saved.
    pub saved_timestamp: String,
    /// Track signature for comparing tracks.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub track_signature: Option<super::signature::TrackSignature>,
    /// Structure signature for exact compatibility checking.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub structure_signature: Option<super::signature::StructureSignature>,
    /// Job ID this layout was copied from (if copied).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub copied_from: Option<String>,
}

impl SavedLayoutData {
    /// Create a new SavedLayoutData with current timestamp.
    pub fn new(job_id: String, sources: HashMap<String, PathBuf>, layout: ManualLayout) -> Self {
        Self {
            job_id,
            sources,
            layout,
            saved_timestamp: chrono::Utc::now().to_rfc3339(),
            track_signature: None,
            structure_signature: None,
            copied_from: None,
        }
    }

    /// Create with signatures for layout compatibility checking.
    pub fn with_signatures(
        job_id: String,
        sources: HashMap<String, PathBuf>,
        layout: ManualLayout,
        track_signature: super::signature::TrackSignature,
        structure_signature: super::signature::StructureSignature,
    ) -> Self {
        Self {
            job_id,
            sources,
            layout,
            saved_timestamp: chrono::Utc::now().to_rfc3339(),
            track_signature: Some(track_signature),
            structure_signature: Some(structure_signature),
            copied_from: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn job_queue_status_display() {
        assert_eq!(JobQueueStatus::Pending.as_str(), "Pending");
        assert_eq!(JobQueueStatus::Configured.as_str(), "Configured");
    }

    #[test]
    fn job_entry_source_display() {
        let mut sources = HashMap::new();
        sources.insert(
            "Source 1".to_string(),
            PathBuf::from("/path/to/very_long_filename_movie.mkv"),
        );

        let job = JobQueueEntry::new("test".to_string(), "test".to_string(), sources);

        let display = job.source_display("Source 1", 20);
        assert!(display.len() <= 20);
    }

    #[test]
    fn manual_layout_serializes() {
        let layout = ManualLayout::new();
        let json = serde_json::to_string(&layout).unwrap();
        assert!(json.contains("final_tracks"));
    }
}
