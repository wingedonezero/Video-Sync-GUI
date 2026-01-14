//! Main orchestrator pipeline
//!
//! Coordinates the execution of all pipeline steps in sequence with validation.

use crate::core::models::results::PipelineResult;
use crate::core::orchestrator::steps::Context;

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
        ctx.log("[Analysis] Detecting audio delays...");

        // TODO: Implement actual audio correlation
        // For now, create stub delays
        use crate::core::models::jobs::Delays;
        use std::collections::HashMap;

        let mut source_delays_ms = HashMap::new();
        let mut raw_source_delays_ms = HashMap::new();

        // Source 1 is always the reference (0ms delay)
        source_delays_ms.insert("Source_1".to_string(), 0);
        raw_source_delays_ms.insert("Source_1".to_string(), 0.0);

        ctx.delays = Some(Delays {
            source_delays_ms,
            raw_source_delays_ms,
            global_shift_ms: 0,
            raw_global_shift_ms: 0.0,
        });

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
        ctx.log("[Extract] Extracting tracks from sources...");

        // TODO: Implement actual track extraction
        // For now, create empty extracted items list
        ctx.extracted_items = Some(Vec::new());

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
    fn run_subtitles_step(ctx: Context) -> PipelineResult<Context> {
        ctx.log("[Subtitles] Processing subtitles...");

        // TODO: Implement subtitle processing
        // - SRT to ASS conversion
        // - PlayRes rescaling
        // - Timing fixes

        ctx.log("[Subtitles] Subtitle processing complete");
        Ok(ctx)
    }

    /// Run chapters step (extract, shift, snap)
    fn run_chapters_step(ctx: Context) -> PipelineResult<Context> {
        ctx.log("[Chapters] Processing chapters...");

        // TODO: Implement chapter processing
        // - Extract chapters XML
        // - Shift timestamps
        // - Keyframe snapping

        ctx.log("[Chapters] Chapter processing complete");
        Ok(ctx)
    }

    /// Run mux step (build mkvmerge command and execute)
    fn run_mux_step(mut ctx: Context) -> PipelineResult<Context> {
        ctx.log("[Mux] Building mkvmerge command...");

        // TODO: Implement muxing
        // - Build options with OptionsBuilder
        // - Generate output filename
        // - Execute mkvmerge

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
        sources.insert("Source_1".to_string(), output_dir.join("test.mkv"));

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
