//! Subtitles step - processes subtitle tracks (sync, OCR, style operations).
//!
//! This is currently a stub that passes through without processing.
//! Real implementation will handle:
//! - Style filtering for generated tracks
//! - Time-based sync adjustments
//! - OCR for image-based subtitles
//! - Style operations (font replacement, rescaling)

use crate::orchestrator::errors::StepResult;
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{Context, JobState, StepOutcome, SubtitlesOutput};

/// Subtitles step for processing subtitle tracks.
///
/// Currently a stub - passes through without modifications.
/// Future implementation will handle sync adjustments, OCR, and styling.
pub struct SubtitlesStep;

impl SubtitlesStep {
    pub fn new() -> Self {
        Self
    }
}

impl Default for SubtitlesStep {
    fn default() -> Self {
        Self::new()
    }
}

impl PipelineStep for SubtitlesStep {
    fn name(&self) -> &str {
        "Subtitles"
    }

    fn description(&self) -> &str {
        "Process subtitle tracks (sync, OCR, styling)"
    }

    fn validate_input(&self, _ctx: &Context) -> StepResult<()> {
        // No strict requirements
        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger
            .info("Subtitles step (stub) - passing through without processing");

        // Check if there are any subtitle tracks to process
        let has_subtitles = ctx
            .job_spec
            .manual_layout
            .as_ref()
            .map(|layout| {
                layout.iter().any(|item| {
                    item.get("type")
                        .and_then(|v| v.as_str())
                        .map(|t| t == "subtitles")
                        .unwrap_or(false)
                })
            })
            .unwrap_or(false);

        if !has_subtitles {
            ctx.logger.info("No subtitle tracks in layout - skipping");
            state.subtitles = Some(SubtitlesOutput::default());
            return Ok(StepOutcome::Skipped("No subtitle tracks".to_string()));
        }

        // Stub: record empty results
        // Real implementation would process each subtitle track
        state.subtitles = Some(SubtitlesOutput {
            processed_files: std::collections::HashMap::new(),
            ocr_performed: false,
        });

        ctx.logger
            .info("Subtitle processing complete (stub - using extracted files directly)");
        Ok(StepOutcome::Success)
    }

    fn validate_output(&self, _ctx: &Context, _state: &JobState) -> StepResult<()> {
        // Subtitles are optional
        Ok(())
    }

    fn is_optional(&self) -> bool {
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn subtitles_step_has_correct_name() {
        let step = SubtitlesStep::new();
        assert_eq!(step.name(), "Subtitles");
    }

    #[test]
    fn subtitles_step_is_optional() {
        let step = SubtitlesStep::new();
        assert!(step.is_optional());
    }
}
