//! Analyze step - calculates sync delays between sources.
//!
//! Uses audio cross-correlation to find the time offset between
//! a reference source (Source 1) and other sources.
//!
//! This step orchestrates pure functions from the analysis module:
//! 1. Extract audio from files
//! 2. Calculate chunk positions
//! 3. Correlate chunks using configured method
//! 4. Select final delay using configured selector
//! 5. Detect drift (PAL, linear, stepping)
//! 6. Calculate stability metrics
//!
//! Handles:
//! - Remux-only mode (single source, no analysis needed)
//! - Multi-correlation comparison mode
//! - Container delay chain correction (adds Source 1 audio container delay)
//! - Global shift calculation to eliminate negative delays
//! - Sync mode (positive_only vs allow_negative)
//! - Per-source stability metrics

use std::collections::HashMap;

use crate::analysis::{
    calculate_chunk_positions, calculate_stability, correlate_chunks, create_from_enum,
    diagnose_drift, extract_full_audio, find_track_by_language, get_audio_tracks, get_duration,
    get_framerate, get_selector, selected_methods, ChunkConfig, CorrelationConfig,
    DriftDetectionConfig, SelectorConfig, SourceStability, StabilityMetrics,
    DEFAULT_ANALYSIS_SAMPLE_RATE,
};
use crate::extraction::probe_file;
use crate::models::{Delays, SyncMode};
use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{AnalysisOutput, Context, JobState, StepOutcome};

/// Analyze step for calculating sync delays.
///
/// Performs audio cross-correlation between Source 1 (reference)
/// and other sources to calculate sync delays.
pub struct AnalyzeStep;

impl AnalyzeStep {
    pub fn new() -> Self {
        Self
    }
}

impl Default for AnalyzeStep {
    fn default() -> Self {
        Self::new()
    }
}

impl PipelineStep for AnalyzeStep {
    fn name(&self) -> &str {
        "Analyze"
    }

    fn description(&self) -> &str {
        "Calculate sync delays between sources"
    }

    fn validate_input(&self, ctx: &Context) -> StepResult<()> {
        // Check that source files exist
        for (name, path) in &ctx.job_spec.sources {
            if !path.exists() {
                return Err(StepError::file_not_found(format!(
                    "{}: {}",
                    name,
                    path.display()
                )));
            }
        }

        // Check that Source 1 exists (it's the reference)
        if !ctx.job_spec.sources.contains_key("Source 1") {
            return Err(StepError::invalid_input("Source 1 (reference) is required"));
        }

        // Note: Single source (remux-only) is valid - we skip analysis in execute()
        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.section("Audio Sync Analysis");

        let settings = &ctx.settings.analysis;

        // ============================================================
        // REMUX-ONLY MODE: Skip analysis if only Source 1 exists
        // ============================================================
        if ctx.job_spec.sources.len() == 1 {
            ctx.logger
                .info("Remux-only mode - no sync sources to analyze");

            // Create empty delays (Source 1 has 0 delay by definition)
            let mut delays = Delays::new();
            delays.set_delay("Source 1", 0.0);

            // Source 1 perfect stability (reference, no analysis needed)
            let mut source_stability = HashMap::new();
            source_stability.insert(
                "Source 1".to_string(),
                SourceStability {
                    accepted_chunks: 0,
                    total_chunks: 0,
                    avg_match_pct: 100.0,
                    delay_std_dev_ms: 0.0,
                    drift_detected: false,
                    acceptance_rate: 100.0,
                },
            );

            state.analysis = Some(AnalysisOutput {
                delays,
                confidence: 1.0, // Perfect confidence (nothing to sync)
                drift_detected: false,
                method: "none (remux-only)".to_string(),
                source_stability,
            });

            return Ok(StepOutcome::Skipped("Remux-only mode".to_string()));
        }

        // Get reference source path
        let ref_path = ctx
            .job_spec
            .sources
            .get("Source 1")
            .ok_or_else(|| StepError::invalid_input("Source 1 not found"))?;

        ctx.logger.info(&format!(
            "Reference: {}",
            ref_path.file_name().unwrap_or_default().to_string_lossy()
        ));

        // ============================================================
        // LOG SYNC MODE
        // ============================================================
        let sync_mode = settings.sync_mode;
        ctx.logger.info(&format!(
            "Sync Mode: {}",
            match sync_mode {
                SyncMode::PositiveOnly => "Positive Only (will shift to eliminate negatives)",
                SyncMode::AllowNegative => "Allow Negative (no global shift)",
            }
        ));

        // ============================================================
        // GET SOURCE 1 CONTAINER DELAYS (using mkvmerge minimum_timestamp)
        // ============================================================
        ctx.logger
            .info("--- Getting Source 1 Container Delays for Analysis ---");
        ctx.logger
            .command(&format!("mkvmerge -J \"{}\"", ref_path.display()));

        let (source1_audio_container_delay, source1_container_delays, source1_selected_track) =
            match probe_file(ref_path) {
                Ok(probe) => {
                    // Get video container delay first
                    let video_delay = probe.video_container_delay();

                    // Log any non-zero container delays
                    for track in &probe.tracks {
                        if track.container_delay_ms != 0 {
                            let track_type = match track.track_type {
                                crate::extraction::TrackType::Video => "video",
                                crate::extraction::TrackType::Audio => "audio",
                                crate::extraction::TrackType::Subtitles => "subtitles",
                            };
                            ctx.logger.info(&format!(
                                "[Container Delay] Source 1 {} track {} has container delay: {:+}ms",
                                track_type, track.id, track.container_delay_ms
                            ));
                        }
                    }

                    // Get all audio container delays relative to video
                    let relative_delays = probe.get_audio_container_delays_relative();

                    // Select audio track for correlation (default audio or first audio)
                    let selected_track = probe
                        .default_audio()
                        .or_else(|| probe.audio_tracks().next());

                    let (default_audio_delay, track_info) = if let Some(track) = selected_track {
                        let relative = track.container_delay_ms - video_delay;
                        let lang = track.language.as_deref().unwrap_or("und");
                        let codec = &track.codec_id;
                        let channels = track.properties.channels.unwrap_or(2);
                        let channel_str = match channels {
                            1 => "Mono".to_string(),
                            2 => "2.0".to_string(),
                            6 => "5.1".to_string(),
                            8 => "7.1".to_string(),
                            n => format!("{}ch", n),
                        };
                        let name = track.name.as_deref().unwrap_or("");

                        // Log selected track
                        let mut track_details =
                            format!("Track {}: {}, {} {}", track.id, lang, codec, channel_str);
                        if !name.is_empty() {
                            track_details.push_str(&format!(", '{}'", name));
                        }
                        ctx.logger
                            .info(&format!("[Source 1] Selected: {}", track_details));

                        (relative, Some((track.id, lang.to_string())))
                    } else {
                        ctx.logger.warn("[Source 1] No audio tracks found");
                        (0, None)
                    };

                    // Log relative delay if non-zero
                    if default_audio_delay != 0 {
                        if let Some((track_id, _)) = &track_info {
                            ctx.logger.info(&format!(
                                "[Container Delay] Audio track {} relative delay (audio - video): {:+}ms. This will be added to correlation results.",
                                track_id, default_audio_delay
                            ));
                        }
                    } else {
                        ctx.logger.info("[Container Delay] Source 1 audio has no container delay relative to video (0ms)");
                    }

                    (default_audio_delay as f64, relative_delays, track_info)
                }
                Err(e) => {
                    ctx.logger.warn(&format!(
                        "Could not probe Source 1 for container delays: {} (assuming 0)",
                        e
                    ));
                    (0.0, HashMap::new(), None)
                }
            };

        // Store for potential per-track lookup later
        let _ = source1_container_delays; // Will be used for per-track delay selection
        let _ = source1_selected_track; // Track ID and language of selected track

        ctx.logger
            .info("--- Running Audio Correlation Analysis ---");

        // Multi-correlation only runs in analyze-only mode (like Python's `and (not ctx.and_merge)`)
        let multi_corr_enabled = settings.multi_correlation_enabled && ctx.analyze_only;

        if multi_corr_enabled {
            ctx.logger.info("Mode: Multi-Correlation Comparison");
        } else {
            ctx.logger.info(&format!(
                "Method: {:?}, SOXR: {}, Peak fit: {}",
                settings.correlation_method, settings.use_soxr, settings.audio_peak_fit
            ));
        }
        ctx.logger.info(&format!(
            "Chunks: {} x {}s, Range: {:.0}%-{:.0}%",
            settings.chunk_count,
            settings.chunk_duration,
            settings.scan_start_pct,
            settings.scan_end_pct
        ));

        // Log filtering if enabled
        if settings.filtering_method != crate::models::FilteringMethod::None {
            ctx.logger.info(&format!(
                "Audio filtering: {} (low={:.0}Hz, high={:.0}Hz)",
                settings.filtering_method, settings.filter_low_cutoff_hz, settings.filter_high_cutoff_hz
            ));
        }

        // ============================================================
        // PREPARE REFERENCE AUDIO (extract once, reuse for all sources)
        // ============================================================
        // Detect reference audio track
        let ref_tracks = get_audio_tracks(ref_path).map_err(|e| {
            StepError::invalid_input(format!("Failed to get audio tracks from Source 1: {}", e))
        })?;

        let ref_track_idx = find_track_by_language(&ref_tracks, settings.lang_source1.as_deref());

        ctx.logger.info(&format!(
            "Using audio tracks: reference={}",
            ref_track_idx.map_or("default".to_string(), |i| i.to_string())
        ));

        // Get reference duration
        let ref_duration = get_duration(ref_path).map_err(|e| {
            StepError::invalid_input(format!("Failed to get duration from Source 1: {}", e))
        })?;

        ctx.logger.info(&format!("Reference duration: {:.1}s", ref_duration));

        // Extract reference audio ONCE
        ctx.logger.info("Decoding reference audio...");
        let ref_audio = extract_full_audio(
            ref_path,
            DEFAULT_ANALYSIS_SAMPLE_RATE,
            settings.use_soxr,
            ref_track_idx,
        )
        .map_err(|e| {
            StepError::invalid_input(format!("Failed to extract audio from Source 1: {}", e))
        })?;

        ctx.logger.info(&format!(
            "Reference audio decoded: {:.1}s",
            ref_audio.duration()
        ));

        // ============================================================
        // ANALYZE EACH SOURCE
        // ============================================================
        let mut delays = Delays::new();
        let mut total_confidence = 0.0;
        let mut source_count = 0;
        let mut any_drift = false;
        let mut method_name = String::from("SCC");
        let mut source_stability: HashMap<String, SourceStability> = HashMap::new();

        // Source 1 always has 0 delay (it's the reference)
        delays.set_delay("Source 1", 0.0);
        // Source 1 has perfect stability (reference)
        source_stability.insert(
            "Source 1".to_string(),
            SourceStability {
                accepted_chunks: 0,
                total_chunks: 0,
                avg_match_pct: 100.0,
                delay_std_dev_ms: 0.0,
                drift_detected: false,
                acceptance_rate: 100.0,
            },
        );

        // Get sources sorted by name for consistent order
        let mut sources: Vec<_> = ctx.job_spec.sources.iter().collect();
        sources.sort_by_key(|(name, _)| *name);

        for (source_name, source_path) in sources {
            if source_name == "Source 1" {
                continue; // Skip reference source
            }

            ctx.logger.info(&format!(
                "Analyzing {}: {}",
                source_name,
                source_path
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
            ));

            // Get source duration
            let other_duration = get_duration(source_path).map_err(|e| {
                StepError::invalid_input(format!(
                    "Failed to get duration from {}: {}",
                    source_name, e
                ))
            })?;

            ctx.logger.info(&format!(
                "Reference: {:.1}s, {}: {:.1}s",
                ref_duration, source_name, other_duration
            ));

            // Use shorter duration for chunk calculation
            let effective_duration = ref_duration.min(other_duration);

            // Calculate chunk positions
            let chunk_config = ChunkConfig::from_settings(
                settings.chunk_count,
                settings.chunk_duration,
                settings.scan_start_pct,
                settings.scan_end_pct,
            );
            let chunk_positions = calculate_chunk_positions(effective_duration, &chunk_config);

            if chunk_positions.is_empty() {
                ctx.logger.error(&format!(
                    "{}: Video too short for chunk analysis",
                    source_name
                ));
                delays.set_delay(source_name, 0.0);
                source_stability.insert(
                    source_name.to_string(),
                    SourceStability {
                        accepted_chunks: 0,
                        total_chunks: 0,
                        avg_match_pct: 0.0,
                        delay_std_dev_ms: 0.0,
                        drift_detected: false,
                        acceptance_rate: 0.0,
                    },
                );
                continue;
            }

            ctx.logger.info(&format!(
                "Analyzing {} chunks of {}s each",
                chunk_positions.len(),
                settings.chunk_duration
            ));

            // Detect audio track
            let other_tracks = get_audio_tracks(source_path).map_err(|e| {
                StepError::invalid_input(format!(
                    "Failed to get audio tracks from {}: {}",
                    source_name, e
                ))
            })?;

            let other_track_idx =
                find_track_by_language(&other_tracks, settings.lang_others.as_deref());

            ctx.logger.info(&format!(
                "Using audio track: {}={}",
                source_name,
                other_track_idx.map_or("default".to_string(), |i| i.to_string())
            ));

            // Extract source audio
            ctx.logger.info(&format!("Decoding {} audio...", source_name));
            let other_audio = match extract_full_audio(
                source_path,
                DEFAULT_ANALYSIS_SAMPLE_RATE,
                settings.use_soxr,
                other_track_idx,
            ) {
                Ok(audio) => audio,
                Err(e) => {
                    ctx.logger.error(&format!(
                        "{}: Failed to extract audio - {}",
                        source_name, e
                    ));
                    delays.set_delay(source_name, 0.0);
                    source_stability.insert(
                        source_name.to_string(),
                        SourceStability {
                            accepted_chunks: 0,
                            total_chunks: 0,
                            avg_match_pct: 0.0,
                            delay_std_dev_ms: 0.0,
                            drift_detected: false,
                            acceptance_rate: 0.0,
                        },
                    );
                    continue;
                }
            };

            ctx.logger.info(&format!(
                "Audio decoded. Analyzing {} chunks...",
                chunk_positions.len()
            ));

            // Build correlation config
            let corr_config = CorrelationConfig {
                chunk_duration: settings.chunk_duration as f64,
                min_match_pct: settings.min_match_pct,
                use_peak_fit: settings.audio_peak_fit,
                sample_rate: DEFAULT_ANALYSIS_SAMPLE_RATE,
                filtering_method: settings.filtering_method,
                filter_low_cutoff_hz: settings.filter_low_cutoff_hz,
                filter_high_cutoff_hz: settings.filter_high_cutoff_hz,
            };

            // Build selector config
            let selector_config = SelectorConfig::from(settings);

            // Check if multi-correlation mode
            if multi_corr_enabled {
                // Multi-correlation: run all selected methods
                let methods = selected_methods(
                    settings.multi_corr_scc,
                    settings.multi_corr_gcc_phat,
                    settings.multi_corr_gcc_scot,
                    settings.multi_corr_whitened,
                    settings.multi_corr_onset,
                    settings.multi_corr_dtw,
                    settings.multi_corr_spectrogram,
                );

                ctx.logger.info(&format!(
                    "\n{}\n  MULTI-CORRELATION ANALYSIS: {}\n{}",
                    "═".repeat(70),
                    source_name,
                    "═".repeat(70)
                ));

                let mut first_result: Option<(String, i64, f64, f64, usize, usize, bool, StabilityMetrics)> = None;

                for method in &methods {
                    ctx.logger.info(&format!(
                        "\n{}\n  Method: {}\n{}",
                        "─".repeat(60),
                        method.name(),
                        "─".repeat(60)
                    ));

                    // Correlate chunks with this method
                    let chunk_results =
                        correlate_chunks(&ref_audio, &other_audio, &chunk_positions, method.as_ref(), &corr_config);

                    // Log each chunk result
                    let total_chunks = chunk_results.len();
                    for result in &chunk_results {
                        ctx.logger.info(&format!(
                            "    Chunk {:2}/{} (@{:.1}s): delay = {:+} ms (raw={:+.3}, match={:.2}) — {}",
                            result.chunk_index,
                            total_chunks,
                            result.chunk_start_secs,
                            result.delay_ms_rounded,
                            result.delay_ms_raw,
                            result.match_pct,
                            result.status_str()
                        ));
                    }

                    // Get accepted chunks
                    let accepted: Vec<_> = chunk_results.iter().filter(|c| c.accepted).cloned().collect();
                    let accepted_count = accepted.len();

                    if accepted_count < settings.min_accepted_chunks as usize {
                        ctx.logger.info(&format!(
                            "  {} FAILED: Insufficient chunks ({} accepted, need {})",
                            method.name(),
                            accepted_count,
                            settings.min_accepted_chunks
                        ));
                        continue;
                    }

                    // Select delay
                    let selector = get_selector(settings.delay_selection_mode);
                    let delay = match selector.select(&accepted, &selector_config) {
                        Some(d) => d,
                        None => {
                            ctx.logger.info(&format!(
                                "  {} FAILED: Could not select delay",
                                method.name()
                            ));
                            continue;
                        }
                    };

                    // Calculate average match
                    let avg_match = accepted.iter().map(|c| c.match_pct).sum::<f64>() / accepted_count as f64;

                    // Calculate stability
                    let stability = calculate_stability(&chunk_results, settings.min_match_pct);
                    let drift_detected = stability.delay_std_dev_ms > 50.0;

                    ctx.logger.info(&format!(
                        "  {} Result: {:+}ms (raw: {:+.3}ms) | match: {:.1}% | accepted: {}/{}",
                        method.name(),
                        delay.delay_ms_rounded,
                        delay.delay_ms_raw,
                        avg_match,
                        accepted_count,
                        total_chunks
                    ));

                    // Store first successful result
                    if first_result.is_none() {
                        first_result = Some((
                            method.name().to_string(),
                            delay.delay_ms_rounded,
                            delay.delay_ms_raw,
                            avg_match,
                            accepted_count,
                            total_chunks,
                            drift_detected,
                            stability,
                        ));
                    }
                }

                // Log summary
                ctx.logger.info(&format!(
                    "\n{}\n  MULTI-CORRELATION SUMMARY\n{}",
                    "═".repeat(70),
                    "═".repeat(70)
                ));

                // Use first result for actual delay
                if let Some((first_method, _, raw_delay, avg_match, accepted_count, total_chunks, drift, stability)) = first_result {
                    ctx.logger.info(&format!(
                        "{}: Using {} result: delay={:+.3}ms, match={:.1}%",
                        source_name, first_method, raw_delay, avg_match
                    ));

                    if drift {
                        ctx.logger.warn(&format!(
                            "{}: Drift detected - delays vary across chunks",
                            source_name
                        ));
                        any_drift = true;
                    }

                    // Apply container delay correction
                    let corrected_delay = raw_delay + source1_audio_container_delay;
                    delays.set_delay(source_name, corrected_delay);
                    total_confidence += avg_match / 100.0;
                    source_count += 1;
                    method_name = format!("Multi ({})", first_method);

                    // Convert StabilityMetrics to SourceStability
                    source_stability.insert(
                        source_name.to_string(),
                        SourceStability {
                            accepted_chunks: accepted_count,
                            total_chunks,
                            avg_match_pct: avg_match,
                            delay_std_dev_ms: stability.delay_std_dev_ms,
                            drift_detected: drift,
                            acceptance_rate: stability.acceptance_rate,
                        },
                    );
                } else {
                    ctx.logger.error(&format!(
                        "{}: All multi-correlation methods failed",
                        source_name
                    ));
                    delays.set_delay(source_name, 0.0);
                    source_stability.insert(
                        source_name.to_string(),
                        SourceStability {
                            accepted_chunks: 0,
                            total_chunks: 0,
                            avg_match_pct: 0.0,
                            delay_std_dev_ms: 0.0,
                            drift_detected: false,
                            acceptance_rate: 0.0,
                        },
                    );
                }
            } else {
                // Standard single-method analysis
                let method = create_from_enum(settings.correlation_method);

                // Correlate all chunks
                let chunk_results =
                    correlate_chunks(&ref_audio, &other_audio, &chunk_positions, method.as_ref(), &corr_config);

                // Log each chunk result
                let total_chunks = chunk_results.len();
                for result in &chunk_results {
                    ctx.logger.info(&format!(
                        "  Chunk {:2}/{} (@{:.1}s): delay = {:+} ms (raw={:+.3}, match={:.2}) — {}",
                        result.chunk_index,
                        total_chunks,
                        result.chunk_start_secs,
                        result.delay_ms_rounded,
                        result.delay_ms_raw,
                        result.match_pct,
                        result.status_str()
                    ));
                }

                // Get accepted chunks
                let accepted: Vec<_> = chunk_results.iter().filter(|c| c.accepted).cloned().collect();
                let accepted_count = accepted.len();

                if accepted_count < settings.min_accepted_chunks as usize {
                    ctx.logger.error(&format!(
                        "{}: Analysis failed - Insufficient chunks ({} accepted, need {})",
                        source_name,
                        accepted_count,
                        settings.min_accepted_chunks
                    ));
                    delays.set_delay(source_name, 0.0);
                    source_stability.insert(
                        source_name.to_string(),
                        SourceStability {
                            accepted_chunks: 0,
                            total_chunks,
                            avg_match_pct: 0.0,
                            delay_std_dev_ms: 0.0,
                            drift_detected: false,
                            acceptance_rate: 0.0,
                        },
                    );
                    continue;
                }

                // Select delay
                let selector = get_selector(settings.delay_selection_mode);
                let delay = match selector.select(&accepted, &selector_config) {
                    Some(d) => d,
                    None => {
                        ctx.logger.error(&format!(
                            "{}: Analysis failed - Could not select delay (delays too scattered?)",
                            source_name
                        ));
                        delays.set_delay(source_name, 0.0);
                        source_stability.insert(
                            source_name.to_string(),
                            SourceStability {
                                accepted_chunks: accepted_count,
                                total_chunks,
                                avg_match_pct: 0.0,
                                delay_std_dev_ms: 0.0,
                                drift_detected: false,
                                acceptance_rate: (accepted_count as f64 / total_chunks as f64) * 100.0,
                            },
                        );
                        continue;
                    }
                };

                // Log delay selection result
                if let Some(ref details) = delay.details {
                    ctx.logger.info(&format!(
                        "[{}] Found stable segment: {}",
                        delay.method_name, details
                    ));
                }
                ctx.logger.info(&format!(
                    "{} delay determined: {:+} ms ({}).",
                    source_name, delay.delay_ms_rounded, delay.method_name
                ));

                // Calculate average match percentage
                let avg_match = accepted.iter().map(|c| c.match_pct).sum::<f64>() / accepted_count as f64;

                // Calculate stability metrics
                let stability = calculate_stability(&chunk_results, settings.min_match_pct);

                ctx.logger.info(&format!(
                    "{}: delay={:+}ms, match={:.1}%, accepted={}/{}",
                    source_name,
                    delay.delay_ms_rounded,
                    avg_match,
                    accepted_count,
                    total_chunks
                ));

                // Drift detection
                let framerate = get_framerate(source_path).ok();
                let drift_config = DriftDetectionConfig::default();
                let drift_diagnosis = diagnose_drift(&chunk_results, &drift_config, framerate);

                if drift_diagnosis.drift_type != crate::analysis::DriftType::Uniform {
                    ctx.logger.warn(&format!(
                        "[Drift] {}: {}",
                        source_name, drift_diagnosis.description
                    ));
                    any_drift = true;
                } else if stability.delay_std_dev_ms > 50.0 {
                    // Basic drift check as fallback
                    ctx.logger.warn(&format!(
                        "{}: Drift detected - delays vary across chunks (std_dev={:.1}ms)",
                        source_name, stability.delay_std_dev_ms
                    ));
                    any_drift = true;
                }

                // Log stability metrics
                ctx.logger.info(&format!(
                    "{}: stability: acceptance={:.0}%, std_dev={:.1}ms",
                    source_name, stability.acceptance_rate, stability.delay_std_dev_ms
                ));

                // Apply container delay correction
                let corrected_delay = delay.delay_ms_raw + source1_audio_container_delay;
                delays.set_delay(source_name, corrected_delay);
                total_confidence += avg_match / 100.0;
                source_count += 1;
                method_name = method.name().to_string();

                // Convert StabilityMetrics to SourceStability
                source_stability.insert(
                    source_name.to_string(),
                    SourceStability {
                        accepted_chunks: accepted_count,
                        total_chunks,
                        avg_match_pct: avg_match,
                        delay_std_dev_ms: stability.delay_std_dev_ms,
                        drift_detected: any_drift,
                        acceptance_rate: stability.acceptance_rate,
                    },
                );
            }
        }

        // ============================================================
        // GLOBAL SHIFT CALCULATION
        // ============================================================
        ctx.logger.info("--- Calculating Global Shift ---");

        // Log pre-shift delays for debugging
        ctx.logger.info("Pre-shift delays (from correlation):");
        for (source, delay) in delays.pre_shift_delays_ms.iter() {
            ctx.logger.info(&format!("  {}: {:+.3}ms", source, delay));
        }

        // Apply global shift using module method (handles sync mode logic)
        let shift_applied = delays.apply_global_shift(sync_mode);

        if shift_applied > 0 {
            ctx.logger.info(&format!(
                "Applied global shift: +{}ms (to eliminate negative delays)",
                shift_applied
            ));
            // Log adjusted delays
            ctx.logger.info("Adjusted delays after global shift:");
            for (source, raw_delay) in delays.raw_source_delays_ms.iter() {
                let pre_shift = delays
                    .pre_shift_delays_ms
                    .get(source)
                    .copied()
                    .unwrap_or(0.0);
                ctx.logger.info(&format!(
                    "  {}: {:+.3}ms → {:+.3}ms",
                    source, pre_shift, raw_delay
                ));
            }
        } else if sync_mode == SyncMode::AllowNegative {
            ctx.logger
                .info("Allow negative mode - no global shift applied.");
        } else {
            ctx.logger
                .info("All delays are non-negative. No global shift needed.");
        }

        // ============================================================
        // FINALIZE
        // ============================================================
        let avg_confidence = if source_count > 0 {
            total_confidence / source_count as f64
        } else {
            0.0
        };

        // Log final delays
        ctx.logger.info(&format!(
            "=== FINAL DELAYS (Sync Mode: {}, Global Shift: +{}ms) ===",
            sync_mode, delays.global_shift_ms
        ));
        for (source, delay) in delays.source_delays_ms.iter() {
            ctx.logger.info(&format!("  {}: {:+}ms", source, delay));
        }

        // Log stability summary
        ctx.logger.info("=== STABILITY SUMMARY ===");
        for (source, stability) in &source_stability {
            if source == "Source 1" {
                continue; // Skip reference
            }
            let status = if stability.drift_detected {
                "DRIFT"
            } else if stability.acceptance_rate < 50.0 {
                "LOW"
            } else {
                "OK"
            };
            ctx.logger.info(&format!(
                "  {}: [{:>4}] accept={:.0}%, match={:.1}%, std_dev={:.1}ms",
                source,
                status,
                stability.acceptance_rate,
                stability.avg_match_pct,
                stability.delay_std_dev_ms
            ));
        }

        // Record analysis output
        state.analysis = Some(AnalysisOutput {
            delays,
            confidence: avg_confidence,
            drift_detected: any_drift,
            method: method_name,
            source_stability,
        });

        ctx.logger.success(&format!(
            "Analysis complete: {} source(s), avg confidence={:.1}%",
            source_count,
            avg_confidence * 100.0
        ));

        Ok(StepOutcome::Success)
    }

    fn validate_output(&self, _ctx: &Context, state: &JobState) -> StepResult<()> {
        if state.analysis.is_none() {
            return Err(StepError::invalid_output("Analysis results not recorded"));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn analyze_step_has_correct_name() {
        let step = AnalyzeStep::new();
        assert_eq!(step.name(), "Analyze");
    }
}
