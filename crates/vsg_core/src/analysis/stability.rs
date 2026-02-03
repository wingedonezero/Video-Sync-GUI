//! Stability metrics calculation for audio sync analysis.
//!
//! Calculates quality and consistency metrics from chunk correlation results.
//! All functions are pure - no I/O, no side effects.

use serde::{Deserialize, Serialize};

use super::types::ChunkResult;

/// Mode for detecting outliers in delay measurements.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum OutlierMode {
    /// Any chunk that differs from the first is an outlier.
    Any,
    /// Chunks that differ from mean by more than threshold are outliers.
    #[default]
    Threshold,
}

/// Configuration for outlier detection.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutlierConfig {
    /// Mode for detecting outliers.
    pub mode: OutlierMode,
    /// Threshold in ms for "threshold" mode (deviations larger than this are outliers).
    pub threshold_ms: f64,
    /// Floating point tolerance for "any" mode.
    pub tolerance_ms: f64,
}

impl Default for OutlierConfig {
    fn default() -> Self {
        Self {
            mode: OutlierMode::Threshold,
            threshold_ms: 5.0, // 5ms default threshold
            tolerance_ms: 0.0001, // Tiny floating point tolerance
        }
    }
}

/// Information about an outlier chunk.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutlierInfo {
    /// Index of the chunk (1-based for display).
    pub chunk_index: usize,
    /// Start time of the chunk in seconds.
    pub time_secs: f64,
    /// Measured delay in milliseconds.
    pub delay_ms: f64,
    /// Deviation from reference/mean in milliseconds.
    pub deviation_ms: f64,
}

/// Stability metrics for a source analysis.
///
/// Captures quality indicators from chunk-based analysis
/// to help assess confidence in the calculated delay.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct StabilityMetrics {
    /// Number of chunks that passed the match threshold.
    pub accepted_chunks: usize,
    /// Total chunks analyzed.
    pub total_chunks: usize,
    /// Average match percentage across accepted chunks.
    pub avg_match_pct: f64,
    /// Standard deviation of delay measurements (ms).
    pub delay_std_dev_ms: f64,
    /// Acceptance rate as percentage (accepted / total * 100).
    pub acceptance_rate: f64,
    /// Minimum delay among accepted chunks (ms).
    pub min_delay_ms: f64,
    /// Maximum delay among accepted chunks (ms).
    pub max_delay_ms: f64,
    /// Maximum variance (max - min) in ms.
    pub max_variance_ms: f64,
    /// Number of outlier chunks detected.
    pub outlier_count: usize,
    /// Details of outlier chunks (limited to first 10).
    pub outliers: Vec<OutlierInfo>,
}

impl StabilityMetrics {
    /// Check if stability is good (high acceptance, low variance).
    pub fn is_stable(&self) -> bool {
        self.acceptance_rate >= 50.0 && self.delay_std_dev_ms < 50.0
    }

    /// Get a status string for logging.
    pub fn status(&self) -> &'static str {
        if self.delay_std_dev_ms > 50.0 {
            "DRIFT"
        } else if self.acceptance_rate < 50.0 {
            "LOW"
        } else {
            "OK"
        }
    }
}

/// Detect outliers in chunk delay measurements.
///
/// Pure function - no I/O, no side effects.
///
/// # Arguments
/// * `accepted_chunks` - Accepted chunk results to analyze
/// * `config` - Outlier detection configuration
///
/// # Returns
/// List of outlier information (limited to first 10).
pub fn detect_outliers(accepted_chunks: &[&ChunkResult], config: &OutlierConfig) -> Vec<OutlierInfo> {
    if accepted_chunks.is_empty() {
        return Vec::new();
    }

    let delays: Vec<f64> = accepted_chunks.iter().map(|c| c.delay_ms_raw).collect();
    let mean_delay = delays.iter().sum::<f64>() / delays.len() as f64;

    let mut outliers = Vec::new();

    match config.mode {
        OutlierMode::Any => {
            // Any chunk that differs from the first is an outlier
            let reference = delays[0];
            for chunk in accepted_chunks.iter() {
                let deviation = chunk.delay_ms_raw - reference;
                if deviation.abs() > config.tolerance_ms {
                    outliers.push(OutlierInfo {
                        chunk_index: chunk.chunk_index + 1, // 1-based for display
                        time_secs: chunk.chunk_start_secs,
                        delay_ms: chunk.delay_ms_raw,
                        deviation_ms: deviation,
                    });
                }
            }
        }
        OutlierMode::Threshold => {
            // Chunks that differ from mean by more than threshold are outliers
            for chunk in accepted_chunks.iter() {
                let deviation = chunk.delay_ms_raw - mean_delay;
                if deviation.abs() > config.threshold_ms {
                    outliers.push(OutlierInfo {
                        chunk_index: chunk.chunk_index + 1, // 1-based for display
                        time_secs: chunk.chunk_start_secs,
                        delay_ms: chunk.delay_ms_raw,
                        deviation_ms: deviation,
                    });
                }
            }
        }
    }

    // Limit to first 10 outliers
    outliers.truncate(10);
    outliers
}

/// Calculate stability metrics from chunk results.
///
/// Pure function - no I/O, no side effects.
/// Uses default outlier configuration.
///
/// # Arguments
/// * `chunks` - All chunk results (accepted and rejected)
/// * `min_match_pct` - Minimum match percentage for acceptance
///
/// # Returns
/// Stability metrics summarizing the analysis quality.
pub fn calculate_stability(chunks: &[ChunkResult], min_match_pct: f64) -> StabilityMetrics {
    calculate_stability_with_outliers(chunks, min_match_pct, &OutlierConfig::default())
}

/// Calculate stability metrics from chunk results with custom outlier detection.
///
/// Pure function - no I/O, no side effects.
///
/// # Arguments
/// * `chunks` - All chunk results (accepted and rejected)
/// * `min_match_pct` - Minimum match percentage for acceptance
/// * `outlier_config` - Configuration for outlier detection
///
/// # Returns
/// Stability metrics summarizing the analysis quality.
pub fn calculate_stability_with_outliers(
    chunks: &[ChunkResult],
    min_match_pct: f64,
    outlier_config: &OutlierConfig,
) -> StabilityMetrics {
    let total_chunks = chunks.len();

    if total_chunks == 0 {
        return StabilityMetrics::default();
    }

    // Get accepted chunks
    let accepted: Vec<&ChunkResult> = chunks
        .iter()
        .filter(|c| c.accepted && c.match_pct >= min_match_pct)
        .collect();

    let accepted_chunks = accepted.len();

    if accepted_chunks == 0 {
        return StabilityMetrics {
            total_chunks,
            ..Default::default()
        };
    }

    // Calculate average match percentage
    let avg_match_pct = accepted.iter().map(|c| c.match_pct).sum::<f64>() / accepted_chunks as f64;

    // Extract delays for statistics
    let delays: Vec<f64> = accepted.iter().map(|c| c.delay_ms_raw).collect();

    // Calculate min/max
    let min_delay_ms = delays.iter().copied().fold(f64::INFINITY, f64::min);
    let max_delay_ms = delays.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let max_variance_ms = max_delay_ms - min_delay_ms;

    // Calculate standard deviation
    let delay_std_dev_ms = calculate_std_dev(&delays);

    // Calculate acceptance rate
    let acceptance_rate = (accepted_chunks as f64 / total_chunks as f64) * 100.0;

    // Detect outliers
    let outliers = detect_outliers(&accepted, outlier_config);
    let outlier_count = outliers.len();

    StabilityMetrics {
        accepted_chunks,
        total_chunks,
        avg_match_pct,
        delay_std_dev_ms,
        acceptance_rate,
        min_delay_ms,
        max_delay_ms,
        max_variance_ms,
        outlier_count,
        outliers,
    }
}

/// Calculate standard deviation of values.
///
/// Returns 0.0 if there are fewer than 2 values.
pub fn calculate_std_dev(values: &[f64]) -> f64 {
    if values.len() <= 1 {
        return 0.0;
    }

    let mean = values.iter().sum::<f64>() / values.len() as f64;
    let variance = values.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / values.len() as f64;
    variance.sqrt()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_chunk(index: usize, delay_ms: f64, match_pct: f64, accepted: bool) -> ChunkResult {
        ChunkResult {
            chunk_index: index,
            chunk_start_secs: index as f64 * 10.0,
            delay_ms_raw: delay_ms,
            delay_ms_rounded: delay_ms.round() as i64,
            match_pct,
            accepted,
            reject_reason: if accepted {
                None
            } else {
                Some("test rejection".to_string())
            },
        }
    }

    #[test]
    fn calculates_stability_for_uniform_delays() {
        let chunks = vec![
            make_chunk(1, -500.0, 95.0, true),
            make_chunk(2, -500.0, 93.0, true),
            make_chunk(3, -500.0, 97.0, true),
            make_chunk(4, -500.0, 91.0, true),
            make_chunk(5, -500.0, 94.0, true),
        ];

        let stability = calculate_stability(&chunks, 5.0);

        assert_eq!(stability.accepted_chunks, 5);
        assert_eq!(stability.total_chunks, 5);
        assert!((stability.acceptance_rate - 100.0).abs() < 0.01);
        assert!(stability.delay_std_dev_ms.abs() < 0.01); // No variance
        assert!(stability.max_variance_ms.abs() < 0.01);
    }

    #[test]
    fn calculates_stability_with_variance() {
        let chunks = vec![
            make_chunk(1, -500.0, 95.0, true),
            make_chunk(2, -510.0, 93.0, true),
            make_chunk(3, -490.0, 97.0, true),
            make_chunk(4, -520.0, 91.0, true),
            make_chunk(5, -480.0, 94.0, true),
        ];

        let stability = calculate_stability(&chunks, 5.0);

        assert_eq!(stability.accepted_chunks, 5);
        assert!(stability.delay_std_dev_ms > 0.0);
        assert!((stability.max_variance_ms - 40.0).abs() < 0.01); // 520 - 480 = 40
        assert!((stability.min_delay_ms - (-520.0)).abs() < 0.01);
        assert!((stability.max_delay_ms - (-480.0)).abs() < 0.01);
    }

    #[test]
    fn handles_rejected_chunks() {
        let chunks = vec![
            make_chunk(1, -500.0, 95.0, true),
            make_chunk(2, -500.0, 93.0, true),
            make_chunk(3, 0.0, 2.0, false), // Rejected
            make_chunk(4, -500.0, 91.0, true),
            make_chunk(5, 0.0, 1.0, false), // Rejected
        ];

        let stability = calculate_stability(&chunks, 5.0);

        assert_eq!(stability.accepted_chunks, 3);
        assert_eq!(stability.total_chunks, 5);
        assert!((stability.acceptance_rate - 60.0).abs() < 0.01);
    }

    #[test]
    fn handles_empty_chunks() {
        let chunks: Vec<ChunkResult> = vec![];
        let stability = calculate_stability(&chunks, 5.0);

        assert_eq!(stability.accepted_chunks, 0);
        assert_eq!(stability.total_chunks, 0);
    }

    #[test]
    fn handles_all_rejected() {
        let chunks = vec![
            make_chunk(1, 0.0, 1.0, false),
            make_chunk(2, 0.0, 2.0, false),
        ];

        let stability = calculate_stability(&chunks, 5.0);

        assert_eq!(stability.accepted_chunks, 0);
        assert_eq!(stability.total_chunks, 2);
        assert_eq!(stability.acceptance_rate, 0.0);
    }

    #[test]
    fn status_returns_correct_value() {
        // Good stability
        let good = StabilityMetrics {
            acceptance_rate: 90.0,
            delay_std_dev_ms: 5.0,
            ..Default::default()
        };
        assert_eq!(good.status(), "OK");

        // Low acceptance
        let low = StabilityMetrics {
            acceptance_rate: 30.0,
            delay_std_dev_ms: 5.0,
            ..Default::default()
        };
        assert_eq!(low.status(), "LOW");

        // High variance (drift)
        let drift = StabilityMetrics {
            acceptance_rate: 90.0,
            delay_std_dev_ms: 100.0,
            ..Default::default()
        };
        assert_eq!(drift.status(), "DRIFT");
    }

    #[test]
    fn std_dev_calculates_correctly() {
        let values = vec![10.0, 12.0, 23.0, 23.0, 16.0, 23.0, 21.0, 16.0];
        let std_dev = calculate_std_dev(&values);

        // Expected std dev is approximately 4.898979
        assert!((std_dev - 4.898979).abs() < 0.001);
    }

    #[test]
    fn std_dev_single_value_is_zero() {
        let values = vec![10.0];
        assert_eq!(calculate_std_dev(&values), 0.0);
    }

    #[test]
    fn std_dev_empty_is_zero() {
        let values: Vec<f64> = vec![];
        assert_eq!(calculate_std_dev(&values), 0.0);
    }

    // Outlier detection tests

    #[test]
    fn detects_no_outliers_for_uniform_delays() {
        let chunks = vec![
            make_chunk(0, -500.0, 95.0, true),
            make_chunk(1, -500.0, 93.0, true),
            make_chunk(2, -500.0, 97.0, true),
        ];
        let accepted: Vec<&ChunkResult> = chunks.iter().collect();
        let config = OutlierConfig::default();

        let outliers = detect_outliers(&accepted, &config);
        assert_eq!(outliers.len(), 0);
    }

    #[test]
    fn detects_outliers_in_threshold_mode() {
        let chunks = vec![
            make_chunk(0, -500.0, 95.0, true),
            make_chunk(1, -500.0, 93.0, true),
            make_chunk(2, -520.0, 97.0, true), // 20ms deviation from mean (-506.67)
        ];
        let accepted: Vec<&ChunkResult> = chunks.iter().collect();
        let config = OutlierConfig {
            mode: OutlierMode::Threshold,
            threshold_ms: 10.0, // 10ms threshold
            tolerance_ms: 0.0001,
        };

        let outliers = detect_outliers(&accepted, &config);
        assert_eq!(outliers.len(), 1);
        assert_eq!(outliers[0].chunk_index, 3); // 1-based
        assert!((outliers[0].delay_ms - (-520.0)).abs() < 0.01);
    }

    #[test]
    fn detects_outliers_in_any_mode() {
        let chunks = vec![
            make_chunk(0, -500.0, 95.0, true),
            make_chunk(1, -500.5, 93.0, true), // Differs from first (-0.5ms)
            make_chunk(2, -500.0, 97.0, true),
        ];
        let accepted: Vec<&ChunkResult> = chunks.iter().collect();
        let config = OutlierConfig {
            mode: OutlierMode::Any,
            threshold_ms: 5.0,
            tolerance_ms: 0.0001,
        };

        let outliers = detect_outliers(&accepted, &config);
        assert_eq!(outliers.len(), 1);
        assert_eq!(outliers[0].chunk_index, 2); // 1-based (chunk index 1)
        assert!((outliers[0].deviation_ms - (-0.5)).abs() < 0.01); // -500.5 - (-500.0) = -0.5
    }

    #[test]
    fn any_mode_respects_tolerance() {
        let chunks = vec![
            make_chunk(0, -500.0, 95.0, true),
            make_chunk(1, -500.00005, 93.0, true), // Within tolerance
        ];
        let accepted: Vec<&ChunkResult> = chunks.iter().collect();
        let config = OutlierConfig {
            mode: OutlierMode::Any,
            threshold_ms: 5.0,
            tolerance_ms: 0.0001,
        };

        let outliers = detect_outliers(&accepted, &config);
        assert_eq!(outliers.len(), 0);
    }

    #[test]
    fn outliers_limited_to_ten() {
        let chunks: Vec<ChunkResult> = (0..20)
            .map(|i| make_chunk(i, -500.0 + (i as f64 * 10.0), 95.0, true))
            .collect();
        let accepted: Vec<&ChunkResult> = chunks.iter().collect();
        let config = OutlierConfig {
            mode: OutlierMode::Threshold,
            threshold_ms: 1.0, // Low threshold to catch all
            tolerance_ms: 0.0001,
        };

        let outliers = detect_outliers(&accepted, &config);
        assert!(outliers.len() <= 10);
    }

    #[test]
    fn stability_includes_outliers() {
        let chunks = vec![
            make_chunk(0, -500.0, 95.0, true),
            make_chunk(1, -500.0, 93.0, true),
            make_chunk(2, -530.0, 97.0, true), // Big outlier
        ];

        let config = OutlierConfig {
            mode: OutlierMode::Threshold,
            threshold_ms: 10.0,
            tolerance_ms: 0.0001,
        };

        let stability = calculate_stability_with_outliers(&chunks, 5.0, &config);
        assert_eq!(stability.outlier_count, 1);
        assert_eq!(stability.outliers.len(), 1);
        assert_eq!(stability.outliers[0].chunk_index, 3); // 1-based
    }

    #[test]
    fn empty_chunks_no_outliers() {
        let chunks: Vec<ChunkResult> = vec![];
        let accepted: Vec<&ChunkResult> = chunks.iter().collect();
        let config = OutlierConfig::default();

        let outliers = detect_outliers(&accepted, &config);
        assert_eq!(outliers.len(), 0);
    }

    #[test]
    fn outlier_info_has_correct_time() {
        let chunks = vec![
            make_chunk(0, -500.0, 95.0, true),  // time = 0.0
            make_chunk(5, -530.0, 93.0, true),  // time = 50.0 (index 5 * 10.0)
        ];
        let accepted: Vec<&ChunkResult> = chunks.iter().collect();
        let config = OutlierConfig {
            mode: OutlierMode::Any,
            threshold_ms: 5.0,
            tolerance_ms: 0.0001,
        };

        let outliers = detect_outliers(&accepted, &config);
        assert_eq!(outliers.len(), 1);
        assert!((outliers[0].time_secs - 50.0).abs() < 0.01);
    }
}
