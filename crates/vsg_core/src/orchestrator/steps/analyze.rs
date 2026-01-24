//! Analyze step - calculates sync delays between sources.
//!
//! This is currently a stub that passes through without doing real analysis.
//! Real implementation will perform audio cross-correlation.

use crate::models::Delays;
use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{AnalysisOutput, Context, JobState, StepOutcome};

/// Analyze step for calculating sync delays.
///
/// Currently a stub - just records placeholder delays.
/// Real implementation will:
/// - Extract audio samples from sources
/// - Run cross-correlation to find offset
/// - Detect drift/stepping patterns
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
        // Check that we have at least one source
        if ctx.job_spec.sources.is_empty() {
            return Err(StepError::invalid_input("No sources provided"));
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

        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.info("Analyze step (stub) - using zero delays");

        // Stub: create zero delays for all sources
        let mut delays = Delays::new();
        for source_name in ctx.job_spec.sources.keys() {
            if source_name != "Source 1" {
                // Source 1 is reference, others get delay relative to it
                delays.set_delay(source_name, 0.0);
                ctx.logger
                    .info(&format!("{}: 0ms (stub)", source_name));
            }
        }

        // Record analysis output
        state.analysis = Some(AnalysisOutput {
            delays,
            confidence: 1.0, // Stub confidence
            drift_detected: false,
            method: "stub".to_string(),
        });

        ctx.logger.info("Analysis complete (stub - no real correlation)");
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
