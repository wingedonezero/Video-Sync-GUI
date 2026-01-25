//! Extract step - reads container info and extracts tracks/attachments.
//!
//! This step is essential for the pipeline because it:
//! 1. Reads container delays from all sources (required for correct sync)
//! 2. Optionally extracts tracks that need processing
//! 3. Extracts attachments (fonts) from selected sources
//!
//! For MVP, actual track extraction is skipped - source files are used directly.
//! Container info reading is always performed as it's essential for delay calculation.

use std::collections::HashMap;
use std::path::PathBuf;

use crate::extraction::{
    extract_fonts, read_container_info, ContainerInfo, ExtractionError,
};
use crate::jobs::ManualLayout;
use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{Context, ExtractOutput, JobState, StepOutcome};

/// Extract step for reading container info and extracting tracks/attachments.
///
/// # What This Step Does
///
/// 1. **Read Container Info** (always):
///    - Reads `minimum_timestamp` from each track in all sources
///    - This is essential for Source 1 A/V sync preservation
///    - Without this, audio from Source 1 would be out of sync
///
/// 2. **Extract Tracks** (future):
///    - Currently skipped - uses source files directly
///    - Will extract tracks that need processing (audio correction, etc.)
///
/// 3. **Extract Attachments** (if configured):
///    - Extracts fonts from sources specified in the layout
///    - Fonts are needed for proper subtitle rendering
pub struct ExtractStep;

impl ExtractStep {
    pub fn new() -> Self {
        Self
    }

    /// Read container info from all sources.
    fn read_all_container_info(
        &self,
        ctx: &Context,
    ) -> Result<HashMap<String, ContainerInfo>, ExtractionError> {
        let mut container_info = HashMap::new();

        for (source_key, source_path) in &ctx.job_spec.sources {
            ctx.logger.info(&format!(
                "Reading container info from {} ({})",
                source_key,
                source_path.file_name().unwrap_or_default().to_string_lossy()
            ));

            let info = read_container_info(source_key, source_path)?;

            // Log container delays for debugging
            if source_key == "Source 1" {
                ctx.logger.debug(&format!(
                    "  Video track delay: {}ms",
                    info.video_delay_ms
                ));
                for (track_id, delay_ms) in &info.track_delays_ms {
                    if Some(*track_id) != info.video_track_id {
                        let relative = delay_ms - info.video_delay_ms;
                        ctx.logger.debug(&format!(
                            "  Track {} delay: {}ms (relative: {}ms)",
                            track_id, delay_ms, relative
                        ));
                    }
                }
            }

            container_info.insert(source_key.clone(), info);
        }

        Ok(container_info)
    }

    /// Extract attachments from specified sources.
    fn extract_attachments(
        &self,
        ctx: &Context,
        layout: &ManualLayout,
    ) -> HashMap<String, PathBuf> {
        let mut attachments = HashMap::new();

        for source_key in &layout.attachment_sources {
            if let Some(source_path) = ctx.job_spec.sources.get(source_key) {
                let output_dir = ctx.work_dir.join("attachments").join(source_key);

                ctx.logger.info(&format!(
                    "Extracting fonts from {}",
                    source_key
                ));

                match extract_fonts(source_key, source_path, &output_dir) {
                    Ok(extracted) => {
                        ctx.logger.info(&format!(
                            "  Extracted {} fonts",
                            extracted.len()
                        ));
                        for attachment in extracted {
                            let key = format!(
                                "{}:{}",
                                source_key,
                                attachment.file_name
                            );
                            attachments.insert(key, attachment.extracted_path);
                        }
                    }
                    Err(e) => {
                        // Attachment extraction failure is non-fatal
                        ctx.logger.warn(&format!(
                            "  Failed to extract fonts: {}",
                            e
                        ));
                    }
                }
            }
        }

        attachments
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
        "Read container info and extract tracks/attachments"
    }

    fn validate_input(&self, ctx: &Context) -> StepResult<()> {
        // Must have at least Source 1
        if !ctx.job_spec.sources.contains_key("Source 1") {
            return Err(StepError::invalid_input("No primary source (Source 1)"));
        }

        // Verify source files exist
        for (source_key, source_path) in &ctx.job_spec.sources {
            if !source_path.exists() {
                return Err(StepError::invalid_input(format!(
                    "{} file not found: {}",
                    source_key,
                    source_path.display()
                )));
            }
        }

        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.section("Reading Container Info");

        // Step 1: Read container info from all sources (ESSENTIAL)
        let container_info = self.read_all_container_info(ctx).map_err(|e| {
            StepError::other(format!("Failed to read container info: {}", e))
        })?;

        ctx.logger.info(&format!(
            "Read container info from {} sources",
            container_info.len()
        ));

        // Step 2: Extract attachments (if configured)
        let attachments = if let Some(ref layout) = ctx.job_spec.manual_layout {
            // Convert from JSON layout to ManualLayout
            // For now, check if there are attachment_sources in the layout
            let manual_layout = serde_json::from_value::<ManualLayout>(
                serde_json::to_value(layout).unwrap_or_default()
            ).unwrap_or_default();

            if !manual_layout.attachment_sources.is_empty() {
                ctx.logger.section("Extracting Attachments");
                self.extract_attachments(ctx, &manual_layout)
            } else {
                HashMap::new()
            }
        } else {
            HashMap::new()
        };

        if !attachments.is_empty() {
            ctx.logger.info(&format!(
                "Extracted {} total attachments",
                attachments.len()
            ));
        }

        // Step 3: Track extraction (skipped for MVP)
        // In the future, this would extract tracks that need processing:
        // - Audio tracks needing drift/stepping correction
        // - Subtitles needing OCR or style processing
        let tracks = HashMap::new();
        ctx.logger.debug("Track extraction skipped (using source files directly)");

        // Record output
        state.extract = Some(ExtractOutput {
            container_info,
            tracks,
            attachments,
        });

        ctx.logger.success("Extraction complete");
        Ok(StepOutcome::Success)
    }

    fn validate_output(&self, _ctx: &Context, state: &JobState) -> StepResult<()> {
        let extract = state.extract.as_ref().ok_or_else(|| {
            StepError::invalid_output("Extraction results not recorded")
        })?;

        // Must have container info for Source 1 at minimum
        if !extract.container_info.contains_key("Source 1") {
            return Err(StepError::invalid_output(
                "Missing container info for Source 1",
            ));
        }

        Ok(())
    }

    fn is_optional(&self) -> bool {
        // Extraction is NOT optional - container info is required for correct delays
        false
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
    fn extract_step_is_not_optional() {
        let step = ExtractStep::new();
        // Container info reading is essential, so this step is NOT optional
        assert!(!step.is_optional());
    }
}
