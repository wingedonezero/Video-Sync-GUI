//! Audio Correction step - applies timing adjustments to audio tracks.
//!
//! This is currently a stub that passes through without processing.
//! Real implementation will handle:
//! - Applying calculated delays to audio tracks
//! - Re-encoding audio with timing offsets
//! - Sample-accurate sync adjustments

use crate::orchestrator::errors::StepResult;
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{Context, CorrectionOutput, JobState, StepOutcome};

/// Audio Correction step for applying timing adjustments.
///
/// Currently a stub - passes through without modifications.
/// Future implementation will apply calculated delays from analysis.
pub struct AudioCorrectionStep;

impl AudioCorrectionStep {
    pub fn new() -> Self {
        Self
    }
}

impl Default for AudioCorrectionStep {
    fn default() -> Self {
        Self::new()
    }
}

impl PipelineStep for AudioCorrectionStep {
    fn name(&self) -> &str {
        "AudioCorrection"
    }

    fn description(&self) -> &str {
        "Apply timing corrections to audio tracks"
    }

    fn validate_input(&self, _ctx: &Context) -> StepResult<()> {
        // No strict requirements for stub
        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger
            .info("Audio correction step (stub) - passing through without processing");

        // Check if we have analysis data with delays
        let has_delays = state
            .analysis
            .as_ref()
            .map(|a| !a.delays.source_delays_ms.is_empty())
            .unwrap_or(false);

        if !has_delays {
            ctx.logger
                .info("No audio delays calculated - skipping correction");
            state.correction = Some(CorrectionOutput {
                correction_type: "none".to_string(),
                corrected_files: std::collections::HashMap::new(),
            });
            return Ok(StepOutcome::Skipped("No audio delays".to_string()));
        }

        // Stub: For now, we'll use mkvmerge's --sync option instead of
        // actually re-encoding audio. This means delays are applied at mux time.
        // Real implementation would:
        // 1. Decode audio to PCM
        // 2. Apply sample-accurate delay
        // 3. Re-encode to original codec

        state.correction = Some(CorrectionOutput {
            correction_type: "sync_delay".to_string(),
            corrected_files: std::collections::HashMap::new(),
        });

        ctx.logger.info(
            "Audio correction complete (stub - delays will be applied at mux time via --sync)",
        );
        Ok(StepOutcome::Success)
    }

    fn validate_output(&self, _ctx: &Context, _state: &JobState) -> StepResult<()> {
        // Audio correction is optional
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
    fn audio_correction_step_has_correct_name() {
        let step = AudioCorrectionStep::new();
        assert_eq!(step.name(), "AudioCorrection");
    }

    #[test]
    fn audio_correction_step_is_optional() {
        let step = AudioCorrectionStep::new();
        assert!(step.is_optional());
    }
}
