//! Mux step - merges tracks into final output file using mkvmerge.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Command;

use crate::mux::{build_merge_plan, MergePlanInput, MkvmergeOptionsBuilder};
use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{Context, JobState, MuxOutput, StepOutcome};

/// Mux step for merging tracks with mkvmerge.
///
/// Builds mkvmerge command from the merge plan and executes it.
pub struct MuxStep {
    /// Path to mkvmerge executable (None = find in PATH).
    mkvmerge_path: Option<PathBuf>,
}

impl MuxStep {
    pub fn new() -> Self {
        Self {
            mkvmerge_path: None,
        }
    }

    /// Set a custom path to mkvmerge executable.
    pub fn with_mkvmerge_path(mut self, path: impl Into<PathBuf>) -> Self {
        self.mkvmerge_path = Some(path.into());
        self
    }

    /// Get the mkvmerge executable path/command.
    fn mkvmerge_cmd(&self) -> &str {
        self.mkvmerge_path
            .as_ref()
            .map(|p| p.to_str().unwrap_or("mkvmerge"))
            .unwrap_or("mkvmerge")
    }

    /// Build the output file path.
    ///
    /// Uses the source1 filename (e.g., movie.mkv -> output/movie.mkv)
    fn output_path(&self, ctx: &Context) -> PathBuf {
        // Get filename from Source 1, fallback to job_name.mkv
        let filename = ctx
            .primary_source()
            .and_then(|p| p.file_name())
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| format!("{}.mkv", ctx.job_name));
        ctx.output_dir.join(filename)
    }

    /// Execute mkvmerge with the given tokens.
    fn run_mkvmerge(
        &self,
        ctx: &Context,
        tokens: &[String],
        output_path: &PathBuf,
    ) -> StepResult<i32> {
        let mkvmerge = self.mkvmerge_cmd();

        // Log the command
        ctx.logger
            .command(&format!("{} {}", mkvmerge, tokens.join(" ")));

        // Log pretty format if enabled
        if ctx.settings.logging.show_options_pretty {
            ctx.logger.log_mkvmerge_options_pretty(tokens);
        }
        if ctx.settings.logging.show_options_json {
            ctx.logger.log_mkvmerge_options_json(tokens);
        }

        // Create output directory if needed
        if let Some(parent) = output_path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| StepError::io_error("creating output directory", e))?;
        }

        // Execute mkvmerge
        let result = Command::new(mkvmerge)
            .args(tokens)
            .output()
            .map_err(|e| StepError::io_error("executing mkvmerge", e))?;

        let exit_code = result.status.code().unwrap_or(-1);

        // Log output
        if !result.stdout.is_empty() {
            let stdout = String::from_utf8_lossy(&result.stdout);
            for line in stdout.lines() {
                ctx.logger.output_line(line, false);
            }
        }
        if !result.stderr.is_empty() {
            let stderr = String::from_utf8_lossy(&result.stderr);
            for line in stderr.lines() {
                ctx.logger.output_line(line, true);
            }
        }

        // Check for errors
        // mkvmerge exit codes: 0 = success, 1 = warnings, 2 = errors
        if exit_code >= 2 {
            ctx.logger.show_tail("mkvmerge output");
            return Err(StepError::command_failed(
                "mkvmerge",
                exit_code,
                String::from_utf8_lossy(&result.stderr).to_string(),
            ));
        }

        if exit_code == 1 {
            ctx.logger.warn("mkvmerge completed with warnings");
        }

        Ok(exit_code)
    }
}

impl Default for MuxStep {
    fn default() -> Self {
        Self::new()
    }
}

impl PipelineStep for MuxStep {
    fn name(&self) -> &str {
        "Mux"
    }

    fn description(&self) -> &str {
        "Merge tracks into output file with mkvmerge"
    }

    fn validate_input(&self, ctx: &Context) -> StepResult<()> {
        // Check that we have at least one source
        if ctx.job_spec.sources.is_empty() {
            return Err(StepError::invalid_input("No sources to merge"));
        }

        // Check output directory is writable (try to create it)
        if let Err(e) = std::fs::create_dir_all(&ctx.output_dir) {
            return Err(StepError::io_error("creating output directory", e));
        }

        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.section("Mux/Merge");
        ctx.logger.info("Building mkvmerge command");

        // Use existing merge plan if available, otherwise build one
        let plan = if let Some(ref existing_plan) = state.merge_plan {
            existing_plan.clone()
        } else {
            // Log what we're building from
            if let Some(ref layout) = ctx.job_spec.manual_layout {
                ctx.logger.info(&format!(
                    "Building merge plan from {} layout entries",
                    layout.len()
                ));
            } else {
                ctx.logger
                    .info("No manual layout - creating minimal plan from Source 1");
            }

            // Prepare input for module function
            let empty_tracks: HashMap<String, PathBuf> = HashMap::new();
            let empty_attachments: HashMap<String, PathBuf> = HashMap::new();

            let extracted_tracks = state
                .extract
                .as_ref()
                .map(|e| &e.tracks)
                .unwrap_or(&empty_tracks);

            let extracted_attachments = state
                .extract
                .as_ref()
                .map(|e| &e.attachments)
                .unwrap_or(&empty_attachments);

            let chapters_xml = state.chapters.as_ref().and_then(|c| c.chapters_xml.clone());

            // Log chapters and attachments inclusion
            if let Some(ref path) = chapters_xml {
                ctx.logger
                    .info(&format!("Including chapters: {}", path.display()));
            }
            for (key, _path) in extracted_attachments {
                ctx.logger.info(&format!("Including attachment: {}", key));
            }

            // Build subtitle-specific delays from video-verified cache
            let subtitle_delays: HashMap<String, f64> = state
                .subtitles
                .as_ref()
                .map(|s| {
                    s.video_verified_cache
                        .iter()
                        .map(|(k, v)| (k.clone(), v.corrected_delay_ms))
                        .collect()
                })
                .unwrap_or_default();

            // Log video-verified subtitle delays
            if !subtitle_delays.is_empty() {
                ctx.logger
                    .info("Using video-verified delays for subtitle tracks:");
                for (source, delay) in &subtitle_delays {
                    ctx.logger
                        .info(&format!("  {}: {:+.1}ms", source, delay));
                }
            }

            let input = MergePlanInput {
                layout: ctx.job_spec.manual_layout.as_ref(),
                sources: &ctx.job_spec.sources,
                extracted_tracks,
                extracted_attachments,
                delays: state.delays().cloned().unwrap_or_default(),
                subtitle_delays: if subtitle_delays.is_empty() {
                    None
                } else {
                    Some(&subtitle_delays)
                },
                chapters_xml,
            };

            // Build plan using module function
            build_merge_plan(input).map_err(|e| StepError::other(e.to_string()))?
        };

        // Log delay summary for debugging
        ctx.logger.info("--- Track Delay Summary ---");
        let global_shift = plan.delays.global_shift_ms;
        ctx.logger
            .info(&format!("Global shift: {:+}ms", global_shift));

        for item in &plan.items {
            let delay_rounded = item.container_delay_ms_raw.round() as i64;
            let pre_shift = plan
                .delays
                .pre_shift_delays_ms
                .get(&item.track.source)
                .copied()
                .unwrap_or(0.0);

            // Always show sync value (even 0) for verification
            ctx.logger.info(&format!(
                "  {} {}:{} - sync {:+}ms (pre-shift: {:+.1}ms + global: {:+}ms)",
                item.track.source,
                item.track.track_type,
                item.track.id,
                delay_rounded,
                pre_shift,
                global_shift
            ));
        }
        ctx.logger.info("---------------------------");

        // Build output path
        let output_path = self.output_path(ctx);
        ctx.logger
            .info(&format!("Output: {}", output_path.display()));

        // Build mkvmerge tokens
        let builder = MkvmergeOptionsBuilder::new(&plan, &ctx.settings, &output_path);
        let tokens = builder.build();

        // Execute mkvmerge
        ctx.logger.section("Executing mkvmerge");
        let exit_code = self.run_mkvmerge(ctx, &tokens, &output_path)?;

        // Record output
        state.mux = Some(MuxOutput {
            output_path: output_path.clone(),
            exit_code,
            command: format!("{} {}", self.mkvmerge_cmd(), tokens.join(" ")),
        });

        // Store the plan
        state.merge_plan = Some(plan);

        ctx.logger.success(&format!(
            "Merged to: {}",
            output_path
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
        ));

        Ok(StepOutcome::Success)
    }

    fn validate_output(&self, _ctx: &Context, state: &JobState) -> StepResult<()> {
        // Check that mux output was recorded
        let mux = state
            .mux
            .as_ref()
            .ok_or_else(|| StepError::invalid_output("Mux results not recorded"))?;

        // Check that output file exists
        if !mux.output_path.exists() {
            return Err(StepError::invalid_output(format!(
                "Output file not created: {}",
                mux.output_path.display()
            )));
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mux_step_has_correct_name() {
        let step = MuxStep::new();
        assert_eq!(step.name(), "Mux");
    }

    #[test]
    fn mux_step_with_custom_path() {
        let step = MuxStep::new().with_mkvmerge_path("/usr/bin/mkvmerge");
        assert_eq!(step.mkvmerge_cmd(), "/usr/bin/mkvmerge");
    }
}
