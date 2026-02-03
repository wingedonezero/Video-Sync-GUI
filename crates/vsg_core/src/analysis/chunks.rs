//! Chunk position calculation for audio analysis.
//!
//! Pure functions for calculating where to extract audio chunks
//! for correlation analysis.

use serde::{Deserialize, Serialize};

/// Configuration for chunk positioning.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkConfig {
    /// Number of chunks to analyze.
    pub chunk_count: usize,
    /// Duration of each chunk in seconds.
    pub chunk_duration: f64,
    /// Start position as percentage (0-100).
    pub scan_start_pct: f64,
    /// End position as percentage (0-100).
    pub scan_end_pct: f64,
}

impl Default for ChunkConfig {
    fn default() -> Self {
        Self {
            chunk_count: 10,
            chunk_duration: 15.0,
            scan_start_pct: 5.0,
            scan_end_pct: 95.0,
        }
    }
}

impl ChunkConfig {
    /// Create from analysis settings.
    pub fn from_settings(
        chunk_count: u32,
        chunk_duration: u32,
        scan_start_pct: f64,
        scan_end_pct: f64,
    ) -> Self {
        Self {
            chunk_count: chunk_count as usize,
            chunk_duration: chunk_duration as f64,
            scan_start_pct,
            scan_end_pct,
        }
    }
}

/// Calculate evenly-distributed chunk start positions.
///
/// Pure function - no I/O, deterministic output.
///
/// # Arguments
/// * `duration` - Total duration in seconds
/// * `config` - Chunk configuration
///
/// # Returns
/// Vector of start times in seconds for each chunk.
/// Returns empty vec if duration is too short for any chunks.
pub fn calculate_chunk_positions(duration: f64, config: &ChunkConfig) -> Vec<f64> {
    let start_time = duration * (config.scan_start_pct / 100.0);
    let end_time = duration * (config.scan_end_pct / 100.0);
    let usable_duration = end_time - start_time - config.chunk_duration;

    if usable_duration <= 0.0 {
        // Not enough room for even one chunk
        return vec![];
    }

    if config.chunk_count <= 1 {
        // Just one chunk in the middle
        return vec![start_time + usable_duration / 2.0];
    }

    // Distribute chunks evenly
    let step = usable_duration / (config.chunk_count - 1) as f64;

    (0..config.chunk_count)
        .map(|i| start_time + (i as f64 * step))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn calculates_positions_for_standard_video() {
        let config = ChunkConfig {
            chunk_count: 10,
            chunk_duration: 15.0,
            scan_start_pct: 5.0,
            scan_end_pct: 95.0,
        };

        // 100 second video
        let positions = calculate_chunk_positions(100.0, &config);

        assert_eq!(positions.len(), 10);

        // First chunk should start around 5% (5 seconds)
        assert!(positions[0] >= 5.0);
        assert!(positions[0] < 10.0);

        // Last chunk should end before 95% (95 seconds)
        let last_end = positions.last().unwrap() + config.chunk_duration;
        assert!(last_end <= 95.0);
    }

    #[test]
    fn handles_short_video() {
        let config = ChunkConfig {
            chunk_count: 10,
            chunk_duration: 15.0,
            scan_start_pct: 5.0,
            scan_end_pct: 95.0,
        };

        // 20 second video - limited room
        let positions = calculate_chunk_positions(20.0, &config);

        // Should still get some positions
        // With 5-95% of 20s = 1s to 19s, usable = 18s - 15s = 3s
        assert!(!positions.is_empty());
    }

    #[test]
    fn returns_empty_for_too_short_video() {
        let config = ChunkConfig {
            chunk_count: 10,
            chunk_duration: 15.0,
            scan_start_pct: 5.0,
            scan_end_pct: 95.0,
        };

        // 10 second video - way too short for 15s chunks
        let positions = calculate_chunk_positions(10.0, &config);

        assert!(positions.is_empty());
    }

    #[test]
    fn single_chunk_goes_in_middle() {
        let config = ChunkConfig {
            chunk_count: 1,
            chunk_duration: 10.0,
            scan_start_pct: 0.0,
            scan_end_pct: 100.0,
        };

        // 100 second video, single chunk
        let positions = calculate_chunk_positions(100.0, &config);

        assert_eq!(positions.len(), 1);
        // Should be in the middle: (100 - 10) / 2 = 45
        assert!((positions[0] - 45.0).abs() < 0.01);
    }
}
