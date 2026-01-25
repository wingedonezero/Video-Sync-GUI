//! Core types for audio analysis.

use serde::{Deserialize, Serialize};

/// Audio data extracted from a source file.
#[derive(Debug, Clone)]
pub struct AudioData {
    /// Audio samples as f64 (mono, interleaved if originally multi-channel).
    pub samples: Vec<f64>,
    /// Sample rate in Hz.
    pub sample_rate: u32,
    /// Duration in seconds.
    pub duration_secs: f64,
}

impl AudioData {
    /// Create new audio data from samples.
    pub fn new(samples: Vec<f64>, sample_rate: u32) -> Self {
        let duration_secs = samples.len() as f64 / sample_rate as f64;
        Self {
            samples,
            sample_rate,
            duration_secs,
        }
    }

    /// Get the number of samples.
    pub fn len(&self) -> usize {
        self.samples.len()
    }

    /// Check if audio data is empty.
    pub fn is_empty(&self) -> bool {
        self.samples.is_empty()
    }

    /// Get the duration in seconds.
    pub fn duration(&self) -> f64 {
        self.duration_secs
    }

    /// Extract a chunk of audio starting at the given time offset.
    ///
    /// Returns None if the chunk would extend past the end of the audio.
    pub fn extract_chunk(&self, start_secs: f64, duration_secs: f64) -> Option<AudioChunk> {
        let start_sample = (start_secs * self.sample_rate as f64) as usize;
        let num_samples = (duration_secs * self.sample_rate as f64) as usize;
        let end_sample = start_sample + num_samples;

        if end_sample > self.samples.len() {
            return None;
        }

        Some(AudioChunk {
            samples: self.samples[start_sample..end_sample].to_vec(),
            sample_rate: self.sample_rate,
            start_time_secs: start_secs,
            duration_secs,
        })
    }
}

/// A chunk of audio for correlation analysis.
#[derive(Debug, Clone)]
pub struct AudioChunk {
    /// Audio samples for this chunk.
    pub samples: Vec<f64>,
    /// Sample rate in Hz.
    pub sample_rate: u32,
    /// Start time of chunk in the source audio (seconds).
    pub start_time_secs: f64,
    /// Duration of chunk in seconds.
    pub duration_secs: f64,
}

impl AudioChunk {
    /// Get the number of samples.
    pub fn len(&self) -> usize {
        self.samples.len()
    }

    /// Check if chunk is empty.
    pub fn is_empty(&self) -> bool {
        self.samples.is_empty()
    }
}

/// Result of correlating two audio chunks (internal calculation result).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CorrelationResult {
    /// Delay in samples (positive = second source is ahead).
    pub delay_samples: f64,
    /// Raw delay in milliseconds (full precision).
    pub delay_ms_raw: f64,
    /// Rounded delay in milliseconds (for mode calculations, mkvmerge).
    pub delay_ms_rounded: i64,
    /// Match percentage (0-100 scale, like Python).
    pub match_pct: f64,
    /// Whether peak fitting was applied.
    pub peak_fitted: bool,
}

impl CorrelationResult {
    /// Create a new correlation result.
    pub fn new(delay_samples: f64, sample_rate: u32, match_pct: f64) -> Self {
        let delay_ms_raw = (delay_samples / sample_rate as f64) * 1000.0;
        let delay_ms_rounded = delay_ms_raw.round() as i64;
        Self {
            delay_samples,
            delay_ms_raw,
            delay_ms_rounded,
            match_pct,
            peak_fitted: false,
        }
    }

    /// Mark this result as having peak fitting applied.
    pub fn with_peak_fitting(mut self) -> Self {
        self.peak_fitted = true;
        self
    }
}

/// Result of analyzing a single chunk pair.
///
/// Stores all data needed for delay selection and later processing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkResult {
    /// Chunk index (1-based for display, matches Python).
    pub chunk_index: usize,
    /// Start time of the chunk in seconds.
    pub chunk_start_secs: f64,
    /// Raw delay in milliseconds (full precision for averaging).
    pub delay_ms_raw: f64,
    /// Rounded delay in milliseconds (for mode calculations).
    pub delay_ms_rounded: i64,
    /// Match percentage (0-100 scale).
    pub match_pct: f64,
    /// Whether this chunk passed the match threshold.
    pub accepted: bool,
    /// Reason for rejection (if not accepted).
    pub reject_reason: Option<String>,
}

impl ChunkResult {
    /// Create a new chunk result from correlation output.
    pub fn new(
        chunk_index: usize,
        chunk_start_secs: f64,
        correlation: CorrelationResult,
        min_match_pct: f64,
    ) -> Self {
        let accepted = correlation.match_pct >= min_match_pct;
        let reject_reason = if accepted {
            None
        } else {
            Some(format!("below {:.1}%", min_match_pct))
        };

        Self {
            chunk_index,
            chunk_start_secs,
            delay_ms_raw: correlation.delay_ms_raw,
            delay_ms_rounded: correlation.delay_ms_rounded,
            match_pct: correlation.match_pct,
            accepted,
            reject_reason,
        }
    }

    /// Create a rejected chunk result (e.g., extraction failed).
    pub fn rejected(
        chunk_index: usize,
        chunk_start_secs: f64,
        reason: impl Into<String>,
    ) -> Self {
        Self {
            chunk_index,
            chunk_start_secs,
            delay_ms_raw: 0.0,
            delay_ms_rounded: 0,
            match_pct: 0.0,
            accepted: false,
            reject_reason: Some(reason.into()),
        }
    }

    /// Get the status string for logging (ACCEPTED or REJECTED with reason).
    pub fn status_str(&self) -> String {
        if self.accepted {
            "ACCEPTED".to_string()
        } else {
            format!(
                "REJECTED ({})",
                self.reject_reason.as_deref().unwrap_or("unknown")
            )
        }
    }
}

/// Result of delay selection from multiple chunks.
///
/// Produced by a DelaySelector after analyzing all accepted chunks.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DelaySelection {
    /// Raw delay in milliseconds (full precision).
    pub delay_ms_raw: f64,
    /// Rounded delay in milliseconds.
    pub delay_ms_rounded: i64,
    /// Name of the selection method used.
    pub method_name: String,
    /// Number of chunks used in calculation.
    pub chunks_used: usize,
    /// Additional details for logging (e.g., "starting at 71.0s").
    pub details: Option<String>,
}

impl DelaySelection {
    /// Create a new delay selection result.
    pub fn new(
        delay_ms_raw: f64,
        method_name: impl Into<String>,
        chunks_used: usize,
    ) -> Self {
        Self {
            delay_ms_raw,
            delay_ms_rounded: delay_ms_raw.round() as i64,
            method_name: method_name.into(),
            chunks_used,
            details: None,
        }
    }

    /// Add details for logging.
    pub fn with_details(mut self, details: impl Into<String>) -> Self {
        self.details = Some(details.into());
        self
    }
}

/// Final analysis result for a source pair.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceAnalysisResult {
    /// Name of the source being analyzed (e.g., "Source 2").
    pub source_name: String,
    /// Selected delay result.
    pub delay: DelaySelection,
    /// Average match percentage of accepted chunks.
    pub avg_match_pct: f64,
    /// Number of accepted chunks.
    pub accepted_chunks: usize,
    /// Total number of chunks analyzed.
    pub total_chunks: usize,
    /// Individual chunk results (all chunks, for drift analysis, stepping, etc.).
    pub chunk_results: Vec<ChunkResult>,
    /// Whether drift was detected (inconsistent delays across chunks).
    pub drift_detected: bool,
    /// Correlation method used (e.g., "SCC", "GCC-PHAT").
    pub correlation_method: String,
}

impl SourceAnalysisResult {
    /// Get the raw delay in milliseconds.
    pub fn delay_ms_raw(&self) -> f64 {
        self.delay.delay_ms_raw
    }

    /// Get the rounded delay in milliseconds.
    pub fn delay_ms_rounded(&self) -> i64 {
        self.delay.delay_ms_rounded
    }

    /// Calculate the acceptance rate (accepted / total).
    pub fn acceptance_rate(&self) -> f64 {
        if self.total_chunks == 0 {
            0.0
        } else {
            (self.accepted_chunks as f64 / self.total_chunks as f64) * 100.0
        }
    }
}

/// Error types for analysis operations.
#[derive(Debug, thiserror::Error)]
pub enum AnalysisError {
    /// FFmpeg execution failed.
    #[error("FFmpeg error: {0}")]
    FfmpegError(String),

    /// Audio extraction failed.
    #[error("Audio extraction failed: {0}")]
    ExtractionError(String),

    /// Correlation failed.
    #[error("Correlation failed: {0}")]
    CorrelationError(String),

    /// Invalid audio data.
    #[error("Invalid audio data: {0}")]
    InvalidAudio(String),

    /// IO error.
    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),

    /// Source file not found.
    #[error("Source file not found: {0}")]
    SourceNotFound(String),

    /// Insufficient valid chunks for analysis.
    #[error("Insufficient valid chunks: got {valid} of {required} required")]
    InsufficientChunks { valid: usize, required: usize },
}

/// Type alias for analysis results.
pub type AnalysisResult<T> = Result<T, AnalysisError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn audio_data_extracts_chunks() {
        // 1 second of audio at 1000 Hz
        let samples: Vec<f64> = (0..1000).map(|i| i as f64 / 1000.0).collect();
        let audio = AudioData::new(samples, 1000);

        // Extract 0.5 second chunk starting at 0.25 seconds
        let chunk = audio.extract_chunk(0.25, 0.5).unwrap();
        assert_eq!(chunk.samples.len(), 500);
        assert!((chunk.samples[0] - 0.25).abs() < 0.01);
    }

    #[test]
    fn audio_data_returns_none_for_out_of_bounds() {
        let samples: Vec<f64> = (0..1000).map(|_| 0.0).collect();
        let audio = AudioData::new(samples, 1000);

        // Try to extract chunk that extends past end
        assert!(audio.extract_chunk(0.8, 0.5).is_none());
    }

    #[test]
    fn correlation_result_calculates_delay_ms() {
        let result = CorrelationResult::new(48.0, 48000, 95.0);
        assert!((result.delay_ms_raw - 1.0).abs() < 0.001); // 48 samples at 48kHz = 1ms
        assert_eq!(result.delay_ms_rounded, 1);
        assert!((result.match_pct - 95.0).abs() < 0.001);
    }

    #[test]
    fn chunk_result_accepts_above_threshold() {
        let corr = CorrelationResult::new(48.0, 48000, 95.0);
        let chunk = ChunkResult::new(1, 10.0, corr, 5.0);
        assert!(chunk.accepted);
        assert!(chunk.reject_reason.is_none());
    }

    #[test]
    fn chunk_result_rejects_below_threshold() {
        let corr = CorrelationResult::new(48.0, 48000, 3.0);
        let chunk = ChunkResult::new(1, 10.0, corr, 5.0);
        assert!(!chunk.accepted);
        assert!(chunk.reject_reason.is_some());
    }

    #[test]
    fn delay_selection_rounds_correctly() {
        let sel = DelaySelection::new(-1000.979, "mode", 10);
        assert_eq!(sel.delay_ms_rounded, -1001);
    }
}
