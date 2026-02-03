//! Attachments step - extracts attachments (fonts, etc.) from source files.
//!
//! Extracts attachments from sources specified by the user in the layout,
//! placing them in the work directory for inclusion in the final mux.

use crate::extraction::{extract_all_attachments, has_attachments};
use crate::orchestrator::errors::StepResult;
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{Context, JobState, StepOutcome};

/// Attachments step for extracting fonts and other attachments.
///
/// Uses the extraction module to pull attachments from MKV containers.
/// Attachments are added to the merge plan for inclusion in the final output.
pub struct AttachmentsStep;

impl AttachmentsStep {
    pub fn new() -> Self {
        Self
    }
}

impl Default for AttachmentsStep {
    fn default() -> Self {
        Self::new()
    }
}

impl PipelineStep for AttachmentsStep {
    fn name(&self) -> &str {
        "Attachments"
    }

    fn description(&self) -> &str {
        "Extract attachments (fonts, etc.) from sources"
    }

    fn validate_input(&self, _ctx: &Context) -> StepResult<()> {
        // No strict requirements - attachments are optional
        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.info("Extracting attachments...");

        // Get attachment sources from job spec
        // If not specified, default to Source 1 only
        let attachment_sources: Vec<String> = if ctx.job_spec.attachment_sources.is_empty() {
            ctx.logger
                .info("No attachment sources specified - defaulting to Source 1");
            vec!["Source 1".to_string()]
        } else {
            ctx.logger.info(&format!(
                "Using specified attachment sources: {:?}",
                ctx.job_spec.attachment_sources
            ));
            ctx.job_spec.attachment_sources.clone()
        };

        if attachment_sources.is_empty() {
            ctx.logger
                .info("No attachment sources specified - skipping");
            return Ok(StepOutcome::Skipped("No attachment sources".to_string()));
        }

        // Create attachments subdirectory
        let attach_dir = ctx.work_dir.join("attachments");

        let mut total_attachments = 0;

        for source_key in &attachment_sources {
            if let Some(source_path) = ctx.job_spec.sources.get(source_key) {
                ctx.logger
                    .info(&format!("Processing attachments from {}...", source_key));

                // Check if source has attachments
                match has_attachments(source_path) {
                    Ok(true) => {
                        // Extract all attachments using the extraction module
                        match extract_all_attachments(source_path, &attach_dir) {
                            Ok(result) => {
                                let count = result.files.len();
                                ctx.logger.info(&format!(
                                    "  Extracted {} attachment(s) from {}",
                                    count, source_key
                                ));

                                // Add attachments to extract output
                                if let Some(ref mut extract) = state.extract {
                                    for path in result.files {
                                        let key = format!(
                                            "attachment_{}",
                                            path.file_name().unwrap_or_default().to_string_lossy()
                                        );
                                        extract.attachments.insert(key, path);
                                    }
                                }

                                total_attachments += count;
                            }
                            Err(e) => {
                                ctx.logger.warn(&format!(
                                    "  Failed to extract attachments from {}: {}",
                                    source_key, e
                                ));
                            }
                        }
                    }
                    Ok(false) => {
                        ctx.logger
                            .info(&format!("  No attachments found in {}", source_key));
                    }
                    Err(e) => {
                        ctx.logger.warn(&format!(
                            "  Failed to check attachments in {}: {}",
                            source_key, e
                        ));
                    }
                }
            }
        }

        ctx.logger.info(&format!(
            "Attachment extraction complete: {} attachment(s) found",
            total_attachments
        ));

        Ok(StepOutcome::Success)
    }

    fn validate_output(&self, _ctx: &Context, _state: &JobState) -> StepResult<()> {
        // Attachments are optional, so no validation needed
        Ok(())
    }

    fn is_optional(&self) -> bool {
        // Attachments are always optional
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn attachments_step_has_correct_name() {
        let step = AttachmentsStep::new();
        assert_eq!(step.name(), "Attachments");
    }

    #[test]
    fn attachments_step_is_optional() {
        let step = AttachmentsStep::new();
        assert!(step.is_optional());
    }
}
