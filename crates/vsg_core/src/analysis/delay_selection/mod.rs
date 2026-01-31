//! Delay selection strategies for choosing final delay from chunk measurements.
//!
//! This module provides a trait-based approach to selecting the final delay
//! from multiple chunk correlation results. Different strategies handle
//! various edge cases (noise, drift, stepping, etc.).

mod average;
mod first_stable;
mod mode;
mod mode_clustered;
mod mode_early;

pub use average::AverageSelector;
pub use first_stable::FirstStableSelector;
pub use mode::ModeSelector;
pub use mode_clustered::ModeClusteredSelector;
pub use mode_early::ModeEarlySelector;

use crate::analysis::types::{ChunkResult, DelaySelection};
use crate::config::AnalysisSettings;
use crate::models::DelaySelectionMode;

/// Configuration for delay selectors.
#[derive(Debug, Clone)]
pub struct SelectorConfig {
    /// Minimum accepted chunks required for selection.
    pub min_accepted_chunks: usize,
    /// [First Stable] Minimum consecutive chunks for stability.
    pub first_stable_min_chunks: usize,
    /// [First Stable] Skip unstable segments.
    pub first_stable_skip_unstable: bool,
    /// [Early Cluster] Number of early chunks to check.
    pub early_cluster_window: usize,
    /// [Early Cluster] Minimum chunks in early window.
    pub early_cluster_threshold: usize,
    /// Tolerance for clustering delays (typically ±1ms).
    pub cluster_tolerance_ms: i64,
}

impl Default for SelectorConfig {
    fn default() -> Self {
        Self {
            min_accepted_chunks: 3,
            first_stable_min_chunks: 3,
            first_stable_skip_unstable: false,
            early_cluster_window: 10,
            early_cluster_threshold: 5,
            cluster_tolerance_ms: 1,
        }
    }
}

impl From<&AnalysisSettings> for SelectorConfig {
    fn from(settings: &AnalysisSettings) -> Self {
        Self {
            min_accepted_chunks: settings.min_accepted_chunks as usize,
            first_stable_min_chunks: settings.first_stable_min_chunks as usize,
            first_stable_skip_unstable: settings.first_stable_skip_unstable,
            early_cluster_window: settings.early_cluster_window as usize,
            early_cluster_threshold: settings.early_cluster_threshold as usize,
            cluster_tolerance_ms: 1,
        }
    }
}

/// Trait for delay selection strategies.
///
/// Implementations receive only accepted chunks and must return a
/// `DelaySelection` with both raw and rounded delay values.
pub trait DelaySelector: Send + Sync {
    /// Get the name of this selection method.
    fn name(&self) -> &'static str;

    /// Select final delay from accepted chunks.
    ///
    /// Returns `None` if selection cannot be made (e.g., insufficient chunks).
    fn select(
        &self,
        chunks: &[ChunkResult],
        config: &SelectorConfig,
    ) -> Option<DelaySelection>;
}

/// Create a delay selector for the given mode.
pub fn get_selector(mode: DelaySelectionMode) -> Box<dyn DelaySelector> {
    match mode {
        DelaySelectionMode::Mode => Box::new(ModeSelector),
        DelaySelectionMode::ModeClustered => Box::new(ModeClusteredSelector),
        DelaySelectionMode::ModeEarly => Box::new(ModeEarlySelector),
        DelaySelectionMode::FirstStable => Box::new(FirstStableSelector),
        DelaySelectionMode::Average => Box::new(AverageSelector),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_chunks(delays: &[(f64, f64)]) -> Vec<ChunkResult> {
        delays
            .iter()
            .enumerate()
            .map(|(i, (delay, start))| ChunkResult {
                chunk_index: i + 1,
                chunk_start_secs: *start,
                delay_ms_raw: *delay,
                delay_ms_rounded: delay.round() as i64,
                match_pct: 95.0,
                accepted: true,
                reject_reason: None,
            })
            .collect()
    }

    #[test]
    fn mode_selector_picks_most_common() {
        let chunks = make_chunks(&[
            (-1000.5, 10.0),
            (-1000.7, 20.0),
            (-1000.3, 30.0), // All round to -1001
            (-500.0, 40.0),  // Outlier
        ]);
        let config = SelectorConfig::default();
        let result = ModeSelector.select(&chunks, &config).unwrap();
        assert_eq!(result.delay_ms_rounded, -1001);
    }

    #[test]
    fn average_selector_averages_raw() {
        let chunks = make_chunks(&[
            (-1000.0, 10.0),
            (-1002.0, 20.0),
            (-1001.0, 30.0),
        ]);
        let config = SelectorConfig::default();
        let result = AverageSelector.select(&chunks, &config).unwrap();
        // Average of -1000, -1002, -1001 = -1001
        assert!((result.delay_ms_raw - (-1001.0)).abs() < 0.01);
    }
}
