//! First Stable delay selector.
//!
//! Finds consecutive chunks with the same rounded delay (±tolerance)
//! and returns the first segment meeting the minimum chunk threshold.
//!
//! Critical for handling files with stepping (sync changes mid-file).

use super::{DelaySelector, SelectorConfig};
use crate::analysis::types::{ChunkResult, DelaySelection};

/// First Stable selector: uses first stable segment's delay.
pub struct FirstStableSelector;

/// A segment of consecutive chunks with consistent delay.
#[derive(Debug)]
#[allow(dead_code)]
struct Segment {
    delay_rounded: i64,
    start_index: usize,
    start_time: f64,
    raw_delays: Vec<f64>,
}

impl Segment {
    fn new(chunk: &ChunkResult, index: usize) -> Self {
        Self {
            delay_rounded: chunk.delay_ms_rounded,
            start_index: index,
            start_time: chunk.chunk_start_secs,
            raw_delays: vec![chunk.delay_ms_raw],
        }
    }

    fn add(&mut self, chunk: &ChunkResult) {
        self.raw_delays.push(chunk.delay_ms_raw);
    }

    fn len(&self) -> usize {
        self.raw_delays.len()
    }

    fn raw_avg(&self) -> f64 {
        self.raw_delays.iter().sum::<f64>() / self.raw_delays.len() as f64
    }

    fn matches(&self, delay_rounded: i64, tolerance: i64) -> bool {
        (self.delay_rounded - delay_rounded).abs() <= tolerance
    }
}

impl DelaySelector for FirstStableSelector {
    fn name(&self) -> &'static str {
        "first_stable"
    }

    fn select(&self, chunks: &[ChunkResult], config: &SelectorConfig) -> Option<DelaySelection> {
        if chunks.len() < config.min_accepted_chunks {
            return None;
        }

        let min_segment_size = config.first_stable_min_chunks;
        let tolerance = config.cluster_tolerance_ms;

        // Build segments of consecutive chunks with same rounded delay
        let mut segments: Vec<Segment> = Vec::new();
        let mut current_segment: Option<Segment> = None;

        for (i, chunk) in chunks.iter().enumerate() {
            match current_segment.take() {
                Some(mut seg) if seg.matches(chunk.delay_ms_rounded, tolerance) => {
                    // Continue current segment
                    seg.add(chunk);
                    current_segment = Some(seg);
                }
                Some(seg) => {
                    // End current segment, start new one
                    segments.push(seg);
                    current_segment = Some(Segment::new(chunk, i));
                }
                None => {
                    // Start first segment
                    current_segment = Some(Segment::new(chunk, i));
                }
            }
        }

        // Don't forget the last segment
        if let Some(seg) = current_segment {
            segments.push(seg);
        }

        // Find first segment meeting minimum size
        let qualifying_segment = if config.first_stable_skip_unstable {
            // Skip segments below threshold, find first that qualifies
            segments.into_iter().find(|s| s.len() >= min_segment_size)
        } else {
            // Just use the first segment if it meets threshold, otherwise first anyway
            let first = segments.into_iter().next()?;
            if first.len() >= min_segment_size {
                Some(first)
            } else {
                // Use it anyway (no skip mode)
                Some(first)
            }
        };

        qualifying_segment.map(|seg| DelaySelection {
            delay_ms_raw: seg.raw_avg(),
            delay_ms_rounded: seg.delay_rounded,
            method_name: self.name().to_string(),
            chunks_used: seg.len(),
            details: Some(format!(
                "{} chunks at {:+}ms (raw avg: {:.3}ms, starting at {:.1}s)",
                seg.len(),
                seg.delay_rounded,
                seg.raw_avg(),
                seg.start_time
            )),
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
    fn finds_first_stable_segment() {
        // Simulate stepping: 2 chunks at -500, then 5 chunks at -1000
        let chunks = vec![
            make_chunk(1, -500.0, 10.0),
            make_chunk(2, -500.5, 20.0),
            make_chunk(3, -1000.0, 30.0),
            make_chunk(4, -1000.2, 40.0),
            make_chunk(5, -1000.1, 50.0),
            make_chunk(6, -1000.3, 60.0),
            make_chunk(7, -1000.0, 70.0),
        ];

        let mut config = SelectorConfig::default();
        config.first_stable_min_chunks = 3;
        config.first_stable_skip_unstable = true;

        let result = FirstStableSelector.select(&chunks, &config).unwrap();
        // Should skip the first 2-chunk segment and use the 5-chunk segment
        assert_eq!(result.delay_ms_rounded, -1000);
        assert_eq!(result.chunks_used, 5);
    }

    #[test]
    fn uses_first_segment_when_not_skipping() {
        let chunks = vec![
            make_chunk(1, -500.0, 10.0),
            make_chunk(2, -500.5, 20.0),
            make_chunk(3, -1000.0, 30.0),
            make_chunk(4, -1000.2, 40.0),
            make_chunk(5, -1000.1, 50.0),
        ];

        let mut config = SelectorConfig::default();
        config.first_stable_min_chunks = 3;
        config.first_stable_skip_unstable = false;

        let result = FirstStableSelector.select(&chunks, &config).unwrap();
        // Should use first segment even though it's only 2 chunks
        assert_eq!(result.delay_ms_rounded, -500);
    }

    #[test]
    fn handles_tolerance() {
        // All should be in same segment due to ±1ms tolerance
        let chunks = vec![
            make_chunk(1, -1000.4, 10.0), // rounds to -1000
            make_chunk(2, -1001.4, 20.0), // rounds to -1001, but within ±1 of -1000
            make_chunk(3, -1000.6, 30.0), // rounds to -1001
        ];

        let config = SelectorConfig::default();
        let result = FirstStableSelector.select(&chunks, &config).unwrap();
        assert_eq!(result.chunks_used, 3); // All in one segment
    }
}
