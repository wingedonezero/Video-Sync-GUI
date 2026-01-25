//! Manual selection and layout handlers.

use std::collections::HashMap;
use std::path::PathBuf;

use vsg_core::jobs::{FinalTrackEntry, ManualLayout};
use vsg_core::models::TrackType;

use crate::app::{App, FinalTrackState, SourceGroupState, TrackWidgetState};
use super::helpers::probe_tracks;

impl App {
    /// Populate source groups from sources.
    pub fn populate_source_groups(&mut self, sources: &HashMap<String, PathBuf>) {
        self.source_groups.clear();

        let mut source_keys: Vec<&String> = sources.keys().collect();
        source_keys.sort();

        for source_key in source_keys {
            let path = &sources[source_key];
            let is_reference = source_key == "Source 1";

            let tracks = probe_tracks(path);

            let file_name = path
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_else(|| path.to_string_lossy().to_string());

            let title = if is_reference {
                format!("{} (Reference) - '{}'", source_key, file_name)
            } else {
                format!("{} - '{}'", source_key, file_name)
            };

            self.source_groups.push(SourceGroupState {
                source_key: source_key.clone(),
                title,
                tracks: tracks
                    .into_iter()
                    .map(|t| {
                        let is_blocked = !is_reference && t.track_type == "video";
                        TrackWidgetState {
                            id: t.track_id,
                            track_type: t.track_type,
                            codec_id: t.codec_id,
                            language: t.language,
                            summary: t.summary,
                            badges: t.badges,
                            is_blocked,
                        }
                    })
                    .collect(),
                is_expanded: true,
            });
        }
    }

    /// Add a track to the final list.
    pub fn add_track_to_final_list(&mut self, track_id: usize, source_key: &str) {
        // Find the track
        let track = self.source_groups.iter().find_map(|g| {
            if g.source_key == source_key {
                g.tracks.iter().find(|t| t.id == track_id).cloned()
            } else {
                None
            }
        });

        if let Some(track) = track {
            if track.is_blocked {
                self.manual_selection_info =
                    "Video tracks can only be added from the reference source.".to_string();
                return;
            }

            // Each added track gets its own unique entry with its own settings
            self.final_tracks.push(FinalTrackState::new(
                track_id,
                source_key.to_string(),
                track.track_type,
                track.codec_id,
                track.summary,
                track.language,
            ));

            self.manual_selection_info.clear();
        }
    }

    /// Move a final track.
    pub fn move_final_track(&mut self, from: usize, to: usize) {
        if from < self.final_tracks.len() && to < self.final_tracks.len() {
            let track = self.final_tracks.remove(from);
            self.final_tracks.insert(to, track);
        }
    }

    /// Remove a final track.
    pub fn remove_final_track(&mut self, idx: usize) {
        if idx < self.final_tracks.len() {
            self.final_tracks.remove(idx);
        }
    }

    /// Accept the layout and save to job.
    /// Saves layout to both the job queue and to disk via LayoutManager.
    pub fn accept_layout(&mut self) {
        if let Some(job_idx) = self.manual_selection_job_idx {
            // Build ManualLayout from state - transfer ALL per-track settings
            let layout = ManualLayout {
                final_tracks: self
                    .final_tracks
                    .iter()
                    .map(|t| {
                        let track_type = match t.track_type.as_str() {
                            "video" => TrackType::Video,
                            "audio" => TrackType::Audio,
                            "subtitles" => TrackType::Subtitles,
                            _ => TrackType::Audio,
                        };

                        let mut entry = FinalTrackEntry::new(t.track_id, t.source_key.clone(), track_type);

                        // Basic flags
                        entry.config.is_default = t.is_default;
                        entry.config.is_forced = t.is_forced;
                        entry.config.sync_to_source = Some(t.sync_to_source.clone());

                        // Custom naming
                        entry.config.custom_lang = t.custom_lang.clone();
                        entry.config.custom_name = t.custom_name.clone();

                        // Subtitle processing options
                        entry.config.perform_ocr = t.perform_ocr;
                        entry.config.convert_to_ass = t.convert_to_ass;
                        entry.config.rescale = t.rescale;
                        entry.config.size_multiplier = t.size_multiplier_pct as f32 / 100.0;
                        entry.config.sync_exclusion_styles = t.sync_exclusion_styles.clone();

                        entry
                    })
                    .collect(),
                attachment_sources: self
                    .attachment_sources
                    .iter()
                    .filter(|(_, &checked)| checked)
                    .map(|(k, _)| k.clone())
                    .collect(),
                source_settings: HashMap::new(),
            };

            // Get job ID for layout persistence
            let job_id = {
                let q = self.job_queue.lock().unwrap();
                q.get(job_idx).map(|j| j.id.clone())
            };

            // Save layout to disk via LayoutManager (for persistence across restarts)
            if let Some(job_id) = &job_id {
                let lm = self.layout_manager.lock().unwrap();
                if let Err(e) = lm.save_layout(job_id, &layout) {
                    tracing::warn!("Failed to save layout to disk: {}", e);
                } else {
                    tracing::debug!("Layout saved to disk for job '{}'", job_id);
                }
            }

            // Save to job queue (and queue.json)
            let mut q = self.job_queue.lock().unwrap();
            q.set_layout(job_idx, layout);
            if let Err(e) = q.save() {
                tracing::warn!("Failed to save queue: {}", e);
            }

            self.job_queue_status = "Job configured".to_string();
        }
    }

    /// Accept track settings - saves all settings back to the specific track entry.
    pub fn accept_track_settings(&mut self) {
        if let Some(track_idx) = self.track_settings_idx {
            if let Some(track) = self.final_tracks.get_mut(track_idx) {
                // Save all settings back to this specific track
                track.custom_lang = self.track_settings.custom_lang.clone();
                track.custom_name = self.track_settings.custom_name.clone();
                track.perform_ocr = self.track_settings.perform_ocr;
                track.convert_to_ass = self.track_settings.convert_to_ass;
                track.rescale = self.track_settings.rescale;
                track.size_multiplier_pct = self.track_settings.size_multiplier_pct;
                track.sync_exclusion_styles = self.track_settings.sync_exclusion_styles.clone();
                track.sync_exclusion_mode = self.track_settings.sync_exclusion_mode;
            }
        }
    }
}
