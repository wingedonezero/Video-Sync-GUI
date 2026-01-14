//! mkvmerge options builder
//!
//! Builds mkvmerge command line options with proper delay calculation.
//! CRITICAL: Must preserve exact Python behavior for delay calculation.

use crate::core::models::jobs::{Delays, MergePlan, PlanItem};

/// mkvmerge options builder
pub struct OptionsBuilder {
    /// Disable track statistics tags
    disable_track_stats: bool,

    /// Apply dialnorm gain
    apply_dialog_norm_gain: bool,
}

impl OptionsBuilder {
    /// Create a new options builder
    pub fn new() -> Self {
        Self {
            disable_track_stats: false,
            apply_dialog_norm_gain: false,
        }
    }

    /// Set disable track statistics tags
    pub fn with_disable_track_stats(mut self, disable: bool) -> Self {
        self.disable_track_stats = disable;
        self
    }

    /// Set apply dialnorm gain
    pub fn with_apply_dialog_norm_gain(mut self, apply: bool) -> Self {
        self.apply_dialog_norm_gain = apply;
        self
    }

    /// Build mkvmerge command options from merge plan
    pub fn build(&self, plan: &MergePlan) -> Vec<String> {
        let mut options = Vec::new();

        // Output file
        options.push("-o".to_string());
        options.push(plan.output_path.display().to_string());

        // Global options
        if self.disable_track_stats {
            options.push("--disable-track-statistics-tags".to_string());
        }

        // Track title (use first video track name)
        if let Some(video) = plan.reference_video() {
            if let Some(name) = &video.track.props.name {
                options.push("--title".to_string());
                options.push(name.clone());
            }
        }

        // Process tracks by source file
        let mut sources: std::collections::HashMap<String, Vec<&PlanItem>> =
            std::collections::HashMap::new();

        for item in &plan.items {
            sources
                .entry(item.track.source.clone())
                .or_insert_with(Vec::new)
                .push(item);
        }

        // Sort sources: REF, SEC, TER
        let source_order = vec!["REF", "SEC", "TER"];
        for source_id in source_order {
            if let Some(items) = sources.get(source_id) {
                self.add_source_options(&mut options, items, &plan.delays, source_id);
            }
        }

        // Chapters
        if plan.include_chapters {
            // Chapters from reference file
            options.push("--chapters".to_string());
            options.push("REF_CHAPTERS.xml".to_string()); // Placeholder
        }

        // Attachments
        if plan.include_attachments {
            // Attachments from all sources
            // Note: Actual implementation would track attachment files
        }

        options
    }

    /// Add options for tracks from a specific source
    fn add_source_options(
        &self,
        options: &mut Vec<String>,
        items: &[&PlanItem],
        delays: &Delays,
        source_id: &str,
    ) {
        if items.is_empty() {
            return;
        }

        // Get source file path from first item
        let source_path = items[0]
            .effective_path()
            .expect("Track must have extracted path");

        // Calculate delay for this source (CRITICAL - must match Python exactly)
        let effective_delay_ms = delays.effective_delay(source_id);

        // Track selection: list track IDs to include
        let track_ids: Vec<String> = items
            .iter()
            .map(|item| item.track.id.to_string())
            .collect();

        options.push("--audio-tracks".to_string());
        options.push(track_ids.join(","));

        // Apply delay to all tracks from this source
        if effective_delay_ms != 0 {
            options.push("--sync".to_string());
            options.push(format!("0:{}", effective_delay_ms));
        }

        // Per-track options
        for item in items {
            let track_id = item.track.id;

            // Track name
            if !item.custom_name.is_empty() {
                options.push("--track-name".to_string());
                options.push(format!("{}:{}", track_id, item.custom_name));
            } else if item.apply_track_name {
                if let Some(name) = &item.track.props.name {
                    options.push("--track-name".to_string());
                    options.push(format!("{}:{}", track_id, name));
                }
            }

            // Language
            if !item.custom_lang.is_empty() {
                options.push("--language".to_string());
                options.push(format!("{}:{}", track_id, item.custom_lang));
            } else if let Some(lang) = &item.track.props.lang {
                options.push("--language".to_string());
                options.push(format!("{}:{}", track_id, lang));
            }

            // Default track flag
            if item.is_default {
                options.push("--default-track-flag".to_string());
                options.push(format!("{}:1", track_id));
            } else {
                options.push("--default-track-flag".to_string());
                options.push(format!("{}:0", track_id));
            }

            // Forced display flag (subtitles)
            if item.is_forced_display && item.is_subtitle() {
                options.push("--forced-display-flag".to_string());
                options.push(format!("{}:1", track_id));
            }

            // Video aspect ratio
            if let Some(aspect) = &item.aspect_ratio {
                if item.is_video() {
                    options.push("--aspect-ratio".to_string());
                    options.push(format!("{}:{}", track_id, aspect));
                }
            }

            // Subtitle options
            if item.is_subtitle() {
                // SRT to ASS conversion is handled during extraction/processing
                // Rescaling is handled during extraction/processing
            }

            // Container delay (additional delay for specific track)
            if item.container_delay_ms != 0 {
                options.push("--sync".to_string());
                options.push(format!("{}:{}", track_id, item.container_delay_ms));
            }
        }

        // Add source file
        options.push(source_path.display().to_string());
    }

    /// Calculate track order (ensure proper ordering)
    pub fn calculate_track_order(plan: &MergePlan) -> Vec<usize> {
        let mut order = Vec::new();

        // Order: Video → Audio → Subtitles
        for (i, item) in plan.items.iter().enumerate() {
            if item.is_video() {
                order.push(i);
            }
        }
        for (i, item) in plan.items.iter().enumerate() {
            if item.is_audio() {
                order.push(i);
            }
        }
        for (i, item) in plan.items.iter().enumerate() {
            if item.is_subtitle() {
                order.push(i);
            }
        }

        order
    }

    /// Format delay value for mkvmerge (milliseconds)
    ///
    /// CRITICAL: This must match Python behavior exactly:
    /// - Python uses: round(delay_ms)
    /// - Must handle positive-only timing model
    /// - Global shift already applied in Delays struct
    pub fn format_delay(delay_ms: i64) -> String {
        format!("{}", delay_ms)
    }

    /// Validate merge plan before building options
    pub fn validate_plan(plan: &MergePlan) -> Result<(), String> {
        if plan.items.is_empty() {
            return Err("Merge plan has no tracks".to_string());
        }

        // Check that at least one video track exists
        if plan.video_tracks().is_empty() {
            return Err("Merge plan must include at least one video track".to_string());
        }

        // Validate all items have extracted paths
        for item in &plan.items {
            if item.effective_path().is_none() {
                return Err(format!(
                    "Track {}-{} has no extracted path",
                    item.track.track_type.prefix(),
                    item.track.id
                ));
            }
        }

        // Validate delay calculations
        if plan.delays.requires_global_shift() {
            // Ensure all effective delays are non-negative
            for item in &plan.items {
                let effective = plan.delays.effective_delay(&item.track.source);
                if effective < 0 {
                    return Err(format!(
                        "Negative effective delay for source {}: {}ms",
                        item.track.source, effective
                    ));
                }
            }
        }

        Ok(())
    }
}

impl Default for OptionsBuilder {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::models::jobs::Delays;
    use crate::core::models::media::{StreamProps, Track};
    use crate::core::models::enums::TrackType;
    use std::collections::HashMap;
    use std::path::PathBuf;

    #[test]
    fn test_format_delay() {
        assert_eq!(OptionsBuilder::format_delay(100), "100");
        assert_eq!(OptionsBuilder::format_delay(-50), "-50");
        assert_eq!(OptionsBuilder::format_delay(0), "0");
    }

    #[test]
    fn test_delay_calculation() {
        let mut raw_delays = HashMap::new();
        raw_delays.insert("REF".to_string(), 0.0);
        raw_delays.insert("SEC".to_string(), -200.0);

        let delays = Delays::new(raw_delays);

        // Global shift should be 200ms
        assert_eq!(delays.global_shift_ms, 200);

        // Effective delays
        assert_eq!(delays.effective_delay("REF"), 200);
        assert_eq!(delays.effective_delay("SEC"), 0);
    }

    #[test]
    fn test_track_order() {
        // Create mock plan
        let video_track = Track::new(
            "REF".to_string(),
            0,
            TrackType::Video,
            StreamProps::default(),
        );
        let audio_track = Track::new(
            "REF".to_string(),
            1,
            TrackType::Audio,
            StreamProps::default(),
        );
        let sub_track = Track::new(
            "REF".to_string(),
            2,
            TrackType::Subtitles,
            StreamProps::default(),
        );

        let items = vec![
            PlanItem::from_track(audio_track),
            PlanItem::from_track(video_track),
            PlanItem::from_track(sub_track),
        ];

        let delays = Delays::new(HashMap::new());
        let plan = MergePlan::new(
            items,
            delays,
            PathBuf::from("output.mkv"),
            PathBuf::from("/tmp"),
        );

        let order = OptionsBuilder::calculate_track_order(&plan);

        // Should be: video (idx 1), audio (idx 0), subtitles (idx 2)
        assert_eq!(order, vec![1, 0, 2]);
    }
}
