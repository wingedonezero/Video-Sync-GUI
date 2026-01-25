//! Merge plan builder.
//!
//! This module builds a `MergePlan` from a `ManualLayout` and analysis results.
//! It uses the `delay_calculator` to compute the correct delay for each track.

use std::collections::HashMap;
use std::path::PathBuf;

use crate::extraction::ContainerInfo;
use crate::jobs::{FinalTrackEntry, ManualLayout};
use crate::models::{Delays, MergePlan, PlanItem, StreamProps, Track};

use super::delay_calculator::{calculate_effective_delay, DelayContext, DelayInput};

/// Error type for plan building.
#[derive(Debug, Clone)]
pub enum PlanError {
    /// No manual layout provided.
    NoLayout,
    /// No analysis results (delays not calculated).
    NoAnalysis,
    /// Missing source file.
    MissingSource(String),
    /// Empty layout (no tracks selected).
    EmptyLayout,
    /// Invalid track configuration.
    InvalidTrack { source: String, track_id: usize, message: String },
}

impl std::fmt::Display for PlanError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PlanError::NoLayout => write!(f, "No manual layout provided"),
            PlanError::NoAnalysis => write!(f, "No analysis results available"),
            PlanError::MissingSource(s) => write!(f, "Missing source: {}", s),
            PlanError::EmptyLayout => write!(f, "Layout has no tracks selected"),
            PlanError::InvalidTrack { source, track_id, message } => {
                write!(f, "Invalid track {}:{}: {}", source, track_id, message)
            }
        }
    }
}

impl std::error::Error for PlanError {}

/// Input for building a merge plan.
pub struct PlanBuildInput<'a> {
    /// The user-configured layout.
    pub layout: &'a ManualLayout,
    /// Calculated sync delays.
    pub delays: &'a Delays,
    /// Container info for each source.
    pub container_info: &'a HashMap<String, ContainerInfo>,
    /// Source file paths.
    pub sources: &'a HashMap<String, PathBuf>,
    /// Extracted track paths (optional - for corrected audio, etc.)
    pub extracted_tracks: Option<&'a HashMap<String, PathBuf>>,
    /// Path to chapters XML file (optional).
    pub chapters_xml: Option<PathBuf>,
    /// Paths to attachment files.
    pub attachments: Vec<PathBuf>,
}

/// Build a merge plan from layout and analysis results.
///
/// This is the main entry point for building a merge plan. It:
/// 1. Validates the input
/// 2. Creates a PlanItem for each track in the layout
/// 3. Calculates the correct delay for each track using delay_calculator
/// 4. Adds chapters and attachments
///
/// # Arguments
///
/// * `input` - All inputs needed to build the plan
///
/// # Returns
///
/// A complete `MergePlan` ready for mkvmerge execution.
pub fn build_merge_plan(input: &PlanBuildInput) -> Result<MergePlan, PlanError> {
    let layout = input.layout;
    let delays = input.delays;
    let container_info = input.container_info;
    let sources = input.sources;

    // Validate
    if layout.final_tracks.is_empty() {
        return Err(PlanError::EmptyLayout);
    }

    // Create delay context
    let delay_ctx = DelayContext::new(delays, container_info);

    // Build plan items
    let mut items = Vec::with_capacity(layout.final_tracks.len());
    let mut build_log = Vec::new();

    for entry in &layout.final_tracks {
        let item = build_plan_item(entry, sources, input.extracted_tracks, &delay_ctx)?;
        build_log.push(format!(
            "  {} {} track {} -> delay {}ms",
            entry.source_key,
            format!("{:?}", entry.track_type),
            entry.track_id,
            item.container_delay_ms
        ));
        items.push(item);
    }

    // Log build summary
    tracing::debug!("Built merge plan with {} tracks:", items.len());
    for line in &build_log {
        tracing::debug!("{}", line);
    }

    // Create merge plan
    let mut plan = MergePlan::new(items, delays.clone());
    plan.chapters_xml = input.chapters_xml.clone();
    plan.attachments = input.attachments.clone();

    Ok(plan)
}

/// Build a single plan item from a track entry.
fn build_plan_item(
    entry: &FinalTrackEntry,
    sources: &HashMap<String, PathBuf>,
    extracted_tracks: Option<&HashMap<String, PathBuf>>,
    delay_ctx: &DelayContext,
) -> Result<PlanItem, PlanError> {
    // Get source path
    let source_path = sources
        .get(&entry.source_key)
        .ok_or_else(|| PlanError::MissingSource(entry.source_key.clone()))?;

    // Check for extracted path (for corrected audio, processed subtitles, etc.)
    let extracted_path = extracted_tracks.and_then(|tracks| {
        let key = format!("{}:{}", entry.source_key, entry.track_id);
        tracks.get(&key).cloned()
    });

    // Calculate delay
    let delay_input = DelayInput {
        source_key: &entry.source_key,
        track_id: entry.track_id,
        track_type: entry.track_type,
        // TODO: Add stepping_adjusted and sync_to from track config
        stepping_adjusted: false,
        sync_to: entry.config.sync_to_source.as_deref(),
    };
    let delay_ms = calculate_effective_delay(&delay_input, delay_ctx);

    // Create track (with placeholder props - actual props come from file scan)
    let track = Track::new(
        &entry.source_key,
        entry.track_id as u32,
        entry.track_type,
        StreamProps::new(""), // Placeholder - will be filled from scan
    );

    // Build plan item
    let mut item = PlanItem::new(track, source_path.clone());
    item.container_delay_ms = delay_ms;
    item.extracted_path = extracted_path;
    item.is_default = entry.config.is_default;
    item.is_forced_display = entry.config.is_forced;

    if let Some(ref name) = entry.config.custom_name {
        item.custom_name = name.clone();
    }
    if let Some(ref lang) = entry.config.custom_lang {
        item.custom_lang = lang.clone();
    }

    Ok(item)
}

/// Build a simple plan for remux-only jobs (no sync analysis).
///
/// This creates a plan that just copies tracks without delay calculations.
/// Used for jobs that only have Source 1 (no sync needed).
pub fn build_remux_plan(
    layout: &ManualLayout,
    sources: &HashMap<String, PathBuf>,
) -> Result<MergePlan, PlanError> {
    if layout.final_tracks.is_empty() {
        return Err(PlanError::EmptyLayout);
    }

    let mut items = Vec::with_capacity(layout.final_tracks.len());

    for entry in &layout.final_tracks {
        let source_path = sources
            .get(&entry.source_key)
            .ok_or_else(|| PlanError::MissingSource(entry.source_key.clone()))?;

        let track = Track::new(
            &entry.source_key,
            entry.track_id as u32,
            entry.track_type,
            StreamProps::new(""), // Placeholder - will be filled from scan
        );

        let mut item = PlanItem::new(track, source_path.clone());
        item.is_default = entry.config.is_default;
        item.is_forced_display = entry.config.is_forced;

        if let Some(ref name) = entry.config.custom_name {
            item.custom_name = name.clone();
        }
        if let Some(ref lang) = entry.config.custom_lang {
            item.custom_lang = lang.clone();
        }

        items.push(item);
    }

    // No delays for remux-only
    let delays = Delays::new();
    Ok(MergePlan::new(items, delays))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::jobs::TrackConfig;
    use crate::models::TrackType;

    fn create_test_layout() -> ManualLayout {
        let mut layout = ManualLayout::new();

        // Add Source 1 video
        layout.final_tracks.push(FinalTrackEntry {
            track_id: 0,
            source_key: "Source 1".to_string(),
            track_type: TrackType::Video,
            config: TrackConfig::default(),
        });

        // Add Source 1 audio
        layout.final_tracks.push(FinalTrackEntry {
            track_id: 1,
            source_key: "Source 1".to_string(),
            track_type: TrackType::Audio,
            config: TrackConfig {
                is_default: true,
                ..Default::default()
            },
        });

        // Add Source 2 audio
        layout.final_tracks.push(FinalTrackEntry {
            track_id: 1,
            source_key: "Source 2".to_string(),
            track_type: TrackType::Audio,
            config: TrackConfig::default(),
        });

        layout.attachment_sources.push("Source 1".to_string());
        layout
    }

    fn create_test_sources() -> HashMap<String, PathBuf> {
        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), PathBuf::from("/path/source1.mkv"));
        sources.insert("Source 2".to_string(), PathBuf::from("/path/source2.mkv"));
        sources
    }

    fn create_test_delays() -> Delays {
        let mut delays = Delays::new();
        delays.global_shift_ms = 100;
        delays.source_delays_ms.insert("Source 1".to_string(), 100);
        delays.source_delays_ms.insert("Source 2".to_string(), 250);
        delays
    }

    fn create_test_container_info() -> HashMap<String, ContainerInfo> {
        let mut info = HashMap::new();

        let mut source1 = ContainerInfo::new("Source 1", PathBuf::from("/path/source1.mkv"));
        source1.video_delay_ms = 100;
        source1.track_delays_ms.insert(0, 100);
        source1.track_delays_ms.insert(1, 150); // Audio 50ms behind video
        info.insert("Source 1".to_string(), source1);

        info
    }

    #[test]
    fn test_build_merge_plan() {
        let layout = create_test_layout();
        let sources = create_test_sources();
        let delays = create_test_delays();
        let container_info = create_test_container_info();

        let input = PlanBuildInput {
            layout: &layout,
            delays: &delays,
            container_info: &container_info,
            sources: &sources,
            extracted_tracks: None,
            chapters_xml: None,
            attachments: Vec::new(),
        };

        let plan = build_merge_plan(&input).unwrap();

        assert_eq!(plan.items.len(), 3);

        // Source 1 video: global_shift = 100
        assert_eq!(plan.items[0].container_delay_ms, 100);

        // Source 1 audio: relative_container (50) + global_shift (100) = 150
        assert_eq!(plan.items[1].container_delay_ms, 150);
        assert!(plan.items[1].is_default);

        // Source 2 audio: correlation delay = 250
        assert_eq!(plan.items[2].container_delay_ms, 250);
    }

    #[test]
    fn test_build_remux_plan() {
        let layout = create_test_layout();
        let sources = create_test_sources();

        let plan = build_remux_plan(&layout, &sources).unwrap();

        assert_eq!(plan.items.len(), 3);
        // All delays should be 0 for remux
        for item in &plan.items {
            assert_eq!(item.container_delay_ms, 0);
        }
    }

    #[test]
    fn test_empty_layout_error() {
        let layout = ManualLayout::new();
        let sources = create_test_sources();

        let result = build_remux_plan(&layout, &sources);
        assert!(matches!(result, Err(PlanError::EmptyLayout)));
    }

    #[test]
    fn test_missing_source_error() {
        let mut layout = ManualLayout::new();
        layout.final_tracks.push(FinalTrackEntry {
            track_id: 0,
            source_key: "Source 3".to_string(), // Doesn't exist
            track_type: TrackType::Video,
            config: TrackConfig::default(),
        });

        let sources = create_test_sources();
        let result = build_remux_plan(&layout, &sources);
        assert!(matches!(result, Err(PlanError::MissingSource(_))));
    }
}
