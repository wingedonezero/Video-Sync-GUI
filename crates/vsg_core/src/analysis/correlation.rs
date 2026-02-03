//! Correlation functions for audio sync analysis.
//!
//! Pure functions that correlate audio chunks using various methods.
//! These functions have no side effects and don't do I/O.

use crate::models::FilteringMethod;

use super::filtering::{apply_filter, FilterConfig, FilterType};
use super::methods::CorrelationMethod;
use super::peak_fit::find_and_fit_peak;
use super::types::{AnalysisError, AnalysisResult, AudioChunk, AudioData, ChunkResult};

/// Configuration for chunk correlation.
#[derive(Debug, Clone)]
pub struct CorrelationConfig {
    /// Duration of each chunk in seconds.
    pub chunk_duration: f64,
    /// Minimum match percentage for a chunk to be accepted (0-100).
    pub min_match_pct: f64,
    /// Whether to use peak fitting for sub-sample accuracy.
    pub use_peak_fit: bool,
    /// Sample rate of audio (for peak fitting).
    pub sample_rate: u32,
    /// Filtering method to apply before correlation.
    pub filtering_method: FilteringMethod,
    /// Low cutoff frequency for filtering (Hz).
    pub filter_low_cutoff_hz: f64,
    /// High cutoff frequency for filtering (Hz).
    pub filter_high_cutoff_hz: f64,
}

impl Default for CorrelationConfig {
    fn default() -> Self {
        Self {
            chunk_duration: 15.0,
            min_match_pct: 5.0,
            use_peak_fit: true,
            sample_rate: 48000,
            filtering_method: FilteringMethod::None,
            filter_low_cutoff_hz: 300.0,
            filter_high_cutoff_hz: 3400.0,
        }
    }
}

impl CorrelationConfig {
    /// Get filter config if filtering is enabled.
    pub fn filter_config(&self) -> Option<FilterConfig> {
        if self.filtering_method == FilteringMethod::None {
            return None;
        }

        Some(FilterConfig {
            filter_type: match self.filtering_method {
                FilteringMethod::None => FilterType::None,
                FilteringMethod::LowPass => FilterType::LowPass,
                FilteringMethod::BandPass => FilterType::BandPass,
                FilteringMethod::HighPass => FilterType::HighPass,
            },
            sample_rate: self.sample_rate,
            low_cutoff_hz: self.filter_low_cutoff_hz,
            high_cutoff_hz: self.filter_high_cutoff_hz,
            order: 5,
        })
    }
}

/// Correlate all chunks between two audio sources.
///
/// Pure function - takes audio data and configuration, returns chunk results.
/// No I/O, no logging, no side effects.
///
/// # Arguments
/// * `ref_audio` - Reference audio data (Source 1)
/// * `other_audio` - Other audio data to compare
/// * `chunk_positions` - Start times for each chunk (in seconds)
/// * `method` - Correlation method to use
/// * `config` - Correlation configuration
///
/// # Returns
/// Vector of chunk results, one per position. Failed chunks are marked as rejected.
pub fn correlate_chunks(
    ref_audio: &AudioData,
    other_audio: &AudioData,
    chunk_positions: &[f64],
    method: &dyn CorrelationMethod,
    config: &CorrelationConfig,
) -> Vec<ChunkResult> {
    let filter_config = config.filter_config();

    chunk_positions
        .iter()
        .enumerate()
        .map(|(idx, &start_time)| {
            let chunk_index = idx + 1; // 1-based for display

            match correlate_single_chunk(
                ref_audio,
                other_audio,
                start_time,
                chunk_index,
                method,
                config,
                filter_config.as_ref(),
            ) {
                Ok(result) => result,
                Err(e) => ChunkResult::rejected(chunk_index, start_time, e.to_string()),
            }
        })
        .collect()
}

/// Correlate a single chunk pair from audio data.
///
/// Extracts chunks, applies filtering if configured, and correlates.
fn correlate_single_chunk(
    ref_audio: &AudioData,
    other_audio: &AudioData,
    start_time: f64,
    chunk_index: usize,
    method: &dyn CorrelationMethod,
    config: &CorrelationConfig,
    filter_config: Option<&FilterConfig>,
) -> AnalysisResult<ChunkResult> {
    // Extract chunks from audio data
    let ref_chunk = ref_audio
        .extract_chunk(start_time, config.chunk_duration)
        .ok_or_else(|| {
            AnalysisError::InvalidAudio(format!(
                "Failed to extract reference chunk at {:.2}s (audio length: {:.2}s)",
                start_time,
                ref_audio.duration()
            ))
        })?;

    let other_chunk = other_audio
        .extract_chunk(start_time, config.chunk_duration)
        .ok_or_else(|| {
            AnalysisError::InvalidAudio(format!(
                "Failed to extract other chunk at {:.2}s (audio length: {:.2}s)",
                start_time,
                other_audio.duration()
            ))
        })?;

    // Apply filtering if configured
    let (ref_chunk, other_chunk) = if let Some(fc) = filter_config {
        let ref_filtered = apply_filter(&ref_chunk.samples, fc);
        let other_filtered = apply_filter(&other_chunk.samples, fc);
        (
            ref_chunk.with_filtered_samples(ref_filtered),
            other_chunk.with_filtered_samples(other_filtered),
        )
    } else {
        (ref_chunk, other_chunk)
    };

    // Correlate the chunks
    let correlation_result =
        correlate_chunk_pair(&ref_chunk, &other_chunk, method, config.use_peak_fit, config.sample_rate)?;

    // Create chunk result with acceptance check
    Ok(ChunkResult::new(
        chunk_index,
        start_time,
        correlation_result,
        config.min_match_pct,
    ))
}

/// Correlate two audio chunks directly.
///
/// Lower-level function that takes pre-extracted chunks.
/// Handles peak fitting for sample-level methods.
///
/// # Arguments
/// * `ref_chunk` - Reference audio chunk
/// * `other_chunk` - Other audio chunk to compare
/// * `method` - Correlation method to use
/// * `use_peak_fit` - Whether to use peak fitting for sub-sample accuracy
/// * `sample_rate` - Audio sample rate (for peak fitting)
///
/// # Returns
/// Correlation result with delay and match percentage.
pub fn correlate_chunk_pair(
    ref_chunk: &AudioChunk,
    other_chunk: &AudioChunk,
    method: &dyn CorrelationMethod,
    use_peak_fit: bool,
    sample_rate: u32,
) -> AnalysisResult<super::types::CorrelationResult> {
    // Peak fitting only works with sample-level correlation methods.
    // Skip for frame-level methods (DTW, Onset, Spectrogram) where it doesn't apply.
    let method_name = method.name();
    let supports_peak_fit = !matches!(method_name, "DTW" | "Onset" | "Spectrogram");

    if use_peak_fit && supports_peak_fit {
        // Get raw correlation for peak fitting
        let raw = method.raw_correlation(ref_chunk, other_chunk)?;
        Ok(find_and_fit_peak(&raw, sample_rate))
    } else {
        // Use direct correlation
        method.correlate(ref_chunk, other_chunk)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::methods::Scc;

    fn make_test_audio(duration_secs: f64, sample_rate: u32) -> AudioData {
        let num_samples = (duration_secs * sample_rate as f64) as usize;
        let samples: Vec<f64> = (0..num_samples)
            .map(|i| (i as f64 * 0.01).sin())
            .collect();
        AudioData::new(samples, sample_rate)
    }

    #[test]
    fn correlate_chunks_returns_results_for_all_positions() {
        let ref_audio = make_test_audio(100.0, 48000);
        let other_audio = make_test_audio(100.0, 48000);
        let positions = vec![10.0, 30.0, 50.0];
        let method = Scc::new();
        let config = CorrelationConfig {
            chunk_duration: 5.0,
            sample_rate: 48000,
            ..Default::default()
        };

        let results = correlate_chunks(&ref_audio, &other_audio, &positions, &method, &config);

        assert_eq!(results.len(), 3);
        assert_eq!(results[0].chunk_index, 1);
        assert_eq!(results[1].chunk_index, 2);
        assert_eq!(results[2].chunk_index, 3);
    }

    #[test]
    fn correlate_chunks_marks_out_of_bounds_as_rejected() {
        let ref_audio = make_test_audio(30.0, 48000);
        let other_audio = make_test_audio(30.0, 48000);
        // Position 50.0 is beyond the 30 second audio
        let positions = vec![10.0, 50.0];
        let method = Scc::new();
        let config = CorrelationConfig {
            chunk_duration: 5.0,
            sample_rate: 48000,
            ..Default::default()
        };

        let results = correlate_chunks(&ref_audio, &other_audio, &positions, &method, &config);

        assert_eq!(results.len(), 2);
        assert!(results[0].accepted || !results[0].accepted); // First should process
        assert!(!results[1].accepted); // Second should be rejected (out of bounds)
        assert!(results[1].reject_reason.is_some());
    }

    #[test]
    fn identical_audio_has_zero_delay() {
        let audio = make_test_audio(20.0, 48000);
        let positions = vec![5.0];
        let method = Scc::new();
        let config = CorrelationConfig {
            chunk_duration: 5.0,
            min_match_pct: 0.0, // Accept any match
            use_peak_fit: false,
            sample_rate: 48000,
            ..Default::default()
        };

        let results = correlate_chunks(&audio, &audio, &positions, &method, &config);

        assert_eq!(results.len(), 1);
        // Identical audio should have ~0ms delay
        assert!(
            results[0].delay_ms_raw.abs() < 1.0,
            "Expected ~0ms delay, got {}ms",
            results[0].delay_ms_raw
        );
    }

    #[test]
    fn config_filter_config_returns_none_when_disabled() {
        let config = CorrelationConfig {
            filtering_method: FilteringMethod::None,
            ..Default::default()
        };
        assert!(config.filter_config().is_none());
    }

    #[test]
    fn config_filter_config_returns_some_when_enabled() {
        let config = CorrelationConfig {
            filtering_method: FilteringMethod::BandPass,
            filter_low_cutoff_hz: 300.0,
            filter_high_cutoff_hz: 3400.0,
            sample_rate: 48000,
            ..Default::default()
        };
        let filter = config.filter_config().unwrap();
        assert_eq!(filter.filter_type, FilterType::BandPass);
        assert_eq!(filter.low_cutoff_hz, 300.0);
        assert_eq!(filter.high_cutoff_hz, 3400.0);
    }
}
