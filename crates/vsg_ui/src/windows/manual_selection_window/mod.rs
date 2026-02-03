//! Manual selection window
//!
//! Allows users to configure track selection and layout for a job.
//! Features:
//! - Source track lists grouped by source file
//! - Final output list with drag-drop reordering
//! - Per-track configuration (default, forced, sync, etc.)
//! - Attachment source selection
//! - External subtitle import

mod logic;
mod messages;
mod model;

pub use messages::{FinalTrackData, ManualSelectionMsg, ManualSelectionOutput};
pub use model::ManualSelectionModel;

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use gtk4::gdk;
use gtk4::glib::prelude::IsA;
use gtk4::prelude::*;
use gtk4::{gio, glib};
use relm4::prelude::*;

use vsg_core::config::ConfigManager;
use vsg_core::jobs::ManualLayout;

/// Initialization data for manual selection window
pub struct ManualSelectionInit {
    /// Source file paths (key -> path)
    pub sources: HashMap<String, PathBuf>,
    /// Config manager
    pub config: Arc<Mutex<ConfigManager>>,
    /// Previous layout to prepopulate (if any)
    pub previous_layout: Option<ManualLayout>,
    /// Parent window
    pub parent: Option<gtk4::Window>,
}

/// Manual selection window component
#[allow(dead_code)]
pub struct ManualSelectionWindow {
    model: ManualSelectionModel,
    config: Arc<Mutex<ConfigManager>>,
    probing_error: Option<String>,
}

#[relm4::component(pub)]
impl Component for ManualSelectionWindow {
    type Init = ManualSelectionInit;
    type Input = ManualSelectionMsg;
    type Output = ManualSelectionOutput;
    type CommandOutput = ();

    view! {
        gtk4::Window {
            set_title: Some("Manual Track Selection"),
            set_default_width: 1400,
            set_default_height: 800,
            set_modal: true,

            gtk4::Box {
                set_orientation: gtk4::Orientation::Vertical,
                set_margin_all: 12,
                set_spacing: 12,

                // === Info label for status/errors ===
                #[name = "info_label"]
                gtk4::Label {
                    set_visible: model.probing_error.is_some(),
                    set_markup: &model.probing_error.clone().unwrap_or_default(),
                    add_css_class: "error",
                },

                // === Main content (horizontal split) ===
                gtk4::Paned {
                    set_orientation: gtk4::Orientation::Horizontal,
                    set_vexpand: true,
                    set_position: 500,

                    // === Left pane: Source tracks ===
                    #[wrap(Some)]
                    set_start_child = &gtk4::Box {
                        set_orientation: gtk4::Orientation::Vertical,
                        set_spacing: 8,
                        set_hexpand: true,

                        gtk4::Label {
                            set_markup: "<b>Source Tracks</b>",
                            set_xalign: 0.0,
                        },

                        gtk4::ScrolledWindow {
                            set_vexpand: true,
                            set_hexpand: true,
                            set_min_content_width: 400,

                            #[name = "source_box"]
                            gtk4::Box {
                                set_orientation: gtk4::Orientation::Vertical,
                                set_spacing: 8,
                            },
                        },

                        gtk4::Button {
                            set_label: "Add External Subtitle(s)...",
                            set_tooltip_text: Some("Add external subtitle files (.srt, .ass, .sup)"),
                            connect_clicked => ManualSelectionMsg::AddExternalSubtitles,
                        },
                    },

                    // === Right pane: Final output ===
                    #[wrap(Some)]
                    set_end_child = &gtk4::Box {
                        set_orientation: gtk4::Orientation::Vertical,
                        set_spacing: 8,
                        set_hexpand: true,

                        gtk4::Label {
                            set_markup: "<b>Final Output (double-click or drag to add)</b>",
                            set_xalign: 0.0,
                        },

                        gtk4::ScrolledWindow {
                            set_vexpand: true,
                            set_hexpand: true,
                            set_min_content_width: 600,

                            #[name = "final_list"]
                            gtk4::ListBox {
                                set_selection_mode: gtk4::SelectionMode::Single,
                                add_css_class: "boxed-list",
                            },
                        },

                        // === Final list toolbar ===
                        gtk4::Box {
                            set_orientation: gtk4::Orientation::Horizontal,
                            set_spacing: 4,

                            gtk4::Button {
                                set_icon_name: "go-up-symbolic",
                                set_tooltip_text: Some("Move selected track up"),
                                connect_clicked[sender] => move |_| {
                                    // Use special sentinel value to indicate "use selection"
                                    sender.input(ManualSelectionMsg::MoveTrackUp { final_index: usize::MAX });
                                },
                            },

                            gtk4::Button {
                                set_icon_name: "go-down-symbolic",
                                set_tooltip_text: Some("Move selected track down"),
                                connect_clicked[sender] => move |_| {
                                    sender.input(ManualSelectionMsg::MoveTrackDown { final_index: usize::MAX });
                                },
                            },

                            gtk4::Separator {
                                set_orientation: gtk4::Orientation::Vertical,
                            },

                            gtk4::Button {
                                set_icon_name: "emblem-system-symbolic",
                                set_tooltip_text: Some("Track settings..."),
                                connect_clicked[sender] => move |_| {
                                    sender.input(ManualSelectionMsg::OpenTrackSettings { final_index: usize::MAX });
                                },
                            },

                            gtk4::Separator {
                                set_orientation: gtk4::Orientation::Vertical,
                            },

                            gtk4::Button {
                                set_icon_name: "list-remove-symbolic",
                                set_tooltip_text: Some("Remove selected track"),
                                connect_clicked[sender] => move |_| {
                                    sender.input(ManualSelectionMsg::RemoveTrackFromFinal { final_index: usize::MAX });
                                },
                            },
                        },

                        // === Attachments section ===
                        gtk4::Frame {
                            set_label: Some("Attachments"),
                            set_margin_top: 8,

                            #[name = "attachment_box"]
                            gtk4::Box {
                                set_orientation: gtk4::Orientation::Horizontal,
                                set_spacing: 8,
                                set_margin_all: 8,

                                gtk4::Label {
                                    set_label: "Include attachments from:",
                                },
                            },
                        },
                    },
                },

                // === Dialog buttons ===
                gtk4::Box {
                    set_orientation: gtk4::Orientation::Horizontal,
                    set_spacing: 8,
                    set_halign: gtk4::Align::End,

                    gtk4::Button {
                        set_label: "Cancel",
                        connect_clicked => ManualSelectionMsg::Cancel,
                    },

                    gtk4::Button {
                        set_label: "OK",
                        add_css_class: "suggested-action",
                        connect_clicked => ManualSelectionMsg::Accept,
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
        // Probe source files
        let probe_result = logic::probe_sources(&init.sources);

        let (model, probing_error) = match probe_result {
            Ok(sources) => {
                let mut m = ManualSelectionModel::new(sources);

                // Prepopulate from previous layout if available
                if let Some(ref layout) = init.previous_layout {
                    logic::prepopulate_from_layout(&mut m, layout);
                }

                (m, None)
            }
            Err(e) => (
                ManualSelectionModel::default(),
                Some(format!(
                    "<span color='red'>Error probing files: {}</span>",
                    e
                )),
            ),
        };

        let model = ManualSelectionWindow {
            model,
            config: init.config,
            probing_error,
        };

        let widgets = view_output!();

        // Set up drop target for final list
        Self::setup_drop_target(&widgets.final_list, sender.clone());

        // Set up selection handling for final list
        Self::setup_list_selection(&widgets.final_list, sender.clone());

        // Populate source track boxes
        Self::populate_source_tracks(&widgets.source_box, &model.model, sender.clone());

        // Populate attachment checkboxes
        Self::populate_attachments(&widgets.attachment_box, &model.model, sender.clone());

        // Refresh final list with custom track widgets
        Self::refresh_final_list(&widgets.final_list, &model.model, sender.clone());

        // Set parent if provided
        if let Some(parent) = init.parent {
            root.set_transient_for(Some(&parent));
        }

        root.present();

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, root: &Self::Root) {
        match msg {
            ManualSelectionMsg::AddTrackToFinal {
                source_key,
                track_index,
            }
            | ManualSelectionMsg::SourceTrackDoubleClicked {
                source_key,
                track_index,
            } => {
                self.model.add_to_final(&source_key, track_index);
                self.refresh_list_from_root(root, sender.clone());
            }

            ManualSelectionMsg::RemoveTrackFromFinal { final_index } => {
                // usize::MAX is sentinel for "use selection"
                let idx = if final_index == usize::MAX {
                    self.model.selected_final_track
                } else {
                    Some(final_index)
                };

                if let Some(idx) = idx {
                    if idx < self.model.final_tracks.len() {
                        self.model.remove_from_final(idx);
                        self.model.selected_final_track = None;
                        self.refresh_list_from_root(root, sender.clone());
                    }
                }
            }

            ManualSelectionMsg::MoveTrackUp { final_index } => {
                // usize::MAX is sentinel for "use selection"
                let idx = if final_index == usize::MAX {
                    self.model.selected_final_track
                } else {
                    Some(final_index)
                };

                if let Some(idx) = idx {
                    if idx > 0 && idx < self.model.final_tracks.len() {
                        self.model.move_up(idx);
                        self.model.selected_final_track = Some(idx - 1);
                        self.refresh_list_from_root(root, sender.clone());
                    }
                }
            }

            ManualSelectionMsg::MoveTrackDown { final_index } => {
                // usize::MAX is sentinel for "use selection"
                let idx = if final_index == usize::MAX {
                    self.model.selected_final_track
                } else {
                    Some(final_index)
                };

                if let Some(idx) = idx {
                    if idx + 1 < self.model.final_tracks.len() {
                        self.model.move_down(idx);
                        self.model.selected_final_track = Some(idx + 1);
                        self.refresh_list_from_root(root, sender.clone());
                    }
                }
            }

            ManualSelectionMsg::ToggleTrackDefault { final_index } => {
                if final_index < self.model.final_tracks.len() {
                    self.model.toggle_default(final_index);
                    self.refresh_list_from_root(root, sender.clone());
                }
            }

            ManualSelectionMsg::ToggleTrackForced { final_index } => {
                if final_index < self.model.final_tracks.len() {
                    self.model.toggle_forced(final_index);
                    self.refresh_list_from_root(root, sender.clone());
                }
            }

            ManualSelectionMsg::ToggleKeepName { final_index } => {
                if let Some(track) = self.model.final_tracks.get_mut(final_index) {
                    track.data.apply_track_name = !track.data.apply_track_name;
                    track.refresh_badges();
                    self.refresh_list_from_root(root, sender.clone());
                }
            }

            ManualSelectionMsg::ToggleAttachmentSource { source_key } => {
                self.model.toggle_attachment_source(&source_key);
            }

            ManualSelectionMsg::FinalTrackSelected { final_index } => {
                self.model.selected_final_track = Some(final_index);
            }

            ManualSelectionMsg::Accept => {
                let layout = self.model.get_layout();
                let attachment_sources = self.model.attachment_sources.clone();

                let _ = sender.output(ManualSelectionOutput::LayoutConfigured {
                    layout,
                    attachment_sources,
                });
                root.close();
            }

            ManualSelectionMsg::Cancel => {
                let _ = sender.output(ManualSelectionOutput::Cancelled);
                root.close();
            }

            ManualSelectionMsg::AddExternalSubtitles => {
                self.open_external_subtitle_dialog(sender.clone(), root);
            }

            ManualSelectionMsg::ExternalSubtitlesSelected(paths) => {
                tracing::info!("Selected {} external subtitle files", paths.len());
            }

            ManualSelectionMsg::OpenTrackSettings { final_index } => {
                // usize::MAX is sentinel for "use selection"
                let idx = if final_index == usize::MAX {
                    self.model.selected_final_track
                } else {
                    Some(final_index)
                };

                if let Some(idx) = idx {
                    if idx < self.model.final_tracks.len() {
                        self.open_track_settings_dialog(idx, sender.clone(), root);
                    }
                }
            }

            ManualSelectionMsg::SetTrackCustomName { final_index, name } => {
                if let Some(track) = self.model.final_tracks.get_mut(final_index) {
                    track.data.custom_name = name;
                    track.refresh_badges();
                    self.refresh_list_from_root(root, sender.clone());
                }
            }

            ManualSelectionMsg::SetTrackCustomLang { final_index, lang } => {
                if let Some(track) = self.model.final_tracks.get_mut(final_index) {
                    track.data.custom_lang = lang;
                    track.refresh_badges();
                    self.refresh_list_from_root(root, sender.clone());
                }
            }

            _ => {
                // Other messages not yet implemented
            }
        }
    }
}

impl ManualSelectionWindow {
    /// Set up drop target for accepting tracks from source lists
    fn setup_drop_target(list_box: &gtk4::ListBox, sender: ComponentSender<Self>) {
        let drop_target = gtk4::DropTarget::new(glib::Type::STRING, gdk::DragAction::COPY);

        drop_target.connect_drop(move |_target, value, _x, _y| {
            if let Ok(data) = value.get::<String>() {
                // Parse "source_key:track_index"
                if let Some((source_key, idx_str)) = data.split_once(':') {
                    if let Ok(track_index) = idx_str.parse::<usize>() {
                        sender.input(ManualSelectionMsg::AddTrackToFinal {
                            source_key: source_key.to_string(),
                            track_index,
                        });
                        return true;
                    }
                }
            }
            false
        });

        // Visual feedback during drag over
        drop_target.connect_enter(|target, _x, _y| {
            if let Some(widget) = target.widget() {
                widget.add_css_class("drop-hover");
            }
            gdk::DragAction::COPY
        });

        drop_target.connect_leave(|target| {
            if let Some(widget) = target.widget() {
                widget.remove_css_class("drop-hover");
            }
        });

        list_box.add_controller(drop_target);
    }

    /// Set up selection handling for the final ListBox
    fn setup_list_selection(list_box: &gtk4::ListBox, sender: ComponentSender<Self>) {
        list_box.connect_row_selected(move |_, row| {
            if let Some(row) = row {
                let idx = row.index();
                if idx >= 0 {
                    sender.input(ManualSelectionMsg::FinalTrackSelected {
                        final_index: idx as usize,
                    });
                }
            }
        });
    }

    /// Create a custom 2-line track row widget
    fn create_track_row(
        index: usize,
        track: &model::FinalTrackEntry,
        sender: ComponentSender<Self>,
    ) -> gtk4::ListBoxRow {
        let row = gtk4::ListBoxRow::new();
        row.set_widget_name(&format!("track-{}", index));

        // Main container - vertical box for 2 lines
        let vbox = gtk4::Box::new(gtk4::Orientation::Vertical, 4);
        vbox.set_margin_all(8);

        // === Line 1: Track description + badges ===
        let line1 = gtk4::Box::new(gtk4::Orientation::Horizontal, 8);

        // Source + Track description (bold)
        let desc_text = format!("[{}] {}", track.data.source_key, track.info.summary());
        let desc_label = gtk4::Label::new(Some(&desc_text));
        desc_label.set_xalign(0.0);
        desc_label.set_hexpand(true);
        desc_label.set_ellipsize(gtk4::pango::EllipsizeMode::End);
        desc_label.add_css_class("heading");
        line1.append(&desc_label);

        // Badges (show when flags are set)
        let badge_text = track.badges.join(" | ");
        if !badge_text.is_empty() {
            let badge_label = gtk4::Label::new(Some(&badge_text));
            badge_label.add_css_class("accent");
            badge_label.set_markup(&format!(
                "<span color='#E0A800' weight='bold'>{}</span>",
                badge_text
            ));
            line1.append(&badge_label);
        }

        vbox.append(&line1);

        // === Line 2: Controls ===
        let line2 = gtk4::Box::new(gtk4::Orientation::Horizontal, 8);
        line2.set_halign(gtk4::Align::End);

        // Default checkbox
        let cb_default = gtk4::CheckButton::with_label("Default");
        cb_default.set_active(track.data.is_default);
        let sender_clone = sender.clone();
        cb_default.connect_toggled(move |_| {
            sender_clone.input(ManualSelectionMsg::ToggleTrackDefault { final_index: index });
        });
        line2.append(&cb_default);

        // Forced checkbox (only for subtitles)
        let cb_forced = gtk4::CheckButton::with_label("Forced");
        cb_forced.set_active(track.data.is_forced);
        let sender_clone = sender.clone();
        cb_forced.connect_toggled(move |_| {
            sender_clone.input(ManualSelectionMsg::ToggleTrackForced { final_index: index });
        });
        line2.append(&cb_forced);

        // Set Name checkbox
        let cb_name = gtk4::CheckButton::with_label("Set Name");
        cb_name.set_active(track.data.apply_track_name);
        let sender_clone = sender.clone();
        cb_name.connect_toggled(move |_| {
            sender_clone.input(ManualSelectionMsg::ToggleKeepName { final_index: index });
        });
        line2.append(&cb_name);

        // Settings button
        let settings_btn = gtk4::Button::with_label("Settings...");
        let sender_clone = sender.clone();
        settings_btn.connect_clicked(move |_| {
            sender_clone.input(ManualSelectionMsg::OpenTrackSettings { final_index: index });
        });
        line2.append(&settings_btn);

        vbox.append(&line2);
        row.set_child(Some(&vbox));

        row
    }

    /// Refresh the final list from root window
    fn refresh_list_from_root(&self, root: &gtk4::Window, sender: ComponentSender<Self>) {
        if let Some(list_box) = Self::find_widget_by_type::<gtk4::ListBox>(root) {
            Self::refresh_final_list(&list_box, &self.model, sender);
        }
    }

    /// Refresh the final output list with custom track widgets
    fn refresh_final_list(
        list_box: &gtk4::ListBox,
        model: &ManualSelectionModel,
        sender: ComponentSender<Self>,
    ) {
        // Clear existing rows
        while let Some(child) = list_box.first_child() {
            list_box.remove(&child);
        }

        // Add track rows
        for (i, track) in model.final_tracks.iter().enumerate() {
            let row = Self::create_track_row(i, track, sender.clone());
            list_box.append(&row);
        }
    }

    /// Populate source track boxes
    fn populate_source_tracks(
        source_box: &gtk4::Box,
        model: &ManualSelectionModel,
        sender: ComponentSender<Self>,
    ) {
        // Clear existing children
        while let Some(child) = source_box.first_child() {
            source_box.remove(&child);
        }

        for source_key in &model.available_sources {
            let tracks = match model.source_tracks.get(source_key) {
                Some(t) => t,
                None => continue,
            };

            // Get source path for title
            let path_name = model
                .get_source(source_key)
                .map(|s| {
                    s.path
                        .file_name()
                        .map(|n| n.to_string_lossy().to_string())
                        .unwrap_or_else(|| s.path.to_string_lossy().to_string())
                })
                .unwrap_or_else(|| "Unknown".to_string());

            let title = if source_key == "Source 1" {
                format!("{} (Reference) - '{}'", source_key, path_name)
            } else {
                format!("{} - '{}'", source_key, path_name)
            };

            // Create frame for this source
            let frame = gtk4::Frame::new(Some(&title));
            frame.set_margin_bottom(8);

            let list_box = gtk4::ListBox::new();
            list_box.set_selection_mode(gtk4::SelectionMode::Single);

            for (idx, track) in tracks.iter().enumerate() {
                let row = gtk4::ListBoxRow::new();

                let label = gtk4::Label::new(Some(&track.display()));
                label.set_xalign(0.0);
                label.set_margin_all(4);

                if track.is_blocked {
                    label.set_sensitive(false);
                    label.set_tooltip_text(track.blocked_reason.as_deref());
                } else {
                    label.set_tooltip_text(Some(&track.tooltip()));

                    // Add DragSource for non-blocked tracks
                    let drag_source = gtk4::DragSource::new();
                    drag_source.set_actions(gdk::DragAction::COPY);

                    // Set drag data: "source_key:track_index"
                    let drag_data = format!("{}:{}", source_key, idx);
                    drag_source.connect_prepare(move |_source, _x, _y| {
                        let provider = gdk::ContentProvider::for_value(&drag_data.to_value());
                        Some(provider)
                    });

                    // Visual feedback when drag starts
                    drag_source.connect_drag_begin(|source, _drag| {
                        if let Some(widget) = source.widget() {
                            widget.add_css_class("dragging");
                        }
                    });

                    drag_source.connect_drag_end(|source, _drag, _delete| {
                        if let Some(widget) = source.widget() {
                            widget.remove_css_class("dragging");
                        }
                    });

                    row.add_controller(drag_source);
                }

                row.set_child(Some(&label));
                list_box.append(&row);

                // Store track info in row for retrieval
                row.set_widget_name(&format!("{}:{}", source_key, idx));
            }

            // Connect double-click to add track
            let sender_clone = sender.clone();
            let source_key_clone = source_key.clone();
            list_box.connect_row_activated(move |_list, row| {
                let name = row.widget_name().to_string();
                if let Some((_, idx_str)) = name.split_once(':') {
                    if let Ok(idx) = idx_str.parse::<usize>() {
                        sender_clone.input(ManualSelectionMsg::SourceTrackDoubleClicked {
                            source_key: source_key_clone.clone(),
                            track_index: idx,
                        });
                    }
                }
            });

            frame.set_child(Some(&list_box));
            source_box.append(&frame);
        }
    }

    /// Populate attachment checkboxes
    fn populate_attachments(
        attachment_box: &gtk4::Box,
        model: &ManualSelectionModel,
        sender: ComponentSender<Self>,
    ) {
        for source_key in &model.available_sources {
            let check = gtk4::CheckButton::with_label(source_key);
            check.set_active(model.attachment_sources.contains(source_key));

            let source_key_clone = source_key.clone();
            let sender_clone = sender.clone();
            check.connect_toggled(move |_| {
                sender_clone.input(ManualSelectionMsg::ToggleAttachmentSource {
                    source_key: source_key_clone.clone(),
                });
            });

            attachment_box.append(&check);
        }
    }

    /// Find a widget of a specific type in the hierarchy
    fn find_widget_by_type<T: IsA<gtk4::Widget>>(root: &gtk4::Window) -> Option<T> {
        fn search<T: IsA<gtk4::Widget>>(widget: &gtk4::Widget) -> Option<T> {
            if let Some(typed) = widget.downcast_ref::<T>() {
                return Some(typed.clone());
            }

            // Search children
            let mut child = widget.first_child();
            while let Some(c) = child {
                if let Some(found) = search::<T>(&c) {
                    return Some(found);
                }
                child = c.next_sibling();
            }

            None
        }

        root.child().and_then(|c| search(&c))
    }

    /// Open external subtitle file dialog
    fn open_external_subtitle_dialog(&self, sender: ComponentSender<Self>, root: &gtk4::Window) {
        let dialog = gtk4::FileDialog::builder()
            .title("Select External Subtitle Files")
            .modal(true)
            .build();

        // Set file filter for subtitles
        let filter = gtk4::FileFilter::new();
        filter.set_name(Some("Subtitle Files"));
        filter.add_pattern("*.srt");
        filter.add_pattern("*.ass");
        filter.add_pattern("*.ssa");
        filter.add_pattern("*.sup");
        filter.add_pattern("*.sub");
        filter.add_pattern("*.idx");

        let filters = gio::ListStore::new::<gtk4::FileFilter>();
        filters.append(&filter);
        dialog.set_filters(Some(&filters));

        let root_clone = root.clone();
        glib::spawn_future_local(async move {
            match dialog.open_multiple_future(Some(&root_clone)).await {
                Ok(files) => {
                    let paths: Vec<PathBuf> = files
                        .iter()
                        .filter_map(|item| item.ok())
                        .filter_map(|file: gio::File| file.path())
                        .collect();

                    if !paths.is_empty() {
                        sender.input(ManualSelectionMsg::ExternalSubtitlesSelected(paths));
                    }
                }
                Err(_) => {}
            }
        });
    }

    /// Open track settings dialog for name and language
    fn open_track_settings_dialog(
        &self,
        final_index: usize,
        sender: ComponentSender<Self>,
        root: &gtk4::Window,
    ) {
        let track = match self.model.final_tracks.get(final_index) {
            Some(t) => t,
            None => return,
        };

        // Get current values
        let current_name = track.data.custom_name.clone().unwrap_or_default();
        let current_lang = track.data.custom_lang.clone();
        let original_lang = track.info.language.clone();

        // Create dialog
        let dialog = gtk4::Window::builder()
            .title("Track Settings")
            .transient_for(root)
            .modal(true)
            .default_width(400)
            .default_height(200)
            .build();

        // Main container
        let vbox = gtk4::Box::new(gtk4::Orientation::Vertical, 12);
        vbox.set_margin_all(16);

        // Track info label
        let info_label = gtk4::Label::new(Some(&format!("<b>{}</b>", track.info.summary())));
        info_label.set_use_markup(true);
        info_label.set_xalign(0.0);
        info_label.set_margin_bottom(8);
        vbox.append(&info_label);

        // Language section
        let lang_frame = gtk4::Frame::new(Some("Language"));
        let lang_box = gtk4::Box::new(gtk4::Orientation::Horizontal, 8);
        lang_box.set_margin_all(8);

        // Common ISO 639-2 language codes used by mkvmerge
        let languages: Vec<(&str, &str)> = vec![
            ("", "(Keep Original)"),
            ("und", "Undetermined"),
            ("eng", "English"),
            ("jpn", "Japanese"),
            ("spa", "Spanish"),
            ("fre", "French"),
            ("ger", "German"),
            ("ita", "Italian"),
            ("por", "Portuguese"),
            ("rus", "Russian"),
            ("chi", "Chinese"),
            ("kor", "Korean"),
            ("ara", "Arabic"),
            ("hin", "Hindi"),
            ("pol", "Polish"),
            ("dut", "Dutch"),
            ("swe", "Swedish"),
            ("nor", "Norwegian"),
            ("dan", "Danish"),
            ("fin", "Finnish"),
            ("tha", "Thai"),
            ("vie", "Vietnamese"),
            ("ind", "Indonesian"),
            ("may", "Malay"),
            ("tur", "Turkish"),
            ("gre", "Greek"),
            ("heb", "Hebrew"),
            ("cze", "Czech"),
            ("hun", "Hungarian"),
            ("rum", "Romanian"),
            ("ukr", "Ukrainian"),
        ];

        // Build display strings for dropdown
        let display_strings: Vec<String> = languages
            .iter()
            .map(|(code, name)| {
                if code.is_empty() {
                    if let Some(ref orig) = original_lang {
                        format!("{} (current: {})", name, orig)
                    } else {
                        name.to_string()
                    }
                } else {
                    format!("{} ({})", name, code)
                }
            })
            .collect();

        // Store language codes for lookup
        let lang_codes: Vec<String> = languages.iter().map(|(code, _)| code.to_string()).collect();
        let lang_codes_for_lookup = lang_codes.clone();

        // Create StringList model for DropDown
        let string_list = gtk4::StringList::new(
            &display_strings
                .iter()
                .map(|s| s.as_str())
                .collect::<Vec<_>>(),
        );
        let lang_dropdown = gtk4::DropDown::new(Some(string_list), gtk4::Expression::NONE);

        // Set active based on current custom_lang
        let selected_idx = match &current_lang {
            Some(lang) => {
                // Try to find matching language code
                lang_codes_for_lookup
                    .iter()
                    .position(|code| code == lang)
                    .unwrap_or(0) as u32
            }
            None => 0, // "Keep Original"
        };
        lang_dropdown.set_selected(selected_idx);

        lang_box.append(&lang_dropdown);
        lang_frame.set_child(Some(&lang_box));
        vbox.append(&lang_frame);

        // Custom name section
        let name_frame = gtk4::Frame::new(Some("Custom Track Name"));
        let name_box = gtk4::Box::new(gtk4::Orientation::Vertical, 4);
        name_box.set_margin_all(8);

        let name_entry = gtk4::Entry::new();
        name_entry.set_placeholder_text(Some("Leave empty to use original name"));
        name_entry.set_text(&current_name);

        name_box.append(&name_entry);
        name_frame.set_child(Some(&name_box));
        vbox.append(&name_frame);

        // Buttons
        let button_box = gtk4::Box::new(gtk4::Orientation::Horizontal, 8);
        button_box.set_halign(gtk4::Align::End);
        button_box.set_margin_top(12);

        let cancel_btn = gtk4::Button::with_label("Cancel");
        let ok_btn = gtk4::Button::with_label("OK");
        ok_btn.add_css_class("suggested-action");

        button_box.append(&cancel_btn);
        button_box.append(&ok_btn);
        vbox.append(&button_box);

        dialog.set_child(Some(&vbox));

        // Connect cancel button
        let dialog_weak = dialog.downgrade();
        cancel_btn.connect_clicked(move |_| {
            if let Some(d) = dialog_weak.upgrade() {
                d.close();
            }
        });

        // Connect OK button
        let dialog_weak = dialog.downgrade();
        let sender_clone = sender.clone();
        ok_btn.connect_clicked(move |_| {
            if let Some(d) = dialog_weak.upgrade() {
                // Get language selection from DropDown
                let selected_idx = lang_dropdown.selected() as usize;
                let lang = lang_codes
                    .get(selected_idx)
                    .filter(|s| !s.is_empty())
                    .cloned();

                // Get name
                let name = name_entry.text();
                let name = if name.is_empty() {
                    None
                } else {
                    Some(name.to_string())
                };

                // Send messages
                sender_clone.input(ManualSelectionMsg::SetTrackCustomLang { final_index, lang });
                sender_clone.input(ManualSelectionMsg::SetTrackCustomName { final_index, name });

                d.close();
            }
        });

        dialog.present();
    }
}
