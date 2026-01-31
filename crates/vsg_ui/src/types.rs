//! Shared types for the Video Sync GUI.
//!
//! This module contains types used across multiple UI components,
//! extracted to avoid circular dependencies and reduce app.rs size.

/// Language codes matching the picker options.
/// Index 0 = "und", 1 = "eng", 2 = "jpn", etc.
pub const LANGUAGE_CODES: &[&str] = &[
    "und", "eng", "jpn", "spa", "fre", "ger", "ita", "por", "rus", "chi", "kor", "ara",
];

/// State for a source group in manual selection.
#[derive(Debug, Clone)]
pub struct SourceGroupState {
    pub source_key: String,
    pub title: String,
    pub tracks: Vec<TrackWidgetState>,
    pub is_expanded: bool,
}

/// State for a track widget.
#[derive(Debug, Clone)]
pub struct TrackWidgetState {
    pub id: usize,
    pub track_type: String,
    pub codec_id: String,
    pub language: Option<String>,
    pub summary: String,
    pub badges: String,
    pub is_blocked: bool,
}

/// State for a final track in the layout.
#[derive(Debug, Clone)]
pub struct FinalTrackState {
    pub entry_id: uuid::Uuid,
    pub track_id: usize,
    pub source_key: String,
    pub track_type: String,
    pub codec_id: String,
    pub summary: String,
    pub is_default: bool,
    pub is_forced_display: bool,
    pub sync_to_source: String,
    pub original_lang: Option<String>,
    pub custom_lang: Option<String>,
    pub custom_name: Option<String>,
    pub perform_ocr: bool,
    pub convert_to_ass: bool,
    pub rescale: bool,
    pub size_multiplier_pct: i32,
    pub style_patch: Option<String>,
    pub font_replacements: Option<String>,
    pub sync_exclusion_styles: Vec<String>,
    pub sync_exclusion_mode: SyncExclusionMode,
    pub is_generated: bool,
    pub generated_filter_styles: Vec<String>,
    pub generated_from_entry_id: Option<uuid::Uuid>,
}

impl FinalTrackState {
    pub fn new(
        track_id: usize,
        source_key: String,
        track_type: String,
        codec_id: String,
        summary: String,
        original_lang: Option<String>,
    ) -> Self {
        Self {
            entry_id: uuid::Uuid::new_v4(),
            track_id,
            source_key,
            track_type,
            codec_id,
            summary,
            is_default: false,
            is_forced_display: false,
            sync_to_source: "Source 1".to_string(),
            original_lang,
            custom_lang: None,
            custom_name: None,
            perform_ocr: false,
            convert_to_ass: false,
            rescale: false,
            size_multiplier_pct: 100,
            style_patch: None,
            font_replacements: None,
            sync_exclusion_styles: Vec::new(),
            sync_exclusion_mode: SyncExclusionMode::Exclude,
            is_generated: false,
            generated_filter_styles: Vec::new(),
            generated_from_entry_id: None,
        }
    }

    pub fn is_ocr_compatible(&self) -> bool {
        let codec_upper = self.codec_id.to_uppercase();
        codec_upper.contains("VOBSUB") || codec_upper.contains("PGS")
    }

    pub fn is_convert_to_ass_compatible(&self) -> bool {
        self.codec_id.to_uppercase().contains("S_TEXT/UTF8")
    }

    pub fn is_style_editable(&self) -> bool {
        let codec_upper = self.codec_id.to_uppercase();
        codec_upper.contains("S_TEXT/ASS") || codec_upper.contains("S_TEXT/SSA")
    }

    pub fn supports_sync_exclusion(&self) -> bool {
        self.is_style_editable()
    }

    pub fn badges(&self) -> String {
        let mut badges: Vec<String> = Vec::new();

        if self.is_default {
            badges.push("Default".to_string());
        }
        if self.is_forced_display {
            badges.push("Forced".to_string());
        }
        if self.perform_ocr {
            badges.push("OCR".to_string());
        }
        if self.convert_to_ass {
            badges.push("→ASS".to_string());
        }
        if self.rescale {
            badges.push("Rescale".to_string());
        }
        if self.size_multiplier_pct != 100 {
            badges.push("Sized".to_string());
        }
        if self.style_patch.is_some() {
            badges.push("Styled".to_string());
        }
        if self.font_replacements.is_some() {
            badges.push("Fonts".to_string());
        }
        if !self.sync_exclusion_styles.is_empty() {
            badges.push("SyncEx".to_string());
        }
        if self.is_generated {
            badges.push("Generated".to_string());
        }
        if let Some(ref custom_lang) = self.custom_lang {
            let original = self.original_lang.as_deref().unwrap_or("und");
            if custom_lang != original {
                badges.push(format!("Lang: {}", custom_lang));
            }
        }
        if self.custom_name.is_some() {
            badges.push("Named".to_string());
        }

        badges.join(" | ")
    }
}

/// Sync exclusion mode for subtitle tracks.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SyncExclusionMode {
    #[default]
    Exclude,
    Include,
}

/// State for track settings dialog.
#[derive(Debug, Clone, Default)]
pub struct TrackSettingsState {
    pub track_type: String,
    pub codec_id: String,
    pub selected_language_idx: usize,
    pub custom_lang: Option<String>,
    pub custom_name: Option<String>,
    pub perform_ocr: bool,
    pub convert_to_ass: bool,
    pub rescale: bool,
    pub size_multiplier_pct: i32,
    pub sync_exclusion_styles: Vec<String>,
    pub sync_exclusion_mode: SyncExclusionMode,
}
