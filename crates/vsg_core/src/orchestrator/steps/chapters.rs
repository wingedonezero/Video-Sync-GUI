//! Chapters step - extracts and processes chapter information from Source 1.
//!
//! Extracts chapters XML from the primary source file using mkvextract,
//! applies global shift to keep chapters in sync with shifted audio tracks.

use std::path::PathBuf;
use std::process::Command;

use crate::orchestrator::errors::{StepError, StepResult};
use crate::orchestrator::step::PipelineStep;
use crate::orchestrator::types::{ChaptersOutput, Context, JobState, StepOutcome};

/// Chapters step for extracting and processing chapter data.
///
/// Uses mkvextract to pull chapter XML from Source 1, then applies
/// any global shift to keep chapters in sync with audio timing adjustments.
pub struct ChaptersStep;

impl ChaptersStep {
    pub fn new() -> Self {
        Self
    }

    /// Extract chapters XML from a source file.
    fn extract_chapters(
        &self,
        source_path: &PathBuf,
        work_dir: &PathBuf,
        mkvextract_path: &str,
    ) -> StepResult<Option<PathBuf>> {
        let output_path = work_dir.join("chapters.xml");

        // mkvextract chapters <source> > chapters.xml
        // Note: mkvextract chapters writes to stdout, we need to capture it
        let output = Command::new(mkvextract_path)
            .arg("chapters")
            .arg(source_path)
            .output()
            .map_err(|e| StepError::io_error("running mkvextract", e))?;

        if !output.status.success() {
            // mkvextract returns non-zero if no chapters, which is fine
            return Ok(None);
        }

        let chapters_xml = String::from_utf8_lossy(&output.stdout);

        // Check if we actually got chapter data
        if chapters_xml.trim().is_empty() || !chapters_xml.contains("<Chapters>") {
            return Ok(None);
        }

        // Write to file
        std::fs::write(&output_path, chapters_xml.as_bytes())
            .map_err(|e| StepError::io_error("writing chapters XML", e))?;

        Ok(Some(output_path))
    }

    /// Apply global shift to chapter timestamps.
    ///
    /// When we shift all audio tracks to eliminate negative delays,
    /// chapters need to be shifted by the same amount to stay in sync.
    fn apply_shift_to_chapters(
        &self,
        chapters_path: &PathBuf,
        shift_ms: i64,
    ) -> StepResult<()> {
        if shift_ms == 0 {
            return Ok(());
        }

        // Read chapters XML
        let content = std::fs::read_to_string(chapters_path)
            .map_err(|e| StepError::io_error("reading chapters XML", e))?;

        // Parse and shift chapter times
        // Chapters use format: <ChapterTimeStart>HH:MM:SS.nnnnnnnnn</ChapterTimeStart>
        let mut modified = String::new();
        let mut in_time_tag = false;
        let mut time_buffer = String::new();
        let mut i = 0;
        let chars: Vec<char> = content.chars().collect();

        while i < chars.len() {
            let remaining: String = chars[i..].iter().collect();

            if remaining.starts_with("<ChapterTimeStart>") {
                modified.push_str("<ChapterTimeStart>");
                i += "<ChapterTimeStart>".len();
                in_time_tag = true;
                time_buffer.clear();
            } else if remaining.starts_with("</ChapterTimeStart>") && in_time_tag {
                // Parse and shift the time
                if let Some(shifted) = self.shift_chapter_time(&time_buffer, shift_ms) {
                    modified.push_str(&shifted);
                } else {
                    modified.push_str(&time_buffer);
                }
                modified.push_str("</ChapterTimeStart>");
                i += "</ChapterTimeStart>".len();
                in_time_tag = false;
            } else if in_time_tag {
                time_buffer.push(chars[i]);
                i += 1;
            } else {
                modified.push(chars[i]);
                i += 1;
            }
        }

        // Write modified chapters
        std::fs::write(chapters_path, modified)
            .map_err(|e| StepError::io_error("writing shifted chapters", e))?;

        Ok(())
    }

    /// Shift a single chapter timestamp by the given milliseconds.
    fn shift_chapter_time(&self, time_str: &str, shift_ms: i64) -> Option<String> {
        // Parse HH:MM:SS.nnnnnnnnn format
        let parts: Vec<&str> = time_str.split(':').collect();
        if parts.len() != 3 {
            return None;
        }

        let hours: u64 = parts[0].parse().ok()?;
        let minutes: u64 = parts[1].parse().ok()?;

        let sec_parts: Vec<&str> = parts[2].split('.').collect();
        let seconds: u64 = sec_parts[0].parse().ok()?;
        let nanos: u64 = if sec_parts.len() > 1 {
            // Pad or truncate to 9 digits
            let nano_str = format!("{:0<9}", sec_parts[1]);
            nano_str[..9.min(nano_str.len())].parse().unwrap_or(0)
        } else {
            0
        };

        // Convert to total nanoseconds
        let total_ns: i128 = (hours as i128 * 3600 + minutes as i128 * 60 + seconds as i128)
            * 1_000_000_000
            + nanos as i128;

        // Apply shift (convert ms to ns)
        let shifted_ns = total_ns + (shift_ms as i128 * 1_000_000);

        // Don't allow negative times
        let shifted_ns = shifted_ns.max(0) as u128;

        // Convert back to HH:MM:SS.nnnnnnnnn
        let total_seconds = shifted_ns / 1_000_000_000;
        let remaining_nanos = shifted_ns % 1_000_000_000;

        let h = total_seconds / 3600;
        let m = (total_seconds % 3600) / 60;
        let s = total_seconds % 60;

        Some(format!(
            "{:02}:{:02}:{:02}.{:09}",
            h, m, s, remaining_nanos
        ))
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

        // Use mkvextract from PATH (configurable tool paths not yet implemented)
        let mkvextract_path = "mkvextract";

        // Extract chapters
        let chapters_xml = match self.extract_chapters(source1, &ctx.work_dir, mkvextract_path) {
            Ok(Some(path)) => {
                ctx.logger.info(&format!("Extracted chapters to: {}", path.display()));
                path
            }
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

            if let Err(e) = self.apply_shift_to_chapters(&chapters_xml, global_shift) {
                ctx.logger.warn(&format!("Failed to shift chapters: {}", e));
                // Continue with unshifted chapters
            }
        }

        state.chapters = Some(ChaptersOutput {
            chapters_xml: Some(chapters_xml),
            snapped: false,
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

    #[test]
    fn shift_chapter_time_positive() {
        let step = ChaptersStep::new();
        let result = step.shift_chapter_time("00:01:30.000000000", 500);
        assert_eq!(result, Some("00:01:30.500000000".to_string()));
    }

    #[test]
    fn shift_chapter_time_negative_clamps() {
        let step = ChaptersStep::new();
        let result = step.shift_chapter_time("00:00:00.100000000", -200);
        assert_eq!(result, Some("00:00:00.000000000".to_string()));
    }
}
