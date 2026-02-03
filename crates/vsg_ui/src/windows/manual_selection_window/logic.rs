//! Manual selection window helper functions

use std::collections::HashMap;
use std::path::PathBuf;

use vsg_core::extraction::{
    build_track_description, get_detailed_stream_info, probe_file, ExtractionResult, ProbeResult,
};
use vsg_core::jobs::ManualLayout;
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
