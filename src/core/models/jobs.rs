//! Job and plan data structures

use super::media::Track;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;

/// Delay information for source files
///
/// Stores raw delays computed by analysis and the global shift needed
/// to make all delays non-negative (positive-only timing model).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Delays {
    /// Per-source delays in milliseconds (can be negative)
    /// Key is source identifier ("REF", "SEC", "TER")
    pub source_delays_ms: HashMap<String, i64>,

    /// Raw floating-point delays before rounding
    pub raw_source_delays_ms: HashMap<String, f64>,

    /// Global shift in milliseconds to make all delays non-negative
    pub global_shift_ms: i64,

    /// Raw floating-point global shift
    pub raw_global_shift_ms: f64,
}

impl Delays {
    /// Create new Delays from raw analysis results
    ///
    /// Computes global shift to ensure no negative delays remain.
    pub fn new(raw_delays: HashMap<String, f64>) -> Self {
        let mut source_delays_ms = HashMap::new();
        let mut raw_source_delays_ms = HashMap::new();

        // Round to nearest millisecond
        for (source, delay_f64) in &raw_delays {
            let delay_ms = delay_f64.round() as i64;
            source_delays_ms.insert(source.clone(), delay_ms);
            raw_source_delays_ms.insert(source.clone(), *delay_f64);
        }

        // Compute global shift (if minimum is negative, shift by absolute value)
        let min_delay = source_delays_ms.values().min().copied().unwrap_or(0);
        let global_shift_ms = if min_delay < 0 { -min_delay } else { 0 };
        let raw_global_shift_ms = global_shift_ms as f64;

        Self {
            source_delays_ms,
            raw_source_delays_ms,
            global_shift_ms,
            raw_global_shift_ms,
        }
    }

    /// Get effective delay for a source after applying global shift
    pub fn effective_delay(&self, source: &str) -> i64 {
        let raw = self.source_delays_ms.get(source).copied().unwrap_or(0);
        raw + self.global_shift_ms
    }

    /// Check if global shift is needed
    pub fn requires_global_shift(&self) -> bool {
        self.global_shift_ms > 0
    }
}

/// Job specification
///
/// Represents a single job to be processed (analysis and/or merge).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobSpec {
    /// Reference file path
    pub ref_path: PathBuf,

    /// Secondary file path (optional)
    pub sec_path: Option<PathBuf>,

    /// Tertiary file path (optional)
    pub ter_path: Option<PathBuf>,

    /// Job name (derived from reference filename)
    pub name: String,
}

impl JobSpec {
    /// Create a new job specification
    pub fn new(
        ref_path: PathBuf,
        sec_path: Option<PathBuf>,
        ter_path: Option<PathBuf>,
    ) -> Self {
        let name = ref_path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("unknown")
            .to_string();

        Self {
            ref_path,
            sec_path,
            ter_path,
            name,
        }
    }

    /// Check if this is an analyze-only job (no secondary/tertiary)
    pub fn is_analysis_only(&self) -> bool {
        self.sec_path.is_none() && self.ter_path.is_none()
    }

    /// Get list of all source paths
    pub fn all_paths(&self) -> Vec<PathBuf> {
        let mut paths = vec![self.ref_path.clone()];
        if let Some(sec) = &self.sec_path {
            paths.push(sec.clone());
        }
        if let Some(ter) = &self.ter_path {
            paths.push(ter.clone());
        }
        paths
    }
}

/// Plan item representing a track in the final merge
///
/// This structure contains all information needed to process and include
/// a track in the final output, including extraction path, processing flags,
/// and mkvmerge options.
#[derive(Debug, Clone)]
pub struct PlanItem {
    /// Track information
    pub track: Track,

    /// Path to extracted track file
    pub extracted_path: Option<PathBuf>,

    /// Mark as default track
    pub is_default: bool,

    /// Mark as forced display (subtitles)
    pub is_forced_display: bool,

    /// Apply original track name
    pub apply_track_name: bool,

    /// Convert SRT to ASS (subtitles only)
    pub convert_to_ass: bool,

    /// Rescale ASS/SSA to video resolution (subtitles only)
    pub rescale: bool,

    /// Font size multiplier (subtitles only)
    pub size_multiplier: f64,

    /// Style patch for subtitles
    pub style_patch: Option<HashMap<String, serde_json::Value>>,

    /// User-modified path (if user edited subtitle manually)
    pub user_modified_path: Option<PathBuf>,

    /// Sync to another track
    pub sync_to: Option<String>,

    /// Track is preserved (from stepping correction)
    pub is_preserved: bool,

    /// Track has been corrected
    pub is_corrected: bool,

    /// Source of correction
    pub correction_source: Option<String>,

    /// Perform OCR on subtitle
    pub perform_ocr: bool,

    /// Perform OCR cleanup
    pub perform_ocr_cleanup: bool,

    /// Container delay in milliseconds
    pub container_delay_ms: i64,

    /// Custom language override
    pub custom_lang: String,

    /// Custom name override
    pub custom_name: String,

    /// Video aspect ratio override
    pub aspect_ratio: Option<String>,

    /// Track was adjusted by stepping correction
    pub stepping_adjusted: bool,

    /// Track is a generated filtered track
    pub is_generated: bool,

    /// Source track ID for generated track
    pub generated_source_track_id: Option<i32>,

    /// Source path for generated track
    pub generated_source_path: Option<PathBuf>,

    /// Generated track filter mode
    pub generated_filter_mode: String,

    /// Styles to filter for generated track
    pub generated_filter_styles: Vec<String>,

    /// Original style list for validation
    pub generated_original_style_list: Vec<String>,

    /// Verify only lines removed during generation
    pub generated_verify_only_lines_removed: bool,

    /// Skip frame validation
    pub skip_frame_validation: bool,

    /// Styles to exclude from sync
    pub sync_exclusion_styles: Vec<String>,

    /// Sync exclusion mode
    pub sync_exclusion_mode: String,

    /// Original styles for sync exclusion validation
    pub sync_exclusion_original_style_list: Vec<String>,
}

impl PlanItem {
    /// Create a new plan item from a track
    pub fn from_track(track: Track) -> Self {
        Self {
            track,
            extracted_path: None,
            is_default: false,
            is_forced_display: false,
            apply_track_name: false,
            convert_to_ass: false,
            rescale: false,
            size_multiplier: 1.0,
            style_patch: None,
            user_modified_path: None,
            sync_to: None,
            is_preserved: false,
            is_corrected: false,
            correction_source: None,
            perform_ocr: false,
            perform_ocr_cleanup: false,
            container_delay_ms: 0,
            custom_lang: String::new(),
            custom_name: String::new(),
            aspect_ratio: None,
            stepping_adjusted: false,
            is_generated: false,
            generated_source_track_id: None,
            generated_source_path: None,
            generated_filter_mode: String::new(),
            generated_filter_styles: Vec::new(),
            generated_original_style_list: Vec::new(),
            generated_verify_only_lines_removed: false,
            skip_frame_validation: false,
            sync_exclusion_styles: Vec::new(),
            sync_exclusion_mode: String::new(),
            sync_exclusion_original_style_list: Vec::new(),
        }
    }

    /// Get the effective path for this track (user-modified > extracted)
    pub fn effective_path(&self) -> Option<&PathBuf> {
        self.user_modified_path
            .as_ref()
            .or(self.extracted_path.as_ref())
    }

    /// Check if this is a subtitle track
    pub fn is_subtitle(&self) -> bool {
        matches!(
            self.track.track_type,
            super::enums::TrackType::Subtitles
        )
    }

    /// Check if this is an audio track
    pub fn is_audio(&self) -> bool {
        matches!(self.track.track_type, super::enums::TrackType::Audio)
    }

    /// Check if this is a video track
    pub fn is_video(&self) -> bool {
        matches!(self.track.track_type, super::enums::TrackType::Video)
    }
}

/// Merge plan containing all tracks and metadata
#[derive(Debug, Clone)]
pub struct MergePlan {
    /// List of plan items in output order
    pub items: Vec<PlanItem>,

    /// Delays information
    pub delays: Delays,

    /// Output file path
    pub output_path: PathBuf,

    /// Temporary working directory
    pub temp_dir: PathBuf,

    /// Whether to include chapters
    pub include_chapters: bool,

    /// Whether to include attachments
    pub include_attachments: bool,
}

impl MergePlan {
    /// Create a new merge plan
    pub fn new(
        items: Vec<PlanItem>,
        delays: Delays,
        output_path: PathBuf,
        temp_dir: PathBuf,
    ) -> Self {
        Self {
            items,
            delays,
            output_path,
            temp_dir,
            include_chapters: true,
            include_attachments: true,
        }
    }

    /// Get all video tracks
    pub fn video_tracks(&self) -> Vec<&PlanItem> {
        self.items.iter().filter(|item| item.is_video()).collect()
    }

    /// Get all audio tracks
    pub fn audio_tracks(&self) -> Vec<&PlanItem> {
        self.items.iter().filter(|item| item.is_audio()).collect()
    }

    /// Get all subtitle tracks
    pub fn subtitle_tracks(&self) -> Vec<&PlanItem> {
        self.items.iter().filter(|item| item.is_subtitle()).collect()
    }

    /// Get the reference video track (first video from REF source)
    pub fn reference_video(&self) -> Option<&PlanItem> {
        self.items
            .iter()
            .find(|item| item.is_video() && item.track.source == "REF")
    }
}

/// Job result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobResult {
    /// Job status
    pub status: JobStatus,

    /// Job name
    pub name: String,

    /// Secondary delay (if analyzed)
    pub delay_sec: Option<i64>,

    /// Tertiary delay (if analyzed)
    pub delay_ter: Option<i64>,

    /// Output file path (if merged)
    pub output: Option<PathBuf>,

    /// Error message (if failed)
    pub error: Option<String>,
}

/// Job status enumeration
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum JobStatus {
    Pending,
    Analyzing,
    Analyzed,
    Merging,
    Merged,
    Failed,
}

impl std::fmt::Display for JobStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            JobStatus::Pending => write!(f, "Pending"),
            JobStatus::Analyzing => write!(f, "Analyzing"),
            JobStatus::Analyzed => write!(f, "Analyzed"),
            JobStatus::Merging => write!(f, "Merging"),
            JobStatus::Merged => write!(f, "Merged"),
            JobStatus::Failed => write!(f, "Failed"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_delays_computation() {
        let mut raw_delays = HashMap::new();
        raw_delays.insert("REF".to_string(), 0.0);
        raw_delays.insert("SEC".to_string(), -200.5);
        raw_delays.insert("TER".to_string(), 150.2);

        let delays = Delays::new(raw_delays);

        assert_eq!(delays.source_delays_ms.get("REF"), Some(&0));
        assert_eq!(delays.source_delays_ms.get("SEC"), Some(&-201));
        assert_eq!(delays.source_delays_ms.get("TER"), Some(&150));
        assert_eq!(delays.global_shift_ms, 201);
        assert!(delays.requires_global_shift());

        // Check effective delays (after global shift)
        assert_eq!(delays.effective_delay("REF"), 201);
        assert_eq!(delays.effective_delay("SEC"), 0);
        assert_eq!(delays.effective_delay("TER"), 351);
    }

    #[test]
    fn test_delays_no_shift_needed() {
        let mut raw_delays = HashMap::new();
        raw_delays.insert("REF".to_string(), 0.0);
        raw_delays.insert("SEC".to_string(), 100.0);

        let delays = Delays::new(raw_delays);

        assert_eq!(delays.global_shift_ms, 0);
        assert!(!delays.requires_global_shift());
    }

    #[test]
    fn test_job_spec_creation() {
        let job = JobSpec::new(
            PathBuf::from("/path/to/ref.mkv"),
            Some(PathBuf::from("/path/to/sec.mkv")),
            None,
        );

        assert_eq!(job.name, "ref");
        assert!(!job.is_analysis_only());
        assert_eq!(job.all_paths().len(), 2);
    }
}
