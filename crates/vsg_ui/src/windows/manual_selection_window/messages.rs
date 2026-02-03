//! Manual selection window messages

use std::path::PathBuf;

use vsg_core::extraction::types::TrackType;

/// Messages for the manual selection window
#[derive(Debug)]
pub enum ManualSelectionMsg {
    // === Track operations ===
    /// Add track to final output list
    AddTrackToFinal {
        source_key: String,
        track_index: usize,
    },
    /// Remove track from final output list
    RemoveTrackFromFinal { final_index: usize },
    /// Move track up in final output list
    MoveTrackUp { final_index: usize },
    /// Move track down in final output list
    MoveTrackDown { final_index: usize },
    /// Reorder track via drag-drop
    ReorderTrack { from_index: usize, to_index: usize },

    // === Track configuration ===
    /// Toggle default flag for track
    ToggleTrackDefault { final_index: usize },
    /// Toggle forced flag for track (subtitles only)
    ToggleTrackForced { final_index: usize },
    /// Toggle keep original track name
    ToggleKeepName { final_index: usize },
    /// Set custom name for track
    SetTrackCustomName {
        final_index: usize,
        name: Option<String>,
    },
    /// Set custom language for track
    SetTrackCustomLang {
        final_index: usize,
        lang: Option<String>,
    },
    /// Open track settings dialog
    OpenTrackSettings { final_index: usize },

    // === Attachments ===
    /// Toggle attachment source
    ToggleAttachmentSource { source_key: String },

    // === External subtitles ===
    /// Add external subtitle file(s)
    AddExternalSubtitles,
    /// External subtitles selected
    ExternalSubtitlesSelected(Vec<PathBuf>),

    // === Selection ===
    /// Source track selected
    SourceTrackSelected {
        source_key: String,
        track_index: usize,
    },
    /// Final track selected
    FinalTrackSelected { final_index: usize },
    /// Source track double-clicked (add to final)
    SourceTrackDoubleClicked {
        source_key: String,
        track_index: usize,
    },
    /// Final track double-clicked (open settings or remove)
    FinalTrackDoubleClicked { final_index: usize },

    // === Dialog buttons ===
    /// OK - save layout and close
    Accept,
    /// Cancel - discard changes and close
    Cancel,
}

/// Output messages sent to parent when dialog closes
#[derive(Debug)]
pub enum ManualSelectionOutput {
    /// Layout configured successfully
    LayoutConfigured {
        /// Final track layout
        layout: Vec<FinalTrackData>,
        /// Sources to include attachments from
        attachment_sources: Vec<String>,
    },
    /// Dialog cancelled
    Cancelled,
}

/// Data for a track in the final output list
#[derive(Debug, Clone)]
pub struct FinalTrackData {
    /// Track ID within source file
    pub track_id: usize,
    /// Source key (e.g., "Source 1", "External")
    pub source_key: String,
    /// Track type
    pub track_type: TrackType,
    /// Whether this is default for its type
    pub is_default: bool,
    /// Whether this is forced (subtitles)
    pub is_forced: bool,
    /// Custom name override
    pub custom_name: Option<String>,
    /// Custom language override
    pub custom_lang: Option<String>,
    /// Apply original track name
    pub apply_track_name: bool,
    /// Sync to source (for non-Source 1 tracks)
    pub sync_to_source: Option<String>,
    /// Position in user's order (0-indexed)
    pub user_order_index: usize,
    /// Position among tracks of same source and type
    pub position_in_source_type: usize,
    /// Path to source file
    pub source_path: PathBuf,
    /// Generated track info (for filtered subtitles)
    pub is_generated: bool,
    /// Source track ID for generated tracks
    pub generated_source_track_id: Option<usize>,

    // === Fields for future subtitle features (not yet implemented in core) ===
    /// Perform OCR (image-based subtitles) - NOT YET IMPLEMENTED
    #[allow(dead_code)]
    pub perform_ocr: bool,
    /// Convert SRT to ASS - NOT YET IMPLEMENTED
    #[allow(dead_code)]
    pub convert_to_ass: bool,
    /// Rescale subtitles - NOT YET IMPLEMENTED
    #[allow(dead_code)]
    pub rescale: bool,
}

impl Default for FinalTrackData {
    fn default() -> Self {
        Self {
            track_id: 0,
            source_key: String::new(),
            track_type: TrackType::Video,
            is_default: false,
            is_forced: false,
            custom_name: None,
            custom_lang: None,
            apply_track_name: false,
            sync_to_source: None,
            perform_ocr: false,
            convert_to_ass: false,
            rescale: false,
            user_order_index: 0,
            position_in_source_type: 0,
            source_path: PathBuf::new(),
            is_generated: false,
            generated_source_track_id: None,
        }
    }
}
