//! Extract step - extracts tracks from sources using mkvextract.
//!
//! Extracts tracks specified in the job layout from their source files,
//! placing them in the work directory for further processing.

use std::collections::HashMap;
use std::path::PathBuf;

use crate::extraction::{extract_track, probe_file, extension_for_codec};
use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{Context, ExtractOutput, JobState, StepOutcome};

/// Extract step for extracting tracks from source files.
///
/// Uses the extraction module to pull individual tracks from MKV containers.
/// Stores extracted file paths in JobState.extract for use by later steps.
pub struct ExtractStep;

impl ExtractStep {
    pub fn new() -> Self {
        Self
    }

    /// Build the output path for an extracted track.
    fn build_output_path(
        &self,
        source_path: &std::path::Path,
        track_id: usize,
        codec_id: &str,
        work_dir: &std::path::Path,
        source_key: &str,
    ) -> PathBuf {
        let source_stem = source_path
            .file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_else(|| "track".to_string());

        let extension = extension_for_codec(codec_id);

        work_dir.join(format!(
            "{}_{}_track{}.{}",
            source_key.replace(' ', "_").to_lowercase(),
            source_stem,
            track_id,
            extension
        ))
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

        // Cache probed info for each source to avoid re-probing
        let mut probe_cache: HashMap<String, crate::extraction::ProbeResult> = HashMap::new();

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
                    Some(p) => p.clone(),
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

                // Get probe info (use cache)
                let probe_result = if let Some(cached) = probe_cache.get(source_key) {
                    cached.clone()
                } else {
                    match probe_file(&source_path) {
                        Ok(probe) => {
                            probe_cache.insert(source_key.to_string(), probe.clone());
                            probe
                        }
                        Err(e) => {
                            ctx.logger.warn(&format!(
                                "Failed to probe {}: {}",
                                source_key, e
                            ));
                            continue;
                        }
                    }
                };

                // Get codec for this track
                let codec_id = probe_result
                    .track_by_id(track_id)
                    .map(|t| t.codec_id.as_str())
                    .unwrap_or("");

                // Build output path
                let output_path = self.build_output_path(
                    &source_path,
                    track_id,
                    codec_id,
                    &ctx.work_dir,
                    source_key,
                );

                // Extract the track
                match extract_track(&source_path, track_id, &output_path) {
                    Ok(()) => {
                        let key = format!("{}_{}", source_key, track_id);
                        ctx.logger.info(&format!(
                            "  Extracted: {}",
                            output_path.file_name().unwrap_or_default().to_string_lossy()
                        ));
                        tracks.insert(key, output_path);
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
