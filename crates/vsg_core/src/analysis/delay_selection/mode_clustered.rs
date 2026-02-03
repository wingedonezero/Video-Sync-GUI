//! Mode (Clustered) delay selector.
//!
//! Finds the most common rounded delay, then collects all chunks within
//! ±1ms tolerance and averages their raw values. Better handles vote-splitting
//! and excludes extreme outliers.

use std::collections::HashMap;

use super::{DelaySelector, SelectorConfig};
use crate::analysis::types::{ChunkResult, DelaySelection};

/// Mode Clustered selector: mode with tolerance for clustering.
pub struct ModeClusteredSelector;

impl DelaySelector for ModeClusteredSelector {
    fn name(&self) -> &'static str {
        "mode_clustered"
    }

    fn select(
        &self,
        chunks: &[ChunkResult],
        config: &SelectorConfig,
    ) -> Option<DelaySelection> {
        if chunks.len() < config.min_accepted_chunks {
            return None;
        }

        let tolerance = config.cluster_tolerance_ms;

        // First, find the mode (most common rounded delay)
        let mut counts: HashMap<i64, usize> = HashMap::new();
        for chunk in chunks {
            *counts.entry(chunk.delay_ms_rounded).or_default() += 1;
        }

        let (&mode_delay, _) = counts.iter().max_by_key(|(_, &count)| count)?;

        // Now collect all chunks within tolerance of the mode
        let cluster: Vec<&ChunkResult> = chunks
            .iter()
            .filter(|c| (c.delay_ms_rounded - mode_delay).abs() <= tolerance)
            .collect();

        if cluster.is_empty() {
            return None;
        }

        // Average raw delays in the cluster
        let raw_avg: f64 = cluster.iter().map(|c| c.delay_ms_raw).sum::<f64>()
            / cluster.len() as f64;

        Some(DelaySelection {
            delay_ms_raw: raw_avg,
            delay_ms_rounded: raw_avg.round() as i64,
            method_name: self.name().to_string(),
            chunks_used: cluster.len(),
            details: Some(format!(
                "cluster around {:+}ms (±{}ms tolerance)",
                mode_delay, tolerance
            )),
        })
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
    fn clusters_within_tolerance() {
        let chunks = vec![
            make_chunk(-1000.0), // -1000
            make_chunk(-1000.5), // -1000 or -1001
            make_chunk(-1001.0), // -1001, within ±1 of -1000
            make_chunk(-5000.0), // Outlier, excluded
        ];
        let config = SelectorConfig::default();
        let result = ModeClusteredSelector.select(&chunks, &config).unwrap();
        // Should include chunks around -1000/-1001, exclude -5000
        assert!(result.chunks_used >= 3);
        assert!(result.delay_ms_rounded >= -1001 && result.delay_ms_rounded <= -1000);
    }

    #[test]
    fn excludes_outliers() {
        let chunks = vec![
            make_chunk(-1000.0),
            make_chunk(-1000.0),
            make_chunk(-1000.0),
            make_chunk(-9999.0), // Far outlier
        ];
        let config = SelectorConfig::default();
        let result = ModeClusteredSelector.select(&chunks, &config).unwrap();
        assert_eq!(result.chunks_used, 3); // Outlier excluded
        assert_eq!(result.delay_ms_rounded, -1000);
    }
}
