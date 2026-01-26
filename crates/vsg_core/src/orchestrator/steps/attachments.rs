//! Attachments step - extracts attachments (fonts, etc.) from source files.
//!
//! Extracts attachments from sources specified by the user in the layout,
//! placing them in the work directory for inclusion in the final mux.

use std::path::PathBuf;
use std::process::Command;

use crate::orchestrator::errors::StepResult;
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{Context, JobState, StepOutcome};

/// Attachments step for extracting fonts and other attachments.
///
/// Uses mkvextract to pull attachments from MKV containers.
/// Attachments are added to the merge plan for inclusion in the final output.
pub struct AttachmentsStep;

impl AttachmentsStep {
    pub fn new() -> Self {
        Self
    }

    /// Extract all attachments from a source file.
    fn extract_attachments(
        &self,
        source_path: &PathBuf,
        work_dir: &PathBuf,
        source_key: &str,
        mkvextract_path: &str,
        logger: &crate::logging::JobLogger,
    ) -> Vec<PathBuf> {
        let mut attachments = Vec::new();

        // First, get attachment info using mkvmerge -J
        let mkvmerge_path = mkvextract_path.replace("mkvextract", "mkvmerge");
        let info_output = Command::new(&mkvmerge_path)
            .arg("-J")
            .arg(source_path)
            .output();

        let attachment_ids: Vec<usize> = match info_output {
            Ok(output) if output.status.success() => {
                let json_str = String::from_utf8_lossy(&output.stdout);
                // Parse JSON to find attachments
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&json_str) {
                    json.get("attachments")
                        .and_then(|a| a.as_array())
                        .map(|arr| {
                            arr.iter()
                                .filter_map(|att| att.get("id").and_then(|id| id.as_u64()))
                                .map(|id| id as usize)
                                .collect()
                        })
                        .unwrap_or_default()
                } else {
                    Vec::new()
                }
            }
            _ => Vec::new(),
        };

        if attachment_ids.is_empty() {
            logger.info(&format!("  No attachments found in {}", source_key));
            return attachments;
        }

        logger.info(&format!(
            "  Found {} attachment(s) in {}",
            attachment_ids.len(),
            source_key
        ));

        // Create attachments subdirectory
        let attach_dir = work_dir.join("attachments");
        if let Err(e) = std::fs::create_dir_all(&attach_dir) {
            logger.warn(&format!("Failed to create attachments directory: {}", e));
            return attachments;
        }

        // Extract each attachment
        // mkvextract attachments <source> <id>:<output>
        let mut extract_args = vec!["attachments".to_string(), source_path.to_string_lossy().to_string()];

        for id in &attachment_ids {
            // Output path includes source key prefix to avoid collisions
            let output_path = attach_dir.join(format!(
                "{}_{}_attachment{}",
                source_key.replace(" ", "_").to_lowercase(),
                source_path.file_stem().unwrap_or_default().to_string_lossy(),
                id
            ));
            extract_args.push(format!("{}:{}", id, output_path.display()));
        }

        let extract_output = Command::new(mkvextract_path)
            .args(&extract_args)
            .output();

        match extract_output {
            Ok(output) if output.status.success() => {
                // Find the extracted files
                if let Ok(entries) = std::fs::read_dir(&attach_dir) {
                    for entry in entries.flatten() {
                        let path = entry.path();
                        if path.is_file() {
                            attachments.push(path);
                        }
                    }
                }
                logger.info(&format!(
                    "  Extracted {} attachment(s) from {}",
                    attachments.len(),
                    source_key
                ));
            }
            Ok(output) => {
                let stderr = String::from_utf8_lossy(&output.stderr);
                logger.warn(&format!(
                    "  mkvextract attachments failed for {}: {}",
                    source_key, stderr
                ));
            }
            Err(e) => {
                logger.warn(&format!(
                    "  Failed to run mkvextract for {}: {}",
                    source_key, e
                ));
            }
        }

        attachments
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

        // Check if we have attachment sources specified in the layout
        let attachment_sources: Vec<String> = ctx
            .job_spec
            .manual_layout
            .as_ref()
            .and_then(|_layout| {
                // Look for attachment_sources in the layout metadata
                // For now, default to Source 1 if not specified
                Some(vec!["Source 1".to_string()])
            })
            .unwrap_or_else(|| vec!["Source 1".to_string()]);

        if attachment_sources.is_empty() {
            ctx.logger.info("No attachment sources specified - skipping");
            return Ok(StepOutcome::Skipped("No attachment sources".to_string()));
        }

        // Use mkvextract from PATH (configurable tool paths not yet implemented)
        let mkvextract_path = "mkvextract";

        let mut all_attachments = Vec::new();

        for source_key in &attachment_sources {
            if let Some(source_path) = ctx.job_spec.sources.get(source_key) {
                ctx.logger.info(&format!("Processing attachments from {}...", source_key));

                let extracted = self.extract_attachments(
                    source_path,
                    &ctx.work_dir,
                    source_key,
                    mkvextract_path,
                    &ctx.logger,
                );

                all_attachments.extend(extracted);
            }
        }

        // Add attachments to extract output
        if let Some(ref mut extract) = state.extract {
            for path in all_attachments.iter() {
                let key = format!(
                    "attachment_{}",
                    path.file_name().unwrap_or_default().to_string_lossy()
                );
                extract.attachments.insert(key, path.clone());
            }
        }

        ctx.logger.info(&format!(
            "Attachment extraction complete: {} attachment(s) found",
            all_attachments.len()
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
