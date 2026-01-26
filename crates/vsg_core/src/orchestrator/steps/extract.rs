//! Extract step - extracts tracks and attachments from sources using mkvextract.
//!
//! Extracts tracks specified in the job layout from their source files,
//! placing them in the work directory for further processing.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Command;

use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{Context, ExtractOutput, JobState, StepOutcome};

/// Extract step for extracting tracks from source files.
///
/// Uses mkvextract to pull individual tracks from MKV containers.
/// Stores extracted file paths in JobState.extract for use by later steps.
pub struct ExtractStep;

impl ExtractStep {
    pub fn new() -> Self {
        Self
    }

    /// Extract a single track from a source file using mkvextract.
    fn extract_track(
        &self,
        source_path: &PathBuf,
        track_id: usize,
        work_dir: &PathBuf,
        source_key: &str,
        mkvextract_path: &str,
    ) -> StepResult<PathBuf> {
        // Determine output filename based on source and track
        let source_stem = source_path
            .file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_else(|| "track".to_string());

        // Output path: work_dir/source_stem_trackID.ext
        // Extension will be determined by mkvextract based on codec
        let output_base = work_dir.join(format!(
            "{}_{}_track{}",
            source_key.replace(" ", "_").to_lowercase(),
            source_stem,
            track_id
        ));

        // mkvextract tracks <source> <trackID>:<output>
        let track_spec = format!("{}:{}", track_id, output_base.display());

        let output = Command::new(mkvextract_path)
            .arg("tracks")
            .arg(source_path)
            .arg(&track_spec)
            .output()
            .map_err(|e| StepError::io_error("running mkvextract", e))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let exit_code = output.status.code().unwrap_or(-1);
            return Err(StepError::command_failed(
                "mkvextract",
                exit_code,
                format!("track {} extraction failed: {}", track_id, stderr),
            ));
        }

        // Find the actual output file (mkvextract adds extension based on codec)
        // Look for files matching the base pattern
        if let Ok(entries) = std::fs::read_dir(work_dir) {
            let base_name = output_base
                .file_name()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_default();

            for entry in entries.flatten() {
                let path = entry.path();
                if let Some(name) = path.file_name() {
                    let name_str = name.to_string_lossy();
                    if name_str.starts_with(&base_name) && path.is_file() {
                        return Ok(path);
                    }
                }
            }
        }

        // If we can't find the file with extension, check if base exists
        if output_base.exists() {
            return Ok(output_base);
        }

        Err(StepError::file_not_found(format!(
            "extracted track {} output file",
            track_id
        )))
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
        "Extract tracks from source files"
    }

    fn validate_input(&self, ctx: &Context) -> StepResult<()> {
        // Check that we have Source 1
        if !ctx.job_spec.sources.contains_key("Source 1") {
            return Err(StepError::invalid_input("No primary source (Source 1)"));
        }
        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.info("Starting track extraction...");

        let mut tracks: HashMap<String, PathBuf> = HashMap::new();
        let attachments: HashMap<String, PathBuf> = HashMap::new();

        // Use mkvextract from PATH (configurable tool paths not yet implemented)
        let mkvextract_path = "mkvextract";

        // Check if we have a manual layout to extract
        if let Some(ref layout) = ctx.job_spec.manual_layout {
            ctx.logger.info(&format!(
                "Extracting {} track(s) from layout",
                layout.len()
            ));

            for item in layout {
                let source_key = item
                    .get("source")
                    .and_then(|v| v.as_str())
                    .unwrap_or("Source 1");

                let track_id = item
                    .get("id")
                    .and_then(|v| v.as_u64())
                    .map(|v| v as usize)
                    .unwrap_or(0);

                let track_type = item
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown");

                // Skip external tracks (not from MKV sources)
                if source_key == "External" {
                    if let Some(path) = item.get("original_path").and_then(|v| v.as_str()) {
                        let key = format!("External_{}", track_id);
                        tracks.insert(key, PathBuf::from(path));
                    }
                    continue;
                }

                // Get source path
                let source_path = match ctx.job_spec.sources.get(source_key) {
                    Some(p) => p,
                    None => {
                        ctx.logger.warn(&format!(
                            "Source {} not found, skipping track {}",
                            source_key, track_id
                        ));
                        continue;
                    }
                };

                ctx.logger.info(&format!(
                    "Extracting {} track {} from {}",
                    track_type, track_id, source_key
                ));

                match self.extract_track(
                    source_path,
                    track_id,
                    &ctx.work_dir,
                    source_key,
                    mkvextract_path,
                ) {
                    Ok(extracted_path) => {
                        let key = format!("{}_{}", source_key, track_id);
                        ctx.logger.info(&format!(
                            "  Extracted: {}",
                            extracted_path.file_name().unwrap_or_default().to_string_lossy()
                        ));
                        tracks.insert(key, extracted_path);
                    }
                    Err(e) => {
                        ctx.logger.warn(&format!(
                            "  Failed to extract track {}: {}",
                            track_id, e
                        ));
                        // Continue with other tracks
                    }
                }
            }
        } else {
            // No manual layout - skip extraction (use source files directly in mux)
            ctx.logger.info("No manual layout - skipping extraction");
        }

        // Store extraction results
        state.extract = Some(ExtractOutput {
            tracks,
            attachments,
        });

        ctx.logger.info(&format!(
            "Extraction complete: {} tracks extracted",
            state.extract.as_ref().map(|e| e.tracks.len()).unwrap_or(0)
        ));

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
        // Extraction may be skipped if using source files directly
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
