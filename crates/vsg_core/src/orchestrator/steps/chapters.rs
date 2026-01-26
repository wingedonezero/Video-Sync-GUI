//! Chapters step - extracts and processes chapter information from Source 1.
//!
//! Extracts chapters XML from the primary source file using mkvextract,
//! applies global shift to keep chapters in sync with shifted audio tracks,
//! and optionally snaps chapters to video keyframes.

use crate::chapters::{
    extract_chapters_to_string, extract_keyframes, format_timestamp_ns, parse_chapter_xml,
    process_chapters, shift_chapters, snap_chapters_with_threshold, write_chapter_file,
    SnapDetail, SnapMode as ChapterSnapMode,
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

        // Process chapters: deduplicate, normalize ends, and optionally rename
        let proc_stats = process_chapters(
            &mut chapter_data,
            true,  // Always deduplicate
            true,  // Always normalize ends
            ctx.settings.chapters.rename,
        );

        // Log duplicate removal details
        if !proc_stats.duplicates.is_empty() {
            ctx.logger.info(&format!(
                "Removed {} duplicate chapters",
                proc_stats.duplicates.len()
            ));
            for dup in &proc_stats.duplicates {
                ctx.logger.info(&format!(
                    "  - Removed duplicate '{}' at {}",
                    dup.name,
                    format_timestamp_ns(dup.timestamp_ns)
                ));
            }
        }

        // Log normalization details
        if !proc_stats.normalized.is_empty() {
            ctx.logger.info("Normalizing chapter data...");
            for norm in &proc_stats.normalized {
                ctx.logger.info(&format!(
                    "  - Normalized {} (to create seamless chapters)",
                    norm.format_change()
                ));
            }
        }

        // Log rename details
        if !proc_stats.renamed.is_empty() {
            ctx.logger.info("Renaming chapters to \"Chapter NN\"...");
            for rename in &proc_stats.renamed {
                let ietf = rename.language_ietf.as_deref().unwrap_or("und");
                ctx.logger.info(&format!(
                    "  - Renamed chapter {} (language: {}, IETF: {})",
                    rename.chapter_number,
                    rename.language,
                    ietf
                ));
            }
        }

        // Apply global shift if needed
        let global_shift = state
            .analysis
            .as_ref()
            .map(|a| a.delays.global_shift_ms)
            .unwrap_or(0);

        if global_shift != 0 {
            ctx.logger.info(&format!(
                "Applying global shift of {:+}ms to chapters",
                global_shift
            ));
            shift_chapters(&mut chapter_data, global_shift);
        } else {
            ctx.logger.info("No global shift needed for chapters");
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
                        "Found {} keyframes for snapping.",
                        keyframes.timestamps_ns.len()
                    ));

                    // Convert settings snap_mode to chapter snap_mode
                    let snap_mode = match ctx.settings.chapters.snap_mode {
                        crate::models::SnapMode::Previous => ChapterSnapMode::Previous,
                        crate::models::SnapMode::Nearest => ChapterSnapMode::Nearest,
                    };

                    let mode_str = match snap_mode {
                        ChapterSnapMode::Nearest => "nearest",
                        ChapterSnapMode::Previous => "previous",
                        ChapterSnapMode::Next => "next",
                    };
                    ctx.logger.info(&format!(
                        "Snapping with mode={}, threshold={}ms...",
                        mode_str,
                        threshold_ms
                    ));

                    // Snap chapters to keyframes with threshold enforcement
                    // snap_starts_only=true means DON'T snap ends, so snap_ends = !snap_starts_only
                    let snap_ends = !ctx.settings.chapters.snap_starts_only;
                    if snap_ends {
                        ctx.logger.info("Also snapping chapter end times");
                    }
                    let stats = snap_chapters_with_threshold(
                        &mut chapter_data,
                        &keyframes,
                        snap_mode,
                        Some(threshold_ms),
                        snap_ends,
                    );

                    snapped = stats.moved > 0 || stats.already_aligned > 0;

                    // Log per-chapter details
                    for detail in &stats.details {
                        match detail {
                            SnapDetail::AlreadyAligned { name, timestamp_ns } => {
                                ctx.logger.info(&format!(
                                    "  - Kept '{}' ({}) - already on keyframe.",
                                    name,
                                    SnapDetail::format_timestamp_full(*timestamp_ns)
                                ));
                            }
                            SnapDetail::Snapped { name, original_ns, new_ns, shift_ns } => {
                                ctx.logger.info(&format!(
                                    "  - Snapped '{}' ({}) -> {} (moved by {})",
                                    name,
                                    SnapDetail::format_timestamp_full(*original_ns),
                                    SnapDetail::format_timestamp_full(*new_ns),
                                    SnapDetail::format_shift(*shift_ns)
                                ));
                            }
                            SnapDetail::Skipped { name, timestamp_ns, would_shift_ns, threshold_ns } => {
                                ctx.logger.info(&format!(
                                    "  - Skipped '{}' ({}) - {} exceeds threshold of {}ms",
                                    name,
                                    SnapDetail::format_timestamp_full(*timestamp_ns),
                                    SnapDetail::format_shift(*would_shift_ns),
                                    threshold_ns / 1_000_000
                                ));
                            }
                        }
                    }

                    // Log summary
                    ctx.logger.info(&format!(
                        "Snap complete: {} moved, {} on keyframe, {} skipped.",
                        stats.moved,
                        stats.already_aligned,
                        stats.skipped
                    ));
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

        ctx.logger.info(&format!(
            "Chapters XML written to: {}",
            output_path.display()
        ));

        state.chapters = Some(ChaptersOutput {
            chapters_xml: Some(output_path.clone()),
            snapped,
        });

        ctx.logger.info(&format!(
            "Successfully processed chapters: {}",
            output_path.display()
        ));
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
