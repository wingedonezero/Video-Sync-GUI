//! Mode (Early Cluster) delay selector.
//!
//! Prioritizes delay clusters that appear frequently in the early portion
//! of the file. Useful for files where beginning sync is most reliable
//! and edits/cuts may occur mid-file.

use std::collections::HashMap;

use super::{DelaySelector, ModeClusteredSelector, SelectorConfig};
use crate::analysis::types::{ChunkResult, DelaySelection};

/// Mode Early selector: prioritizes clusters stable early in the file.
pub struct ModeEarlySelector;

impl DelaySelector for ModeEarlySelector {
    fn name(&self) -> &'static str {
        "mode_early"
    }

    fn select(
        &self,
        chunks: &[ChunkResult],
        config: &SelectorConfig,
    ) -> Option<DelaySelection> {
        if chunks.len() < config.min_accepted_chunks {
            return None;
        }

        let early_window = config.early_cluster_window.min(chunks.len());
        let early_threshold = config.early_cluster_threshold;
        let tolerance = config.cluster_tolerance_ms;

        // Get early chunks (first N chunks)
        let early_chunks: Vec<&ChunkResult> = chunks.iter().take(early_window).collect();

        // Count delays in early window
        let mut early_counts: HashMap<i64, usize> = HashMap::new();
        for chunk in &early_chunks {
            *early_counts.entry(chunk.delay_ms_rounded).or_default() += 1;
        }

        // Find delays that appear frequently in early window (including tolerance)
        let mut early_stable_delays: Vec<(i64, usize)> = Vec::new();
        for (&delay, &_count) in &early_counts {
            // Count including tolerance
            let total_in_tolerance: usize = early_chunks
                .iter()
                .filter(|c| (c.delay_ms_rounded - delay).abs() <= tolerance)
                .count();

            if total_in_tolerance >= early_threshold {
                early_stable_delays.push((delay, total_in_tolerance));
            }
        }

        // If we found early stable delays, use the most common one
        if let Some((best_delay, _)) = early_stable_delays.iter().max_by_key(|(_, count)| count) {
            // Collect all chunks (not just early) within tolerance of this delay
            let cluster: Vec<&ChunkResult> = chunks
                .iter()
                .filter(|c| (c.delay_ms_rounded - best_delay).abs() <= tolerance)
                .collect();

            if !cluster.is_empty() {
                let raw_avg: f64 = cluster.iter().map(|c| c.delay_ms_raw).sum::<f64>()
                    / cluster.len() as f64;

                return Some(DelaySelection {
                    delay_ms_raw: raw_avg,
                    delay_ms_rounded: raw_avg.round() as i64,
                    method_name: self.name().to_string(),
                    chunks_used: cluster.len(),
                    details: Some(format!(
                        "early stable cluster around {:+}ms ({} in first {} chunks)",
                        best_delay,
                        early_stable_delays.iter().find(|(d, _)| d == best_delay).map(|(_, c)| *c).unwrap_or(0),
                        early_window
                    )),
                });
            }
        }

        // Fall back to regular clustered mode if no early stable cluster found
        ModeClusteredSelector.select(chunks, config).map(|mut sel| {
            sel.method_name = format!("{} (fallback)", self.name());
            sel
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_chunk(index: usize, delay_raw: f64, start: f64) -> ChunkResult {
        ChunkResult {
            chunk_index: index,
            chunk_start_secs: start,
            delay_ms_raw: delay_raw,
            delay_ms_rounded: delay_raw.round() as i64,
            match_pct: 95.0,
            accepted: true,
            reject_reason: None,
        }
    }

    #[test]
    fn prioritizes_early_stable_cluster() {
        // Early chunks have -1000, later chunks have -2000
        let chunks = vec![
            make_chunk(1, -1000.0, 10.0),
            make_chunk(2, -1000.0, 20.0),
            make_chunk(3, -1000.0, 30.0),
            make_chunk(4, -1000.0, 40.0),
            make_chunk(5, -1000.0, 50.0),
            make_chunk(6, -2000.0, 60.0),
            make_chunk(7, -2000.0, 70.0),
            make_chunk(8, -2000.0, 80.0),
            make_chunk(9, -2000.0, 90.0),
            make_chunk(10, -2000.0, 100.0),
            make_chunk(11, -2000.0, 110.0),
            make_chunk(12, -2000.0, 120.0),
        ];

        let mut config = SelectorConfig::default();
        config.early_cluster_window = 10;
        config.early_cluster_threshold = 5;

        let result = ModeEarlySelector.select(&chunks, &config).unwrap();
        // Should prefer -1000 because it's stable in early window
        assert_eq!(result.delay_ms_rounded, -1000);
    }

    #[test]
    fn falls_back_to_clustered_if_no_early_stable() {
        // No cluster meets early threshold
        let chunks = vec![
            make_chunk(1, -100.0, 10.0),
            make_chunk(2, -200.0, 20.0),
            make_chunk(3, -300.0, 30.0),
            make_chunk(4, -1000.0, 40.0),
            make_chunk(5, -1000.0, 50.0),
            make_chunk(6, -1000.0, 60.0),
        ];

        let mut config = SelectorConfig::default();
        config.early_cluster_window = 3;
        config.early_cluster_threshold = 3; // None in first 3 meet this

        let result = ModeEarlySelector.select(&chunks, &config).unwrap();
        // Should fall back and pick -1000 as mode
        assert_eq!(result.delay_ms_rounded, -1000);
        assert!(result.method_name.contains("fallback"));
    }
}
