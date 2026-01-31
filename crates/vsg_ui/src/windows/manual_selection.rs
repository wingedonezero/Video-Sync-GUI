//! Manual selection dialog component.
//!
//! Dialog for configuring track layout for a job.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use gtk::gdk;
use gtk::glib;
use gtk::prelude::*;
use libadwaita::prelude::*;
use relm4::prelude::*;
use relm4::{Component, ComponentParts, ComponentSender};

use vsg_core::extraction::{probe_file, build_track_description, get_detailed_stream_info, TrackType, FfprobeStreamInfo};
use vsg_core::jobs::{JobQueue, JobQueueStatus, LayoutManager, ManualLayout, FinalTrackEntry, TrackConfig, StylePatches, FontReplacements};
use vsg_core::models::{SourceIndex, SourceRef, TrackType as CoreTrackType};

use crate::types::{FinalTrackState, SourceGroupState, TrackWidgetState};

/// Output messages from the manual selection dialog.
#[derive(Debug)]
pub enum ManualSelectionOutput {
    LayoutAccepted,
    Cancelled,
}

/// Input messages for the manual selection dialog.
#[derive(Debug)]
pub enum ManualSelectionMsg {
    // Track selection
    AddTrackToFinal(usize, String),
    RemoveFromFinal(usize),
    MoveTrackUp(usize),
    MoveTrackDown(usize),

    // Drag-drop reorder
    DragStart(usize),
    DragDrop(usize, usize), // from_idx, to_idx

    // Track settings
    SetDefault(usize, bool),
    SetForced(usize, bool),
    SetSyncSource(usize, String),
    OpenTrackSettings(usize),

    // Attachment management
    ToggleAttachment(String, bool),

    // External subtitles
    AddExternalSubtitles,
    ExternalFilesSelected(Vec<PathBuf>),

    // Dialog actions
    Accept,
    Cancel,
}

/// Manual selection dialog state.
pub struct ManualSelectionDialog {
    job_queue: Arc<Mutex<JobQueue>>,
    layout_manager: Arc<Mutex<LayoutManager>>,
    job_idx: usize,

    source_groups: Vec<SourceGroupState>,
    final_tracks: Vec<FinalTrackState>,
    attachment_sources: std::collections::HashMap<String, bool>,
    external_subtitles: Vec<PathBuf>,
    info_text: String,
    dragging_idx: Option<usize>, // Currently dragged track index

    // Widget references for refreshing lists
    source_list: Option<gtk::ListBox>,
    final_list: Option<gtk::ListBox>,
}

#[relm4::component(pub)]
impl Component for ManualSelectionDialog {
    type Init = (Arc<Mutex<JobQueue>>, Arc<Mutex<LayoutManager>>, usize);
    type Input = ManualSelectionMsg;
    type Output = ManualSelectionOutput;
    type CommandOutput = ();

    view! {
        adw::Window {
            set_title: Some("Manual Selection"),
            set_default_width: 1000,
            set_default_height: 700,
            set_modal: true,

            #[wrap(Some)]
            set_content = &gtk::Box {
                set_orientation: gtk::Orientation::Vertical,

                adw::HeaderBar {
                    #[wrap(Some)]
                    set_title_widget = &gtk::Label {
                        set_label: "Configure Track Layout",
                    },
                },

                gtk::Box {
                    set_orientation: gtk::Orientation::Vertical,
                    set_spacing: 12,
                    set_margin_all: 16,
                    set_vexpand: true,

                    // Two-pane layout
                    gtk::Paned {
                        set_orientation: gtk::Orientation::Horizontal,
                        set_vexpand: true,
                        set_position: 400,

                        // Left: Source tracks
                        #[wrap(Some)]
                        set_start_child = &gtk::Frame {
                            set_label: Some("Available Tracks"),
                            set_hexpand: true,

                            gtk::ScrolledWindow {
                                set_vexpand: true,
                                set_hexpand: true,

                                #[name = "source_list"]
                                gtk::ListBox {
                                    set_selection_mode: gtk::SelectionMode::None,
                                    add_css_class: "boxed-list",
                                },
                            },
                        },

                        // Right: Final layout
                        #[wrap(Some)]
                        set_end_child = &gtk::Frame {
                            set_label: Some("Final Layout"),
                            set_hexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 8,
                                set_margin_all: 8,

                                gtk::ScrolledWindow {
                                    set_vexpand: true,
                                    set_hexpand: true,

                                    #[name = "final_list"]
                                    gtk::ListBox {
                                        set_selection_mode: gtk::SelectionMode::None,
                                        add_css_class: "boxed-list",
                                    },
                                },

                                // Attachment sources
                                gtk::Label {
                                    set_label: "Include Attachments From:",
                                    set_xalign: 0.0,
                                    add_css_class: "title-4",
                                },

                                #[name = "attachments_box"]
                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 8,
                                },

                                // External subtitles
                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 8,

                                    gtk::Button {
                                        set_label: "Add External Subtitles...",
                                        connect_clicked => ManualSelectionMsg::AddExternalSubtitles,
                                    },
                                },
                            },
                        },
                    },

                    // Info text
                    gtk::Label {
                        #[watch]
                        set_label: &model.info_text,
                        set_xalign: 0.0,
                    },

                    // Dialog buttons
                    gtk::Box {
                        set_orientation: gtk::Orientation::Horizontal,
                        set_spacing: 8,
                        set_halign: gtk::Align::End,

                        gtk::Button {
                            set_label: "Accept",
                            add_css_class: "suggested-action",
                            connect_clicked => ManualSelectionMsg::Accept,
                        },

                        gtk::Button {
                            set_label: "Cancel",
                            connect_clicked => ManualSelectionMsg::Cancel,
                        },
                    },
                },
            },
        }
    }

    fn init(
        init: Self::Init,
        root: Self::Root,
        sender: ComponentSender<Self>,
    ) -> ComponentParts<Self> {
        let (job_queue, layout_manager, job_idx) = init;

        // Load job data and probe source files for tracks
        let (source_groups, final_tracks, attachment_sources) = {
            let queue = job_queue.lock().unwrap();
            if let Some(job) = queue.jobs().get(job_idx) {
                // Build source groups from job sources
                let mut groups = Vec::new();
                let mut attachments = std::collections::HashMap::new();

                // Sort sources by index for consistent ordering
                let mut sources: Vec<_> = job.sources.iter().collect();
                sources.sort_by_key(|(idx, _)| idx.index());

                for (source_idx, path) in sources {
                    let source_key = format!("Source {}", source_idx.index());
                    attachments.insert(source_key.clone(), true);

                    // Probe the file to get tracks
                    let mut tracks = Vec::new();
                    if let Ok(probe_result) = probe_file(path) {
                        // Optionally get detailed ffprobe info for richer descriptions
                        let ffprobe_info = get_detailed_stream_info(path).ok();

                        for track_info in &probe_result.tracks {
                            // Build description
                            let ffp_stream = ffprobe_info.as_ref().and_then(|fp: &std::collections::HashMap<usize, FfprobeStreamInfo>| fp.get(&track_info.id));
                            let summary = build_track_description(track_info, ffp_stream);

                            // Build badges
                            let mut badge_parts = Vec::new();
                            if track_info.is_default {
                                badge_parts.push("Default");
                            }
                            if track_info.is_forced {
                                badge_parts.push("Forced");
                            }

                            let track_type_str = match track_info.track_type {
                                TrackType::Video => "Video",
                                TrackType::Audio => "Audio",
                                TrackType::Subtitles => "Subtitles",
                            };

                            tracks.push(TrackWidgetState {
                                id: track_info.id,
                                track_type: track_type_str.to_string(),
                                codec_id: track_info.codec_id.clone(),
                                language: track_info.language.clone(),
                                summary,
                                badges: badge_parts.join(", "),
                                is_blocked: false,
                            });
                        }
                    } else {
                        tracing::warn!("Failed to probe file: {}", path.display());
                    }

                    groups.push(SourceGroupState {
                        source_key: source_key.clone(),
                        title: format!("{} ({})", source_key, path.file_name()
                            .map(|n| n.to_string_lossy().to_string())
                            .unwrap_or_else(|| "Unknown".to_string())),
                        tracks,
                        is_expanded: true,
                    });
                }

                (groups, Vec::new(), attachments)
            } else {
                (Vec::new(), Vec::new(), std::collections::HashMap::new())
            }
        };

        let mut model = ManualSelectionDialog {
            job_queue,
            layout_manager,
            job_idx,
            source_groups,
            final_tracks,
            attachment_sources,
            external_subtitles: Vec::new(),
            info_text: "Double-click a track to add it. Drag to reorder final tracks.".to_string(),
            dragging_idx: None,
            source_list: None,
            final_list: None,
        };

        let widgets = view_output!();

        // Store widget references for later updates
        model.source_list = Some(widgets.source_list.clone());
        model.final_list = Some(widgets.final_list.clone());

        // Populate lists
        Self::populate_source_list(&model, &widgets.source_list, &sender);
        Self::populate_final_list(&model, &widgets.final_list, &sender);
        Self::populate_attachments(&model, &widgets.attachments_box, &sender);

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, root: &Self::Root) {
        match msg {
            ManualSelectionMsg::AddTrackToFinal(track_id, source_key) => {
                // Find the track in source groups
                for group in &self.source_groups {
                    if group.source_key == source_key {
                        if let Some(track) = group.tracks.iter().find(|t| t.id == track_id) {
                            let final_track = FinalTrackState::new(
                                track.id,
                                source_key.clone(),
                                track.track_type.clone(),
                                track.codec_id.clone(),
                                track.summary.clone(),
                                track.language.clone(),
                            );
                            self.final_tracks.push(final_track);
                            self.info_text = format!("Added track {} from {}", track_id, source_key);
                        }
                        break;
                    }
                }
                // Refresh final list
                if let Some(ref list_box) = self.final_list {
                    Self::populate_final_list(self, list_box, &sender);
                }
            }

            ManualSelectionMsg::RemoveFromFinal(idx) => {
                if idx < self.final_tracks.len() {
                    self.final_tracks.remove(idx);
                    self.info_text = format!("Removed track at position {}", idx + 1);
                }
                // Refresh final list
                if let Some(ref list_box) = self.final_list {
                    Self::populate_final_list(self, list_box, &sender);
                }
            }

            ManualSelectionMsg::MoveTrackUp(idx) => {
                if idx > 0 && idx < self.final_tracks.len() {
                    self.final_tracks.swap(idx, idx - 1);
                    self.info_text = format!("Moved track up to position {}", idx);
                }
                // Refresh final list
                if let Some(ref list_box) = self.final_list {
                    Self::populate_final_list(self, list_box, &sender);
                }
            }

            ManualSelectionMsg::MoveTrackDown(idx) => {
                if idx + 1 < self.final_tracks.len() {
                    self.final_tracks.swap(idx, idx + 1);
                    self.info_text = format!("Moved track down to position {}", idx + 2);
                }
                // Refresh final list
                if let Some(ref list_box) = self.final_list {
                    Self::populate_final_list(self, list_box, &sender);
                }
            }

            ManualSelectionMsg::DragStart(idx) => {
                self.dragging_idx = Some(idx);
            }

            ManualSelectionMsg::DragDrop(from_idx, to_idx) => {
                if from_idx != to_idx && from_idx < self.final_tracks.len() && to_idx < self.final_tracks.len() {
                    let track = self.final_tracks.remove(from_idx);
                    // Adjust target index if we removed from before it
                    let adjusted_to = if from_idx < to_idx { to_idx - 1 } else { to_idx };
                    self.final_tracks.insert(adjusted_to.min(self.final_tracks.len()), track);
                    self.info_text = format!("Moved track from position {} to {}", from_idx + 1, adjusted_to + 1);
                }
                self.dragging_idx = None;
                // Refresh final list
                if let Some(ref list_box) = self.final_list {
                    Self::populate_final_list(self, list_box, &sender);
                }
            }

            ManualSelectionMsg::SetDefault(idx, value) => {
                if let Some(track) = self.final_tracks.get_mut(idx) {
                    track.is_default = value;
                }
            }

            ManualSelectionMsg::SetForced(idx, value) => {
                if let Some(track) = self.final_tracks.get_mut(idx) {
                    track.is_forced_display = value;
                }
            }

            ManualSelectionMsg::SetSyncSource(idx, source) => {
                if let Some(track) = self.final_tracks.get_mut(idx) {
                    track.sync_to_source = source;
                }
            }

            ManualSelectionMsg::OpenTrackSettings(_idx) => {
                // TODO: Open track settings dialog
                self.info_text = "Track settings dialog would open here.".to_string();
            }

            ManualSelectionMsg::ToggleAttachment(source, checked) => {
                self.attachment_sources.insert(source, checked);
            }

            ManualSelectionMsg::AddExternalSubtitles => {
                let sender = sender.clone();
                let root = root.clone();
                relm4::spawn_local(async move {
                    let dialog = gtk::FileDialog::builder()
                        .title("Select Subtitle Files")
                        .modal(true)
                        .build();

                    if let Ok(files) = dialog.open_multiple_future(Some(&root)).await {
                        let paths: Vec<PathBuf> = files
                            .iter::<gtk::gio::File>()
                            .filter_map(|f| f.ok())
                            .filter_map(|f| f.path())
                            .collect();

                        if !paths.is_empty() {
                            sender.input(ManualSelectionMsg::ExternalFilesSelected(paths));
                        }
                    }
                });
            }

            ManualSelectionMsg::ExternalFilesSelected(paths) => {
                self.external_subtitles.extend(paths);
                self.info_text = format!(
                    "{} external subtitle(s) added.",
                    self.external_subtitles.len()
                );
            }

            ManualSelectionMsg::Accept => {
                // Convert UI FinalTrackState to core FinalTrackEntry
                let final_tracks: Vec<FinalTrackEntry> = self.final_tracks
                    .iter()
                    .enumerate()
                    .map(|(idx, track)| {
                        // Parse source_key like "Source 1" to SourceIndex
                        let source_ref = SourceIndex::from_display_name(&track.source_key)
                            .map(SourceRef::Index)
                            .unwrap_or(SourceRef::External);

                        // Parse track type
                        let track_type = match track.track_type.to_lowercase().as_str() {
                            "video" => CoreTrackType::Video,
                            "audio" => CoreTrackType::Audio,
                            _ => CoreTrackType::Subtitles,
                        };

                        // Parse style_patches from JSON string if present
                        let style_patches: Option<StylePatches> = track.style_patch
                            .as_ref()
                            .and_then(|json| serde_json::from_str(json).ok());

                        // Parse font_replacements from JSON string if present
                        let font_replacements: Option<FontReplacements> = track.font_replacements
                            .as_ref()
                            .and_then(|json| serde_json::from_str(json).ok());

                        // Build TrackConfig from UI state
                        let config = TrackConfig {
                            sync_to_source: if track.sync_to_source != "Source 1" {
                                Some(track.sync_to_source.clone())
                            } else {
                                None
                            },
                            is_default: track.is_default,
                            is_forced_display: track.is_forced_display,
                            custom_name: track.custom_name.clone(),
                            custom_lang: track.custom_lang.clone(),
                            apply_track_name: false,
                            perform_ocr: track.perform_ocr,
                            convert_to_ass: track.convert_to_ass,
                            rescale: track.rescale,
                            size_multiplier: track.size_multiplier_pct as f32 / 100.0,
                            sync_exclusion_styles: track.sync_exclusion_styles.clone(),
                            sync_exclusion_mode: match track.sync_exclusion_mode {
                                crate::types::SyncExclusionMode::Exclude => "exclude".to_string(),
                                crate::types::SyncExclusionMode::Include => "include".to_string(),
                            },
                            sync_exclusion_original_style_list: Vec::new(),
                            skip_frame_validation: false,
                            style_patches,
                            font_replacements,
                            aspect_ratio: None,
                        };

                        FinalTrackEntry {
                            track_id: track.track_id,
                            source_ref,
                            track_type,
                            config,
                            user_order_index: idx,
                            position_in_source_type: 0, // Will be computed by orchestrator
                            is_generated: track.is_generated,
                            generated_source_track_id: track.generated_from_entry_id.map(|_| track.track_id),
                            generated_source_path: None,
                            generated_filter_mode: "exclude".to_string(),
                            generated_filter_styles: track.generated_filter_styles.clone(),
                            generated_original_style_list: Vec::new(),
                            generated_verify_only_lines_removed: true,
                        }
                    })
                    .collect();

                // Convert attachment_sources HashMap<String, bool> to Vec<SourceIndex>
                let attachment_sources: Vec<SourceIndex> = self.attachment_sources
                    .iter()
                    .filter(|(_, &enabled)| enabled)
                    .filter_map(|(key, _)| SourceIndex::from_display_name(key))
                    .collect();

                // Build ManualLayout
                let layout = ManualLayout {
                    final_tracks,
                    attachment_sources,
                    source_settings: std::collections::HashMap::new(),
                };

                // Save layout and update job
                let mut queue = self.job_queue.lock().unwrap();
                if let Some(job) = queue.get_mut(self.job_idx) {
                    // Save layout to disk via LayoutManager
                    let lm = self.layout_manager.lock().unwrap();
                    if let Err(e) = lm.save_layout_with_metadata(&job.layout_id, &job.sources, &layout) {
                        tracing::error!("Failed to save layout: {}", e);
                    } else {
                        tracing::info!("Saved layout for job: {}", job.layout_id);
                    }

                    // Update job with layout and mark as configured
                    job.layout = Some(layout);
                    job.status = JobQueueStatus::Configured;

                    // Save queue to persist status change
                    if let Err(e) = queue.save() {
                        tracing::warn!("Failed to save queue: {}", e);
                    }
                }

                let _ = sender.output(ManualSelectionOutput::LayoutAccepted);
            }

            ManualSelectionMsg::Cancel => {
                let _ = sender.output(ManualSelectionOutput::Cancelled);
            }
        }
    }
}

impl ManualSelectionDialog {
    fn populate_source_list(
        model: &ManualSelectionDialog,
        list_box: &gtk::ListBox,
        sender: &ComponentSender<Self>,
    ) {
        // Clear existing
        while let Some(child) = list_box.first_child() {
            list_box.remove(&child);
        }

        if model.source_groups.is_empty() {
            let row = adw::ActionRow::builder()
                .title("No sources available")
                .subtitle("Add source files to the job first")
                .build();
            list_box.append(&row);
        } else {
            for group in &model.source_groups {
                // Group header
                let header = adw::ActionRow::builder()
                    .title(&group.title)
                    .build();
                header.add_css_class("title-3");
                list_box.append(&header);

                if group.tracks.is_empty() {
                    let empty_row = adw::ActionRow::builder()
                        .title("No tracks found")
                        .subtitle("File could not be probed")
                        .build();
                    list_box.append(&empty_row);
                } else {
                    for track in &group.tracks {
                        let row = adw::ActionRow::builder()
                            .title(&track.summary)
                            .subtitle(&format!(
                                "{} | {}",
                                track.track_type,
                                track.language.as_deref().unwrap_or("und")
                            ))
                            .activatable(true)
                            .build();

                        let type_icon = match track.track_type.as_str() {
                            "Video" => "video-x-generic-symbolic",
                            "Audio" => "audio-x-generic-symbolic",
                            "Subtitles" => "text-x-generic-symbolic",
                            _ => "document-symbolic",
                        };

                        let icon = gtk::Image::from_icon_name(type_icon);
                        row.add_prefix(&icon);

                        // Add "Add" button for quick adding
                        let add_btn = gtk::Button::builder()
                            .label("Add")
                            .valign(gtk::Align::Center)
                            .build();

                        let sender_add = sender.clone();
                        let track_id = track.id;
                        let source_key = group.source_key.clone();
                        add_btn.connect_clicked(move |_| {
                            sender_add.input(ManualSelectionMsg::AddTrackToFinal(track_id, source_key.clone()));
                        });
                        row.add_suffix(&add_btn);

                        // Also add double-click to add via gesture
                        let gesture = gtk::GestureClick::new();
                        gesture.set_button(1); // Left mouse button
                        let sender_dbl = sender.clone();
                        let track_id_dbl = track.id;
                        let source_key_dbl = group.source_key.clone();
                        gesture.connect_released(move |gesture, n_press, _x, _y| {
                            if n_press == 2 {
                                // Double-click
                                sender_dbl.input(ManualSelectionMsg::AddTrackToFinal(track_id_dbl, source_key_dbl.clone()));
                                gesture.set_state(gtk::EventSequenceState::Claimed);
                            }
                        });
                        row.add_controller(gesture);

                        list_box.append(&row);
                    }
                }
            }
        }
    }

    fn populate_final_list(
        model: &ManualSelectionDialog,
        list_box: &gtk::ListBox,
        sender: &ComponentSender<Self>,
    ) {
        // Clear existing
        while let Some(child) = list_box.first_child() {
            list_box.remove(&child);
        }

        if model.final_tracks.is_empty() {
            let row = adw::ActionRow::builder()
                .title("No tracks selected")
                .subtitle("Double-click tracks on the left to add them")
                .build();
            list_box.append(&row);
        } else {
            for (idx, track) in model.final_tracks.iter().enumerate() {
                let row = adw::ActionRow::builder()
                    .title(&track.summary)
                    .subtitle(&format!(
                        "{} | {} | {}",
                        track.source_key,
                        track.track_type,
                        track.badges()
                    ))
                    .build();

                // Add drag source for reordering
                let drag_source = gtk::DragSource::new();
                drag_source.set_actions(gdk::DragAction::MOVE);

                let sender_drag = sender.clone();
                let drag_idx = idx;
                drag_source.connect_prepare(move |_source, _x, _y| {
                    sender_drag.input(ManualSelectionMsg::DragStart(drag_idx));
                    // Use a simple string content provider with the index
                    Some(gdk::ContentProvider::for_value(&glib::Value::from(&format!("{}", drag_idx))))
                });

                // Add icon for drag using a widget paintable
                drag_source.connect_drag_begin(|source, _drag| {
                    let icon = gtk::Image::from_icon_name("view-list-symbolic");
                    let paintable = gtk::WidgetPaintable::new(Some(&icon));
                    source.set_icon(Some(&paintable), 0, 0);
                });

                row.add_controller(drag_source);

                // Add drop target for receiving dragged tracks
                let drop_target = gtk::DropTarget::new(glib::Type::STRING, gdk::DragAction::MOVE);

                let sender_drop = sender.clone();
                let drop_idx = idx;
                drop_target.connect_drop(move |_target, value, _x, _y| {
                    if let Ok(from_str) = value.get::<String>() {
                        if let Ok(from_idx) = from_str.parse::<usize>() {
                            sender_drop.input(ManualSelectionMsg::DragDrop(from_idx, drop_idx));
                            return true;
                        }
                    }
                    false
                });

                row.add_controller(drop_target);

                // Move buttons
                let up_btn = gtk::Button::builder()
                    .icon_name("go-up-symbolic")
                    .valign(gtk::Align::Center)
                    .tooltip_text("Move up")
                    .build();

                let sender_clone = sender.clone();
                let idx_clone = idx;
                up_btn.connect_clicked(move |_| {
                    sender_clone.input(ManualSelectionMsg::MoveTrackUp(idx_clone));
                });

                let down_btn = gtk::Button::builder()
                    .icon_name("go-down-symbolic")
                    .valign(gtk::Align::Center)
                    .tooltip_text("Move down")
                    .build();

                let sender_clone = sender.clone();
                let idx_clone = idx;
                down_btn.connect_clicked(move |_| {
                    sender_clone.input(ManualSelectionMsg::MoveTrackDown(idx_clone));
                });

                // Remove button
                let remove_btn = gtk::Button::builder()
                    .icon_name("list-remove-symbolic")
                    .valign(gtk::Align::Center)
                    .tooltip_text("Remove track")
                    .build();

                let sender_clone = sender.clone();
                let idx_clone = idx;
                remove_btn.connect_clicked(move |_| {
                    sender_clone.input(ManualSelectionMsg::RemoveFromFinal(idx_clone));
                });

                // Settings button
                let settings_btn = gtk::Button::builder()
                    .icon_name("emblem-system-symbolic")
                    .valign(gtk::Align::Center)
                    .tooltip_text("Track settings")
                    .build();

                let sender_clone = sender.clone();
                let idx_clone = idx;
                settings_btn.connect_clicked(move |_| {
                    sender_clone.input(ManualSelectionMsg::OpenTrackSettings(idx_clone));
                });

                row.add_suffix(&up_btn);
                row.add_suffix(&down_btn);
                row.add_suffix(&remove_btn);
                row.add_suffix(&settings_btn);

                list_box.append(&row);
            }
        }
    }

    fn populate_attachments(
        model: &ManualSelectionDialog,
        container: &gtk::Box,
        sender: &ComponentSender<Self>,
    ) {
        // Clear existing
        while let Some(child) = container.first_child() {
            container.remove(&child);
        }

        for (source, checked) in &model.attachment_sources {
            let check = gtk::CheckButton::builder()
                .label(source)
                .active(*checked)
                .build();

            let sender_clone = sender.clone();
            let source_clone = source.clone();
            check.connect_toggled(move |btn| {
                sender_clone.input(ManualSelectionMsg::ToggleAttachment(
                    source_clone.clone(),
                    btn.is_active(),
                ));
            });

            container.append(&check);
        }
    }
}
