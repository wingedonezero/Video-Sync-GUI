//! Stability metrics calculation for audio sync analysis.
//!
//! Calculates quality and consistency metrics from chunk correlation results.
//! All functions are pure - no I/O, no side effects.

use serde::{Deserialize, Serialize};

use super::types::ChunkResult;

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

/// Calculate stability metrics from chunk results.
///
/// Pure function - no I/O, no side effects.
///
/// # Arguments
/// * `chunks` - All chunk results (accepted and rejected)
/// * `min_match_pct` - Minimum match percentage for acceptance
///
/// # Returns
/// Stability metrics summarizing the analysis quality.
pub fn calculate_stability(chunks: &[ChunkResult], min_match_pct: f64) -> StabilityMetrics {
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

    StabilityMetrics {
        accepted_chunks,
        total_chunks,
        avg_match_pct,
        delay_std_dev_ms,
        acceptance_rate,
        min_delay_ms,
        max_delay_ms,
        max_variance_ms,
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
}
