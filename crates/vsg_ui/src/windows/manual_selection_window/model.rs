//! Manual selection window state model

use std::collections::HashMap;
use std::path::PathBuf;

use vsg_core::extraction::types::{ProbeResult, TrackInfo, TrackType};

use super::messages::FinalTrackData;

/// Source info with track data
#[derive(Debug, Clone)]
pub struct SourceInfo {
    /// Source key (e.g., "Source 1")
    pub key: String,
    /// Path to source file
    pub path: PathBuf,
    /// Probe result with tracks
    pub probe: ProbeResult,
}

/// Track display entry in source list
#[derive(Debug, Clone)]
pub struct SourceTrackEntry {
    /// Track info from probe
    pub info: TrackInfo,
    /// Source key this track belongs to
    pub source_key: String,
    /// Path to source file
    pub source_path: PathBuf,
    /// Whether this track is blocked (e.g., video from non-Source 1)
    pub is_blocked: bool,
    /// Tooltip explaining why blocked
    pub blocked_reason: Option<String>,
}

impl SourceTrackEntry {
    /// Get display string for list
    pub fn display(&self) -> String {
        self.info.summary()
    }

    /// Get tooltip text
    pub fn tooltip(&self) -> String {
        if let Some(reason) = &self.blocked_reason {
            return reason.clone();
        }

        let mut parts = vec![format!("Track ID: {}", self.info.id)];

        if let Some(name) = &self.info.name {
            parts.push(format!("Name: {}", name));
        }

        parts.push(format!("Codec: {} ({})", self.info.codec_name, self.info.codec_id));

        if let Some(lang) = &self.info.language {
            parts.push(format!("Language: {}", lang));
        }

        parts.join("\n")
    }
}

/// Track display entry in final output list
#[derive(Debug, Clone)]
pub struct FinalTrackEntry {
    /// Track info from probe
    pub info: TrackInfo,
    /// Configuration data
    pub data: FinalTrackData,
    /// Display badges (Default, Forced, Sync, etc.)
    pub badges: Vec<String>,
}

impl FinalTrackEntry {
    /// Create from track info and data
    pub fn new(info: TrackInfo, data: FinalTrackData) -> Self {
        let mut entry = Self {
            info,
            data,
            badges: Vec::new(),
        };
        entry.refresh_badges();
        entry
    }

    /// Refresh badges based on current config
    pub fn refresh_badges(&mut self) {
        self.badges.clear();

        if self.data.is_default {
            self.badges.push("Default".to_string());
        }
        if self.data.is_forced {
            self.badges.push("Forced".to_string());
        }
        if self.data.sync_to_source.is_some() {
            self.badges.push("Sync".to_string());
        }
        if self.data.perform_ocr {
            self.badges.push("OCR".to_string());
        }
        if self.data.convert_to_ass {
            self.badges.push("→ASS".to_string());
        }
        if self.data.rescale {
            self.badges.push("Rescale".to_string());
        }
        if self.data.is_generated {
            self.badges.push("Generated".to_string());
        }
    }

    /// Get display string
    pub fn display(&self) -> String {
        let base = self.info.summary();
        if self.badges.is_empty() {
            base
        } else {
            format!("{} [{}]", base, self.badges.join(", "))
        }
    }

    /// Get tooltip
    pub fn tooltip(&self) -> String {
        let mut parts = vec![
            format!("Source: {}", self.data.source_key),
            format!("Track ID: {}", self.data.track_id),
        ];

        if let Some(name) = &self.data.custom_name {
            parts.push(format!("Custom Name: {}", name));
        } else if let Some(name) = &self.info.name {
            parts.push(format!("Name: {}", name));
        }

        if let Some(lang) = &self.data.custom_lang {
            parts.push(format!("Custom Language: {}", lang));
        } else if let Some(lang) = &self.info.language {
            parts.push(format!("Language: {}", lang));
        }

        if let Some(sync) = &self.data.sync_to_source {
            parts.push(format!("Sync to: {}", sync));
        }

        parts.join("\n")
    }
}

/// Manual selection window state
#[derive(Debug)]
pub struct ManualSelectionModel {
    /// Source files with their track info
    pub sources: Vec<SourceInfo>,
    /// Map of source key to source index
    pub source_map: HashMap<String, usize>,
    /// Tracks grouped by source for display
    pub source_tracks: HashMap<String, Vec<SourceTrackEntry>>,
    /// External subtitle tracks
    pub external_tracks: Vec<SourceTrackEntry>,
    /// Final output track list
    pub final_tracks: Vec<FinalTrackEntry>,
    /// Selected attachment sources
    pub attachment_sources: Vec<String>,
    /// Currently selected source track
    pub selected_source_track: Option<(String, usize)>,
    /// Currently selected final track index
    pub selected_final_track: Option<usize>,
    /// Available source keys (sorted)
    pub available_sources: Vec<String>,
}

impl ManualSelectionModel {
    /// Create a new model from source probes
    pub fn new(sources: Vec<(String, PathBuf, ProbeResult)>) -> Self {
        let mut model = Self {
            sources: Vec::new(),
            source_map: HashMap::new(),
            source_tracks: HashMap::new(),
            external_tracks: Vec::new(),
            final_tracks: Vec::new(),
            attachment_sources: Vec::new(),
            selected_source_track: None,
            selected_final_track: None,
            available_sources: Vec::new(),
        };

        // Process sources
        for (i, (key, path, probe)) in sources.into_iter().enumerate() {
            model.source_map.insert(key.clone(), i);
            model.available_sources.push(key.clone());

            // Create track entries
            let mut tracks = Vec::new();
            for track in &probe.tracks {
                let is_blocked = Self::is_track_blocked(&key, track);
                let blocked_reason = if is_blocked {
                    Some("Video from secondary sources is disabled.\nOnly Source 1 video is allowed.".to_string())
                } else {
                    None
                };

                tracks.push(SourceTrackEntry {
                    info: track.clone(),
                    source_key: key.clone(),
                    source_path: path.clone(),
                    is_blocked,
                    blocked_reason,
                });
            }

            model.source_tracks.insert(key.clone(), tracks);
            model.sources.push(SourceInfo {
                key,
                path,
                probe,
            });
        }

        // Sort sources naturally (Source 1, Source 2, ...)
        model.available_sources.sort_by(|a, b| {
            let num_a = a.chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse::<u32>().unwrap_or(0);
            let num_b = b.chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse::<u32>().unwrap_or(0);
            num_a.cmp(&num_b)
        });

        model
    }

    /// Check if a track should be blocked
    fn is_track_blocked(source_key: &str, track: &TrackInfo) -> bool {
        // Video tracks only allowed from Source 1
        track.track_type == TrackType::Video && source_key != "Source 1"
    }

    /// Add a track to the final output list
    pub fn add_to_final(&mut self, source_key: &str, track_index: usize) -> bool {
        let tracks = match self.source_tracks.get(source_key) {
            Some(t) => t,
            None => return false,
        };

        let entry = match tracks.get(track_index) {
            Some(e) if !e.is_blocked => e,
            _ => return false,
        };

        // Count existing tracks of same source and type for position
        let position = self.final_tracks.iter()
            .filter(|t| t.data.source_key == source_key && t.data.track_type == entry.info.track_type)
            .count();

        let data = FinalTrackData {
            track_id: entry.info.id,
            source_key: source_key.to_string(),
            track_type: entry.info.track_type,
            is_default: entry.info.is_default,
            is_forced: entry.info.is_forced,
            custom_name: None,
            custom_lang: None,
            apply_track_name: false,
            sync_to_source: if source_key != "Source 1" { Some("Source 1".to_string()) } else { None },
            perform_ocr: false,
            convert_to_ass: false,
            rescale: false,
            user_order_index: self.final_tracks.len(),
            position_in_source_type: position,
            source_path: entry.source_path.clone(),
            is_generated: false,
            generated_source_track_id: None,
        };

        let final_entry = FinalTrackEntry::new(entry.info.clone(), data);
        self.final_tracks.push(final_entry);

        // Normalize default flags
        self.normalize_defaults();

        true
    }

    /// Remove a track from the final output list
    pub fn remove_from_final(&mut self, index: usize) {
        if index < self.final_tracks.len() {
            self.final_tracks.remove(index);
            self.update_user_order_indices();
            self.normalize_defaults();
        }
    }

    /// Move a track up in the final list
    pub fn move_up(&mut self, index: usize) {
        if index > 0 && index < self.final_tracks.len() {
            self.final_tracks.swap(index, index - 1);
            self.update_user_order_indices();
        }
    }

    /// Move a track down in the final list
    pub fn move_down(&mut self, index: usize) {
        if index + 1 < self.final_tracks.len() {
            self.final_tracks.swap(index, index + 1);
            self.update_user_order_indices();
        }
    }

    /// Update user order indices after reordering
    fn update_user_order_indices(&mut self) {
        for (i, track) in self.final_tracks.iter_mut().enumerate() {
            track.data.user_order_index = i;
        }
    }

    /// Normalize default flags (only one per type)
    fn normalize_defaults(&mut self) {
        for track_type in [TrackType::Video, TrackType::Audio, TrackType::Subtitles] {
            let mut found_default = false;
            let mut first_of_type = None;

            for (i, track) in self.final_tracks.iter_mut().enumerate() {
                if track.data.track_type == track_type {
                    if first_of_type.is_none() {
                        first_of_type = Some(i);
                    }
                    if track.data.is_default {
                        if found_default {
                            track.data.is_default = false;
                        } else {
                            found_default = true;
                        }
                    }
                    track.refresh_badges();
                }
            }

            // If no default found for audio, make first one default
            if !found_default && track_type == TrackType::Audio {
                if let Some(i) = first_of_type {
                    self.final_tracks[i].data.is_default = true;
                    self.final_tracks[i].refresh_badges();
                }
            }
        }
    }

    /// Toggle default flag for a track
    pub fn toggle_default(&mut self, index: usize) {
        if let Some(track) = self.final_tracks.get_mut(index) {
            let track_type = track.data.track_type;
            let new_state = !track.data.is_default;

            // Clear other defaults of same type
            for t in &mut self.final_tracks {
                if t.data.track_type == track_type {
                    t.data.is_default = false;
                    t.refresh_badges();
                }
            }

            // Set this one
            if let Some(track) = self.final_tracks.get_mut(index) {
                track.data.is_default = new_state;
                track.refresh_badges();
            }

            self.normalize_defaults();
        }
    }

    /// Toggle forced flag for a track
    pub fn toggle_forced(&mut self, index: usize) {
        if let Some(track) = self.final_tracks.get_mut(index) {
            if track.data.track_type == TrackType::Subtitles {
                let new_state = !track.data.is_forced;

                // Clear other forced flags
                if new_state {
                    for t in &mut self.final_tracks {
                        if t.data.track_type == TrackType::Subtitles {
                            t.data.is_forced = false;
                            t.refresh_badges();
                        }
                    }
                }

                if let Some(track) = self.final_tracks.get_mut(index) {
                    track.data.is_forced = new_state;
                    track.refresh_badges();
                }
            }
        }
    }

    /// Toggle attachment source
    pub fn toggle_attachment_source(&mut self, source_key: &str) {
        if let Some(pos) = self.attachment_sources.iter().position(|s| s == source_key) {
            self.attachment_sources.remove(pos);
        } else {
            self.attachment_sources.push(source_key.to_string());
        }
    }

    /// Get the final layout data
    pub fn get_layout(&self) -> Vec<FinalTrackData> {
        self.final_tracks.iter().map(|t| t.data.clone()).collect()
    }

    /// Get source info by key
    pub fn get_source(&self, key: &str) -> Option<&SourceInfo> {
        self.source_map.get(key).and_then(|&i| self.sources.get(i))
    }
}

impl Default for ManualSelectionModel {
    fn default() -> Self {
        Self {
            sources: Vec::new(),
            source_map: HashMap::new(),
            source_tracks: HashMap::new(),
            external_tracks: Vec::new(),
            final_tracks: Vec::new(),
            attachment_sources: Vec::new(),
            selected_source_track: None,
            selected_final_track: None,
            available_sources: Vec::new(),
        }
    }
}
