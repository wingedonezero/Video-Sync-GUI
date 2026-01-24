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

/// Result of correlating two audio chunks.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CorrelationResult {
    /// Delay in samples (positive = second source is ahead).
    pub delay_samples: f64,
    /// Delay in milliseconds.
    pub delay_ms: f64,
    /// Correlation peak value (0.0 - 1.0).
    pub correlation_peak: f64,
    /// Confidence score (0.0 - 1.0).
    pub confidence: f64,
    /// Whether peak fitting was applied.
    pub peak_fitted: bool,
}

impl CorrelationResult {
    /// Create a new correlation result.
    pub fn new(delay_samples: f64, sample_rate: u32, correlation_peak: f64) -> Self {
        let delay_ms = (delay_samples / sample_rate as f64) * 1000.0;
        Self {
            delay_samples,
            delay_ms,
            correlation_peak,
            confidence: correlation_peak.abs(), // Simple confidence = peak magnitude
            peak_fitted: false,
        }
    }

    /// Mark this result as having peak fitting applied.
    pub fn with_peak_fitting(mut self) -> Self {
        self.peak_fitted = true;
        self
    }

    /// Set the confidence score.
    pub fn with_confidence(mut self, confidence: f64) -> Self {
        self.confidence = confidence;
        self
    }
}

/// Result of analyzing a single chunk pair.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkResult {
    /// Chunk index (0-based).
    pub chunk_index: usize,
    /// Start time of the chunk (seconds).
    pub chunk_start_secs: f64,
    /// Correlation result for this chunk.
    pub correlation: CorrelationResult,
    /// Whether this chunk's result is considered valid.
    pub valid: bool,
    /// Reason for invalid result (if any).
    pub invalid_reason: Option<String>,
}

impl ChunkResult {
    /// Create a new valid chunk result.
    pub fn new(chunk_index: usize, chunk_start_secs: f64, correlation: CorrelationResult) -> Self {
        Self {
            chunk_index,
            chunk_start_secs,
            correlation,
            valid: true,
            invalid_reason: None,
        }
    }

    /// Create an invalid chunk result.
    pub fn invalid(chunk_index: usize, chunk_start_secs: f64, reason: impl Into<String>) -> Self {
        Self {
            chunk_index,
            chunk_start_secs,
            correlation: CorrelationResult {
                delay_samples: 0.0,
                delay_ms: 0.0,
                correlation_peak: 0.0,
                confidence: 0.0,
                peak_fitted: false,
            },
            valid: false,
            invalid_reason: Some(reason.into()),
        }
    }
}

/// Final analysis result for a source pair.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceAnalysisResult {
    /// Name of the source being analyzed (e.g., "Source 2").
    pub source_name: String,
    /// Final calculated delay in milliseconds.
    pub delay_ms: f64,
    /// Overall confidence score (0.0 - 1.0).
    pub confidence: f64,
    /// Number of valid chunks used.
    pub valid_chunks: usize,
    /// Total number of chunks analyzed.
    pub total_chunks: usize,
    /// Individual chunk results.
    pub chunk_results: Vec<ChunkResult>,
    /// Whether drift was detected (inconsistent delays across chunks).
    pub drift_detected: bool,
    /// Analysis method used.
    pub method: String,
}

impl SourceAnalysisResult {
    /// Calculate the match percentage (valid chunks / total chunks).
    pub fn match_percentage(&self) -> f64 {
        if self.total_chunks == 0 {
            0.0
        } else {
            (self.valid_chunks as f64 / self.total_chunks as f64) * 100.0
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
        let result = CorrelationResult::new(48.0, 48000, 0.95);
        assert!((result.delay_ms - 1.0).abs() < 0.001); // 48 samples at 48kHz = 1ms
    }
}
