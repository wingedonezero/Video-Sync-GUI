//! Main orchestrator pipeline
//!
//! Coordinates the execution of all pipeline steps in sequence with validation.

use crate::core::models::results::PipelineResult;
use crate::core::orchestrator::steps::Context;
use std::sync::Arc;

/// Main pipeline orchestrator
pub struct Orchestrator;

impl Orchestrator {
    /// Run the complete pipeline
    ///
    /// Executes all steps in sequence:
    /// 1. Analysis - Extract audio delays via correlation
    /// 2. Extraction - Extract tracks from MKV sources
    /// 3. Subtitles - Apply conversions, rescaling, timing fixes
    /// 4. Chapters - Process chapters with keyframe snapping
    /// 5. Mux - Build mkvmerge command and execute
    ///
    /// Each step validates its output before proceeding to the next.
    pub fn run(mut ctx: Context) -> PipelineResult<Context> {
        ctx.log("[Orchestrator] Starting pipeline execution...");
        ctx.update_progress(0.0);

        // Step 1: Analysis
        ctx.log("[Orchestrator] Step 1/5: Analysis");
        ctx.update_progress(0.1);
        ctx = Self::run_analysis_step(ctx)?;
        Self::validate_analysis(&ctx)?;

        // Check if we should continue to merge
        if !ctx.and_merge {
            ctx.log("[Orchestrator] Analysis-only mode - skipping merge steps");
            ctx.update_progress(1.0);
            return Ok(ctx);
        }

        // Step 2: Extraction
        ctx.log("[Orchestrator] Step 2/5: Track Extraction");
        ctx.update_progress(0.3);
        ctx = Self::run_extract_step(ctx)?;
        Self::validate_extraction(&ctx)?;

        // Step 3: Subtitles
        ctx.log("[Orchestrator] Step 3/5: Subtitle Processing");
        ctx.update_progress(0.5);
        ctx = Self::run_subtitles_step(ctx)?;

        // Step 4: Chapters
        ctx.log("[Orchestrator] Step 4/5: Chapter Processing");
        ctx.update_progress(0.7);
        ctx = Self::run_chapters_step(ctx)?;

        // Step 5: Mux
        ctx.log("[Orchestrator] Step 5/5: Muxing");
        ctx.update_progress(0.9);
        ctx = Self::run_mux_step(ctx)?;
        Self::validate_mux(&ctx)?;

        ctx.log("[Orchestrator] Pipeline execution complete!");
        ctx.update_progress(1.0);

        Ok(ctx)
    }

    /// Run analysis step (audio correlation)
    fn run_analysis_step(mut ctx: Context) -> PipelineResult<Context> {
        use crate::core::analysis::audio_corr::{AudioCorrelator, CorrelationMethod};
        use crate::core::io::runner::CommandRunner;
        use crate::core::models::jobs::Delays;
        use std::collections::HashMap;

        ctx.log("[Analysis] Detecting audio delays...");

        // Build raw delays map
        let mut raw_delays = HashMap::new();

        // Reference is always 0
        raw_delays.insert("REF".to_string(), 0.0);

        // Get analysis configuration
        let sample_rate = ctx
            .settings_dict
            .get("audio_sample_rate")
            .and_then(|v| v.as_u64())
            .unwrap_or(48000) as u32;

        let chunk_duration = ctx
            .settings_dict
            .get("scan_chunk_duration")
            .and_then(|v| v.as_u64())
            .unwrap_or(15) as u32;

        let chunk_count = ctx
            .settings_dict
            .get("scan_chunk_count")
            .and_then(|v| v.as_u64())
            .unwrap_or(10) as u32;

        // Get analysis mode
        let analysis_mode = ctx
            .settings_dict
            .get("analysis_mode")
            .and_then(|v| v.as_str())
            .unwrap_or("Audio Correlation");

        if analysis_mode != "Audio Correlation" {
            return Err(format!("Unsupported analysis mode: {}", analysis_mode).into());
        }

        // Create command runner
        let runner = CommandRunner::new()
            .with_compact_mode(true)
            .with_log_callback(Arc::new({
                let log = ctx.log.clone();
                move |msg: &str| log(msg)
            }));

        // Create audio correlator
        let correlator = AudioCorrelator::new(
            runner,
            CorrelationMethod::GccPhat,
            sample_rate,
            chunk_duration,
            chunk_count,
        );

        // Get reference path
        let ref_path = ctx
            .sources
            .get("REF")
            .ok_or("Reference source not found")?
            .clone();

        // Analyze secondary if present
        if let Some(sec_path) = ctx.sources.get("SEC") {
            ctx.log("[Analysis] Analyzing secondary source...");
            match correlator.analyze_delay(&ref_path, sec_path, &ctx.temp_dir) {
                Ok(result) => {
                    ctx.log(&format!(
                        "[Analysis] Secondary delay: {:.2} ms (confidence: {:.2})",
                        result.delay_ms, result.confidence
                    ));
                    raw_delays.insert("SEC".to_string(), result.delay_ms);
                }
                Err(e) => {
                    ctx.log(&format!("[Analysis] Warning: Secondary analysis failed: {}", e));
                    raw_delays.insert("SEC".to_string(), 0.0);
                }
            }
        }

        // Analyze tertiary if present
        if let Some(ter_path) = ctx.sources.get("TER") {
            ctx.log("[Analysis] Analyzing tertiary source...");
            match correlator.analyze_delay(&ref_path, ter_path, &ctx.temp_dir) {
                Ok(result) => {
                    ctx.log(&format!(
                        "[Analysis] Tertiary delay: {:.2} ms (confidence: {:.2})",
                        result.delay_ms, result.confidence
                    ));
                    raw_delays.insert("TER".to_string(), result.delay_ms);
                }
                Err(e) => {
                    ctx.log(&format!("[Analysis] Warning: Tertiary analysis failed: {}", e));
                    raw_delays.insert("TER".to_string(), 0.0);
                }
            }
        }

        // Compute delays with global shift
        let delays = Delays::new(raw_delays);

        ctx.log(&format!(
            "[Analysis] Global shift: {} ms (required: {})",
            delays.global_shift_ms,
            delays.requires_global_shift()
        ));

        ctx.delays = Some(delays);
        ctx.log("[Analysis] Audio delay detection complete");
        Ok(ctx)
    }

    /// Validate analysis step
    fn validate_analysis(ctx: &Context) -> PipelineResult<()> {
        if ctx.delays.is_none() {
            return Err("Analysis step failed: no delays calculated".into());
        }
        Ok(())
    }

    /// Run extraction step (extract tracks from MKV)
    fn run_extract_step(mut ctx: Context) -> PipelineResult<Context> {
        use crate::core::extraction::tracks::TrackExtractor;
        use crate::core::io::runner::CommandRunner;
        use crate::core::models::jobs::PlanItem;

        ctx.log("[Extract] Extracting tracks from sources...");

        // Create command runner
        let runner = CommandRunner::new()
            .with_compact_mode(true)
            .with_log_callback(Arc::new({
                let log = ctx.log.clone();
                move |msg: &str| log(msg)
            }));

        // Create track extractor
        let extractor = TrackExtractor::new(runner, ctx.temp_dir.clone());

        let mut plan_items = Vec::new();

        // Extract from each source
        for (source_id, source_path) in &ctx.sources {
            ctx.log(&format!("[Extract] Processing source: {}", source_id));

            // Get media info
            let tracks = match extractor.get_media_info(source_path) {
                Ok(tracks) => tracks,
                Err(e) => {
                    ctx.log(&format!(
                        "[Extract] Warning: Failed to get media info for {}: {}",
                        source_id, e
                    ));
                    continue;
                }
            };

            ctx.log(&format!(
                "[Extract] Found {} tracks in {}",
                tracks.len(),
                source_id
            ));

            // Extract each track
            for track in tracks {
                ctx.log(&format!(
                    "[Extract] Extracting {} track {} from {}",
                    track.track_type.prefix(),
                    track.id,
                    source_id
                ));

                match extractor.extract_track(source_path, &track) {
                    Ok(extracted_path) => {
                        let mut item = PlanItem::from_track(track.clone());
                        item.extracted_path = Some(extracted_path.clone());

                        ctx.log(&format!(
                            "[Extract] Extracted to: {}",
                            extracted_path.display()
                        ));

                        plan_items.push(item);
                    }
                    Err(e) => {
                        ctx.log(&format!(
                            "[Extract] Warning: Failed to extract track {}: {}",
                            track.id, e
                        ));
                    }
                }
            }
        }

        ctx.log(&format!(
            "[Extract] Successfully extracted {} tracks",
            plan_items.len()
        ));

        ctx.extracted_items = Some(plan_items);
        ctx.log("[Extract] Track extraction complete");
        Ok(ctx)
    }

    /// Validate extraction step
    fn validate_extraction(ctx: &Context) -> PipelineResult<()> {
        if ctx.extracted_items.is_none() {
            return Err("Extraction step failed: no tracks extracted".into());
        }
        Ok(())
    }

    /// Run subtitles step (convert, rescale, timing fixes)
    fn run_subtitles_step(mut ctx: Context) -> PipelineResult<Context> {
        use crate::core::io::runner::CommandRunner;
        use crate::core::subtitles::convert::convert_srt_to_ass;
        use crate::core::subtitles::rescale::{get_video_resolution, rescale_playres};
        use crate::core::subtitles::style::multiply_font_sizes;

        ctx.log("[Subtitles] Processing subtitles...");

        // Create command runner for ffprobe
        let runner = CommandRunner::new()
            .with_compact_mode(true)
            .with_log_callback(Arc::new({
                let log = ctx.log.clone();
                move |msg: &str| log(msg)
            }));

        // Get reference video resolution (if we need to rescale)
        let ref_path = ctx.sources.get("REF");
        let video_resolution = if ref_path.is_some() {
            match ref_path
                .and_then(|p| get_video_resolution(p, &runner).ok())
            {
                Some(res) => {
                    ctx.log(&format!(
                        "[Subtitles] Reference video resolution: {}x{}",
                        res.0, res.1
                    ));
                    Some(res)
                }
                None => {
                    ctx.log("[Subtitles] Warning: Could not determine reference video resolution");
                    None
                }
            }
        } else {
            None
        };

        // Clone log function to avoid borrow checker issues
        let log = ctx.log.clone();

        // Process subtitle tracks
        if let Some(items) = &mut ctx.extracted_items {
            let mut subtitle_count = 0;

            for item in items.iter_mut() {
                if !item.is_subtitle() {
                    continue;
                }

                subtitle_count += 1;

                let current_path = match &item.extracted_path {
                    Some(p) => p.clone(),
                    None => continue,
                };

                log(&format!(
                    "[Subtitles] Processing subtitle track {} from {}",
                    item.track.id, item.track.source
                ));

                // Step 1: Convert SRT to ASS if requested
                let mut working_path = current_path.clone();
                if item.convert_to_ass {
                    match convert_srt_to_ass(&working_path, &runner) {
                        Ok(converted_path) => {
                            working_path = converted_path.clone();
                            item.extracted_path = Some(converted_path);
                            log("[Subtitles] Converted to ASS format");
                        }
                        Err(e) => {
                            log(&format!("[Subtitles] Warning: Conversion failed: {}", e));
                        }
                    }
                }

                // Step 2: Rescale PlayRes if requested and possible
                if item.rescale {
                    if let Some((width, height)) = video_resolution {
                        match rescale_playres(&working_path, width, height) {
                            Ok(true) => {
                                log(&format!(
                                    "[Subtitles] Rescaled PlayRes to {}x{}",
                                    width, height
                                ));
                            }
                            Ok(false) => {
                                log("[Subtitles] No PlayRes tags found to rescale");
                            }
                            Err(e) => {
                                log(&format!("[Subtitles] Warning: Rescale failed: {}", e));
                            }
                        }
                    } else {
                        log("[Subtitles] Warning: Cannot rescale without video resolution");
                    }
                }

                // Step 3: Apply font size multiplier if requested
                if item.size_multiplier != 1.0 && item.size_multiplier > 0.0 {
                    match multiply_font_sizes(&working_path, item.size_multiplier) {
                        Ok(count) => {
                            log(&format!(
                                "[Subtitles] Multiplied font sizes by {:.2}x ({} styles modified)",
                                item.size_multiplier, count
                            ));
                        }
                        Err(e) => {
                            log(&format!(
                                "[Subtitles] Warning: Font size multiplication failed: {}",
                                e
                            ));
                        }
                    }
                }
            }

            log(&format!(
                "[Subtitles] Processed {} subtitle tracks",
                subtitle_count
            ));
        }

        ctx.log("[Subtitles] Subtitle processing complete");
        Ok(ctx)
    }

    /// Run chapters step (extract, shift, snap)
    fn run_chapters_step(mut ctx: Context) -> PipelineResult<Context> {
        use crate::core::chapters::process::process_chapters;
        use crate::core::io::runner::CommandRunner;

        ctx.log("[Chapters] Processing chapters...");

        // Get reference MKV path
        let ref_path = match ctx.sources.get("REF") {
            Some(p) => p,
            None => {
                ctx.log("[Chapters] No reference source found, skipping chapter processing");
                return Ok(ctx);
            }
        };

        // Get global shift from delays
        let shift_ms = ctx
            .delays
            .as_ref()
            .map(|d| d.global_shift_ms)
            .unwrap_or(0);

        // Build config from settings
        let config = ctx.settings_dict.clone();

        // Create command runner
        let runner = CommandRunner::new()
            .with_compact_mode(true)
            .with_log_callback(Arc::new({
                let log = ctx.log.clone();
                move |msg: &str| log(msg)
            }));

        // Process chapters (use reference path as video for keyframe snapping)
        match process_chapters(
            ref_path,
            &ctx.temp_dir,
            shift_ms,
            &config,
            &runner,
            Some(ref_path),
        ) {
            Ok(Some(chapters_xml_path)) => {
                ctx.log(&format!(
                    "[Chapters] Chapters processed successfully: {}",
                    chapters_xml_path.display()
                ));
                ctx.chapters_xml = Some(chapters_xml_path);
            }
            Ok(None) => {
                ctx.log("[Chapters] No chapters found in reference file");
            }
            Err(e) => {
                ctx.log(&format!("[Chapters] Warning: Chapter processing failed: {}", e));
            }
        }

        ctx.log("[Chapters] Chapter processing complete");
        Ok(ctx)
    }

    /// Run mux step (build mkvmerge command and execute)
    fn run_mux_step(mut ctx: Context) -> PipelineResult<Context> {
        use crate::core::io::runner::CommandRunner;
        use crate::core::models::jobs::MergePlan;
        use crate::core::mux::options_builder::OptionsBuilder;

        ctx.log("[Mux] Building mkvmerge command...");

        // Get required data
        let items = ctx
            .extracted_items
            .as_ref()
            .ok_or("No extracted items available")?
            .clone();

        let delays = ctx
            .delays
            .as_ref()
            .ok_or("No delays available")?
            .clone();

        // Build output path
        let ref_path = ctx
            .sources
            .get("REF")
            .ok_or("Reference source not found")?;

        let output_filename = ref_path
            .file_stem()
            .and_then(|s| s.to_str())
            .ok_or("Invalid reference filename")?;

        let output_path = ctx.output_dir.join(format!("{}_merged.mkv", output_filename));

        ctx.log(&format!("[Mux] Output file: {}", output_path.display()));

        // Create merge plan
        let mut plan = MergePlan::new(
            items,
            delays,
            output_path.clone(),
            ctx.temp_dir.clone(),
        );

        // Set chapters flag
        plan.include_chapters = ctx.chapters_xml.is_some();

        // Build mkvmerge options
        let builder = OptionsBuilder::new()
            .with_disable_track_stats(
                ctx.settings_dict
                    .get("disable_track_statistics_tags")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false),
            )
            .with_apply_dialog_norm_gain(
                ctx.settings_dict
                    .get("apply_dialog_norm_gain")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false),
            );

        let mut options = builder.build(&plan);

        // Add chapters if available
        if let Some(chapters_xml) = &ctx.chapters_xml {
            // Replace placeholder with actual chapters path
            if let Some(pos) = options.iter().position(|s| s.contains("REF_CHAPTERS.xml")) {
                options[pos] = chapters_xml.display().to_string();
            } else {
                options.push("--chapters".to_string());
                options.push(chapters_xml.display().to_string());
            }
        }

        // Store tokens for inspection
        ctx.tokens = Some(options.clone());

        // Log command preview
        ctx.log(&format!("[Mux] mkvmerge options: {} arguments", options.len()));

        // Create command runner
        let runner = CommandRunner::new()
            .with_compact_mode(true)
            .with_log_callback(Arc::new({
                let log = ctx.log.clone();
                move |msg: &str| log(msg)
            }));

        // Build full command
        let mut cmd = vec!["mkvmerge"];
        cmd.extend(options.iter().map(|s| s.as_str()));

        ctx.log("[Mux] Executing mkvmerge...");

        // Execute mkvmerge
        match runner.run(&cmd) {
            Ok(output) => {
                if output.success {
                    ctx.log(&format!(
                        "[Mux] Successfully created: {}",
                        output_path.display()
                    ));
                    ctx.out_file = Some(output_path);
                } else {
                    return Err(format!("mkvmerge failed: {}", output.stderr).into());
                }
            }
            Err(e) => {
                return Err(format!("Failed to execute mkvmerge: {}", e).into());
            }
        }

        ctx.log("[Mux] Muxing complete");
        Ok(ctx)
    }

    /// Validate mux step
    fn validate_mux(ctx: &Context) -> PipelineResult<()> {
        if ctx.out_file.is_none() {
            return Err("Mux step failed: no output file generated".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::models::settings::AppSettings;
    use std::collections::HashMap;
    use std::sync::Arc;
    use tempfile::TempDir;

    #[test]
    fn test_analysis_only_pipeline() {
        let temp_dir = TempDir::new().unwrap();
        let output_dir = temp_dir.path().to_path_buf();
        let temp_work_dir = temp_dir.path().join("temp");
        std::fs::create_dir(&temp_work_dir).unwrap();

        let mut sources = HashMap::new();
        sources.insert("REF".to_string(), output_dir.join("test.mkv"));

        let log = Arc::new(|msg: &str| {
            println!("{}", msg);
        });

        let progress = Arc::new(|p: f64| {
            println!("Progress: {:.1}%", p * 100.0);
        });

        let ctx = Context::new(
            AppSettings::default(),
            output_dir,
            temp_work_dir,
            sources,
            log,
            progress,
        );

        // Run analysis-only (and_merge = false by default)
        let result = Orchestrator::run(ctx);
        assert!(result.is_ok());

        let ctx = result.unwrap();
        assert!(ctx.delays.is_some());
        assert!(ctx.extracted_items.is_none()); // Should not extract in analysis-only mode
    }
}
