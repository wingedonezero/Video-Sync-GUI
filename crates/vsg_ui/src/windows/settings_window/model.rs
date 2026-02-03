//! Settings window state model

use vsg_core::config::{
    AnalysisSettings, ChapterSettings, LoggingSettings, PathSettings, PostProcessSettings,
};

/// Settings window state - holds a working copy of settings
#[derive(Debug, Clone)]
pub struct SettingsModel {
    pub paths: PathSettings,
    pub logging: LoggingSettings,
    pub analysis: AnalysisSettings,
    pub chapters: ChapterSettings,
    pub postprocess: PostProcessSettings,
    /// Track if settings have been modified
    pub modified: bool,
}

impl SettingsModel {
    /// Create from current config settings
    pub fn from_settings(
        paths: PathSettings,
        logging: LoggingSettings,
        analysis: AnalysisSettings,
        chapters: ChapterSettings,
        postprocess: PostProcessSettings,
    ) -> Self {
        Self {
            paths,
            logging,
            analysis,
            chapters,
            postprocess,
            modified: false,
        }
    }

    /// Mark settings as modified
    pub fn mark_modified(&mut self) {
        self.modified = true;
    }
}
