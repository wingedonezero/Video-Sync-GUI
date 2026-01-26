//! Mux step - merges tracks into final output file using mkvmerge.

use std::path::PathBuf;
use std::process::Command;

use crate::models::MergePlan;
use crate::mux::MkvmergeOptionsBuilder;
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

    /// Build merge plan from job state.
    ///
    /// Constructs the merge plan from:
    /// - Manual layout (track selection and order)
    /// - Extracted tracks (paths from extraction step)
    /// - Analysis delays (sync offsets for audio/subtitle tracks)
    /// - Chapters and attachments from their respective steps
    fn build_merge_plan(&self, ctx: &Context, state: &JobState) -> StepResult<MergePlan> {
        // Use existing merge plan if available
        if let Some(ref plan) = state.merge_plan {
            return Ok(plan.clone());
        }

        use crate::models::{PlanItem, StreamProps, Track, TrackType};

        let mut items = Vec::new();
        let delays = state.delays().cloned().unwrap_or_default();

        // Build items from manual layout
        if let Some(ref layout) = ctx.job_spec.manual_layout {
            ctx.logger.info(&format!("Building merge plan from {} layout entries", layout.len()));

            for (idx, item) in layout.iter().enumerate() {
                let source_key = item
                    .get("source")
                    .and_then(|v| v.as_str())
                    .unwrap_or("Source 1");

                let track_id = item
                    .get("id")
                    .and_then(|v| v.as_u64())
                    .map(|v| v as u32)
                    .unwrap_or(0);

                let track_type_str = item
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("video");

                let track_type = match track_type_str {
                    "video" => TrackType::Video,
                    "audio" => TrackType::Audio,
                    "subtitles" => TrackType::Subtitles,
                    _ => TrackType::Video,
                };

                // Get codec and language from layout
                let codec = item
                    .get("codec")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown");

                let lang = item
                    .get("language")
                    .and_then(|v| v.as_str())
                    .unwrap_or("und");

                let name = item
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                // Get track config options
                let is_default = item
                    .get("is_default")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(idx == 0 && track_type == TrackType::Video);

                let is_forced = item
                    .get("is_forced_display")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false);

                let custom_lang = item
                    .get("custom_lang")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                let custom_name = item
                    .get("custom_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                // Get source path
                let source_path = if source_key == "External" {
                    item.get("original_path")
                        .and_then(|v| v.as_str())
                        .map(PathBuf::from)
                        .ok_or_else(|| {
                            StepError::invalid_input(format!(
                                "External track {} missing original_path",
                                track_id
                            ))
                        })?
                } else {
                    ctx.job_spec
                        .sources
                        .get(source_key)
                        .cloned()
                        .ok_or_else(|| {
                            StepError::invalid_input(format!(
                                "Source {} not found for track {}",
                                source_key, track_id
                            ))
                        })?
                };

                // Create track
                let props = StreamProps::new(codec)
                    .with_lang(if custom_lang.is_empty() { lang } else { custom_lang })
                    .with_name(if custom_name.is_empty() { name } else { custom_name });

                let track = Track::new(source_key, track_id, track_type, props);

                // Create plan item
                let mut plan_item = PlanItem::new(track, source_path);
                plan_item.is_default = is_default;
                plan_item.is_forced_display = is_forced;

                // Check for extracted path
                if let Some(ref extract) = state.extract {
                    let extract_key = format!("{}_{}", source_key, track_id);
                    if let Some(extracted_path) = extract.tracks.get(&extract_key) {
                        plan_item.extracted_path = Some(extracted_path.clone());
                    }
                }

                // Apply delay from raw_source_delays_ms (already includes global shift from AnalyzeStep)
                // Use raw f64 for precision - only rounded at final mkvmerge command
                //
                // CRITICAL: The delay in raw_source_delays_ms ALREADY has global_shift applied.
                // Do NOT add global_shift again here or in options_builder.
                //
                // Expected values after analysis:
                // - Source 1 = global_shift (since its raw delay was 0)
                // - Source 2+ = correlation_delay + global_shift
                if let Some(&delay_ms_raw) = delays.raw_source_delays_ms.get(source_key) {
                    plan_item.container_delay_ms_raw = delay_ms_raw;

                    // Log the delay being applied for debugging
                    let pre_shift = delays.pre_shift_delays_ms.get(source_key).copied().unwrap_or(0.0);
                    ctx.logger.debug(&format!(
                        "Track {}:{} ({}): pre-shift={:+.1}ms, global_shift={:+}ms, final={:+.1}ms",
                        source_key, track_id, track_type,
                        pre_shift, delays.global_shift_ms, delay_ms_raw
                    ));
                }

                items.push(plan_item);
            }
        } else {
            // No manual layout - create minimal plan with just Source 1 video
            ctx.logger.info("No manual layout - creating minimal plan from Source 1");

            if let Some(source1_path) = ctx.job_spec.sources.get("Source 1") {
                let video_track = Track::new(
                    "Source 1",
                    0,
                    TrackType::Video,
                    StreamProps::new("V_MPEG4/ISO/AVC"),
                );
                items.push(PlanItem::new(video_track, source1_path.clone()).with_default(true));
            }
        }

        let mut plan = MergePlan::new(items, delays);

        // Add chapters from chapters step
        if let Some(ref chapters) = state.chapters {
            if let Some(ref chapters_xml) = chapters.chapters_xml {
                ctx.logger.info(&format!("Including chapters: {}", chapters_xml.display()));
                plan.chapters_xml = Some(chapters_xml.clone());
            }
        }

        // Add attachments from extraction step
        if let Some(ref extract) = state.extract {
            for (key, path) in &extract.attachments {
                ctx.logger.info(&format!("Including attachment: {}", key));
                plan.attachments.push(path.clone());
            }
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

        // Check output directory is writable (try to create it)
        if let Err(e) = std::fs::create_dir_all(&ctx.output_dir) {
            return Err(StepError::io_error("creating output directory", e));
        }

        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.section("Mux/Merge");
        ctx.logger.info("Building mkvmerge command");

        // Build merge plan
        let plan = self.build_merge_plan(ctx, state)?;

        // Log delay summary for debugging
        ctx.logger.info("--- Track Delay Summary ---");
        let global_shift = plan.delays.global_shift_ms;
        ctx.logger.info(&format!("Global shift: {:+}ms", global_shift));

        for item in &plan.items {
            let delay_rounded = item.container_delay_ms_raw.round() as i64;
            let pre_shift = plan.delays.pre_shift_delays_ms
                .get(&item.track.source)
                .copied()
                .unwrap_or(0.0);

            if item.container_delay_ms_raw.abs() > 0.001 {
                ctx.logger.info(&format!(
                    "  {} {}:{} - sync {:+}ms (pre-shift: {:+.1}ms + global: {:+}ms)",
                    item.track.source,
                    item.track.track_type,
                    item.track.id,
                    delay_rounded,
                    pre_shift,
                    global_shift
                ));
            } else {
                ctx.logger.info(&format!(
                    "  {} {}:{} - no sync delay",
                    item.track.source,
                    item.track.track_type,
                    item.track.id
                ));
            }
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
