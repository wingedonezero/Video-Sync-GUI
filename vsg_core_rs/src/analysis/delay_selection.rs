// src/analysis/delay_selection.rs
// Delay selection strategies for choosing final delay from correlation results

use super::correlation::ChunkResult;
use std::collections::HashMap;

/// Delay selection mode enum
#[derive(Debug, Clone, Copy)]
pub enum DelaySelectionMode {
    MostCommon,      // Mode of rounded delays
    ModeClustered,   // Most common ±1ms cluster
    Average,         // Mean of raw delays
    FirstStable,     // First N consecutive with same delay
}

/// Configuration for delay selection
#[derive(Debug, Clone)]
pub struct DelaySelectionConfig {
    pub min_accepted_chunks: usize,
    pub first_stable_min_chunks: usize,
    pub first_stable_skip_unstable: bool,
}

impl Default for DelaySelectionConfig {
    fn default() -> Self {
        DelaySelectionConfig {
            min_accepted_chunks: 3,
            first_stable_min_chunks: 3,
            first_stable_skip_unstable: true,
        }
    }
}

/// Segment of consecutive chunks with similar delays
#[derive(Debug, Clone)]
struct Segment {
    delay: i32,           // Rounded delay value
    raw_delays: Vec<f64>, // All raw delay values in this segment
    count: usize,
    start_time: f64,
}

impl Segment {
    fn raw_average(&self) -> f64 {
        self.raw_delays.iter().sum::<f64>() / self.raw_delays.len() as f64
    }
}

/// Find first stable segment in accepted chunks
/// CRITICAL: Must match Python logic exactly
fn find_first_stable_segment(
    accepted: &[&ChunkResult],
    config: &DelaySelectionConfig,
) -> Option<Segment> {
    if accepted.len() < config.min_accepted_chunks {
        return None;
    }

    // Group consecutive chunks with the same delay (within 1ms tolerance)
    let mut segments = Vec::new();
    let mut current_segment = Segment {
        delay: accepted[0].delay_ms,
        raw_delays: vec![accepted[0].raw_delay_ms],
        count: 1,
        start_time: accepted[0].start_time_s,
    };

    for chunk in &accepted[1..] {
        if (chunk.delay_ms - current_segment.delay).abs() <= 1 {
            // Same segment continues
            current_segment.count += 1;
            current_segment.raw_delays.push(chunk.raw_delay_ms);
        } else {
            // New segment starts
            segments.push(current_segment.clone());
            current_segment = Segment {
                delay: chunk.delay_ms,
                raw_delays: vec![chunk.raw_delay_ms],
                count: 1,
                start_time: chunk.start_time_s,
            };
        }
    }

    // Don't forget the last segment
    segments.push(current_segment);

    // Find the first stable segment based on configuration
    if config.first_stable_skip_unstable {
        // Skip segments that don't meet minimum chunk count
        segments.into_iter()
            .find(|s| s.count >= config.first_stable_min_chunks)
    } else {
        // Use the first segment regardless of chunk count
        segments.into_iter().next()
    }
}

/// Select final delay using Most Common mode
fn select_most_common(accepted: &[&ChunkResult]) -> Option<(i32, f64)> {
    if accepted.is_empty() {
        return None;
    }

    let mut counts = HashMap::new();
    for chunk in accepted {
        *counts.entry(chunk.delay_ms).or_insert(0) += 1;
    }

    let mode_delay = counts.into_iter()
        .max_by_key(|(_, count)| *count)
        .map(|(delay, _)| delay)?;

    // Find raw delay for first chunk matching the mode
    let raw_delay = accepted.iter()
        .find(|c| c.delay_ms == mode_delay)
        .map(|c| c.raw_delay_ms)?;

    Some((mode_delay, raw_delay))
}

/// Select final delay using Mode Clustered mode
/// CRITICAL: Find most common, then average ±1ms cluster
fn select_mode_clustered(accepted: &[&ChunkResult]) -> Option<(i32, f64)> {
    if accepted.is_empty() {
        return None;
    }

    // Find most common rounded delay
    let mut counts = HashMap::new();
    for chunk in accepted {
        *counts.entry(chunk.delay_ms).or_insert(0) += 1;
    }

    let mode_winner = counts.into_iter()
        .max_by_key(|(_, count)| *count)
        .map(|(delay, _)| delay)?;

    // Collect raw values from chunks within ±1ms of the mode
    let cluster_raw_values: Vec<f64> = accepted.iter()
        .filter(|c| (c.delay_ms - mode_winner).abs() <= 1)
        .map(|c| c.raw_delay_ms)
        .collect();

    if cluster_raw_values.is_empty() {
        return None;
    }

    // Average the clustered raw values
    let raw_avg = cluster_raw_values.iter().sum::<f64>() / cluster_raw_values.len() as f64;
    let final_delay = raw_avg.round() as i32;

    Some((final_delay, raw_avg))
}

/// Select final delay using Average mode
/// CRITICAL: Average RAW values, then round once
fn select_average(accepted: &[&ChunkResult]) -> Option<(i32, f64)> {
    if accepted.is_empty() {
        return None;
    }

    let raw_avg = accepted.iter()
        .map(|c| c.raw_delay_ms)
        .sum::<f64>() / accepted.len() as f64;

    let final_delay = raw_avg.round() as i32;

    Some((final_delay, raw_avg))
}

/// Select final delay using First Stable mode
/// CRITICAL: Returns average of RAW delays in first stable segment
fn select_first_stable(
    accepted: &[&ChunkResult],
    config: &DelaySelectionConfig,
) -> Option<(i32, f64)> {
    let segment = find_first_stable_segment(accepted, config)?;

    // CRITICAL: Round the raw average, don't use first chunk's delay
    let raw_avg = segment.raw_average();
    let rounded_avg = raw_avg.round() as i32;

    Some((rounded_avg, raw_avg))
}

/// Select final delay from correlation results using configured mode
/// Returns (rounded_delay_ms, raw_delay_ms)
pub fn select_final_delay(
    results: &[ChunkResult],
    mode: DelaySelectionMode,
    config: &DelaySelectionConfig,
) -> Option<(i32, f64)> {
    // Filter for accepted chunks
    let accepted: Vec<&ChunkResult> = results.iter()
        .filter(|r| r.accepted)
        .collect();

    if accepted.len() < config.min_accepted_chunks {
        return None;
    }

    match mode {
        DelaySelectionMode::MostCommon => select_most_common(&accepted),
        DelaySelectionMode::ModeClustered => select_mode_clustered(&accepted),
        DelaySelectionMode::Average => select_average(&accepted),
        DelaySelectionMode::FirstStable => select_first_stable(&accepted, config),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_chunk(delay_ms: i32, raw_delay_ms: f64, accepted: bool) -> ChunkResult {
        ChunkResult {
            delay_ms,
            raw_delay_ms,
            confidence: if accepted { 50.0 } else { 0.0 },
            start_time_s: 0.0,
            accepted,
        }
    }

    #[test]
    fn test_most_common() {
        let results = vec![
            make_chunk(100, 100.1, true),
            make_chunk(100, 100.2, true),
            make_chunk(100, 100.3, true),
            make_chunk(105, 105.1, true),
        ];

        let config = DelaySelectionConfig::default();
        let (delay, _raw) = select_final_delay(&results, DelaySelectionMode::MostCommon, &config).unwrap();
        assert_eq!(delay, 100);
    }

    #[test]
    fn test_average() {
        let results = vec![
            make_chunk(100, 100.0, true),
            make_chunk(101, 101.0, true),
            make_chunk(102, 102.0, true),
        ];

        let config = DelaySelectionConfig::default();
        let (delay, raw) = select_final_delay(&results, DelaySelectionMode::Average, &config).unwrap();
        assert_eq!(delay, 101); // round(101.0)
        assert!((raw - 101.0).abs() < 0.01);
    }

    #[test]
    fn test_mode_clustered() {
        let results = vec![
            make_chunk(100, 100.1, true),
            make_chunk(100, 100.2, true),
            make_chunk(101, 101.3, true), // Within ±1ms cluster
            make_chunk(105, 105.1, true), // Outside cluster
        ];

        let config = DelaySelectionConfig::default();
        let (delay, raw) = select_final_delay(&results, DelaySelectionMode::ModeClustered, &config).unwrap();
        // Should average 100.1, 100.2, 101.3 = 100.533... → round to 101
        assert_eq!(delay, 101);
    }

    #[test]
    fn test_first_stable() {
        let results = vec![
            make_chunk(100, 100.1, true),
            make_chunk(100, 100.2, true),
            make_chunk(100, 100.3, true), // First stable segment (3 chunks)
            make_chunk(200, 200.1, true),
            make_chunk(200, 200.2, true),
            make_chunk(200, 200.3, true),
        ];

        let config = DelaySelectionConfig::default();
        let (delay, raw) = select_final_delay(&results, DelaySelectionMode::FirstStable, &config).unwrap();
        // First stable: avg(100.1, 100.2, 100.3) = 100.2
        assert_eq!(delay, 100);
        assert!((raw - 100.2).abs() < 0.01);
    }
}
