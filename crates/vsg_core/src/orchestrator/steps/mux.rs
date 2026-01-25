//! Mux step - merges tracks into final output file using mkvmerge.
//!
//! This step builds a MergePlan from the job state (analysis, extraction results)
//! and executes mkvmerge to create the final output file.

use std::path::PathBuf;
use std::process::Command;

use crate::jobs::ManualLayout;
use crate::models::MergePlan;
use crate::mux::{build_merge_plan, build_remux_plan, MkvmergeOptionsBuilder, PlanBuildInput};
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

    /// Parse ManualLayout from job spec's JSON layout.
    ///
    /// The job spec stores layout as JSON for CXX bridge compatibility.
    /// This converts it to the proper ManualLayout type.
    fn parse_manual_layout(ctx: &Context) -> Option<ManualLayout> {
        ctx.job_spec.manual_layout.as_ref().and_then(|layout| {
            // The layout is stored as Vec<HashMap<String, Value>>
            // Try to convert to ManualLayout
            serde_json::to_value(layout)
                .ok()
                .and_then(|v| serde_json::from_value::<ManualLayout>(v).ok())
        })
    }

    /// Build merge plan from job state.
    ///
    /// Uses the plan_builder module to create a MergePlan with correct delays.
    fn build_merge_plan(&self, ctx: &Context, state: &JobState) -> StepResult<MergePlan> {
        // Use existing merge plan if available (e.g., from previous run)
        if let Some(ref plan) = state.merge_plan {
            ctx.logger.debug("Using existing merge plan from state");
            return Ok(plan.clone());
        }

        // Get the manual layout
        let layout = Self::parse_manual_layout(ctx).ok_or_else(|| {
            StepError::precondition_failed(
                "No manual layout configured - please configure tracks in the UI",
            )
        })?;

        if layout.final_tracks.is_empty() {
            return Err(StepError::precondition_failed(
                "Layout has no tracks selected",
            ));
        }

        // Check if we have analysis results (delays)
        let has_analysis = state.analysis.is_some();
        let has_extraction = state.extract.is_some();

        // For simple remux (Source 1 only, no sync needed), use build_remux_plan
        let needs_sync = ctx.job_spec.sources.len() > 1;

        if !needs_sync {
            ctx.logger.info("Single source - using remux plan (no sync)");
            return build_remux_plan(&layout, &ctx.job_spec.sources).map_err(|e| {
                StepError::other(format!("Failed to build remux plan: {}", e))
            });
        }

        // Multi-source job - need delays and container info
        if !has_analysis {
            return Err(StepError::precondition_failed(
                "Analysis step must complete before mux (delays not calculated)",
            ));
        }

        let delays = state
            .analysis
            .as_ref()
            .map(|a| &a.delays)
            .ok_or_else(|| StepError::precondition_failed("No delays in analysis results"))?;

        // Get container info (from extract step, or use empty if not extracted)
        let container_info = state
            .extract
            .as_ref()
            .map(|e| &e.container_info)
            .cloned()
            .unwrap_or_default();

        if !has_extraction {
            ctx.logger.warn(
                "Extract step not completed - container delays may be incorrect",
            );
        }

        // Get chapters XML path (if chapters step completed)
        let chapters_xml = state
            .chapters
            .as_ref()
            .and_then(|c| c.chapters_xml.clone());

        // Get extracted attachments
        let attachments: Vec<PathBuf> = state
            .extract
            .as_ref()
            .map(|e| e.attachments.values().cloned().collect())
            .unwrap_or_default();

        // Get extracted tracks (for corrected audio, etc.)
        let extracted_tracks = state.extract.as_ref().map(|e| &e.tracks);

        // Build the plan
        ctx.logger.info(&format!(
            "Building merge plan: {} tracks, {} sources",
            layout.final_tracks.len(),
            ctx.job_spec.sources.len()
        ));

        let input = PlanBuildInput {
            layout: &layout,
            delays,
            container_info: &container_info,
            sources: &ctx.job_spec.sources,
            extracted_tracks,
            chapters_xml,
            attachments,
        };

        let plan = build_merge_plan(&input).map_err(|e| {
            StepError::other(format!("Failed to build merge plan: {}", e))
        })?;

        // Log plan summary
        ctx.logger.debug(&format!(
            "Plan: {} items, global_shift={}ms",
            plan.items.len(),
            plan.delays.global_shift_ms
        ));

        for item in &plan.items {
            ctx.logger.debug(&format!(
                "  {} {} #{}: delay={}ms, default={}, forced={}",
                item.track.source,
                format!("{:?}", item.track.track_type),
                item.track.id,
                item.container_delay_ms,
                item.is_default,
                item.is_forced_display,
            ));
        }

        Ok(plan)
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
        ctx.logger.command(&format!("{} {}", mkvmerge, tokens.join(" ")));

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

        // Check that we have a layout configured
        if Self::parse_manual_layout(ctx).is_none() {
            return Err(StepError::invalid_input(
                "No track layout configured - please select tracks in the UI",
            ));
        }

        // Check output directory is writable (try to create it)
        if let Err(e) = std::fs::create_dir_all(&ctx.output_dir) {
            return Err(StepError::io_error("creating output directory", e));
        }

        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.section("Building Merge Plan");

        // Build merge plan
        let plan = self.build_merge_plan(ctx, state)?;

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
            output_path.file_name().unwrap_or_default().to_string_lossy()
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
