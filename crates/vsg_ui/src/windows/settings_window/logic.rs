//! Settings window UI logic helpers

use vsg_core::models::{
    CorrelationMethod, DelaySelectionMode, FilteringMethod, SnapMode, SyncMode,
};

/// Get display names for correlation methods
pub fn correlation_method_names() -> Vec<(&'static str, CorrelationMethod)> {
    vec![
        ("Standard Correlation (SCC)", CorrelationMethod::Scc),
        ("Phase Correlation (GCC-PHAT)", CorrelationMethod::GccPhat),
        ("GCC-SCOT", CorrelationMethod::GccScot),
        ("Whitened Cross-Correlation", CorrelationMethod::Whitened),
        ("Onset Detection", CorrelationMethod::Onset),
        ("DTW (Dynamic Time Warping)", CorrelationMethod::Dtw),
        ("Spectrogram Correlation", CorrelationMethod::Spectrogram),
    ]
}

/// Get index for correlation method
pub fn correlation_method_index(method: &CorrelationMethod) -> u32 {
    match method {
        CorrelationMethod::Scc => 0,
        CorrelationMethod::GccPhat => 1,
        CorrelationMethod::GccScot => 2,
        CorrelationMethod::Whitened => 3,
        CorrelationMethod::Onset => 4,
        CorrelationMethod::Dtw => 5,
        CorrelationMethod::Spectrogram => 6,
    }
}

/// Get display names for filtering methods
pub fn filtering_method_names() -> Vec<(&'static str, FilteringMethod)> {
    vec![
        ("None", FilteringMethod::None),
        ("Low Pass", FilteringMethod::LowPass),
        ("Band Pass", FilteringMethod::BandPass),
        ("High Pass", FilteringMethod::HighPass),
    ]
}

/// Get index for filtering method
pub fn filtering_method_index(method: &FilteringMethod) -> u32 {
    match method {
        FilteringMethod::None => 0,
        FilteringMethod::LowPass => 1,
        FilteringMethod::BandPass => 2,
        FilteringMethod::HighPass => 3,
    }
}

/// Get display names for delay selection modes
pub fn delay_selection_mode_names() -> Vec<(&'static str, DelaySelectionMode)> {
    vec![
        ("Mode (Most Common)", DelaySelectionMode::Mode),
        ("Mode (Clustered)", DelaySelectionMode::ModeClustered),
        ("Mode (Early Cluster)", DelaySelectionMode::ModeEarly),
        ("First Stable", DelaySelectionMode::FirstStable),
        ("Average", DelaySelectionMode::Average),
    ]
}

/// Get index for delay selection mode
pub fn delay_selection_mode_index(mode: &DelaySelectionMode) -> u32 {
    match mode {
        DelaySelectionMode::Mode => 0,
        DelaySelectionMode::ModeClustered => 1,
        DelaySelectionMode::ModeEarly => 2,
        DelaySelectionMode::FirstStable => 3,
        DelaySelectionMode::Average => 4,
    }
}

/// Get display names for snap modes
pub fn snap_mode_names() -> Vec<(&'static str, SnapMode)> {
    vec![
        ("Previous", SnapMode::Previous),
        ("Nearest", SnapMode::Nearest),
        ("Next", SnapMode::Next),
    ]
}

/// Get index for snap mode
pub fn snap_mode_index(mode: &SnapMode) -> u32 {
    match mode {
        SnapMode::Previous => 0,
        SnapMode::Nearest => 1,
        SnapMode::Next => 2,
    }
}

/// Get display names for sync modes
pub fn sync_mode_names() -> Vec<(&'static str, SyncMode)> {
    vec![
        ("Positive Only (Shift all)", SyncMode::PositiveOnly),
        ("Allow Negative", SyncMode::AllowNegative),
    ]
}

/// Get index for sync mode
pub fn sync_mode_index(mode: &SyncMode) -> u32 {
    match mode {
        SyncMode::PositiveOnly => 0,
        SyncMode::AllowNegative => 1,
    }
}
