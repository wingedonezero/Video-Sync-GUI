//! Merge plan builder for constructing MergePlan from job inputs.
//!
//! This module handles the business logic of building a MergePlan from:
//! - Manual layout (track selection and order)
//! - Source file paths
//! - Extracted track paths
//! - Analysis delays
//! - Chapters and attachments

use std::collections::HashMap;
use std::path::PathBuf;

use serde_json::Value;

use crate::models::{Delays, MergePlan, PlanItem, StreamProps, Track, TrackType};

/// Error types for merge plan building.
#[derive(Debug, thiserror::Error)]
pub enum MuxError {
    /// Source file not found in sources map.
    #[error("Source not found: {0}")]
    SourceNotFound(String),

    /// External track missing required original_path.
    #[error("External track {0} missing original_path")]
    ExternalTrackMissingPath(u32),
}

/// Input data for building a merge plan.
///
/// Contains all the raw data needed to construct a MergePlan,
/// without any orchestrator-specific types.
pub struct MergePlanInput<'a> {
    /// Manual layout from job spec (track selection and order).
    pub layout: Option<&'a Vec<HashMap<String, Value>>>,
    /// Source file paths.
    pub sources: &'a HashMap<String, PathBuf>,
    /// Extracted track paths (source_trackid -> path).
    pub extracted_tracks: &'a HashMap<String, PathBuf>,
    /// Extracted attachment paths.
    pub extracted_attachments: &'a HashMap<String, PathBuf>,
    /// Delays from analysis (for audio tracks).
    pub delays: Delays,
    /// Subtitle-specific delays (from video-verified mode).
    /// Key is source name (e.g., "Source 2"), value is delay in ms.
    /// If None or source not found, falls back to audio delay.
    pub subtitle_delays: Option<&'a HashMap<String, f64>>,
    /// Chapters XML path (if any).
    pub chapters_xml: Option<PathBuf>,
}

/// Build a MergePlan from job inputs.
///
/// Processes the manual layout to create PlanItem entries with proper
/// track configuration, delays, and extracted paths.
pub fn build_merge_plan(input: MergePlanInput) -> Result<MergePlan, MuxError> {
    let mut items = Vec::new();

    if let Some(layout) = input.layout {
        for (idx, item) in layout.iter().enumerate() {
            let plan_item = build_plan_item(item, idx, &input)?;
            items.push(plan_item);
        }
    } else {
        // No manual layout - create minimal plan with just Source 1 video
        if let Some(source1_path) = input.sources.get("Source 1") {
            let video_track = Track::new(
                "Source 1",
                0,
                TrackType::Video,
                StreamProps::new("V_MPEG4/ISO/AVC"),
            );
            items.push(PlanItem::new(video_track, source1_path.clone()).with_default(true));
        }
    }

    let mut plan = MergePlan::new(items, input.delays);

    // Add chapters
    plan.chapters_xml = input.chapters_xml;

    // Add attachments
    for (_key, path) in input.extracted_attachments {
        plan.attachments.push(path.clone());
    }

    Ok(plan)
}

/// Build a single PlanItem from a layout entry.
fn build_plan_item(
    item: &HashMap<String, Value>,
    idx: usize,
    input: &MergePlanInput,
) -> Result<PlanItem, MuxError> {
    // Extract fields from layout item
    let source_key = item
        .get("source")
        .and_then(|v| v.as_str())
        .unwrap_or("Source 1");

    let track_id = item
        .get("id")
        .and_then(|v| v.as_u64())
        .map(|v| v as u32)
        .unwrap_or(0);

    let track_type = parse_track_type(item.get("type").and_then(|v| v.as_str()).unwrap_or("video"));

    let codec = item
        .get("codec")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown");

    let lang = item
        .get("language")
        .and_then(|v| v.as_str())
        .unwrap_or("und");

    let name = item.get("name").and_then(|v| v.as_str()).unwrap_or("");

    // Track config options
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
            .ok_or_else(|| MuxError::ExternalTrackMissingPath(track_id))?
    } else {
        input
            .sources
            .get(source_key)
            .cloned()
            .ok_or_else(|| MuxError::SourceNotFound(source_key.to_string()))?
    };

    // Create track with properties
    let props = StreamProps::new(codec)
        .with_lang(if custom_lang.is_empty() {
            lang
        } else {
            custom_lang
        })
        .with_name(if custom_name.is_empty() {
            name
        } else {
            custom_name
        });

    let track = Track::new(source_key, track_id, track_type, props);

    // Create plan item
    let mut plan_item = PlanItem::new(track, source_path);
    plan_item.is_default = is_default;
    plan_item.is_forced_display = is_forced;

    // Check for extracted path (key format: "Source 2:subtitles:5")
    let type_str = match track_type {
        TrackType::Video => "video",
        TrackType::Audio => "audio",
        TrackType::Subtitles => "subtitles",
    };
    let extract_key = format!("{}:{}:{}", source_key, type_str, track_id);
    if let Some(extracted_path) = input.extracted_tracks.get(&extract_key) {
        plan_item.extracted_path = Some(extracted_path.clone());
    }

    // Apply delay - use subtitle-specific delays for subtitle tracks if available
    let delay_ms = if track_type == TrackType::Subtitles {
        // For subtitles, prefer video-verified delay if available
        input
            .subtitle_delays
            .and_then(|sd| sd.get(source_key).copied())
            .or_else(|| input.delays.raw_source_delays_ms.get(source_key).copied())
            .unwrap_or(0.0)
    } else {
        // For audio/video, use standard delays
        input
            .delays
            .raw_source_delays_ms
            .get(source_key)
            .copied()
            .unwrap_or(0.0)
    };
    plan_item.container_delay_ms_raw = delay_ms;

    Ok(plan_item)
}

/// Parse track type from string.
fn parse_track_type(s: &str) -> TrackType {
    match s {
        "video" => TrackType::Video,
        "audio" => TrackType::Audio,
        "subtitles" => TrackType::Subtitles,
        _ => TrackType::Video,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_minimal_plan_without_layout() {
        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), PathBuf::from("/test/source1.mkv"));

        let input = MergePlanInput {
            layout: None,
            sources: &sources,
            extracted_tracks: &HashMap::new(),
            extracted_attachments: &HashMap::new(),
            delays: Delays::default(),
            subtitle_delays: None,
            chapters_xml: None,
        };

        let plan = build_merge_plan(input).unwrap();
        assert_eq!(plan.items.len(), 1);
        assert_eq!(plan.items[0].track.source, "Source 1");
    }

    #[test]
    fn builds_plan_from_layout() {
        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), PathBuf::from("/test/source1.mkv"));

        let mut layout_item = HashMap::new();
        layout_item.insert("source".to_string(), Value::String("Source 1".to_string()));
        layout_item.insert("id".to_string(), Value::Number(0.into()));
        layout_item.insert("type".to_string(), Value::String("video".to_string()));
        layout_item.insert("codec".to_string(), Value::String("V_MPEG4".to_string()));

        let layout = vec![layout_item];

        let input = MergePlanInput {
            layout: Some(&layout),
            sources: &sources,
            extracted_tracks: &HashMap::new(),
            extracted_attachments: &HashMap::new(),
            delays: Delays::default(),
            subtitle_delays: None,
            chapters_xml: None,
        };

        let plan = build_merge_plan(input).unwrap();
        assert_eq!(plan.items.len(), 1);
    }

    #[test]
    fn applies_delays_to_tracks() {
        let mut sources = HashMap::new();
        sources.insert("Source 2".to_string(), PathBuf::from("/test/source2.mkv"));

        let mut layout_item = HashMap::new();
        layout_item.insert("source".to_string(), Value::String("Source 2".to_string()));
        layout_item.insert("id".to_string(), Value::Number(1.into()));
        layout_item.insert("type".to_string(), Value::String("audio".to_string()));

        let layout = vec![layout_item];

        let mut delays = Delays::default();
        delays
            .raw_source_delays_ms
            .insert("Source 2".to_string(), 150.5);

        let input = MergePlanInput {
            layout: Some(&layout),
            sources: &sources,
            extracted_tracks: &HashMap::new(),
            extracted_attachments: &HashMap::new(),
            delays,
            subtitle_delays: None,
            chapters_xml: None,
        };

        let plan = build_merge_plan(input).unwrap();
        assert!((plan.items[0].container_delay_ms_raw - 150.5).abs() < 0.001);
    }

    #[test]
    fn error_on_missing_source() {
        let sources = HashMap::new(); // Empty - no sources

        let mut layout_item = HashMap::new();
        layout_item.insert("source".to_string(), Value::String("Source 1".to_string()));
        layout_item.insert("id".to_string(), Value::Number(0.into()));

        let layout = vec![layout_item];

        let input = MergePlanInput {
            layout: Some(&layout),
            sources: &sources,
            extracted_tracks: &HashMap::new(),
            extracted_attachments: &HashMap::new(),
            delays: Delays::default(),
            subtitle_delays: None,
            chapters_xml: None,
        };

        let result = build_merge_plan(input);
        assert!(result.is_err());
    }
}
