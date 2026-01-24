//! Analyze step - calculates sync delays between sources.
//!
//! Uses audio cross-correlation to find the time offset between
//! a reference source (Source 1) and other sources.

use crate::analysis::Analyzer;
use crate::models::Delays;
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
        // Check that we have at least two sources
        if ctx.job_spec.sources.len() < 2 {
            return Err(StepError::invalid_input(
                "At least two sources required for analysis",
            ));
        }

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

        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.section("Audio Sync Analysis");

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

        // Create analyzer from settings
        let analyzer = Analyzer::from_settings(&ctx.settings.analysis);

        ctx.logger.info(&format!(
            "Method: SCC, SOXR: {}, Peak fit: {}",
            ctx.settings.analysis.use_soxr, ctx.settings.analysis.audio_peak_fit
        ));
        ctx.logger.info(&format!(
            "Chunks: {} x {}s, Range: {:.0}%-{:.0}%",
            ctx.settings.analysis.chunk_count,
            ctx.settings.analysis.chunk_duration,
            ctx.settings.analysis.scan_start_pct,
            ctx.settings.analysis.scan_end_pct
        ));

        // Analyze each non-reference source
        let mut delays = Delays::new();
        let mut total_confidence = 0.0;
        let mut source_count = 0;
        let mut any_drift = false;
        let mut method_name = String::from("SCC");

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

            match analyzer.analyze(ref_path, source_path, source_name) {
                Ok(result) => {
                    ctx.logger.info(&format!(
                        "{}: delay={:.2}ms, confidence={:.1}%, valid={}/{}",
                        source_name,
                        result.delay_ms,
                        result.confidence * 100.0,
                        result.valid_chunks,
                        result.total_chunks
                    ));

                    if result.drift_detected {
                        ctx.logger.warn(&format!(
                            "{}: Drift detected - delays vary across chunks",
                            source_name
                        ));
                        any_drift = true;
                    }

                    delays.set_delay(source_name, result.delay_ms);
                    total_confidence += result.confidence;
                    source_count += 1;
                    method_name = result.method;
                }
                Err(e) => {
                    ctx.logger.error(&format!(
                        "{}: Analysis failed - {}",
                        source_name, e
                    ));
                    // Set zero delay for failed source
                    delays.set_delay(source_name, 0.0);
                }
            }
        }

        // Calculate average confidence
        let avg_confidence = if source_count > 0 {
            total_confidence / source_count as f64
        } else {
            0.0
        };

        // Record analysis output
        state.analysis = Some(AnalysisOutput {
            delays,
            confidence: avg_confidence,
            drift_detected: any_drift,
            method: method_name,
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
