//! Settings window UI logic helpers

use vsg_core::models::{
    CorrelationMethod, DelaySelectionMode, FilteringMethod, SnapMode, SyncMode,
};
use vsg_core::subtitles::frame_utils::{
    ComparisonMethod, DeinterlaceMethod, HashAlgorithm, IndexerBackend,
};
use vsg_core::subtitles::sync::SyncModeType;
use vsg_core::subtitles::RoundingMode;

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

// === Subtitle Sync helpers ===

/// Get display names for subtitle sync mode types
pub fn subtitle_sync_mode_names() -> Vec<(&'static str, SyncModeType)> {
    vec![
        ("Time-Based", SyncModeType::TimeBased),
        ("Video-Verified", SyncModeType::VideoVerified),
    ]
}

/// Get index for subtitle sync mode type
pub fn subtitle_sync_mode_index(mode: &SyncModeType) -> u32 {
    match mode {
        SyncModeType::TimeBased => 0,
        SyncModeType::VideoVerified => 1,
    }
}

/// Get display names for rounding modes
pub fn rounding_mode_names() -> Vec<(&'static str, RoundingMode)> {
    vec![
        ("Floor (Round Down)", RoundingMode::Floor),
        ("Round (Nearest)", RoundingMode::Round),
        ("Ceil (Round Up)", RoundingMode::Ceil),
    ]
}

/// Get index for rounding mode
pub fn rounding_mode_index(mode: &RoundingMode) -> u32 {
    match mode {
        RoundingMode::Floor => 0,
        RoundingMode::Round => 1,
        RoundingMode::Ceil => 2,
    }
}

/// Get display names for hash algorithms
pub fn hash_algorithm_names() -> Vec<(&'static str, HashAlgorithm)> {
    vec![
        ("PHash (Perceptual)", HashAlgorithm::PHash),
        ("DHash (Difference)", HashAlgorithm::DHash),
        ("AHash (Average)", HashAlgorithm::AHash),
        ("Block Hash", HashAlgorithm::BlockHash),
    ]
}

/// Get index for hash algorithm
pub fn hash_algorithm_index(algo: &HashAlgorithm) -> u32 {
    match algo {
        HashAlgorithm::PHash => 0,
        HashAlgorithm::DHash => 1,
        HashAlgorithm::AHash => 2,
        HashAlgorithm::BlockHash => 3,
    }
}

/// Get display names for comparison methods
pub fn comparison_method_names() -> Vec<(&'static str, ComparisonMethod)> {
    vec![
        ("Hash + Hamming Distance", ComparisonMethod::Hash),
        ("SSIM (Structural Similarity)", ComparisonMethod::Ssim),
        ("MSE (Mean Squared Error)", ComparisonMethod::Mse),
    ]
}

/// Get index for comparison method
pub fn comparison_method_index(method: &ComparisonMethod) -> u32 {
    match method {
        ComparisonMethod::Hash => 0,
        ComparisonMethod::Ssim => 1,
        ComparisonMethod::Mse => 2,
    }
}

/// Get display names for indexer backends
pub fn indexer_backend_names() -> Vec<(&'static str, IndexerBackend)> {
    vec![
        ("FFMS2", IndexerBackend::Ffms2),
        ("BestSource", IndexerBackend::BestSource),
        ("L-SMASH", IndexerBackend::LSmash),
    ]
}

/// Get index for indexer backend
pub fn indexer_backend_index(backend: &IndexerBackend) -> u32 {
    match backend {
        IndexerBackend::Ffms2 => 0,
        IndexerBackend::BestSource => 1,
        IndexerBackend::LSmash => 2,
    }
}

/// Get display names for deinterlace methods
pub fn deinterlace_method_names() -> Vec<(&'static str, DeinterlaceMethod)> {
    vec![
        ("Auto", DeinterlaceMethod::Auto),
        ("None", DeinterlaceMethod::None),
        ("YADIF", DeinterlaceMethod::Yadif),
        ("YADIFmod", DeinterlaceMethod::YadifMod),
        ("Bob", DeinterlaceMethod::Bob),
        ("BWDIF", DeinterlaceMethod::Bwdif),
    ]
}

/// Get index for deinterlace method
pub fn deinterlace_method_index(method: &DeinterlaceMethod) -> u32 {
    match method {
        DeinterlaceMethod::Auto => 0,
        DeinterlaceMethod::None => 1,
        DeinterlaceMethod::Yadif => 2,
        DeinterlaceMethod::YadifMod => 3,
        DeinterlaceMethod::Bob => 4,
        DeinterlaceMethod::Bwdif => 5,
    }
}
