//! Chapters step - extracts and processes chapter information from Source 1.
//!
//! Extracts chapters XML from the primary source file using mkvextract,
//! applies global shift to keep chapters in sync with shifted audio tracks,
//! and optionally snaps chapters to video keyframes.

use crate::chapters::{
    extract_chapters_to_string, extract_keyframes, parse_chapter_xml, shift_chapters,
    snap_chapters_with_threshold, write_chapter_file, SnapMode as ChapterSnapMode,
};
use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{ChaptersOutput, Context, JobState, StepOutcome};

/// Chapters step for extracting and processing chapter data.
///
/// Uses the chapters module to pull chapter XML from Source 1, then applies
/// any global shift to keep chapters in sync with audio timing adjustments.
pub struct ChaptersStep;

impl ChaptersStep {
    pub fn new() -> Self {
        Self
    }
}

impl Default for ChaptersStep {
    fn default() -> Self {
        Self::new()
    }
}

impl PipelineStep for ChaptersStep {
    fn name(&self) -> &str {
        "Chapters"
    }

    fn description(&self) -> &str {
        "Extract and process chapter information"
    }

    fn validate_input(&self, ctx: &Context) -> StepResult<()> {
        // Need Source 1 for chapters
        if !ctx.job_spec.sources.contains_key("Source 1") {
            return Err(StepError::invalid_input("No Source 1 for chapter extraction"));
        }
        Ok(())
    }

    fn execute(&self, ctx: &Context, state: &mut JobState) -> StepResult<StepOutcome> {
        ctx.logger.info("Processing chapters...");

        let source1 = match ctx.job_spec.sources.get("Source 1") {
            Some(p) => p,
            None => {
                ctx.logger.info("No Source 1 - skipping chapters");
                state.chapters = Some(ChaptersOutput {
                    chapters_xml: None,
                    snapped: false,
                });
                return Ok(StepOutcome::Skipped("No Source 1".to_string()));
            }
        };

        // Extract chapters using the chapters module
        let chapter_xml = match extract_chapters_to_string(source1) {
            Ok(Some(xml)) => xml,
            Ok(None) => {
                ctx.logger.info("No chapters found in source");
                state.chapters = Some(ChaptersOutput {
                    chapters_xml: None,
                    snapped: false,
                });
                return Ok(StepOutcome::Success);
            }
            Err(e) => {
                // Chapters are optional - log warning but continue
                ctx.logger.warn(&format!("Failed to extract chapters: {}", e));
                state.chapters = Some(ChaptersOutput {
                    chapters_xml: None,
                    snapped: false,
                });
                return Ok(StepOutcome::Success);
            }
        };

        // Parse the chapter XML into structured data
        let mut chapter_data = match parse_chapter_xml(&chapter_xml) {
            Ok(data) => {
                ctx.logger.info(&format!("Parsed {} chapters", data.len()));
                data
            }
            Err(e) => {
                ctx.logger.warn(&format!("Failed to parse chapters: {}", e));
                state.chapters = Some(ChaptersOutput {
                    chapters_xml: None,
                    snapped: false,
                });
                return Ok(StepOutcome::Success);
            }
        };

        // Apply global shift if needed
        let global_shift = state
            .analysis
            .as_ref()
            .map(|a| a.delays.global_shift_ms)
            .unwrap_or(0);

        if global_shift != 0 {
            ctx.logger.info(&format!(
                "Applying global shift of +{}ms to chapters",
                global_shift
            ));
            shift_chapters(&mut chapter_data, global_shift);
        }

        // Apply keyframe snapping if enabled in settings
        let mut snapped = false;
        if ctx.settings.chapters.snap_enabled {
            let threshold_ms = ctx.settings.chapters.snap_threshold_ms as i64;
            ctx.logger.info(&format!(
                "Chapter snapping enabled (mode: {:?}, threshold: {}ms)",
                ctx.settings.chapters.snap_mode,
                threshold_ms
            ));

            // Extract keyframes from video
            match extract_keyframes(source1) {
                Ok(keyframes) => {
                    ctx.logger.info(&format!(
                        "Found {} keyframes in video",
                        keyframes.timestamps_ns.len()
                    ));

                    // Convert settings snap_mode to chapter snap_mode
                    let snap_mode = match ctx.settings.chapters.snap_mode {
                        crate::models::SnapMode::Previous => ChapterSnapMode::Previous,
                        crate::models::SnapMode::Nearest => ChapterSnapMode::Nearest,
                    };

                    // Snap chapters to keyframes with threshold enforcement
                    let stats = snap_chapters_with_threshold(
                        &mut chapter_data,
                        &keyframes,
                        snap_mode,
                        Some(threshold_ms),
                    );

                    snapped = stats.moved > 0 || stats.already_aligned > 0;

                    // Log detailed results
                    ctx.logger.info(&format!(
                        "Snap complete: {} moved, {} already on keyframe, {} skipped (exceeded {}ms threshold)",
                        stats.moved,
                        stats.already_aligned,
                        stats.skipped,
                        threshold_ms
                    ));

                    if stats.moved > 0 {
                        ctx.logger.info(&format!(
                            "Max shift: {}ms, avg shift: {:.1}ms",
                            stats.max_shift_ms,
                            stats.avg_shift_ms
                        ));
                    }
                }
                Err(e) => {
                    ctx.logger.warn(&format!(
                        "Failed to extract keyframes for snapping: {}",
                        e
                    ));
                }
            }
        } else {
            ctx.logger.info("Chapter snapping disabled");
        }

        // Write the (possibly shifted and snapped) chapters to a file
        let output_path = ctx.work_dir.join("chapters.xml");
        if let Err(e) = write_chapter_file(&chapter_data, &output_path) {
            ctx.logger.warn(&format!("Failed to write chapters: {}", e));
            state.chapters = Some(ChaptersOutput {
                chapters_xml: None,
                snapped: false,
            });
            return Ok(StepOutcome::Success);
        }

        ctx.logger
            .info(&format!("Wrote chapters to: {}", output_path.display()));

        state.chapters = Some(ChaptersOutput {
            chapters_xml: Some(output_path),
            snapped,
        });

        ctx.logger.info("Chapter processing complete");
        Ok(StepOutcome::Success)
    }

    fn validate_output(&self, _ctx: &Context, _state: &JobState) -> StepResult<()> {
        // Chapters are optional, so no strict validation
        Ok(())
    }

    fn is_optional(&self) -> bool {
        // Chapters are always optional
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chapters_step_has_correct_name() {
        let step = ChaptersStep::new();
        assert_eq!(step.name(), "Chapters");
    }

    #[test]
    fn chapters_step_is_optional() {
        let step = ChaptersStep::new();
        assert!(step.is_optional());
    }
}
