//! Main analyzer for audio sync analysis.
//!
//! Orchestrates the full analysis pipeline:
//! 1. Get media duration
//! 2. Calculate chunk positions
//! 3. Extract and correlate audio chunks
//! 4. Aggregate results and calculate final delay

use std::path::Path;
use std::sync::Arc;

use crate::config::AnalysisSettings;

use super::ffmpeg::{extract_full_audio, get_duration, DEFAULT_ANALYSIS_SAMPLE_RATE};
use super::methods::{CorrelationMethod, Scc};
use super::peak_fit::find_and_fit_peak;
use super::tracks::{find_track_by_language, get_audio_tracks};
use super::types::{AnalysisError, AnalysisResult, ChunkResult, SourceAnalysisResult};

/// Callback type for logging messages from the analyzer.
pub type AnalyzerLogCallback = Arc<dyn Fn(&str) + Send + Sync>;

/// Audio sync analyzer.
///
/// Analyzes the sync offset between a reference source and other sources
/// using chunked cross-correlation.
pub struct Analyzer {
    /// Correlation method to use.
    method: Box<dyn CorrelationMethod>,
    /// Sample rate for analysis.
    sample_rate: u32,
    /// Whether to use SOXR resampling.
    use_soxr: bool,
    /// Whether to use peak fitting.
    use_peak_fit: bool,
    /// Number of chunks to analyze.
    chunk_count: usize,
    /// Duration of each chunk in seconds.
    chunk_duration: f64,
    /// Start position as percentage (0-100).
    scan_start_pct: f64,
    /// End position as percentage (0-100).
    scan_end_pct: f64,
    /// Minimum correlation peak for valid result.
    min_correlation: f64,
    /// Language filter for Source 1 (reference).
    lang_source1: Option<String>,
    /// Language filter for other sources.
    lang_others: Option<String>,
    /// Optional logging callback for progress messages.
    log_callback: Option<AnalyzerLogCallback>,
}

impl Analyzer {
    /// Create a new analyzer with default settings.
    pub fn new() -> Self {
        Self {
            method: Box::new(Scc::new()),
            sample_rate: DEFAULT_ANALYSIS_SAMPLE_RATE,
            use_soxr: true,
            use_peak_fit: true,
            chunk_count: 10,
            chunk_duration: 15.0,
            scan_start_pct: 5.0,
            scan_end_pct: 95.0,
            min_correlation: 0.3,
            lang_source1: None,
            lang_others: None,
            log_callback: None,
        }
    }

    /// Create an analyzer from settings.
    pub fn from_settings(settings: &AnalysisSettings) -> Self {
        Self {
            method: Box::new(Scc::new()),
            sample_rate: DEFAULT_ANALYSIS_SAMPLE_RATE,
            use_soxr: settings.use_soxr,
            use_peak_fit: settings.audio_peak_fit,
            chunk_count: settings.chunk_count as usize,
            chunk_duration: settings.chunk_duration as f64,
            scan_start_pct: settings.scan_start_pct,
            scan_end_pct: settings.scan_end_pct,
            min_correlation: settings.min_match_pct / 100.0, // Convert from percentage
            lang_source1: settings.lang_source1.clone(),
            lang_others: settings.lang_others.clone(),
            log_callback: None,
        }
    }

    /// Set the logging callback.
    pub fn with_log_callback(mut self, callback: AnalyzerLogCallback) -> Self {
        self.log_callback = Some(callback);
        self
    }

    /// Set the correlation method.
    pub fn with_method(mut self, method: Box<dyn CorrelationMethod>) -> Self {
        self.method = method;
        self
    }

    /// Set whether to use SOXR resampling.
    pub fn with_soxr(mut self, use_soxr: bool) -> Self {
        self.use_soxr = use_soxr;
        self
    }

    /// Set whether to use peak fitting.
    pub fn with_peak_fit(mut self, use_peak_fit: bool) -> Self {
        self.use_peak_fit = use_peak_fit;
        self
    }

    /// Log a message using the callback if set, otherwise use tracing.
    fn log(&self, msg: &str) {
        if let Some(ref callback) = self.log_callback {
            callback(msg);
        }
        // Always also log to tracing for file/console output
        tracing::info!("{}", msg);
    }

    /// Analyze the sync offset between reference and other source.
    ///
    /// # Arguments
    /// * `reference_path` - Path to the reference source (Source 1)
    /// * `other_path` - Path to the source to analyze
    /// * `source_name` - Name of the source being analyzed (e.g., "Source 2")
    ///
    /// # Returns
    /// SourceAnalysisResult with delay and confidence information.
    pub fn analyze(
        &self,
        reference_path: &Path,
        other_path: &Path,
        source_name: &str,
    ) -> AnalysisResult<SourceAnalysisResult> {
        self.log(&format!(
            "Analyzing {} vs reference using {}",
            source_name,
            self.method.name()
        ));

        // Detect audio tracks and find matching language
        let ref_track_idx = self.find_audio_track(reference_path, self.lang_source1.as_deref())?;
        let other_track_idx = self.find_audio_track(other_path, self.lang_others.as_deref())?;

        self.log(&format!(
            "Using audio tracks: reference={}, other={}",
            ref_track_idx.map_or("default".to_string(), |i| i.to_string()),
            other_track_idx.map_or("default".to_string(), |i| i.to_string())
        ));

        // Get durations first (fast ffprobe call)
        let ref_duration = get_duration(reference_path)?;
        let other_duration = get_duration(other_path)?;

        // Use shorter duration for chunk calculation
        let effective_duration = ref_duration.min(other_duration);

        self.log(&format!(
            "Reference duration: {:.2}s, Other duration: {:.2}s, Effective: {:.2}s",
            ref_duration,
            other_duration,
            effective_duration
        ));

        // Calculate chunk positions
        let chunk_positions = self.calculate_chunk_positions(effective_duration);

        if chunk_positions.is_empty() {
            return Err(AnalysisError::InvalidAudio(
                "No valid chunk positions calculated".to_string(),
            ));
        }

        self.log(&format!(
            "Will analyze {} chunks of {:.1}s each",
            chunk_positions.len(),
            self.chunk_duration
        ));

        // DECODE FULL AUDIO ONCE (not per-chunk!)
        self.log("Decoding reference audio...");
        let ref_audio = extract_full_audio(
            reference_path,
            self.sample_rate,
            self.use_soxr,
            ref_track_idx,
        )?;

        self.log(&format!("Decoding {} audio...", source_name));
        let other_audio = extract_full_audio(
            other_path,
            self.sample_rate,
            self.use_soxr,
            other_track_idx,
        )?;

        self.log(&format!("Audio decoded. Analyzing {} chunks...", chunk_positions.len()));

        // Analyze each chunk from the in-memory audio data
        let mut chunk_results = Vec::with_capacity(chunk_positions.len());

        for (idx, &start_time) in chunk_positions.iter().enumerate() {
            match self.analyze_chunk_from_memory(&ref_audio, &other_audio, start_time, idx) {
                Ok(result) => {
                    // Detailed per-chunk logging (like Python original)
                    let status = if result.valid { "OK" } else { "LOW" };
                    self.log(&format!(
                        "  Chunk {:2}/{}: delay={:+8.2}ms  corr={:.3}  [{}]",
                        idx + 1,
                        chunk_positions.len(),
                        result.correlation.delay_ms,
                        result.correlation.correlation_peak,
                        status
                    ));
                    chunk_results.push(result);
                }
                Err(e) => {
                    self.log(&format!(
                        "  Chunk {:2}/{}: FAILED - {}",
                        idx + 1,
                        chunk_positions.len(),
                        e
                    ));
                    chunk_results.push(ChunkResult::invalid(idx, start_time, e.to_string()));
                }
            }
        }

        // Aggregate results
        self.aggregate_results(source_name, chunk_results)
    }

    /// Calculate chunk start positions evenly distributed across the scan range.
    fn calculate_chunk_positions(&self, duration: f64) -> Vec<f64> {
        let start_time = duration * (self.scan_start_pct / 100.0);
        let end_time = duration * (self.scan_end_pct / 100.0);
        let usable_duration = end_time - start_time - self.chunk_duration;

        if usable_duration <= 0.0 {
            // Not enough room for even one chunk
            return vec![];
        }

        if self.chunk_count <= 1 {
            // Just one chunk in the middle
            return vec![start_time + usable_duration / 2.0];
        }

        // Distribute chunks evenly
        let step = usable_duration / (self.chunk_count - 1) as f64;

        (0..self.chunk_count)
            .map(|i| start_time + (i as f64 * step))
            .collect()
    }

    /// Find audio track index by language.
    fn find_audio_track(&self, path: &Path, language: Option<&str>) -> AnalysisResult<Option<usize>> {
        // Get all audio tracks
        let tracks = get_audio_tracks(path)?;

        if tracks.is_empty() {
            return Err(AnalysisError::InvalidAudio(format!(
                "No audio tracks found in {}",
                path.display()
            )));
        }

        // Log available tracks
        for track in &tracks {
            tracing::debug!(
                "  Track {}: lang={}, name={}, codec={}",
                track.stream_index,
                track.language.as_deref().unwrap_or("und"),
                track.name.as_deref().unwrap_or(""),
                track.codec.as_deref().unwrap_or("unknown")
            );
        }

        // Find matching track
        Ok(find_track_by_language(&tracks, language))
    }

    /// Analyze a single chunk from in-memory audio data.
    fn analyze_chunk_from_memory(
        &self,
        ref_audio: &super::types::AudioData,
        other_audio: &super::types::AudioData,
        start_time: f64,
        chunk_index: usize,
    ) -> AnalysisResult<ChunkResult> {
        // Extract chunks from the in-memory audio data
        let ref_chunk = ref_audio
            .extract_chunk(start_time, self.chunk_duration)
            .ok_or_else(|| {
                AnalysisError::InvalidAudio(format!(
                    "Failed to extract reference chunk at {:.2}s (audio length: {:.2}s)",
                    start_time,
                    ref_audio.duration()
                ))
            })?;

        let other_chunk = other_audio
            .extract_chunk(start_time, self.chunk_duration)
            .ok_or_else(|| {
                AnalysisError::InvalidAudio(format!(
                    "Failed to extract other chunk at {:.2}s (audio length: {:.2}s)",
                    start_time,
                    other_audio.duration()
                ))
            })?;

        // Correlate
        let correlation_result = if self.use_peak_fit {
            // Get raw correlation for peak fitting
            let raw = self.method.raw_correlation(&ref_chunk, &other_chunk)?;
            find_and_fit_peak(&raw, self.sample_rate)
        } else {
            self.method.correlate(&ref_chunk, &other_chunk)?
        };

        // Check validity based on correlation peak
        let peak = correlation_result.correlation_peak;
        let valid = peak >= self.min_correlation;

        if valid {
            Ok(ChunkResult::new(chunk_index, start_time, correlation_result))
        } else {
            Ok(ChunkResult {
                chunk_index,
                chunk_start_secs: start_time,
                correlation: correlation_result,
                valid: false,
                invalid_reason: Some(format!(
                    "Correlation {:.3} below threshold {:.3}",
                    peak, self.min_correlation
                )),
            })
        }
    }

    /// Aggregate chunk results into final analysis result.
    fn aggregate_results(
        &self,
        source_name: &str,
        chunk_results: Vec<ChunkResult>,
    ) -> AnalysisResult<SourceAnalysisResult> {
        let total_chunks = chunk_results.len();
        let valid_chunks: Vec<&ChunkResult> = chunk_results.iter().filter(|r| r.valid).collect();
        let valid_count = valid_chunks.len();

        if valid_count == 0 {
            return Err(AnalysisError::InsufficientChunks {
                valid: 0,
                required: 1,
            });
        }

        // Calculate median delay (more robust than mean)
        let mut delays: Vec<f64> = valid_chunks.iter().map(|r| r.correlation.delay_ms).collect();
        delays.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let median_delay = delays[delays.len() / 2];

        // Calculate mean for drift detection
        let mean_delay: f64 = delays.iter().sum::<f64>() / delays.len() as f64;

        // Check for drift (significant variation in delays)
        let variance: f64 = delays.iter().map(|d| (d - mean_delay).powi(2)).sum::<f64>() / delays.len() as f64;
        let std_dev = variance.sqrt();
        let drift_detected = std_dev > 50.0; // More than 50ms variation suggests drift

        // Calculate confidence (average of valid chunk correlations)
        let confidence: f64 = valid_chunks
            .iter()
            .map(|r| r.correlation.correlation_peak)
            .sum::<f64>()
            / valid_count as f64;

        tracing::info!(
            "{}: median delay={:.2}ms, confidence={:.3}, valid={}/{}, drift={}",
            source_name,
            median_delay,
            confidence,
            valid_count,
            total_chunks,
            drift_detected
        );

        Ok(SourceAnalysisResult {
            source_name: source_name.to_string(),
            delay_ms: median_delay,
            confidence,
            valid_chunks: valid_count,
            total_chunks,
            chunk_results,
            drift_detected,
            method: self.method.name().to_string(),
        })
    }
}

impl Default for Analyzer {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn analyzer_calculates_chunk_positions() {
        let analyzer = Analyzer::new();

        // 100 second video, 10 chunks, 5-95% range
        let positions = analyzer.calculate_chunk_positions(100.0);

        assert_eq!(positions.len(), 10);

        // First chunk should start around 5% (5 seconds)
        assert!(positions[0] >= 5.0);
        assert!(positions[0] < 10.0);

        // Last chunk should end before 95% (95 seconds)
        let last_end = positions.last().unwrap() + analyzer.chunk_duration;
        assert!(last_end <= 95.0);
    }

    #[test]
    fn analyzer_handles_short_video() {
        let mut analyzer = Analyzer::new();
        analyzer.chunk_duration = 15.0;
        analyzer.chunk_count = 10;

        // 20 second video - not enough room for 10 chunks
        let positions = analyzer.calculate_chunk_positions(20.0);

        // Should still get some positions (may be fewer)
        // With 5-95% of 20s = 1s to 19s, usable = 18s - 15s = 3s
        // Can fit a few chunks
        assert!(positions.len() > 0);
    }

    #[test]
    fn analyzer_from_settings() {
        let mut settings = AnalysisSettings::default();
        settings.chunk_count = 5;
        settings.chunk_duration = 20;
        settings.use_soxr = false;
        settings.audio_peak_fit = false;

        let analyzer = Analyzer::from_settings(&settings);

        assert_eq!(analyzer.chunk_count, 5);
        assert_eq!(analyzer.chunk_duration, 20.0);
        assert!(!analyzer.use_soxr);
        assert!(!analyzer.use_peak_fit);
    }
}
