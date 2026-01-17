// src/correction/edl.rs
// Edit Decision List generation for stepping audio correction

use crate::analysis::ChunkResult;

/// Audio segment for EDL (Edit Decision List)
/// Represents a time region with a specific delay
#[derive(Debug, Clone, PartialEq)]
pub struct AudioSegment {
    pub start_s: f64,
    pub end_s: f64,
    pub delay_ms: i32,
    pub delay_raw: f64,
    pub drift_rate_ms_s: f64,
}

impl AudioSegment {
    pub fn new(start_s: f64, end_s: f64, delay_ms: i32) -> Self {
        AudioSegment {
            start_s,
            end_s,
            delay_ms,
            delay_raw: delay_ms as f64,
            drift_rate_ms_s: 0.0,
        }
    }

    pub fn with_raw_delay(start_s: f64, end_s: f64, delay_ms: i32, delay_raw: f64) -> Self {
        AudioSegment {
            start_s,
            end_s,
            delay_ms,
            delay_raw,
            drift_rate_ms_s: 0.0,
        }
    }

    pub fn with_drift(
        start_s: f64,
        end_s: f64,
        delay_ms: i32,
        delay_raw: f64,
        drift_rate_ms_s: f64,
    ) -> Self {
        AudioSegment {
            start_s,
            end_s,
            delay_ms,
            delay_raw,
            drift_rate_ms_s,
        }
    }
}

/// Configuration for EDL generation
#[derive(Debug, Clone)]
pub struct EdlConfig {
    /// Tolerance for grouping consecutive chunks by delay (default: 50ms)
    pub segment_tolerance_ms: i32,
}

impl Default for EdlConfig {
    fn default() -> Self {
        EdlConfig {
            segment_tolerance_ms: 50,
        }
    }
}

/// Cluster filtering information from diagnosis
#[derive(Debug, Clone)]
pub struct ClusterFilterInfo {
    pub correction_mode: String,
    pub invalid_time_ranges: Vec<(f64, f64)>,
}

/// Generate EDL from correlation chunks
/// Used for subtitle adjustment when stepping is detected
///
/// CRITICAL PRESERVATION:
/// - Groups consecutive chunks by delay (within tolerance)
/// - Filters invalid clusters if provided
/// - Returns list of AudioSegment objects
pub fn generate_edl_from_correlation(
    chunks: &[ChunkResult],
    config: &EdlConfig,
    filter_info: Option<&ClusterFilterInfo>,
) -> Vec<AudioSegment> {
    // Filter for accepted chunks
    let mut accepted: Vec<&ChunkResult> = chunks.iter()
        .filter(|c| c.accepted)
        .collect();

    if accepted.is_empty() {
        return Vec::new();
    }

    // Apply cluster filtering if provided
    if let Some(filter) = filter_info {
        if filter.correction_mode == "filtered" && !filter.invalid_time_ranges.is_empty() {
            let original_count = accepted.len();

            // Filter out chunks in invalid time ranges
            accepted.retain(|chunk| {
                let chunk_time = chunk.start_time_s;
                !filter.invalid_time_ranges.iter().any(|(start, end)| {
                    chunk_time >= *start && chunk_time <= *end
                })
            });

            let filtered_count = original_count - accepted.len();
            if filtered_count > 0 {
                // In production, this would log via runner
                // For now, this is just logic
            }

            if accepted.is_empty() {
                return Vec::new();
            }
        }
    }

    // Group consecutive chunks by delay (within tolerance)
    let mut edl = Vec::new();
    let first_chunk = accepted[0];
    let mut current_delay_ms = first_chunk.delay_ms;
    let mut current_delay_raw = first_chunk.raw_delay_ms;

    // Add initial segment at time 0
    edl.push(AudioSegment::with_raw_delay(
        0.0,
        0.0,
        current_delay_ms,
        current_delay_raw,
    ));

    // Process remaining chunks
    for chunk in &accepted[1..] {
        let delay_diff = (chunk.delay_ms - current_delay_ms).abs();

        if delay_diff > config.segment_tolerance_ms {
            // Delay change detected - add new segment
            let boundary_time_s = chunk.start_time_s;
            current_delay_ms = chunk.delay_ms;
            current_delay_raw = chunk.raw_delay_ms;

            edl.push(AudioSegment::with_raw_delay(
                boundary_time_s,
                boundary_time_s,
                current_delay_ms,
                current_delay_raw,
            ));
        }
    }

    edl
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_chunk(delay_ms: i32, raw_delay_ms: f64, start_time_s: f64, accepted: bool) -> ChunkResult {
        ChunkResult {
            delay_ms,
            raw_delay_ms,
            confidence: if accepted { 50.0 } else { 0.0 },
            start_time_s,
            accepted,
        }
    }

    #[test]
    fn test_edl_generation_uniform() {
        let chunks = vec![
            make_chunk(100, 100.1, 0.0, true),
            make_chunk(100, 100.2, 15.0, true),
            make_chunk(101, 101.0, 30.0, true),
            make_chunk(100, 100.3, 45.0, true),
        ];

        let config = EdlConfig::default();
        let edl = generate_edl_from_correlation(&chunks, &config, None);

        // Should have single segment since all delays are within 50ms tolerance
        assert_eq!(edl.len(), 1);
        assert_eq!(edl[0].delay_ms, 100);
        assert_eq!(edl[0].start_s, 0.0);
    }

    #[test]
    fn test_edl_generation_stepping() {
        let chunks = vec![
            make_chunk(100, 100.1, 0.0, true),
            make_chunk(100, 100.2, 15.0, true),
            make_chunk(100, 100.3, 30.0, true),
            make_chunk(200, 200.1, 45.0, true),  // Big jump
            make_chunk(200, 200.2, 60.0, true),
            make_chunk(200, 200.3, 75.0, true),
        ];

        let config = EdlConfig::default();
        let edl = generate_edl_from_correlation(&chunks, &config, None);

        // Should have 2 segments
        assert_eq!(edl.len(), 2);
        assert_eq!(edl[0].delay_ms, 100);
        assert_eq!(edl[0].start_s, 0.0);
        assert_eq!(edl[1].delay_ms, 200);
        assert_eq!(edl[1].start_s, 45.0);
    }

    #[test]
    fn test_edl_generation_with_filter() {
        let chunks = vec![
            make_chunk(100, 100.1, 0.0, true),
            make_chunk(100, 100.2, 15.0, true),
            make_chunk(50, 50.1, 30.0, true),  // Invalid cluster
            make_chunk(50, 50.2, 45.0, true),  // Invalid cluster
            make_chunk(200, 200.1, 60.0, true),
            make_chunk(200, 200.2, 75.0, true),
        ];

        let config = EdlConfig::default();
        let filter = ClusterFilterInfo {
            correction_mode: "filtered".to_string(),
            invalid_time_ranges: vec![(30.0, 50.0)],
        };
        let edl = generate_edl_from_correlation(&chunks, &config, Some(&filter));

        // Should have 2 segments, excluding the filtered chunks
        assert_eq!(edl.len(), 2);
        assert_eq!(edl[0].delay_ms, 100);
        assert_eq!(edl[1].delay_ms, 200);
        assert_eq!(edl[1].start_s, 60.0);
    }

    #[test]
    fn test_edl_empty_chunks() {
        let chunks: Vec<ChunkResult> = vec![];
        let config = EdlConfig::default();
        let edl = generate_edl_from_correlation(&chunks, &config, None);
        assert!(edl.is_empty());
    }

    #[test]
    fn test_edl_no_accepted_chunks() {
        let chunks = vec![
            make_chunk(100, 100.1, 0.0, false),
            make_chunk(100, 100.2, 15.0, false),
        ];
        let config = EdlConfig::default();
        let edl = generate_edl_from_correlation(&chunks, &config, None);
        assert!(edl.is_empty());
    }
}
