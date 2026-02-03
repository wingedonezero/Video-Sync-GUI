//! Manual selection window helper functions

use std::collections::HashMap;
use std::path::PathBuf;

use vsg_core::extraction::{
    build_track_description, get_detailed_stream_info, probe_file, ExtractionResult, ProbeResult,
};
use vsg_core::jobs::{FinalTrackEntry as CoreFinalTrackEntry, ManualLayout, TrackConfig};
use vsg_core::models::TrackType as CoreTrackType;

use super::model::ManualSelectionModel;

/// Probe all source files and create model
pub fn probe_sources(
    sources: &HashMap<String, PathBuf>,
) -> ExtractionResult<Vec<(String, PathBuf, ProbeResult)>> {
    let mut results = Vec::new();

    for (key, path) in sources {
        if !path.exists() {
            continue;
        }

        let probe = probe_file(path)?;

        // Try to get detailed info from ffprobe (optional)
        let detailed = get_detailed_stream_info(path).ok();

        // Enhance track descriptions if we have ffprobe info
        let mut enhanced_probe = probe;
        if let Some(ref detail_map) = detailed {
            for track in &mut enhanced_probe.tracks {
                // Map mkvmerge track ID to ffprobe stream index
                // They're usually the same but can differ
                if let Some(detail) = detail_map.get(&track.id) {
                    let desc = build_track_description(track, Some(detail));
                    // Store enhanced description in codec_name for now
                    // A proper solution would add a description field to TrackInfo
                    track.codec_name = desc;
                }
            }
        }

        results.push((key.clone(), path.clone(), enhanced_probe));
    }

    // Sort by source key
    results.sort_by(|a, b| {
        let num_a =
            a.0.chars()
                .filter(|c| c.is_ascii_digit())
                .collect::<String>()
                .parse::<u32>()
                .unwrap_or(0);
        let num_b =
            b.0.chars()
                .filter(|c| c.is_ascii_digit())
                .collect::<String>()
                .parse::<u32>()
                .unwrap_or(0);
        num_a.cmp(&num_b)
    });

    Ok(results)
}

/// Convert UI FinalTrackData to core ManualLayout
pub fn convert_to_manual_layout(model: &ManualSelectionModel) -> ManualLayout {
    let mut final_tracks = Vec::new();

    for (i, entry) in model.final_tracks.iter().enumerate() {
        let core_track_type = match entry.data.track_type {
            vsg_core::extraction::types::TrackType::Video => CoreTrackType::Video,
            vsg_core::extraction::types::TrackType::Audio => CoreTrackType::Audio,
            vsg_core::extraction::types::TrackType::Subtitles => CoreTrackType::Subtitles,
        };

        let config = TrackConfig {
            sync_to_source: entry.data.sync_to_source.clone(),
            is_default: entry.data.is_default,
            is_forced_display: entry.data.is_forced,
            custom_name: entry.data.custom_name.clone(),
            custom_lang: entry.data.custom_lang.clone(),
            apply_track_name: entry.data.apply_track_name,
            perform_ocr: entry.data.perform_ocr,
            convert_to_ass: entry.data.convert_to_ass,
            rescale: entry.data.rescale,
            ..Default::default()
        };

        let core_entry = CoreFinalTrackEntry {
            track_id: entry.data.track_id,
            source_key: entry.data.source_key.clone(),
            track_type: core_track_type,
            config,
            user_order_index: i,
            position_in_source_type: entry.data.position_in_source_type,
            is_generated: entry.data.is_generated,
            generated_source_track_id: entry.data.generated_source_track_id,
            generated_source_path: None,
            generated_filter_mode: "exclude".to_string(),
            generated_filter_styles: Vec::new(),
            generated_original_style_list: Vec::new(),
            generated_verify_only_lines_removed: true,
        };

        final_tracks.push(core_entry);
    }

    ManualLayout {
        final_tracks,
        attachment_sources: model.attachment_sources.clone(),
        source_settings: HashMap::new(),
    }
}

/// Pre-populate model from a previous layout
pub fn prepopulate_from_layout(model: &mut ManualSelectionModel, layout: &ManualLayout) {
    // Clear existing final tracks
    model.final_tracks.clear();

    // Track counters per (source, type) for position matching
    let mut counters: HashMap<(String, String), usize> = HashMap::new();

    for entry in &layout.final_tracks {
        let source_key = &entry.source_key;
        let type_str = match entry.track_type {
            CoreTrackType::Video => "video",
            CoreTrackType::Audio => "audio",
            CoreTrackType::Subtitles => "subtitles",
        };

        // Skip generated tracks for now (they need special handling)
        if entry.is_generated {
            continue;
        }

        // Get the position counter
        let key = (source_key.clone(), type_str.to_string());
        let position = *counters.get(&key).unwrap_or(&0);
        counters.insert(key, position + 1);

        // Find matching track in source tracks
        if let Some(source_tracks) = model.source_tracks.get(source_key) {
            // Find track at this position of this type
            let mut type_count = 0;
            for source_track in source_tracks {
                if source_track.info.track_type.to_string() == type_str {
                    if type_count == position {
                        // Found the matching track - add it
                        let track_index = source_tracks
                            .iter()
                            .position(|t| t.info.id == source_track.info.id)
                            .unwrap_or(0);

                        // Add with config from layout
                        if model.add_to_final(source_key, track_index) {
                            // Apply saved configuration
                            if let Some(final_track) = model.final_tracks.last_mut() {
                                final_track.data.is_default = entry.config.is_default;
                                final_track.data.is_forced = entry.config.is_forced_display;
                                final_track.data.custom_name = entry.config.custom_name.clone();
                                final_track.data.custom_lang = entry.config.custom_lang.clone();
                                final_track.data.apply_track_name = entry.config.apply_track_name;
                                final_track.data.sync_to_source =
                                    entry.config.sync_to_source.clone();
                                final_track.data.perform_ocr = entry.config.perform_ocr;
                                final_track.data.convert_to_ass = entry.config.convert_to_ass;
                                final_track.data.rescale = entry.config.rescale;
                                final_track.refresh_badges();
                            }
                        }
                        break;
                    }
                    type_count += 1;
                }
            }
        }
    }

    // Restore attachment sources
    model.attachment_sources = layout.attachment_sources.clone();
}

/// Get track type icon/prefix for display
pub fn track_type_icon(track_type: vsg_core::extraction::types::TrackType) -> &'static str {
    match track_type {
        vsg_core::extraction::types::TrackType::Video => "🎬",
        vsg_core::extraction::types::TrackType::Audio => "🔊",
        vsg_core::extraction::types::TrackType::Subtitles => "💬",
    }
}

/// Check if a subtitle track is text-based (vs image-based like PGS/VobSub)
pub fn is_text_subtitle(codec_id: &str) -> bool {
    let codec_upper = codec_id.to_uppercase();
    codec_upper.starts_with("S_TEXT/") || codec_upper == "S_SSA" || codec_upper == "S_ASS"
}

/// Check if a subtitle track is image-based (needs OCR)
pub fn is_image_subtitle(codec_id: &str) -> bool {
    let codec_upper = codec_id.to_uppercase();
    codec_upper.contains("PGS")
        || codec_upper.contains("HDMV")
        || codec_upper.contains("VOBSUB")
        || codec_upper.contains("DVD")
}
