//! Average delay selector.
//!
//! Calculates the mean of all raw delay values and rounds once at the end.
//! Simple but can be skewed by outliers.

use super::{DelaySelector, SelectorConfig};
use crate::analysis::types::{ChunkResult, DelaySelection};

/// Average selector: mean of all raw delays.
pub struct AverageSelector;

impl DelaySelector for AverageSelector {
    fn name(&self) -> &'static str {
        "average"
    }

    fn select(
        &self,
        chunks: &[ChunkResult],
        config: &SelectorConfig,
    ) -> Option<DelaySelection> {
        if chunks.len() < config.min_accepted_chunks {
            return None;
        }

        let sum: f64 = chunks.iter().map(|c| c.delay_ms_raw).sum();
        let avg = sum / chunks.len() as f64;

        Some(DelaySelection::new(avg, self.name(), chunks.len()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_chunk(delay_raw: f64) -> ChunkResult {
        ChunkResult {
            chunk_index: 1,
            chunk_start_secs: 0.0,
            delay_ms_raw: delay_raw,
            delay_ms_rounded: delay_raw.round() as i64,
            match_pct: 95.0,
            accepted: true,
            reject_reason: None,
        }
    }

    #[test]
    fn averages_correctly() {
        let chunks = vec![
            make_chunk(-1000.0),
            make_chunk(-1001.0),
            make_chunk(-1002.0),
        ];
        let config = SelectorConfig::default();
        let result = AverageSelector.select(&chunks, &config).unwrap();
        assert!((result.delay_ms_raw - (-1001.0)).abs() < 0.01);
        assert_eq!(result.delay_ms_rounded, -1001);
    }

    #[test]
    fn sensitive_to_outliers() {
        let chunks = vec![
            make_chunk(-1000.0),
            make_chunk(-1000.0),
            make_chunk(-5000.0), // Big outlier
        ];
        let config = SelectorConfig::default();
        let result = AverageSelector.select(&chunks, &config).unwrap();
        // Average is skewed by outlier
        assert!((result.delay_ms_raw - (-2333.33)).abs() < 1.0);
    }
}
