//! Extract step - extracts tracks from sources using mkvextract.
//!
//! Extracts tracks specified in the job layout from their source files,
//! placing them in the work directory for further processing.
//!
//! Features:
//! - Detailed per-track logging (codec, language, container delay)
//! - A_MS/ACM audio fallback extraction via ffmpeg (via extract_track_smart)
//! - Post-extraction verification (file exists and non-empty)
//! - Detailed error messages with troubleshooting steps

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use crate::extraction::{
    build_track_output_path, extract_track_smart, probe_file, ExtractionMethod, ProbeResult,
    TrackType,
};
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

    /// Log detailed track information before extraction.
    fn log_track_details(
        &self,
        ctx: &Context,
        probe_result: &ProbeResult,
        track_id: usize,
        source_key: &str,
    ) {
        let track_info = probe_result.track_by_id(track_id);
        let codec_id = track_info.map(|t| t.codec_id.as_str()).unwrap_or("");
        let track_name = track_info
            .and_then(|t| t.name.as_deref())
            .unwrap_or("unnamed");
        let track_type = track_info
            .map(|t| match t.track_type {
                TrackType::Video => "Video",
                TrackType::Audio => "Audio",
                TrackType::Subtitles => "Subtitles",
            })
            .unwrap_or("Unknown");
        let lang = track_info
            .and_then(|t| t.language.as_deref())
            .unwrap_or("und");
        let container_delay = track_info.map(|t| t.container_delay_ms).unwrap_or(0);

        let mut details = format!("{} ({})", track_type, lang);
        if !track_name.is_empty() && track_name != "unnamed" {
            details.push_str(&format!(" '{}'", track_name));
        }
        details.push_str(&format!(" [{}]", codec_id));
        if container_delay != 0 {
            details.push_str(&format!(" delay: {:+}ms", container_delay));
        }

        ctx.logger.info(&format!(
            "  [{}] Track {}: {}",
            source_key, track_id, details
        ));
    }

    /// Build a detailed error message for extraction failures.
    fn build_error_message(
        &self,
        source_key: &str,
        source_path: &Path,
        failed_tracks: &[(usize, String)],
        successful_tracks: &[(usize, u64)],
    ) -> String {
        let separator = "=".repeat(80);
        let mut msg = format!("\n{}\n", separator);
        msg.push_str("EXTRACTION FAILED\n");
        msg.push_str(&format!("{}\n", separator));
        msg.push_str(&format!("Source: {}\n", source_key));
        msg.push_str(&format!(
            "File: {}\n",
            source_path
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
        ));
        msg.push_str(&format!("Full Path: {}\n", source_path.display()));
        msg.push_str(&format!("{}\n\n", separator));

        if !successful_tracks.is_empty() {
            msg.push_str(&format!(
                "Successfully extracted ({} tracks):\n",
                successful_tracks.len()
            ));
            for (tid, size) in successful_tracks {
                let size_mb = *size as f64 / (1024.0 * 1024.0);
                msg.push_str(&format!("  [OK] Track {} [{:.1} MB]\n", tid, size_mb));
            }
            msg.push('\n');
        }

        if !failed_tracks.is_empty() {
            msg.push_str(&format!(
                "FAILED to extract ({} tracks):\n",
                failed_tracks.len()
            ));
            for (tid, reason) in failed_tracks {
                msg.push_str(&format!("  [FAIL] Track {}: {}\n", tid, reason));
            }
            msg.push('\n');
        }

        msg.push_str("Possible causes:\n");
        msg.push_str("  - Corrupted track data in the source file\n");
        msg.push_str("  - Insufficient disk space in temp directory\n");
        msg.push_str("  - Insufficient read/write permissions\n");
        msg.push_str("  - Unsupported codec or malformed stream data\n");
        msg.push_str("  - Hardware/storage errors (bad sectors)\n");
        msg.push_str("  - File system issues (FAT32 4GB limit, etc.)\n\n");

        msg.push_str("Troubleshooting:\n");
        msg.push_str(&format!(
            "  1. Verify source integrity: mkvmerge -i \"{}\"\n",
            source_path.display()
        ));
        msg.push_str("  2. Try extracting failed track(s) manually:\n");
        for (tid, _) in failed_tracks.iter().take(3) {
            msg.push_str(&format!(
                "     mkvextract \"{}\" tracks {}:test_track_{}.bin\n",
                source_path.display(),
                tid,
                tid
            ));
        }
        msg.push_str("  3. Check disk space in temp directory\n");
        msg.push_str("  4. Try playing source file to check for corruption\n");
        msg.push_str(&format!("{}\n", separator));

        msg
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
        let mut probe_cache: HashMap<String, ProbeResult> = HashMap::new();

        // Track extraction results for detailed error reporting
        let mut successful_extractions: Vec<(usize, u64)> = Vec::new();
        let mut failed_extractions: Vec<(usize, String)> = Vec::new();
        let mut last_source_key = String::new();
        let mut last_source_path = PathBuf::new();

        // Check if we have a manual layout to extract
        if let Some(ref layout) = ctx.job_spec.manual_layout {
            ctx.logger.info(&format!(
                "Extracting {} track(s) from manual layout",
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

                // Skip external tracks (not from MKV sources)
                if source_key == "External" {
                    if let Some(path) = item.get("original_path").and_then(|v| v.as_str()) {
                        // Determine type from file extension
                        let ext = std::path::Path::new(path)
                            .extension()
                            .and_then(|e| e.to_str())
                            .map(|s| s.to_lowercase())
                            .unwrap_or_default();
                        let type_str = match ext.as_str() {
                            "srt" | "ass" | "ssa" | "sub" | "idx" | "sup" | "vtt" => "subtitles",
                            "mp3" | "aac" | "ac3" | "dts" | "flac" | "wav" | "opus" | "ogg" | "eac3" | "truehd" => "audio",
                            _ => "video",
                        };
                        let key = format!("External:{}:{}", type_str, track_id);
                        ctx.logger
                            .info(&format!("  [External] Using file: {}", path));
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

                last_source_key = source_key.to_string();
                last_source_path = source_path.clone();

                // Get probe info (use cache)
                let probe_result = if let Some(cached) = probe_cache.get(source_key) {
                    cached.clone()
                } else {
                    ctx.logger
                        .command(&format!("mkvmerge -J \"{}\"", source_path.display()));
                    match probe_file(&source_path) {
                        Ok(probe) => {
                            // Log container delays if present
                            let delays = probe.get_audio_container_delays_relative();
                            if !delays.is_empty() {
                                let non_zero: Vec<_> =
                                    delays.iter().filter(|(_, d)| **d != 0).collect();
                                if !non_zero.is_empty() {
                                    ctx.logger.info(&format!(
                                        "[{}] Container delays detected:",
                                        source_key
                                    ));
                                    for (tid, delay) in non_zero {
                                        ctx.logger.info(&format!("  Track {}: {:+}ms", tid, delay));
                                    }
                                }
                            }
                            probe_cache.insert(source_key.to_string(), probe.clone());
                            probe
                        }
                        Err(e) => {
                            let reason = format!("Failed to probe source: {}", e);
                            ctx.logger.warn(&format!(
                                "  [{}] Track {}: {}",
                                source_key, track_id, reason
                            ));
                            failed_extractions.push((track_id, reason));
                            continue;
                        }
                    }
                };

                // Get track info
                let track_info = probe_result.track_by_id(track_id);
                let codec_id = track_info.map(|t| t.codec_id.as_str()).unwrap_or("");
                let track_type = track_info.map(|t| t.track_type).unwrap_or(TrackType::Video);

                // Build output path using module function
                let output_path = build_track_output_path(
                    &source_path,
                    track_id,
                    codec_id,
                    &ctx.work_dir,
                    source_key,
                );

                // Log track details
                self.log_track_details(ctx, &probe_result, track_id, source_key);

                // Extract the track using smart extraction (handles ffmpeg fallback)
                match extract_track_smart(&source_path, track_id, &output_path, &probe_result) {
                    Ok(result) => {
                        let size_mb = result.size_bytes as f64 / (1024.0 * 1024.0);
                        let method_str = match result.method {
                            ExtractionMethod::Ffmpeg => " (ffmpeg)",
                            ExtractionMethod::Mkvextract => "",
                        };
                        ctx.logger.info(&format!(
                            "    -> OK{}: {} [{:.1} MB]",
                            method_str,
                            output_path
                                .file_name()
                                .unwrap_or_default()
                                .to_string_lossy(),
                            size_mb
                        ));
                        // Build key with track type: "Source 2:subtitles:5"
                        let type_str = match track_type {
                            TrackType::Video => "video",
                            TrackType::Audio => "audio",
                            TrackType::Subtitles => "subtitles",
                        };
                        let key = format!("{}:{}:{}", source_key, type_str, track_id);
                        tracks.insert(key, output_path);
                        successful_extractions.push((track_id, result.size_bytes));
                    }
                    Err(e) => {
                        let reason = format!("Extraction failed: {}", e);
                        ctx.logger.warn(&format!("    -> FAIL: {}", reason));
                        failed_extractions.push((track_id, reason));
                    }
                }
            }
        } else {
            // No manual layout - skip extraction (use source files directly in mux)
            ctx.logger.info("No manual layout - skipping extraction");
        }

        // Report any failures with detailed error message
        if !failed_extractions.is_empty() {
            let error_msg = self.build_error_message(
                &last_source_key,
                &last_source_path,
                &failed_extractions,
                &successful_extractions,
            );
            ctx.logger.warn(&error_msg);

            // If all tracks failed, return error
            if successful_extractions.is_empty() && !failed_extractions.is_empty() {
                return Err(StepError::other(format!(
                    "All track extractions failed\n{}",
                    error_msg
                )));
            }
        }

        // Store extraction results
        state.extract = Some(ExtractOutput {
            tracks,
            attachments,
        });

        let extracted_count = state.extract.as_ref().map(|e| e.tracks.len()).unwrap_or(0);
        ctx.logger.info(&format!(
            "Extraction complete: {} tracks extracted ({} succeeded, {} failed)",
            extracted_count,
            successful_extractions.len(),
            failed_extractions.len()
        ));

        Ok(StepOutcome::Success)
    }

    fn validate_output(&self, _ctx: &Context, state: &JobState) -> StepResult<()> {
        if state.extract.is_none() {
            return Err(StepError::invalid_output("Extraction results not recorded"));
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
