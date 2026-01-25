//! Manual Selection Dialog logic controller.
//!
//! Handles track selection from sources into final output list.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Command;
use std::sync::{Arc, Mutex};

use slint::{ComponentHandle, Model, ModelRc, SharedString, VecModel};
use vsg_core::jobs::{FinalTrackEntry, ManualLayout, TrackConfig};
use vsg_core::models::TrackType;

use crate::ui::{
    AttachmentSourceOption, FinalTrackData, ManualSelectionDialog, SourceGroupData,
    TrackSettingsDialog, TrackWidgetData,
};
use crate::windows::track_settings_dialog::setup_track_settings_dialog;

/// Set up all callbacks for ManualSelectionDialog.
///
/// The `on_accept` callback is called when the user accepts the layout,
/// with the ManualLayout (or None if cancelled).
pub fn setup_manual_selection_dialog<F>(
    dialog: &ManualSelectionDialog,
    job_name: &str,
    sources: &HashMap<String, PathBuf>,
    on_accept: F,
) where
    F: Fn(Option<ManualLayout>) + Clone + 'static,
{
    // Store layout state in Arc<Mutex> for callbacks
    let layout_state = Arc::new(Mutex::new(ManualLayout::new()));

    // Populate source groups with tracks
    populate_source_groups(dialog, sources, Arc::clone(&layout_state));

    // Set up attachment options
    populate_attachment_options(dialog, sources);

    // Set up callbacks
    setup_source_track_double_click(dialog, Arc::clone(&layout_state));
    setup_final_track_callbacks(dialog, Arc::clone(&layout_state));
    setup_track_settings(dialog, Arc::clone(&layout_state));
    setup_attachment_toggle(dialog, Arc::clone(&layout_state));
    setup_add_external_subtitles(dialog);
    setup_accept_cancel(dialog, layout_state, on_accept);
}

/// Populate source groups with track data from each source.
fn populate_source_groups(
    dialog: &ManualSelectionDialog,
    sources: &HashMap<String, PathBuf>,
    _layout_state: Arc<Mutex<ManualLayout>>,
) {
    let mut groups: Vec<SourceGroupData> = Vec::new();

    // Sort source keys for consistent ordering
    let mut source_keys: Vec<&String> = sources.keys().collect();
    source_keys.sort();

    for source_key in source_keys {
        let path = &sources[source_key];
        let is_reference = source_key == "Source 1";

        // Get tracks from mkvmerge -J
        let tracks = probe_tracks(path);

        // Convert to TrackWidgetData
        let track_widgets: Vec<TrackWidgetData> = tracks
            .iter()
            .enumerate()
            .map(|(idx, track)| TrackWidgetData {
                id: idx as i32,
                source: source_key.clone().into(),
                track_type: track.track_type.clone(),
                codec_id: track.codec_id.clone(),
                summary: track.summary.clone(),
                badges: track.badges.clone(),
                options_summary: SharedString::new(),
                is_default: false,
                is_forced: false,
                has_custom_name: false,
                is_generated: false,
                has_style_patch: false,
                has_sync_exclusions: false,
                sync_to_source: SharedString::new(),
            })
            .collect();

        // Determine blocked tracks (video from non-reference sources)
        let blocked: Vec<bool> = tracks
            .iter()
            .map(|t| !is_reference && t.track_type == "video")
            .collect();

        let file_name = path
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| path.to_string_lossy().to_string());

        let title = if is_reference {
            format!("{} (Reference) - '{}'", source_key, file_name)
        } else {
            format!("{} - '{}'", source_key, file_name)
        };

        let group = SourceGroupData {
            source_key: source_key.clone().into(),
            title: title.into(),
            tracks: ModelRc::from(std::rc::Rc::new(VecModel::from(track_widgets))),
            blocked: ModelRc::from(std::rc::Rc::new(VecModel::from(blocked))),
        };

        groups.push(group);
    }

    let model = std::rc::Rc::new(VecModel::from(groups));
    dialog.set_source_groups(ModelRc::from(model));
}

/// Track info from probing.
struct TrackInfo {
    track_type: SharedString,
    summary: SharedString,
    badges: SharedString,
    codec_id: SharedString,
}

/// Probe tracks from a video file using mkvmerge -J.
fn probe_tracks(path: &PathBuf) -> Vec<TrackInfo> {
    // Run mkvmerge -J to get track info
    let output = Command::new("mkvmerge")
        .arg("-J")
        .arg(path)
        .output();

    match output {
        Ok(output) if output.status.success() => {
            parse_mkvmerge_json(&String::from_utf8_lossy(&output.stdout))
        }
        Ok(output) => {
            tracing::warn!(
                "mkvmerge failed for {}: {}",
                path.display(),
                String::from_utf8_lossy(&output.stderr)
            );
            // Return placeholder tracks
            vec![
                TrackInfo {
                    track_type: "video".into(),
                    summary: "Video Track (probe failed)".into(),
                    badges: SharedString::new(),
                    codec_id: SharedString::new(),
                },
                TrackInfo {
                    track_type: "audio".into(),
                    summary: "Audio Track (probe failed)".into(),
                    badges: SharedString::new(),
                    codec_id: SharedString::new(),
                },
            ]
        }
        Err(e) => {
            tracing::warn!("Failed to run mkvmerge for {}: {}", path.display(), e);
            vec![
                TrackInfo {
                    track_type: "video".into(),
                    summary: "Video Track (mkvmerge not found)".into(),
                    badges: SharedString::new(),
                    codec_id: SharedString::new(),
                },
                TrackInfo {
                    track_type: "audio".into(),
                    summary: "Audio Track (mkvmerge not found)".into(),
                    badges: SharedString::new(),
                    codec_id: SharedString::new(),
                },
            ]
        }
    }
}

/// Parse mkvmerge -J JSON output into track info.
fn parse_mkvmerge_json(json_str: &str) -> Vec<TrackInfo> {
    let json: serde_json::Value = match serde_json::from_str(json_str) {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("Failed to parse mkvmerge JSON: {}", e);
            return Vec::new();
        }
    };

    let mut tracks = Vec::new();

    if let Some(track_array) = json.get("tracks").and_then(|t| t.as_array()) {
        for track in track_array {
            let track_type = track
                .get("type")
                .and_then(|t| t.as_str())
                .unwrap_or("unknown");

            let codec = track
                .get("codec")
                .and_then(|c| c.as_str())
                .unwrap_or("Unknown");

            let properties = track.get("properties");

            let language = properties
                .and_then(|p| p.get("language"))
                .and_then(|l| l.as_str())
                .map(|l| language_display(l))
                .unwrap_or_else(|| "und".to_string());

            let codec_id = properties
                .and_then(|p| p.get("codec_id"))
                .and_then(|c| c.as_str())
                .unwrap_or("");

            let is_default = properties
                .and_then(|p| p.get("default_track"))
                .and_then(|d| d.as_bool())
                .unwrap_or(false);

            let is_forced = properties
                .and_then(|p| p.get("forced_track"))
                .and_then(|f| f.as_bool())
                .unwrap_or(false);

            // Build summary based on track type
            let summary = match track_type {
                "video" => {
                    let width = properties
                        .and_then(|p| p.get("pixel_dimensions"))
                        .and_then(|d| d.as_str())
                        .unwrap_or("");
                    format!("{}, {}", codec, width)
                }
                "audio" => {
                    let channels = properties
                        .and_then(|p| p.get("audio_channels"))
                        .and_then(|c| c.as_u64())
                        .unwrap_or(2);
                    let channel_str = channel_layout(channels as u8);
                    format!("{}, {}, {}", language, codec, channel_str)
                }
                "subtitles" => {
                    format!("{}, {}", language, codec)
                }
                _ => codec.to_string(),
            };

            // Build badges
            let mut badges = Vec::new();
            if is_default {
                badges.push("Default");
            }
            if is_forced {
                badges.push("Forced");
            }

            tracks.push(TrackInfo {
                track_type: track_type.into(),
                summary: summary.into(),
                badges: badges.join(" | ").into(),
                codec_id: codec_id.into(),
            });
        }
    }

    tracks
}

/// Convert language code to display name.
fn language_display(code: &str) -> String {
    match code {
        "eng" => "English".to_string(),
        "jpn" => "Japanese".to_string(),
        "spa" => "Spanish".to_string(),
        "fre" | "fra" => "French".to_string(),
        "ger" | "deu" => "German".to_string(),
        "ita" => "Italian".to_string(),
        "por" => "Portuguese".to_string(),
        "rus" => "Russian".to_string(),
        "chi" | "zho" => "Chinese".to_string(),
        "kor" => "Korean".to_string(),
        "ara" => "Arabic".to_string(),
        "und" => "Undetermined".to_string(),
        _ => code.to_uppercase(),
    }
}

/// Convert channel count to display string.
fn channel_layout(channels: u8) -> String {
    match channels {
        1 => "Mono".to_string(),
        2 => "Stereo".to_string(),
        6 => "5.1".to_string(),
        8 => "7.1".to_string(),
        _ => format!("{} ch", channels),
    }
}

/// Populate attachment source options.
fn populate_attachment_options(dialog: &ManualSelectionDialog, sources: &HashMap<String, PathBuf>) {
    let mut options: Vec<AttachmentSourceOption> = sources
        .keys()
        .map(|key| AttachmentSourceOption {
            source_key: key.clone().into(),
            label: key.clone().into(),
            checked: key == "Source 1", // Default to Source 1
        })
        .collect();

    // Sort by source key
    options.sort_by(|a, b| a.source_key.as_str().cmp(b.source_key.as_str()));

    let model = std::rc::Rc::new(VecModel::from(options));
    dialog.set_attachment_options(ModelRc::from(model));
}

/// Set up source track double-click to add to final list.
fn setup_source_track_double_click(
    dialog: &ManualSelectionDialog,
    layout_state: Arc<Mutex<ManualLayout>>,
) {
    let dialog_weak = dialog.as_weak();
    let state = Arc::clone(&layout_state);

    dialog.on_source_track_double_clicked(move |track_id, source_key| {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        // Find the track info from source groups
        let source_groups = dialog.get_source_groups();
        let mut track_type = "audio".to_string();
        let mut summary = SharedString::new();

        for i in 0..source_groups.row_count() {
            if let Some(group) = source_groups.row_data(i) {
                if group.source_key.as_str() == source_key.as_str() {
                    let blocked = group.blocked;
                    if let Some(is_blocked) = blocked.row_data(track_id as usize) {
                        if is_blocked {
                            dialog.set_info_message(
                                "Video tracks can only be added from the reference source.".into(),
                            );
                            dialog.set_show_info(true);
                            return;
                        }
                    }

                    if let Some(track) = group.tracks.row_data(track_id as usize) {
                        track_type = track.track_type.to_string();
                        summary = track.summary.clone();
                    }
                    break;
                }
            }
        }

        // Add to final tracks
        let final_tracks = dialog.get_final_tracks();
        if let Some(model) = final_tracks.as_any().downcast_ref::<VecModel<FinalTrackData>>() {
            // Create available sync sources list
            let sync_sources: Vec<SharedString> = {
                let groups = dialog.get_source_groups();
                (0..groups.row_count())
                    .filter_map(|i| groups.row_data(i).map(|g| g.source_key.clone()))
                    .collect()
            };

            // Build the nested TrackWidgetData
            let track_widget = TrackWidgetData {
                id: track_id,
                source: source_key.clone(),
                track_type: track_type.clone().into(),
                codec_id: SharedString::new(),
                summary: summary,
                badges: SharedString::new(),
                options_summary: SharedString::new(),
                is_default: false,
                is_forced: false,
                has_custom_name: false,
                is_generated: false,
                has_style_patch: false,
                has_sync_exclusions: false,
                sync_to_source: "Source 1".into(),
            };

            let new_track = FinalTrackData {
                track: track_widget,
                position: model.row_count() as i32,
                sync_source_options: ModelRc::from(std::rc::Rc::new(VecModel::from(sync_sources))),
            };

            model.push(new_track);

            // Update layout state
            let mut layout = state.lock().unwrap();
            let track_type_enum = match track_type.as_str() {
                "video" => TrackType::Video,
                "audio" => TrackType::Audio,
                "subtitles" => TrackType::Subtitles,
                _ => TrackType::Audio,
            };

            layout.final_tracks.push(FinalTrackEntry::new(
                track_id as usize,
                source_key.to_string(),
                track_type_enum,
            ));
        }

        dialog.set_show_info(false);
    });
}

/// Set up final track list callbacks.
fn setup_final_track_callbacks(
    dialog: &ManualSelectionDialog,
    layout_state: Arc<Mutex<ManualLayout>>,
) {
    // Track moved (reorder)
    let dialog_weak = dialog.as_weak();
    let state = Arc::clone(&layout_state);

    dialog.on_final_track_moved(move |from_idx, to_idx| {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let from = from_idx as usize;
        let to = to_idx as usize;

        // Update UI model
        let final_tracks = dialog.get_final_tracks();
        if let Some(model) = final_tracks.as_any().downcast_ref::<VecModel<FinalTrackData>>() {
            if from < model.row_count() && to < model.row_count() {
                // Get the track to move
                if let Some(track) = model.row_data(from) {
                    model.remove(from);
                    model.insert(to, track);
                }
            }
        }

        // Update layout state
        let mut layout = state.lock().unwrap();
        if from < layout.final_tracks.len() && to < layout.final_tracks.len() {
            let track = layout.final_tracks.remove(from);
            layout.final_tracks.insert(to, track);
        }
    });

    // Track removed
    let dialog_weak = dialog.as_weak();
    let state = Arc::clone(&layout_state);

    dialog.on_final_track_removed(move |idx| {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let index = idx as usize;

        // Update UI model
        let final_tracks = dialog.get_final_tracks();
        if let Some(model) = final_tracks.as_any().downcast_ref::<VecModel<FinalTrackData>>() {
            if index < model.row_count() {
                model.remove(index);
            }
        }

        // Update layout state
        let mut layout = state.lock().unwrap();
        if index < layout.final_tracks.len() {
            layout.final_tracks.remove(index);
        }
    });

    // Default changed
    let state = Arc::clone(&layout_state);
    dialog.on_final_track_default_changed(move |idx, is_default| {
        let mut layout = state.lock().unwrap();
        if let Some(track) = layout.final_tracks.get_mut(idx as usize) {
            track.config.is_default = is_default;
        }
    });

    // Forced changed
    let state = Arc::clone(&layout_state);
    dialog.on_final_track_forced_changed(move |idx, is_forced| {
        let mut layout = state.lock().unwrap();
        if let Some(track) = layout.final_tracks.get_mut(idx as usize) {
            track.config.is_forced = is_forced;
        }
    });

    // Sync source changed
    let state = Arc::clone(&layout_state);
    dialog.on_final_track_sync_changed(move |idx, sync_source| {
        let mut layout = state.lock().unwrap();
        if let Some(track) = layout.final_tracks.get_mut(idx as usize) {
            track.config.sync_to_source = Some(sync_source.to_string());
        }
    });
}

/// Set up track settings button.
fn setup_track_settings(
    dialog: &ManualSelectionDialog,
    layout_state: Arc<Mutex<ManualLayout>>,
) {
    let dialog_weak = dialog.as_weak();
    let state = Arc::clone(&layout_state);

    dialog.on_final_track_settings_clicked(move |idx| {
        let Some(parent_dialog) = dialog_weak.upgrade() else {
            return;
        };

        // Get track info (nested under .track in FinalTrackData)
        let final_tracks = parent_dialog.get_final_tracks();
        let (track_type, codec_id) = match final_tracks.row_data(idx as usize) {
            Some(data) => (data.track.track_type.to_string(), data.track.codec_id.to_string()),
            None => return,
        };

        // Get current config
        let current_config = {
            let layout = state.lock().unwrap();
            layout
                .final_tracks
                .get(idx as usize)
                .map(|t| t.config.clone())
                .unwrap_or_default()
        };

        // Create TrackSettingsDialog
        match TrackSettingsDialog::new() {
            Ok(settings_dialog) => {
                let state_for_save = Arc::clone(&state);
                let track_idx = idx as usize;

                setup_track_settings_dialog(
                    &settings_dialog,
                    &track_type,
                    &codec_id,
                    current_config,
                    move |new_config| {
                        if let Some(config) = new_config {
                            let mut layout = state_for_save.lock().unwrap();
                            if let Some(track) = layout.final_tracks.get_mut(track_idx) {
                                track.config = config;
                            }
                        }
                    },
                );

                if let Err(e) = settings_dialog.show() {
                    tracing::warn!("Failed to show track settings: {}", e);
                }
            }
            Err(e) => {
                tracing::warn!("Failed to create track settings dialog: {}", e);
            }
        }
    });

    // Style editor (stub)
    dialog.on_final_track_style_editor_clicked(move |_idx| {
        // TODO: Open StyleEditorDialog (stub)
        tracing::info!("Style editor not yet implemented");
    });
}

/// Set up attachment toggle.
fn setup_attachment_toggle(
    dialog: &ManualSelectionDialog,
    layout_state: Arc<Mutex<ManualLayout>>,
) {
    let dialog_weak = dialog.as_weak();
    let state = Arc::clone(&layout_state);

    dialog.on_attachment_toggled(move |source_key, checked| {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        // Update UI model
        let options = dialog.get_attachment_options();
        if let Some(model) = options.as_any().downcast_ref::<VecModel<AttachmentSourceOption>>() {
            for i in 0..model.row_count() {
                if let Some(mut opt) = model.row_data(i) {
                    if opt.source_key.as_str() == source_key.as_str() {
                        opt.checked = checked;
                        model.set_row_data(i, opt);
                        break;
                    }
                }
            }
        }

        // Update layout state
        let mut layout = state.lock().unwrap();
        let key = source_key.to_string();
        if checked {
            if !layout.attachment_sources.contains(&key) {
                layout.attachment_sources.push(key);
            }
        } else {
            layout.attachment_sources.retain(|k| k != &key);
        }
    });
}

/// Set up add external subtitles button.
fn setup_add_external_subtitles(dialog: &ManualSelectionDialog) {
    let dialog_weak = dialog.as_weak();

    dialog.on_add_external_subtitles(move || {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        // Open file picker for subtitle files
        if let Some(paths) = rfd::FileDialog::new()
            .set_title("Select External Subtitle File(s)")
            .add_filter("Subtitle Files", &["srt", "ass", "ssa", "sub", "idx", "sup"])
            .add_filter("All Files", &["*"])
            .pick_files()
        {
            if !paths.is_empty() {
                dialog.set_show_external_group(true);
                // TODO: Add external tracks to external_tracks model
                tracing::info!("Selected {} external subtitle file(s)", paths.len());
            }
        }
    });
}

/// Set up accept/cancel buttons.
fn setup_accept_cancel<F>(
    dialog: &ManualSelectionDialog,
    layout_state: Arc<Mutex<ManualLayout>>,
    on_accept: F,
) where
    F: Fn(Option<ManualLayout>) + Clone + 'static,
{
    // Accept
    let dialog_weak = dialog.as_weak();
    let state = Arc::clone(&layout_state);
    let callback = on_accept.clone();

    dialog.on_accept(move || {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let layout = state.lock().unwrap().clone();
        callback(Some(layout));
        dialog.hide().ok();
    });

    // Cancel
    let dialog_weak = dialog.as_weak();
    let callback = on_accept;

    dialog.on_cancel(move || {
        if let Some(dialog) = dialog_weak.upgrade() {
            callback(None);
            dialog.hide().ok();
        }
    });
}
