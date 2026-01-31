//! Job queue types and data structures.

use std::collections::HashMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use super::style_types::{FontReplacements, StylePatches};
use crate::models::{SourceIndex, SourceRef, TrackType};

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
    /// Map of source indices to file paths.
    pub sources: HashMap<SourceIndex, PathBuf>,
    /// Layout ID for referencing the layout file (MD5 hash of source filenames).
    /// This is calculated from sources and used to find the layout in job_layouts/{id}.json.
    pub layout_id: String,
    /// Current status.
    pub status: JobQueueStatus,
    /// Manual layout if configured.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub layout: Option<ManualLayout>,
    /// Error message if status is Error.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_message: Option<String>,
}

impl JobQueueEntry {
    /// Create a new pending job.
    /// The layout_id is automatically calculated from source filenames.
    pub fn new(id: String, name: String, sources: HashMap<SourceIndex, PathBuf>) -> Self {
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
    pub fn source_display(&self, source: SourceIndex, max_len: usize) -> String {
        self.sources
            .get(&source)
            .map(|p| {
                let s = p.file_name()
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
        self.sources.contains_key(&SourceIndex::source1())
            && self.sources.contains_key(&SourceIndex::source2())
    }
}

/// User-configured track layout for a job.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManualLayout {
    /// Ordered list of tracks to include in final output.
    pub final_tracks: Vec<FinalTrackEntry>,
    /// Sources to include attachments from.
    pub attachment_sources: Vec<SourceIndex>,
    /// Per-source correlation settings.
    #[serde(default)]
    pub source_settings: HashMap<SourceIndex, SourceCorrelationSettings>,
}

impl ManualLayout {
    /// Create an empty layout.
    pub fn new() -> Self {
        Self {
            final_tracks: Vec::new(),
            attachment_sources: Vec::new(),
            source_settings: HashMap::new(),
        }
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
    /// Source reference this track comes from (indexed source or external).
    pub source_ref: SourceRef,
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

    // === Generated track fields (for tracks created by filtering styles) ===
    /// Marks this as a generated track (created from another track).
    #[serde(default)]
    pub is_generated: bool,
    /// ID of the source track this was generated from.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub generated_source_track_id: Option<usize>,
    /// Path to source subtitle file.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub generated_source_path: Option<String>,
    /// Filter mode: "include" or "exclude" styles.
    #[serde(default = "default_filter_mode")]
    pub generated_filter_mode: String,
    /// Style names to include/exclude.
    #[serde(default)]
    pub generated_filter_styles: Vec<String>,
    /// Complete style list from original source (for validation).
    #[serde(default)]
    pub generated_original_style_list: Vec<String>,
    /// Verify only event lines removed, nothing else changed.
    #[serde(default = "default_true")]
    pub generated_verify_only_lines_removed: bool,
}

fn default_filter_mode() -> String {
    "exclude".to_string()
}

fn default_true() -> bool {
    true
}

impl FinalTrackEntry {
    /// Create a new entry with default config.
    pub fn new(track_id: usize, source_ref: SourceRef, track_type: TrackType) -> Self {
        Self {
            track_id,
            source_ref,
            track_type,
            config: TrackConfig::default(),
            user_order_index: 0,
            position_in_source_type: 0,
            is_generated: false,
            generated_source_track_id: None,
            generated_source_path: None,
            generated_filter_mode: "exclude".to_string(),
            generated_filter_styles: Vec::new(),
            generated_original_style_list: Vec::new(),
            generated_verify_only_lines_removed: true,
        }
    }

    /// Create a new entry from an indexed source.
    pub fn from_source(track_id: usize, source: SourceIndex, track_type: TrackType) -> Self {
        Self::new(track_id, SourceRef::Index(source), track_type)
    }

    /// Create a new entry from an external file.
    pub fn external(track_id: usize, track_type: TrackType) -> Self {
        Self::new(track_id, SourceRef::External, track_type)
    }

    /// Get the source index if this track comes from an indexed source.
    pub fn source_index(&self) -> Option<SourceIndex> {
        self.source_ref.as_index()
    }

    /// Check if this track comes from an external source.
    pub fn is_external(&self) -> bool {
        self.source_ref.is_external()
    }
}

/// Per-track configuration options.
#[derive(Debug, Clone, Serialize, Deserialize)]
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

    // === Subtitle-specific options ===
    /// Perform OCR on image-based subtitles.
    #[serde(default)]
    pub perform_ocr: bool,
    /// Convert SRT to ASS format.
    #[serde(default)]
    pub convert_to_ass: bool,
    /// Rescale subtitles to video resolution.
    #[serde(default)]
    pub rescale: bool,
    /// Size multiplier for subtitle scaling.
    #[serde(default = "default_size_multiplier")]
    pub size_multiplier: f32,
    /// Styles to exclude from frame sync.
    #[serde(default)]
    pub sync_exclusion_styles: Vec<String>,
    /// Mode for sync exclusion: "exclude" or "include".
    #[serde(default = "default_sync_exclusion_mode")]
    pub sync_exclusion_mode: String,
    /// Complete style list from original source (for validation).
    #[serde(default)]
    pub sync_exclusion_original_style_list: Vec<String>,
    /// Skip duration-align frame validation.
    #[serde(default)]
    pub skip_frame_validation: bool,

    // === Style modification options ===
    /// Style patches to apply (style_name -> property overrides).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub style_patches: Option<StylePatches>,
    /// Font replacement mappings (old_font -> new_font).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub font_replacements: Option<FontReplacements>,

    // === Video-specific options ===
    /// Original aspect ratio to preserve (e.g., "16:9", "109:60").
    #[serde(skip_serializing_if = "Option::is_none")]
    pub aspect_ratio: Option<String>,
}

fn default_size_multiplier() -> f32 {
    1.0
}

fn default_sync_exclusion_mode() -> String {
    "exclude".to_string()
}

impl Default for TrackConfig {
    fn default() -> Self {
        Self {
            sync_to_source: None,
            is_default: false,
            is_forced_display: false,
            custom_name: None,
            custom_lang: None,
            apply_track_name: false,
            perform_ocr: false,
            convert_to_ass: false,
            rescale: false,
            size_multiplier: 1.0,
            sync_exclusion_styles: Vec::new(),
            sync_exclusion_mode: "exclude".to_string(),
            sync_exclusion_original_style_list: Vec::new(),
            skip_frame_validation: false,
            style_patches: None,
            font_replacements: None,
            aspect_ratio: None,
        }
    }
}

/// Per-source correlation settings.
///
/// Controls how audio correlation is performed for a specific source.
/// All fields have sensible defaults if not specified.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SourceCorrelationSettings {
    /// Audio track index to use for correlation (this source).
    #[serde(default)]
    pub correlation_track: Option<usize>,
    /// Reference audio track index to use from Source 1.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub correlation_ref_track: Option<usize>,
    /// Override start time for correlation window (milliseconds).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub window_start_ms: Option<i64>,
    /// Override end time for correlation window (milliseconds).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub window_end_ms: Option<i64>,
    /// Enable source separation for this source.
    #[serde(default)]
    pub use_source_separation: bool,
    /// Enable stepping correction for this source.
    #[serde(default)]
    pub stepping_enabled: bool,
}

/// Wrapper for saved layout files with metadata.
/// This is what gets serialized to disk by LayoutManager.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SavedLayoutData {
    /// Job identifier (MD5 hash of source filenames).
    pub job_id: String,
    /// Source file paths at time of saving.
    pub sources: HashMap<SourceIndex, PathBuf>,
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
    pub fn new(job_id: String, sources: HashMap<SourceIndex, PathBuf>, layout: ManualLayout) -> Self {
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
        sources: HashMap<SourceIndex, PathBuf>,
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
        sources.insert(SourceIndex::source1(), PathBuf::from("/path/to/very_long_filename_movie.mkv"));

        let job = JobQueueEntry::new("test".to_string(), "test".to_string(), sources);

        let display = job.source_display(SourceIndex::source1(), 20);
        assert!(display.len() <= 20);
    }

    #[test]
    fn manual_layout_serializes() {
        let layout = ManualLayout::new();
        let json = serde_json::to_string(&layout).unwrap();
        assert!(json.contains("final_tracks"));
    }
}
