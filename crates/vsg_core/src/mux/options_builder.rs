//! mkvmerge command options builder.
//!
//! Builds command-line tokens for mkvmerge based on a MergePlan.
//! Handles track options, delays, chapters, and attachments.
//!
//! # Delay Calculation
//!
//! Delays are calculated differently depending on track type and source:
//!
//! - **Source 1 VIDEO**: Only gets `global_shift_ms` (video defines timeline)
//! - **Source 1 AUDIO**: Gets `container_delay_ms` (track's original delay) + `global_shift_ms`
//! - **Other sources**: Gets `source_delays_ms[source]` which already includes global_shift
//!
//! This matches the Python implementation in `_effective_delay_ms()`.

use std::path::Path;

use crate::config::Settings;
use crate::models::{MergePlan, PlanItem, TrackType};

/// Builder for mkvmerge command-line options.
///
/// Generates a list of string tokens that form a complete mkvmerge command.
pub struct MkvmergeOptionsBuilder<'a> {
    plan: &'a MergePlan,
    settings: &'a Settings,
    output_path: &'a Path,
}

impl<'a> MkvmergeOptionsBuilder<'a> {
    /// Create a new options builder.
    pub fn new(plan: &'a MergePlan, settings: &'a Settings, output_path: &'a Path) -> Self {
        Self {
            plan,
            settings,
            output_path,
        }
    }

    /// Build the complete mkvmerge command tokens.
    ///
    /// Returns a vector of strings ready to pass to mkvmerge.
    pub fn build(&self) -> Vec<String> {
        let mut tokens = Vec::new();

        // Output file
        tokens.push("-o".to_string());
        tokens.push(self.output_path.to_string_lossy().to_string());

        // Global options
        self.add_global_options(&mut tokens);

        // Chapters (if any)
        if let Some(ref chapters_path) = self.plan.chapters_xml {
            tokens.push("--chapters".to_string());
            tokens.push(chapters_path.to_string_lossy().to_string());
        }

        // Track options and files
        self.add_track_options(&mut tokens);

        // Attachments
        for attachment_path in &self.plan.attachments {
            tokens.push("--attach-file".to_string());
            tokens.push(attachment_path.to_string_lossy().to_string());
        }

        // Track order
        self.add_track_order(&mut tokens);

        tokens
    }

    /// Add global options based on settings.
    fn add_global_options(&self, tokens: &mut Vec<String>) {
        if self.settings.postprocess.disable_track_stats_tags {
            tokens.push("--disable-track-statistics-tags".to_string());
        }
    }

    /// Add options for each track.
    fn add_track_options(&self, tokens: &mut Vec<String>) {
        for item in &self.plan.items {
            self.add_single_track_options(tokens, item);
        }
    }

    /// Add options for a single track/file.
    fn add_single_track_options(&self, tokens: &mut Vec<String>, item: &PlanItem) {
        let track = &item.track;
        let track_id = "0"; // Track ID within the file (usually 0 for extracted tracks)

        // Language
        if !item.custom_lang.is_empty() {
            tokens.push("--language".to_string());
            tokens.push(format!("{}:{}", track_id, item.custom_lang));
        } else if !track.props.lang.is_empty() && track.props.lang != "und" {
            tokens.push("--language".to_string());
            tokens.push(format!("{}:{}", track_id, track.props.lang));
        }

        // Track name
        if !item.custom_name.is_empty() {
            tokens.push("--track-name".to_string());
            tokens.push(format!("{}:{}", track_id, item.custom_name));
        } else if !track.props.name.is_empty() {
            tokens.push("--track-name".to_string());
            tokens.push(format!("{}:{}", track_id, track.props.name));
        }

        // Sync delay - round raw value only here for mkvmerge
        // mkvmerge only accepts integer milliseconds
        //
        // IMPORTANT: container_delay_ms_raw ALREADY includes global_shift from the analysis step.
        // Do NOT add global_shift again here - that would cause double-application.
        //
        // The delay flow is:
        // 1. AnalyzeStep: calculates raw delay, adds global_shift, stores in raw_source_delays_ms
        // 2. MuxStep: reads from raw_source_delays_ms, sets container_delay_ms_raw
        // 3. OptionsBuilder (here): uses container_delay_ms_raw directly (NO additional shift)
        let final_delay_ms = item.container_delay_ms_raw;
        if final_delay_ms.abs() > 0.001 {
            let delay_rounded = final_delay_ms.round() as i64;
            tokens.push("--sync".to_string());
            tokens.push(format!("{}:{:+}", track_id, delay_rounded));

            // Log for debugging
            tracing::debug!(
                "mkvmerge --sync for {} ({}:{}): raw={:.3}ms → rounded={:+}ms",
                track.source,
                track.track_type,
                track.id,
                final_delay_ms,
                delay_rounded
            );
        }

        // Default track flag
        tokens.push("--default-track-flag".to_string());
        tokens.push(format!(
            "{}:{}",
            track_id,
            if item.is_default { "yes" } else { "no" }
        ));

        // Forced display flag (for subtitles)
        if item.is_forced_display && track.track_type == TrackType::Subtitles {
            tokens.push("--forced-display-flag".to_string());
            tokens.push(format!("{}:yes", track_id));
        }

        // Header compression (if disabled in settings)
        if self.settings.postprocess.disable_header_compression {
            tokens.push("--compression".to_string());
            tokens.push(format!("{}:none", track_id));
        }

        // Dialog normalization (for audio)
        if self.settings.postprocess.apply_dialog_norm && track.track_type == TrackType::Audio {
            let codec_lower = track.props.codec_id.to_lowercase();
            if codec_lower.contains("ac3") || codec_lower.contains("eac3") {
                tokens.push("--remove-dialog-normalization-gain".to_string());
                tokens.push(track_id.to_string());
            }
        }

        // File path (use extracted path if available, otherwise source)
        let file_path = item.extracted_path.as_ref().unwrap_or(&item.source_path);

        // Wrap in parentheses for mkvmerge file grouping
        tokens.push("(".to_string());
        tokens.push(file_path.to_string_lossy().to_string());
        tokens.push(")".to_string());
    }

    /// Add track order option.
    fn add_track_order(&self, tokens: &mut Vec<String>) {
        if self.plan.items.is_empty() {
            return;
        }

        // Build track order string: "0:0,1:0,2:0,..."
        // Each entry is file_index:track_index
        let order: Vec<String> = self
            .plan
            .items
            .iter()
            .enumerate()
            .map(|(file_idx, _)| format!("{}:0", file_idx))
            .collect();

        if !order.is_empty() {
            tokens.push("--track-order".to_string());
            tokens.push(order.join(","));
        }
    }
}

/// Format tokens for pretty display (one option per line).
pub fn format_tokens_pretty(tokens: &[String]) -> String {
    let mut result = String::new();
    let mut i = 0;

    while i < tokens.len() {
        let token = &tokens[i];

        if token.starts_with('-') && i + 1 < tokens.len() && !tokens[i + 1].starts_with('-') {
            // Option with value
            result.push_str(&format!("{} {} \\\n", token, tokens[i + 1]));
            i += 2;
        } else if token == "(" || token == ")" {
            // File grouping
            result.push_str(&format!("{}\n", token));
            i += 1;
        } else {
            result.push_str(&format!("{} \\\n", token));
            i += 1;
        }
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::{Delays, StreamProps, Track};
    use std::path::PathBuf;

    fn make_test_track(track_type: TrackType) -> Track {
        Track::new(
            "Source 1",
            0,
            track_type,
            StreamProps::new("TestCodec")
                .with_lang("eng")
                .with_name("Test Track"),
        )
    }

    #[test]
    fn builds_basic_command() {
        let plan = MergePlan::new(
            vec![PlanItem::new(
                make_test_track(TrackType::Video),
                "/test/source.mkv",
            )],
            Delays::default(),
        );
        let settings = Settings::default();
        let output = PathBuf::from("/test/output.mkv");

        let builder = MkvmergeOptionsBuilder::new(&plan, &settings, &output);
        let tokens = builder.build();

        assert!(tokens.contains(&"-o".to_string()));
        assert!(tokens.contains(&"/test/output.mkv".to_string()));
    }

    #[test]
    fn adds_delay_option() {
        let mut item = PlanItem::new(make_test_track(TrackType::Audio), "/test/source.mkv");
        item.container_delay_ms_raw = -150.0;

        let plan = MergePlan::new(vec![item], Delays::default());
        let settings = Settings::default();
        let output = PathBuf::from("/test/output.mkv");

        let builder = MkvmergeOptionsBuilder::new(&plan, &settings, &output);
        let tokens = builder.build();

        assert!(tokens.contains(&"--sync".to_string()));
        assert!(tokens.contains(&"0:-150".to_string()));
    }

    #[test]
    fn adds_chapters() {
        let mut plan = MergePlan::new(vec![], Delays::default());
        plan.chapters_xml = Some(PathBuf::from("/test/chapters.xml"));

        let settings = Settings::default();
        let output = PathBuf::from("/test/output.mkv");

        let builder = MkvmergeOptionsBuilder::new(&plan, &settings, &output);
        let tokens = builder.build();

        assert!(tokens.contains(&"--chapters".to_string()));
        assert!(tokens.contains(&"/test/chapters.xml".to_string()));
    }
}
