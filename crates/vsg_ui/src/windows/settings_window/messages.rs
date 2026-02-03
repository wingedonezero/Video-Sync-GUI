//! Settings window messages (events)

use vsg_core::analysis::OutlierMode;
use vsg_core::models::{
    AnalysisMode, CorrelationMethod, DelaySelectionMode, FilteringMethod, SnapMode, SyncMode,
};

/// Messages for the settings window
#[derive(Debug)]
pub enum SettingsMsg {
    // === Tab: Storage ===
    SetOutputFolder(String),
    SetTempRoot(String),
    SetLogsFolder(String),
    BrowseOutputFolder,
    BrowseTempRoot,
    BrowseLogsFolder,
    BrowseResult {
        field: PathField,
        path: Option<String>,
    },

    // === Tab: Analysis ===
    SetAnalysisMode(AnalysisMode),
    SetCorrelationMethod(CorrelationMethod),
    SetLangSource1(String),
    SetLangOthers(String),
    SetChunkCount(u32),
    SetChunkDuration(u32),
    SetMinMatchPct(f64),
    SetMinAcceptedChunks(u32),
    SetScanStartPct(f64),
    SetScanEndPct(f64),
    ToggleUseSoxr(bool),
    ToggleAudioPeakFit(bool),
    SetFilteringMethod(FilteringMethod),
    SetFilterLowCutoff(f64),
    SetFilterHighCutoff(f64),
    ToggleMultiCorrelation(bool),
    ToggleMultiCorrScc(bool),
    ToggleMultiCorrGccPhat(bool),
    ToggleMultiCorrGccScot(bool),
    ToggleMultiCorrWhitened(bool),
    ToggleMultiCorrOnset(bool),
    ToggleMultiCorrDtw(bool),
    ToggleMultiCorrSpectrogram(bool),
    SetDelaySelectionMode(DelaySelectionMode),
    SetFirstStableMinChunks(u32),
    ToggleFirstStableSkipUnstable(bool),
    SetEarlyClusterWindow(u32),
    SetEarlyClusterThreshold(u32),
    SetSyncMode(SyncMode),

    // Sync Stability settings
    ToggleSyncStabilityEnabled(bool),
    SetSyncStabilityVarianceThreshold(f64),
    SetSyncStabilityMinChunks(u32),
    SetSyncStabilityOutlierMode(OutlierMode),
    SetSyncStabilityOutlierThreshold(f64),

    // === Tab: Chapters ===
    ToggleChapterRename(bool),
    ToggleSnapEnabled(bool),
    SetSnapMode(SnapMode),
    SetSnapThreshold(u32),
    ToggleSnapStartsOnly(bool),

    // === Tab: Merge Behavior ===
    ToggleDisableTrackStatsTags(bool),
    ToggleDisableHeaderCompression(bool),
    ToggleApplyDialogNorm(bool),

    // === Tab: Logging ===
    ToggleCompact(bool),
    ToggleAutoscroll(bool),
    SetErrorTail(u32),
    SetProgressStep(u32),
    ToggleShowOptionsPretty(bool),
    ToggleShowOptionsJson(bool),
    ToggleArchiveLogs(bool),

    // === Dialog actions ===
    Save,
    Cancel,
}

/// Which path field is being browsed
#[derive(Debug, Clone, Copy)]
pub enum PathField {
    OutputFolder,
    TempRoot,
    LogsFolder,
}

/// Output message sent to parent when dialog closes
#[derive(Debug)]
pub enum SettingsOutput {
    /// Settings were saved (parent should reload config)
    Saved,
    /// Dialog was cancelled
    Cancelled,
}
