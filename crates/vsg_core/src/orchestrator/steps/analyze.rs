//! Analyze step - calculates sync delays between sources.
//!
//! Uses audio cross-correlation to find the time offset between
//! a reference source (Source 1) and other sources.
//!
//! Handles:
//! - Remux-only mode (single source, no analysis needed)
//! - Multi-correlation comparison mode
//! - Container delay chain correction (adds Source 1 audio container delay)
//! - Global shift calculation to eliminate negative delays
//! - Sync mode (positive_only vs allow_negative)
//! - Per-source stability metrics

use std::collections::HashMap;

use crate::analysis::Analyzer;
use crate::extraction::probe_file;
use crate::models::{Delays, SyncMode};
use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{AnalysisOutput, Context, JobState, SourceStability, StepOutcome};

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
            return Err(StepError::invalid_input(
                "Source 1 (reference) is required",
            ));
        }

        // Note: Single source (remux-only) is valid - we skip analysis in execute()
        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.section("Audio Sync Analysis");

        // ============================================================
        // REMUX-ONLY MODE: Skip analysis if only Source 1 exists
        // ============================================================
        if ctx.job_spec.sources.len() == 1 {
            ctx.logger.info("Remux-only mode - no sync sources to analyze");

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
        let sync_mode = ctx.settings.analysis.sync_mode;
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
        // Container delays are embedded timing offsets in the file that need
        // to be added to correlation results for accurate sync.
        // We use mkvmerge -J to get minimum_timestamp per track, which is more
        // reliable than ffprobe's start_time for Matroska containers.
        let (source1_audio_container_delay, source1_container_delays) = match probe_file(ref_path) {
            Ok(probe) => {
                // Get all audio container delays relative to video
                let relative_delays = probe.get_audio_container_delays_relative();

                // Get delay for default audio track
                let default_audio_delay = probe
                    .default_audio()
                    .map(|t| t.container_delay_ms - probe.video_container_delay())
                    .unwrap_or(0);

                if default_audio_delay != 0 {
                    ctx.logger.info(&format!(
                        "Source 1 audio container delay: {:+}ms (will be added to correlation results)",
                        default_audio_delay
                    ));

                    // Log per-track delays if they differ
                    for track in probe.audio_tracks() {
                        let relative = track.container_delay_ms - probe.video_container_delay();
                        if relative != default_audio_delay {
                            ctx.logger.info(&format!(
                                "  Track {} ({}): {:+}ms",
                                track.id,
                                track.language.as_deref().unwrap_or("und"),
                                relative
                            ));
                        }
                    }
                }

                (default_audio_delay as f64, relative_delays)
            }
            Err(e) => {
                ctx.logger.warn(&format!(
                    "Could not probe Source 1 for container delays: {} (assuming 0)",
                    e
                ));
                (0.0, HashMap::new())
            }
        };

        // Store for potential per-track lookup later
        let _ = source1_container_delays; // Will be used for per-track delay selection

        // Create analyzer from settings with job logger for detailed progress
        let analyzer = Analyzer::from_settings(&ctx.settings.analysis)
            .with_logger(ctx.logger.clone());

        if ctx.settings.analysis.multi_correlation_enabled {
            ctx.logger.info("Mode: Multi-Correlation Comparison");
        } else {
            ctx.logger.info(&format!(
                "Method: {:?}, SOXR: {}, Peak fit: {}",
                ctx.settings.analysis.correlation_method,
                ctx.settings.analysis.use_soxr,
                ctx.settings.analysis.audio_peak_fit
            ));
        }
        ctx.logger.info(&format!(
            "Chunks: {} x {}s, Range: {:.0}%-{:.0}%",
            ctx.settings.analysis.chunk_count,
            ctx.settings.analysis.chunk_duration,
            ctx.settings.analysis.scan_start_pct,
            ctx.settings.analysis.scan_end_pct
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
                source_path.file_name().unwrap_or_default().to_string_lossy()
            ));

            // Check if multi-correlation mode is enabled
            if ctx.settings.analysis.multi_correlation_enabled {
                // Multi-correlation: run all selected methods and compare
                match analyzer.analyze_multi_correlation(ref_path, source_path, source_name) {
                    Ok(results) => {
                        // Log summary of all methods
                        ctx.logger.info(&format!(
                            "{}: Multi-correlation comparison ({} methods)",
                            source_name,
                            results.len()
                        ));

                        // Use the first available result for the actual delay
                        // (multi-correlation is primarily for comparison/analysis)
                        if let Some((first_method, first_result)) = results.iter().next() {
                            ctx.logger.info(&format!(
                                "{}: Using {} result: delay={:+}ms, match={:.1}%",
                                source_name,
                                first_method,
                                first_result.delay_ms_rounded(),
                                first_result.avg_match_pct
                            ));

                            if first_result.drift_detected {
                                ctx.logger.warn(&format!(
                                    "{}: Drift detected - delays vary across chunks",
                                    source_name
                                ));
                                any_drift = true;
                            }

                            // Apply container delay correction
                            let corrected_delay = first_result.delay_ms_raw() + source1_audio_container_delay;
                            delays.set_delay(source_name, corrected_delay);
                            total_confidence += first_result.avg_match_pct / 100.0;
                            source_count += 1;
                            method_name = format!("Multi ({})", first_method);

                            // Calculate stability metrics
                            let accepted_delays: Vec<f64> = first_result
                                .chunk_results
                                .iter()
                                .filter(|c| c.match_pct >= ctx.settings.analysis.min_match_pct)
                                .map(|c| c.delay_ms_raw)
                                .collect();
                            let std_dev = if accepted_delays.len() > 1 {
                                let mean = accepted_delays.iter().sum::<f64>() / accepted_delays.len() as f64;
                                let variance = accepted_delays.iter().map(|d| (d - mean).powi(2)).sum::<f64>()
                                    / accepted_delays.len() as f64;
                                variance.sqrt()
                            } else {
                                0.0
                            };

                            source_stability.insert(
                                source_name.to_string(),
                                SourceStability {
                                    accepted_chunks: first_result.accepted_chunks,
                                    total_chunks: first_result.total_chunks,
                                    avg_match_pct: first_result.avg_match_pct,
                                    delay_std_dev_ms: std_dev,
                                    drift_detected: first_result.drift_detected,
                                    acceptance_rate: first_result.acceptance_rate(),
                                },
                            );
                        }
                    }
                    Err(e) => {
                        ctx.logger.error(&format!(
                            "{}: Multi-correlation analysis failed - {}",
                            source_name, e
                        ));
                        delays.set_delay(source_name, 0.0);
                        // Record failed analysis stability
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
                }
            } else {
                // Standard single-method analysis
                match analyzer.analyze(ref_path, source_path, source_name) {
                    Ok(result) => {
                        ctx.logger.info(&format!(
                            "{}: delay={:+}ms, match={:.1}%, accepted={}/{}",
                            source_name,
                            result.delay_ms_rounded(),
                            result.avg_match_pct,
                            result.accepted_chunks,
                            result.total_chunks
                        ));

                        if result.drift_detected {
                            ctx.logger.warn(&format!(
                                "{}: Drift detected - delays vary across chunks",
                                source_name
                            ));
                            any_drift = true;
                        }

                        // Apply container delay correction
                        let corrected_delay = result.delay_ms_raw() + source1_audio_container_delay;
                        delays.set_delay(source_name, corrected_delay);
                        total_confidence += result.avg_match_pct / 100.0;
                        source_count += 1;
                        method_name = result.correlation_method.clone();

                        // Calculate stability metrics
                        let accepted_delays: Vec<f64> = result
                            .chunk_results
                            .iter()
                            .filter(|c| c.match_pct >= ctx.settings.analysis.min_match_pct)
                            .map(|c| c.delay_ms_raw)
                            .collect();
                        let std_dev = if accepted_delays.len() > 1 {
                            let mean = accepted_delays.iter().sum::<f64>() / accepted_delays.len() as f64;
                            let variance = accepted_delays.iter().map(|d| (d - mean).powi(2)).sum::<f64>()
                                / accepted_delays.len() as f64;
                            variance.sqrt()
                        } else {
                            0.0
                        };

                        // Log stability metrics
                        ctx.logger.info(&format!(
                            "{}: stability: acceptance={:.0}%, std_dev={:.1}ms",
                            source_name,
                            result.acceptance_rate(),
                            std_dev
                        ));

                        source_stability.insert(
                            source_name.to_string(),
                            SourceStability {
                                accepted_chunks: result.accepted_chunks,
                                total_chunks: result.total_chunks,
                                avg_match_pct: result.avg_match_pct,
                                delay_std_dev_ms: std_dev,
                                drift_detected: result.drift_detected,
                                acceptance_rate: result.acceptance_rate(),
                            },
                        );
                    }
                    Err(e) => {
                        ctx.logger.error(&format!(
                            "{}: Analysis failed - {}",
                            source_name, e
                        ));
                        // Set zero delay for failed source
                        delays.set_delay(source_name, 0.0);
                        // Record failed analysis stability
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
                }
            }
        }

        // ============================================================
        // GLOBAL SHIFT CALCULATION
        // ============================================================
        // Find most negative delay and apply shift if sync_mode is PositiveOnly
        ctx.logger.info("--- Calculating Global Shift ---");

        // Log pre-shift delays for debugging
        ctx.logger.info("Pre-shift delays (from correlation):");
        for (source, delay) in delays.pre_shift_delays_ms.iter() {
            ctx.logger.info(&format!("  {}: {:+.3}ms", source, delay));
        }

        let most_negative_raw = delays.raw_source_delays_ms
            .values()
            .cloned()
            .fold(0.0_f64, |min, val| min.min(val));

        if most_negative_raw < 0.0 && sync_mode == SyncMode::PositiveOnly {
            // Calculate shift to eliminate negative delays
            let raw_shift = most_negative_raw.abs();
            let rounded_shift = raw_shift.round() as i64;

            ctx.logger.info(&format!(
                "Most negative delay: {:.3}ms",
                most_negative_raw
            ));
            ctx.logger.info(&format!(
                "Applying global shift: +{:.3}ms (rounded: +{}ms)",
                raw_shift, rounded_shift
            ));

            // Store the shift
            delays.raw_global_shift_ms = raw_shift;
            delays.global_shift_ms = rounded_shift;

            // Apply shift to all delays (but keep pre_shift_delays_ms unchanged)
            ctx.logger.info("Adjusted delays after global shift:");
            for (source, raw_delay) in delays.raw_source_delays_ms.iter_mut() {
                let original = *raw_delay;
                *raw_delay += raw_shift;
                ctx.logger.info(&format!(
                    "  {}: {:+.3}ms → {:+.3}ms (shift applied ONCE)",
                    source, original, *raw_delay
                ));
            }

            // Update rounded delays too
            for (source, rounded_delay) in delays.source_delays_ms.iter_mut() {
                let raw = delays.raw_source_delays_ms.get(source).copied().unwrap_or(0.0);
                *rounded_delay = raw.round() as i64;
            }
        } else if most_negative_raw < 0.0 && sync_mode == SyncMode::AllowNegative {
            ctx.logger.info(&format!(
                "Most negative delay: {:.3}ms (kept as-is, allow_negative mode)",
                most_negative_raw
            ));
        } else {
            ctx.logger.info("All delays are non-negative. No global shift needed.");
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
            sync_mode,
            delays.global_shift_ms
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
                source, status, stability.acceptance_rate, stability.avg_match_pct, stability.delay_std_dev_ms
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
