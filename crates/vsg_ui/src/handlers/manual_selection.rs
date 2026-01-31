//! Manual selection and layout handlers.

use std::collections::HashMap;
use std::path::PathBuf;

use vsg_core::jobs::{FinalTrackEntry, ManualLayout, generate_layout_id};
use vsg_core::models::{SourceIndex, SourceRef, TrackType};

use crate::app::{App, FinalTrackState, SourceGroupState, SyncExclusionMode, TrackWidgetState};
use super::helpers::probe_tracks;

impl App {
    /// Populate source groups from sources.
    pub fn populate_source_groups(&mut self, sources: &HashMap<SourceIndex, PathBuf>) {
        self.source_groups.clear();

        let mut source_entries: Vec<_> = sources.iter().collect();
        source_entries.sort_by_key(|(idx, _)| *idx);

        for (source_idx, path) in source_entries {
            let source_key = source_idx.display_name();
            let is_reference = *source_idx == SourceIndex::source1();

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
        use crate::app::SyncExclusionMode;

        if let Some(job_idx) = self.manual_selection_job_idx {
            // Track position counters for position_in_source_type
            let mut source_type_counters: HashMap<String, usize> = HashMap::new();

            // Build ManualLayout from state - transfer ALL per-track settings
            let layout = ManualLayout {
                final_tracks: self
                    .final_tracks
                    .iter()
                    .enumerate()
                    .map(|(user_idx, t)| {
                        let track_type = match t.track_type.as_str() {
                            "video" => TrackType::Video,
                            "audio" => TrackType::Audio,
                            "subtitles" => TrackType::Subtitles,
                            _ => TrackType::Audio,
                        };

                        // Calculate position_in_source_type
                        let source_type_key = format!("{}_{}", t.source_key, t.track_type);
                        let position = source_type_counters.get(&source_type_key).copied().unwrap_or(0);
                        source_type_counters.insert(source_type_key, position + 1);

                        // Convert source_key string to SourceRef
                        let source_ref = SourceRef::from_display_name(&t.source_key)
                            .unwrap_or(SourceRef::Index(SourceIndex::source1()));
                        let mut entry = FinalTrackEntry::new(t.track_id, source_ref, track_type);

                        // Enhanced metadata
                        entry.user_order_index = user_idx;
                        entry.position_in_source_type = position;

                        // Basic flags
                        entry.config.is_default = t.is_default;
                        entry.config.is_forced_display = t.is_forced_display;
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
                        entry.config.sync_exclusion_mode = match t.sync_exclusion_mode {
                            SyncExclusionMode::Exclude => "exclude".to_string(),
                            SyncExclusionMode::Include => "include".to_string(),
                        };

                        entry
                    })
                    .collect(),
                attachment_sources: self
                    .attachment_sources
                    .iter()
                    .filter(|(_, &checked)| checked)
                    .filter_map(|(k, _)| SourceIndex::from_display_name(k))
                    .collect(),
                source_settings: HashMap::new(),
            };

            // Get sources for layout persistence
            let sources = {
                let q = self.job_queue.lock().unwrap();
                q.get(job_idx).map(|j| j.sources.clone())
            };

            // Save layout to disk via LayoutManager (for persistence across restarts)
            // Use deterministic layout ID based on source filenames (matches Python)
            if let Some(sources) = &sources {
                let layout_id = generate_layout_id(sources);
                let lm = self.layout_manager.lock().unwrap();
                if let Err(e) = lm.save_layout_with_metadata(&layout_id, sources, &layout) {
                    tracing::warn!("Failed to save layout to disk: {}", e);
                } else {
                    tracing::debug!("Layout saved to disk for layout_id '{}'", layout_id);
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

    /// Load an existing layout from disk and populate final_tracks.
    /// Returns true if a layout was loaded.
    pub fn load_existing_layout(&mut self, sources: &HashMap<SourceIndex, PathBuf>) -> bool {
        let layout_id = generate_layout_id(sources);

        // Try to load the layout from disk
        let layout = {
            let lm = self.layout_manager.lock().unwrap();
            match lm.load_layout(&layout_id) {
                Ok(Some(layout)) => layout,
                Ok(None) => {
                    tracing::debug!("No existing layout found for layout_id '{}'", layout_id);
                    return false;
                }
                Err(e) => {
                    tracing::warn!("Failed to load layout for '{}': {}", layout_id, e);
                    return false;
                }
            }
        };

        tracing::debug!(
            "Loading existing layout with {} tracks",
            layout.final_tracks.len()
        );

        // Convert FinalTrackEntry to FinalTrackState
        // We need to match tracks from the layout to tracks in source_groups
        for entry in layout.final_tracks {
            let entry_source_name = entry.source_ref.display_name();
            // Find the matching track in source_groups
            let track_info = self.source_groups.iter()
                .find(|sg| sg.source_key == entry_source_name)
                .and_then(|sg| {
                    sg.tracks.iter().find(|t| t.id == entry.track_id)
                });

            if let Some(track) = track_info {
                let sync_exclusion_mode = if entry.config.sync_exclusion_mode == "include" {
                    SyncExclusionMode::Include
                } else {
                    SyncExclusionMode::Exclude
                };

                let track_type = match entry.track_type {
                    TrackType::Video => "video",
                    TrackType::Audio => "audio",
                    TrackType::Subtitles => "subtitles",
                };

                let state = FinalTrackState {
                    entry_id: uuid::Uuid::new_v4(),
                    track_id: entry.track_id,
                    source_key: entry_source_name.clone(),
                    track_type: track_type.to_string(),
                    codec_id: track.codec_id.clone(),
                    summary: track.summary.clone(),
                    is_default: entry.config.is_default,
                    is_forced_display: entry.config.is_forced_display,
                    sync_to_source: entry.config.sync_to_source.unwrap_or_else(|| "Source 1".to_string()),
                    original_lang: track.language.clone(),
                    custom_lang: entry.config.custom_lang,
                    custom_name: entry.config.custom_name,
                    perform_ocr: entry.config.perform_ocr,
                    convert_to_ass: entry.config.convert_to_ass,
                    rescale: entry.config.rescale,
                    size_multiplier_pct: (entry.config.size_multiplier * 100.0) as i32,
                    style_patch: None,
                    font_replacements: None,
                    sync_exclusion_styles: entry.config.sync_exclusion_styles,
                    sync_exclusion_mode,
                    is_generated: false,
                    generated_filter_styles: Vec::new(),
                    generated_from_entry_id: None,
                };

                self.final_tracks.push(state);
            } else {
                tracing::warn!(
                    "Track {} from source '{}' not found in current sources - skipping",
                    entry.track_id,
                    entry_source_name
                );
            }
        }

        // Load attachment sources (convert SourceIndex to display name)
        for source in layout.attachment_sources {
            self.attachment_sources.insert(source.display_name(), true);
        }

        !self.final_tracks.is_empty()
    }
}
