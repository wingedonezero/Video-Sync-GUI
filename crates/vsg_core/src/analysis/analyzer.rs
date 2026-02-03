//! Main analyzer for audio sync analysis.
//!
//! Orchestrates the full analysis pipeline:
//! 1. Get media duration
//! 2. Calculate chunk positions
//! 3. Extract and correlate audio chunks
//! 4. Select final delay using configured mode
//! 5. Return comprehensive analysis result

use std::path::Path;
use std::sync::Arc;

use crate::config::AnalysisSettings;
use crate::logging::JobLogger;
use crate::models::{DelaySelectionMode, FilteringMethod};

use super::delay_selection::{get_selector, SelectorConfig};
use super::ffmpeg::{extract_full_audio, get_duration, DEFAULT_ANALYSIS_SAMPLE_RATE};
use super::filtering::{apply_filter, FilterConfig, FilterType};
use super::methods::{
    create_from_enum, selected_methods, CorrelationMethod as CorrelationMethodTrait, Scc,
};
use super::peak_fit::find_and_fit_peak;
use super::tracks::{find_track_by_language, get_audio_tracks};
use super::types::{AnalysisError, AnalysisResult, AudioData, ChunkResult, SourceAnalysisResult};

/// Audio sync analyzer.
///
/// Analyzes the sync offset between a reference source and other sources
/// using chunked cross-correlation.
pub struct Analyzer {
    /// Correlation method to use.
    method: Box<dyn CorrelationMethodTrait>,
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
    /// Minimum match percentage for valid result (0-100).
    min_match_pct: f64,
    /// Minimum accepted chunks for valid analysis.
    min_accepted_chunks: usize,
    /// Delay selection mode.
    delay_selection_mode: DelaySelectionMode,
    /// Selector configuration.
    selector_config: SelectorConfig,
    /// Language filter for Source 1 (reference).
    lang_source1: Option<String>,
    /// Language filter for other sources.
    lang_others: Option<String>,
    /// Optional job logger for progress messages (goes to job log, not app log).
    logger: Option<Arc<JobLogger>>,
    /// [Multi-Correlation] Use SCC method.
    multi_corr_scc: bool,
    /// [Multi-Correlation] Use GCC-PHAT method.
    multi_corr_gcc_phat: bool,
    /// [Multi-Correlation] Use GCC-SCOT method.
    multi_corr_gcc_scot: bool,
    /// [Multi-Correlation] Use Whitened method.
    multi_corr_whitened: bool,
    /// [Multi-Correlation] Use Onset Detection method.
    multi_corr_onset: bool,
    /// [Multi-Correlation] Use DTW method.
    multi_corr_dtw: bool,
    /// [Multi-Correlation] Use Spectrogram Correlation method.
    multi_corr_spectrogram: bool,
    /// Audio filtering method to apply before correlation.
    filtering_method: FilteringMethod,
    /// Low cutoff frequency for filtering (Hz).
    filter_low_cutoff_hz: f64,
    /// High cutoff frequency for filtering (Hz).
    filter_high_cutoff_hz: f64,
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
            min_match_pct: 5.0,
            min_accepted_chunks: 3,
            delay_selection_mode: DelaySelectionMode::default(),
            selector_config: SelectorConfig::default(),
            lang_source1: None,
            lang_others: None,
            logger: None,
            multi_corr_scc: true,
            multi_corr_gcc_phat: true,
            multi_corr_gcc_scot: true,
            multi_corr_whitened: true,
            multi_corr_onset: true,
            multi_corr_dtw: true,
            multi_corr_spectrogram: true,
            filtering_method: FilteringMethod::None,
            filter_low_cutoff_hz: 300.0,
            filter_high_cutoff_hz: 3400.0,
        }
    }

    /// Create an analyzer from settings.
    pub fn from_settings(settings: &AnalysisSettings) -> Self {
        Self {
            method: create_from_enum(settings.correlation_method),
            sample_rate: DEFAULT_ANALYSIS_SAMPLE_RATE,
            use_soxr: settings.use_soxr,
            use_peak_fit: settings.audio_peak_fit,
            chunk_count: settings.chunk_count as usize,
            chunk_duration: settings.chunk_duration as f64,
            scan_start_pct: settings.scan_start_pct,
            scan_end_pct: settings.scan_end_pct,
            min_match_pct: settings.min_match_pct,
            min_accepted_chunks: settings.min_accepted_chunks as usize,
            delay_selection_mode: settings.delay_selection_mode,
            selector_config: SelectorConfig::from(settings),
            lang_source1: settings.lang_source1.clone(),
            lang_others: settings.lang_others.clone(),
            logger: None,
            multi_corr_scc: settings.multi_corr_scc,
            multi_corr_gcc_phat: settings.multi_corr_gcc_phat,
            multi_corr_gcc_scot: settings.multi_corr_gcc_scot,
            multi_corr_whitened: settings.multi_corr_whitened,
            multi_corr_onset: settings.multi_corr_onset,
            multi_corr_dtw: settings.multi_corr_dtw,
            multi_corr_spectrogram: settings.multi_corr_spectrogram,
            filtering_method: settings.filtering_method,
            filter_low_cutoff_hz: settings.filter_low_cutoff_hz,
            filter_high_cutoff_hz: settings.filter_high_cutoff_hz,
        }
    }

    /// Set the job logger for progress messages.
    /// Messages logged here go to the job log (GUI), not the app log.
    pub fn with_logger(mut self, logger: Arc<JobLogger>) -> Self {
        self.logger = Some(logger);
        self
    }

    /// Set the correlation method.
    pub fn with_method(mut self, method: Box<dyn CorrelationMethodTrait>) -> Self {
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

    /// Log a message to the job log (if logger is set).
    /// These messages go to the job log for detailed per-chunk progress.
    /// They do NOT go to the app log (tracing) - that's for high-level app events.
    fn log(&self, msg: &str) {
        if let Some(ref logger) = self.logger {
            logger.info(msg);
        }
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
            "Using audio tracks: reference={}, {}={}",
            ref_track_idx.map_or("default".to_string(), |i| i.to_string()),
            source_name,
            other_track_idx.map_or("default".to_string(), |i| i.to_string())
        ));

        // Get durations first (fast ffprobe call)
        let ref_duration = get_duration(reference_path)?;
        let other_duration = get_duration(other_path)?;

        // Use shorter duration for chunk calculation
        let effective_duration = ref_duration.min(other_duration);

        self.log(&format!(
            "Reference: {:.1}s, {}: {:.1}s",
            ref_duration, source_name, other_duration
        ));

        // Calculate chunk positions
        let chunk_positions = self.calculate_chunk_positions(effective_duration);

        if chunk_positions.is_empty() {
            return Err(AnalysisError::InvalidAudio(
                "No valid chunk positions calculated".to_string(),
            ));
        }

        self.log(&format!(
            "Analyzing {} chunks of {:.0}s each",
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
        let other_audio =
            extract_full_audio(other_path, self.sample_rate, self.use_soxr, other_track_idx)?;

        self.log(&format!(
            "Audio decoded. Analyzing {} chunks...",
            chunk_positions.len()
        ));

        // Log filtering if enabled
        if self.filtering_method != FilteringMethod::None {
            self.log(&format!(
                "Audio filtering: {} (low={:.0}Hz, high={:.0}Hz)",
                self.filtering_method, self.filter_low_cutoff_hz, self.filter_high_cutoff_hz
            ));
        }

        // Analyze each chunk from the in-memory audio data
        let mut chunk_results = Vec::with_capacity(chunk_positions.len());
        let total_chunks = chunk_positions.len();

        for (idx, &start_time) in chunk_positions.iter().enumerate() {
            let chunk_num = idx + 1; // 1-based for display

            match self.analyze_chunk_from_memory(&ref_audio, &other_audio, start_time, chunk_num) {
                Ok(result) => {
                    // Log in Python-compatible format
                    self.log(&format!(
                        "  Chunk {:2}/{} (@{:.1}s): delay = {:+} ms (raw={:+.3}, match={:.2}) — {}",
                        chunk_num,
                        total_chunks,
                        result.chunk_start_secs,
                        result.delay_ms_rounded,
                        result.delay_ms_raw,
                        result.match_pct,
                        result.status_str()
                    ));
                    chunk_results.push(result);
                }
                Err(e) => {
                    self.log(&format!(
                        "  Chunk {:2}/{} (@{:.1}s): FAILED — {}",
                        chunk_num, total_chunks, start_time, e
                    ));
                    chunk_results.push(ChunkResult::rejected(chunk_num, start_time, e.to_string()));
                }
            }
        }

        // Aggregate results using delay selector
        self.aggregate_results(source_name, chunk_results)
    }

    /// Run multi-correlation: analyze with all available methods for comparison.
    ///
    /// This decodes audio once and runs each method on the same chunks.
    /// Useful for comparing method performance on specific content.
    ///
    /// # Arguments
    /// * `reference_path` - Path to the reference source (Source 1)
    /// * `other_path` - Path to the source to analyze
    /// * `source_name` - Name of the source being analyzed
    ///
    /// # Returns
    /// HashMap mapping method names to their SourceAnalysisResult.
    pub fn analyze_multi_correlation(
        &self,
        reference_path: &Path,
        other_path: &Path,
        source_name: &str,
    ) -> AnalysisResult<std::collections::HashMap<String, SourceAnalysisResult>> {
        self.log(&format!(
            "\n{}\n  MULTI-CORRELATION ANALYSIS: {}\n{}",
            "═".repeat(70),
            source_name,
            "═".repeat(70)
        ));

        // Detect audio tracks and find matching language
        let ref_track_idx = self.find_audio_track(reference_path, self.lang_source1.as_deref())?;
        let other_track_idx = self.find_audio_track(other_path, self.lang_others.as_deref())?;

        self.log(&format!(
            "Using audio tracks: reference={}, {}={}",
            ref_track_idx.map_or("default".to_string(), |i| i.to_string()),
            source_name,
            other_track_idx.map_or("default".to_string(), |i| i.to_string())
        ));

        // Get durations
        let ref_duration = get_duration(reference_path)?;
        let other_duration = get_duration(other_path)?;
        let effective_duration = ref_duration.min(other_duration);

        self.log(&format!(
            "Reference: {:.1}s, {}: {:.1}s",
            ref_duration, source_name, other_duration
        ));

        // Calculate chunk positions
        let chunk_positions = self.calculate_chunk_positions(effective_duration);

        if chunk_positions.is_empty() {
            return Err(AnalysisError::InvalidAudio(
                "No valid chunk positions calculated".to_string(),
            ));
        }

        // DECODE FULL AUDIO ONCE
        self.log("Decoding reference audio...");
        let ref_audio = extract_full_audio(
            reference_path,
            self.sample_rate,
            self.use_soxr,
            ref_track_idx,
        )?;

        self.log(&format!("Decoding {} audio...", source_name));
        let other_audio =
            extract_full_audio(other_path, self.sample_rate, self.use_soxr, other_track_idx)?;

        // Get selected methods for multi-correlation
        let methods = selected_methods(
            self.multi_corr_scc,
            self.multi_corr_gcc_phat,
            self.multi_corr_gcc_scot,
            self.multi_corr_whitened,
            self.multi_corr_onset,
            self.multi_corr_dtw,
            self.multi_corr_spectrogram,
        );

        if methods.is_empty() {
            return Err(AnalysisError::InvalidAudio(
                "No correlation methods selected for multi-correlation".to_string(),
            ));
        }

        self.log(&format!(
            "Audio decoded. Running {} methods on {} chunks...",
            methods.len(),
            chunk_positions.len()
        ));

        // Run each method on the same audio data
        let mut results = std::collections::HashMap::new();

        for method in methods {
            let method_name = method.name().to_string();
            self.log(&format!(
                "\n{}\n  Method: {}\n{}",
                "─".repeat(60),
                method_name,
                "─".repeat(60)
            ));

            match self.analyze_with_method(
                method.as_ref(),
                &ref_audio,
                &other_audio,
                &chunk_positions,
                source_name,
            ) {
                Ok(result) => {
                    self.log(&format!(
                        "  {} Result: {:+}ms (raw: {:+.3}ms) | match: {:.1}% | accepted: {}/{}",
                        method_name,
                        result.delay.delay_ms_rounded,
                        result.delay.delay_ms_raw,
                        result.avg_match_pct,
                        result.accepted_chunks,
                        result.total_chunks
                    ));
                    results.insert(method_name, result);
                }
                Err(e) => {
                    self.log(&format!("  {} FAILED: {}", method_name, e));
                }
            }
        }

        // Log summary comparison (matching Python format)
        self.log(&format!(
            "\n{}\n  MULTI-CORRELATION SUMMARY\n{}",
            "═".repeat(70),
            "═".repeat(70)
        ));
        for (name, result) in &results {
            self.log(&format!(
                "  {}: {:+}ms (raw avg: {:+.3}ms) | match: {:.1}% | accepted: {}/{}",
                name,
                result.delay.delay_ms_rounded,
                result.delay.delay_ms_raw,
                result.avg_match_pct,
                result.accepted_chunks,
                result.total_chunks
            ));
        }
        self.log(&format!("{}", "═".repeat(70)));

        Ok(results)
    }

    /// Analyze with a specific method using pre-decoded audio.
    fn analyze_with_method(
        &self,
        method: &dyn CorrelationMethodTrait,
        ref_audio: &AudioData,
        other_audio: &AudioData,
        chunk_positions: &[f64],
        source_name: &str,
    ) -> AnalysisResult<SourceAnalysisResult> {
        let mut chunk_results = Vec::with_capacity(chunk_positions.len());
        let total_chunks = chunk_positions.len();

        for (idx, &start_time) in chunk_positions.iter().enumerate() {
            let chunk_num = idx + 1;

            match self.analyze_chunk_with_method(
                method,
                ref_audio,
                other_audio,
                start_time,
                chunk_num,
            ) {
                Ok(result) => {
                    self.log(&format!(
                        "    Chunk {:2}/{} (@{:.1}s): delay = {:+} ms (match={:.2}) — {}",
                        chunk_num,
                        total_chunks,
                        result.chunk_start_secs,
                        result.delay_ms_rounded,
                        result.match_pct,
                        result.status_str()
                    ));
                    chunk_results.push(result);
                }
                Err(e) => {
                    self.log(&format!(
                        "    Chunk {:2}/{} (@{:.1}s): FAILED — {}",
                        chunk_num, total_chunks, start_time, e
                    ));
                    chunk_results.push(ChunkResult::rejected(chunk_num, start_time, e.to_string()));
                }
            }
        }

        self.aggregate_results_with_method(source_name, method.name(), chunk_results)
    }

    /// Analyze a single chunk with a specific method.
    fn analyze_chunk_with_method(
        &self,
        method: &dyn CorrelationMethodTrait,
        ref_audio: &AudioData,
        other_audio: &AudioData,
        start_time: f64,
        chunk_index: usize,
    ) -> AnalysisResult<ChunkResult> {
        let ref_chunk = ref_audio
            .extract_chunk(start_time, self.chunk_duration)
            .ok_or_else(|| {
                AnalysisError::InvalidAudio(format!(
                    "Failed to extract reference chunk at {:.2}s",
                    start_time
                ))
            })?;

        let other_chunk = other_audio
            .extract_chunk(start_time, self.chunk_duration)
            .ok_or_else(|| {
                AnalysisError::InvalidAudio(format!(
                    "Failed to extract other chunk at {:.2}s",
                    start_time
                ))
            })?;

        // Apply filtering if enabled
        let (ref_chunk, other_chunk) = if self.filtering_method != FilteringMethod::None {
            let filter_config = FilterConfig {
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
            };
            let ref_filtered = apply_filter(&ref_chunk.samples, &filter_config);
            let other_filtered = apply_filter(&other_chunk.samples, &filter_config);
            (
                ref_chunk.with_filtered_samples(ref_filtered),
                other_chunk.with_filtered_samples(other_filtered),
            )
        } else {
            (ref_chunk, other_chunk)
        };

        // Peak fitting only works with sample-level correlation methods (SCC).
        // Skip for frame-level methods (DTW, Onset, Spectrogram) where it doesn't apply.
        let method_name = method.name();
        let supports_peak_fit = !matches!(
            method_name,
            "DTW" | "Onset" | "Spectrogram"
        );

        let correlation_result = if self.use_peak_fit && supports_peak_fit {
            let raw = method.raw_correlation(&ref_chunk, &other_chunk)?;
            find_and_fit_peak(&raw, self.sample_rate)
        } else {
            method.correlate(&ref_chunk, &other_chunk)?
        };

        Ok(ChunkResult::new(
            chunk_index,
            start_time,
            correlation_result,
            self.min_match_pct,
        ))
    }

    /// Aggregate results for a specific method.
    fn aggregate_results_with_method(
        &self,
        source_name: &str,
        method_name: &str,
        chunk_results: Vec<ChunkResult>,
    ) -> AnalysisResult<SourceAnalysisResult> {
        let total_chunks = chunk_results.len();
        let accepted_chunks: Vec<&ChunkResult> =
            chunk_results.iter().filter(|r| r.accepted).collect();
        let accepted_count = accepted_chunks.len();

        if accepted_count < self.min_accepted_chunks {
            return Err(AnalysisError::InsufficientChunks {
                valid: accepted_count,
                required: self.min_accepted_chunks,
            });
        }

        let avg_match_pct: f64 =
            accepted_chunks.iter().map(|c| c.match_pct).sum::<f64>() / accepted_count as f64;

        let selector = get_selector(self.delay_selection_mode);
        let accepted_for_selector: Vec<ChunkResult> = chunk_results
            .iter()
            .filter(|r| r.accepted)
            .cloned()
            .collect();

        let delay = selector
            .select(&accepted_for_selector, &self.selector_config)
            .ok_or_else(|| AnalysisError::SelectorFailed {
                reason: format!(
                    "no stable segment found (selector: {}, delays too scattered?)",
                    selector.name()
                ),
                accepted: accepted_count,
            })?;

        let delays: Vec<f64> = accepted_chunks.iter().map(|c| c.delay_ms_raw).collect();
        let mean_delay: f64 = delays.iter().sum::<f64>() / delays.len() as f64;
        let variance: f64 =
            delays.iter().map(|d| (d - mean_delay).powi(2)).sum::<f64>() / delays.len() as f64;
        let std_dev = variance.sqrt();
        let drift_detected = std_dev > 50.0;

        Ok(SourceAnalysisResult {
            source_name: source_name.to_string(),
            delay,
            avg_match_pct,
            accepted_chunks: accepted_count,
            total_chunks,
            chunk_results,
            drift_detected,
            correlation_method: method_name.to_string(),
        })
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
    fn find_audio_track(
        &self,
        path: &Path,
        language: Option<&str>,
    ) -> AnalysisResult<Option<usize>> {
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

        // Apply filtering if enabled
        let (ref_chunk, other_chunk) = if self.filtering_method != FilteringMethod::None {
            let filter_config = FilterConfig {
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
            };
            let ref_filtered = apply_filter(&ref_chunk.samples, &filter_config);
            let other_filtered = apply_filter(&other_chunk.samples, &filter_config);
            (
                ref_chunk.with_filtered_samples(ref_filtered),
                other_chunk.with_filtered_samples(other_filtered),
            )
        } else {
            (ref_chunk, other_chunk)
        };

        // Correlate
        let correlation_result = if self.use_peak_fit {
            // Get raw correlation for peak fitting
            let raw = self.method.raw_correlation(&ref_chunk, &other_chunk)?;
            // find_and_fit_peak returns CorrelationResult with match_pct in 0-100 scale
            find_and_fit_peak(&raw, self.sample_rate)
        } else {
            // correlate returns CorrelationResult with match_pct in 0-100 scale
            self.method.correlate(&ref_chunk, &other_chunk)?
        };

        // Create chunk result with acceptance check
        Ok(ChunkResult::new(
            chunk_index,
            start_time,
            correlation_result,
            self.min_match_pct,
        ))
    }

    /// Aggregate chunk results into final analysis result using delay selector.
    fn aggregate_results(
        &self,
        source_name: &str,
        chunk_results: Vec<ChunkResult>,
    ) -> AnalysisResult<SourceAnalysisResult> {
        let total_chunks = chunk_results.len();

        // Get accepted chunks
        let accepted_chunks: Vec<&ChunkResult> =
            chunk_results.iter().filter(|r| r.accepted).collect();
        let accepted_count = accepted_chunks.len();

        // Check minimum accepted chunks
        if accepted_count < self.min_accepted_chunks {
            return Err(AnalysisError::InsufficientChunks {
                valid: accepted_count,
                required: self.min_accepted_chunks,
            });
        }

        // Calculate average match percentage
        let avg_match_pct: f64 =
            accepted_chunks.iter().map(|c| c.match_pct).sum::<f64>() / accepted_count as f64;

        // Use delay selector to choose final delay
        let selector = get_selector(self.delay_selection_mode);

        // Filter to only accepted chunks for selector
        let accepted_for_selector: Vec<ChunkResult> = chunk_results
            .iter()
            .filter(|r| r.accepted)
            .cloned()
            .collect();

        let delay = selector
            .select(&accepted_for_selector, &self.selector_config)
            .ok_or_else(|| AnalysisError::SelectorFailed {
                reason: format!(
                    "no stable segment found (selector: {}, delays too scattered?)",
                    selector.name()
                ),
                accepted: accepted_count,
            })?;

        // Log delay selection result
        if let Some(ref details) = delay.details {
            self.log(&format!(
                "[{}] Found stable segment: {}",
                delay.method_name, details
            ));
        }
        self.log(&format!(
            "{} delay determined: {:+} ms ({}).",
            source_name, delay.delay_ms_rounded, delay.method_name
        ));

        // Check for drift (significant variation in delays)
        let delays: Vec<f64> = accepted_chunks.iter().map(|c| c.delay_ms_raw).collect();
        let mean_delay: f64 = delays.iter().sum::<f64>() / delays.len() as f64;
        let variance: f64 =
            delays.iter().map(|d| (d - mean_delay).powi(2)).sum::<f64>() / delays.len() as f64;
        let std_dev = variance.sqrt();
        let drift_detected = std_dev > 50.0; // More than 50ms variation suggests drift

        if drift_detected {
            self.log(&format!(
                "[Drift] Warning: {} shows delay variation (stddev: {:.1}ms)",
                source_name, std_dev
            ));
        }

        Ok(SourceAnalysisResult {
            source_name: source_name.to_string(),
            delay,
            avg_match_pct,
            accepted_chunks: accepted_count,
            total_chunks,
            chunk_results,
            drift_detected,
            correlation_method: self.method.name().to_string(),
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
        assert!(!positions.is_empty());
    }

    #[test]
    fn analyzer_from_settings() {
        let mut settings = AnalysisSettings::default();
        settings.chunk_count = 5;
        settings.chunk_duration = 20;
        settings.use_soxr = false;
        settings.audio_peak_fit = false;
        settings.delay_selection_mode = DelaySelectionMode::FirstStable;

        let analyzer = Analyzer::from_settings(&settings);

        assert_eq!(analyzer.chunk_count, 5);
        assert_eq!(analyzer.chunk_duration, 20.0);
        assert!(!analyzer.use_soxr);
        assert!(!analyzer.use_peak_fit);
        assert_eq!(
            analyzer.delay_selection_mode,
            DelaySelectionMode::FirstStable
        );
    }
}
