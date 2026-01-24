//! Extract step - extracts tracks and attachments from sources.
//!
//! This is currently a stub that passes through without extracting.
//! Real implementation will use ffmpeg/mkvextract to extract tracks.

use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{Context, ExtractOutput, JobState, StepOutcome};

/// Extract step for extracting tracks from source files.
///
/// Currently a stub - just records empty extraction results.
/// Real implementation will:
/// - Extract video track from primary source
/// - Extract audio tracks that need correction
/// - Extract attachments (fonts, etc.)
pub struct ExtractStep;

impl ExtractStep {
    pub fn new() -> Self {
        Self
    }
}

impl Default for ExtractStep {
    fn default() -> Self {
        Self::new()
    }
}

impl PipelineStep for ExtractStep {
    fn name(&self) -> &str {
        "Extract"
    }

    fn description(&self) -> &str {
        "Extract tracks and attachments from sources"
    }

    fn validate_input(&self, ctx: &Context) -> StepResult<()> {
        // Check that analysis was completed
        if !ctx.job_spec.sources.contains_key("Source 1") {
            return Err(StepError::invalid_input("No primary source (Source 1)"));
        }
        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger
            .info("Extract step (stub) - no extraction performed");

        // Stub: record empty extraction results
        // Real implementation would extract tracks that need processing
        state.extract = Some(ExtractOutput::default());

        ctx.logger
            .info("Extraction complete (stub - using source files directly)");
        Ok(StepOutcome::Success)
    }

    fn validate_output(&self, _ctx: &Context, state: &JobState) -> StepResult<()> {
        if state.extract.is_none() {
            return Err(StepError::invalid_output(
                "Extraction results not recorded",
            ));
        }
        Ok(())
    }

    fn is_optional(&self) -> bool {
        // Extraction may be skipped if no tracks need processing
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_step_has_correct_name() {
        let step = ExtractStep::new();
        assert_eq!(step.name(), "Extract");
    }

    #[test]
    fn extract_step_is_optional() {
        let step = ExtractStep::new();
        assert!(step.is_optional());
    }
}
