//! Manual selection window
//!
//! Allows users to configure track selection and layout for a job.
//! Features:
//! - Source track lists grouped by source file
//! - Final output list with drag-drop reordering
//! - Per-track configuration (default, forced, sync, etc.)
//! - Attachment source selection
//! - External subtitle import

// TreeView is deprecated in GTK 4.10 but we use it intentionally
#![allow(deprecated)]

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
                            set_min_content_width: 500,

                            #[name = "final_tree"]
                            gtk4::TreeView {
                                set_model: Some(&gtk4::ListStore::new(&[
                                    glib::Type::STRING, // Column 0: Type icon
                                    glib::Type::STRING, // Column 1: Track description
                                    glib::Type::BOOL,   // Column 2: Default checkbox
                                    glib::Type::BOOL,   // Column 3: Forced checkbox
                                    glib::Type::STRING, // Column 4: Source
                                    glib::Type::U32,    // Column 5: Original index (hidden)
                                ])),
                                set_headers_visible: true,
                                set_reorderable: true,
                                set_enable_search: false,
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
                                    // Will be handled via selection
                                    sender.input(ManualSelectionMsg::MoveTrackUp { final_index: 0 });
                                },
                            },

                            gtk4::Button {
                                set_icon_name: "go-down-symbolic",
                                set_tooltip_text: Some("Move selected track down"),
                                connect_clicked[sender] => move |_| {
                                    sender.input(ManualSelectionMsg::MoveTrackDown { final_index: 0 });
                                },
                            },

                            gtk4::Separator {
                                set_orientation: gtk4::Orientation::Vertical,
                            },

                            gtk4::Button {
                                set_icon_name: "list-remove-symbolic",
                                set_tooltip_text: Some("Remove selected track"),
                                connect_clicked[sender] => move |_| {
                                    sender.input(ManualSelectionMsg::RemoveTrackFromFinal { final_index: 0 });
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

        // Set up the final list columns (with sender for toggle callbacks)
        Self::setup_final_tree(&widgets.final_tree, sender.clone());

        // Set up drop target for final tree
        Self::setup_drop_target(&widgets.final_tree, sender.clone());

        // Set up selection handling for final tree
        Self::setup_selection_handling(&widgets.final_tree, sender.clone());

        // Set up right-click context menu for final tree
        Self::setup_context_menu(&widgets.final_tree, sender.clone());

        // Populate source track boxes
        Self::populate_source_tracks(&widgets.source_box, &model.model, sender.clone());

        // Populate attachment checkboxes
        Self::populate_attachments(&widgets.attachment_box, &model.model, sender.clone());

        // Refresh final list
        Self::refresh_final_list(&widgets.final_tree, &model.model);

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
                self.refresh_final_tree(root);
            }

            ManualSelectionMsg::RemoveTrackFromFinal { final_index } => {
                // Use provided index from context menu, or fall back to selected
                let idx = if final_index > 0 || self.model.selected_final_track.is_none() {
                    final_index
                } else {
                    self.model.selected_final_track.unwrap_or(0)
                };

                if idx < self.model.final_tracks.len() {
                    self.model.remove_from_final(idx);
                    self.model.selected_final_track = None;
                    self.refresh_final_tree(root);
                }
            }

            ManualSelectionMsg::MoveTrackUp { final_index } => {
                // Use provided index from context menu, or fall back to selected
                let idx = if final_index > 0 || self.model.selected_final_track.is_none() {
                    final_index
                } else {
                    self.model.selected_final_track.unwrap_or(0)
                };

                if idx > 0 && idx < self.model.final_tracks.len() {
                    self.model.move_up(idx);
                    self.model.selected_final_track = Some(idx - 1);
                    self.refresh_final_tree(root);
                }
            }

            ManualSelectionMsg::MoveTrackDown { final_index } => {
                // Use provided index from context menu, or fall back to selected
                let idx = if final_index > 0 || self.model.selected_final_track.is_none() {
                    final_index
                } else {
                    self.model.selected_final_track.unwrap_or(0)
                };

                if idx + 1 < self.model.final_tracks.len() {
                    self.model.move_down(idx);
                    self.model.selected_final_track = Some(idx + 1);
                    self.refresh_final_tree(root);
                }
            }

            ManualSelectionMsg::ToggleTrackDefault { final_index } => {
                self.model.toggle_default(final_index);
                self.refresh_final_tree(root);
            }

            ManualSelectionMsg::ToggleTrackForced { final_index } => {
                self.model.toggle_forced(final_index);
                self.refresh_final_tree(root);
            }

            ManualSelectionMsg::ToggleAttachmentSource { source_key } => {
                self.model.toggle_attachment_source(&source_key);
            }

            ManualSelectionMsg::FinalTrackSelected { final_index } => {
                self.model.selected_final_track = Some(final_index);
            }

            ManualSelectionMsg::Accept => {
                // Sync order from TreeView in case user used drag-reordering
                self.sync_order_from_tree(root);

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

            // Handle other messages...
            ManualSelectionMsg::AddExternalSubtitles => {
                // Open file chooser for external subtitles
                self.open_external_subtitle_dialog(sender.clone(), root);
            }

            ManualSelectionMsg::ExternalSubtitlesSelected(paths) => {
                // TODO: Process external subtitle files
                tracing::info!("Selected {} external subtitle files", paths.len());
            }

            ManualSelectionMsg::OpenTrackSettings { final_index } => {
                if final_index < self.model.final_tracks.len() {
                    self.open_track_settings_dialog(final_index, sender.clone(), root);
                }
            }

            ManualSelectionMsg::SetTrackCustomName { final_index, name } => {
                if let Some(track) = self.model.final_tracks.get_mut(final_index) {
                    track.data.custom_name = name;
                    track.refresh_badges();
                    self.refresh_final_tree(root);
                }
            }

            ManualSelectionMsg::SetTrackCustomLang { final_index, lang } => {
                if let Some(track) = self.model.final_tracks.get_mut(final_index) {
                    track.data.custom_lang = lang;
                    track.refresh_badges();
                    self.refresh_final_tree(root);
                }
            }

            _ => {
                // Other messages not yet implemented
            }
        }
    }
}

impl ManualSelectionWindow {
    /// Set up the final output TreeView columns
    fn setup_final_tree(tree: &gtk4::TreeView, sender: ComponentSender<Self>) {
        // Column 0: Type icon
        let renderer0 = gtk4::CellRendererText::new();
        let column0 = gtk4::TreeViewColumn::new();
        column0.set_title("");
        column0.set_min_width(30);
        column0.pack_start(&renderer0, false);
        column0.add_attribute(&renderer0, "text", 0);
        tree.append_column(&column0);

        // Column 1: Track description
        let renderer1 = gtk4::CellRendererText::new();
        let column1 = gtk4::TreeViewColumn::new();
        column1.set_title("Track");
        column1.set_expand(true);
        column1.set_resizable(true);
        column1.pack_start(&renderer1, true);
        column1.add_attribute(&renderer1, "text", 1);
        tree.append_column(&column1);

        // Column 2: Default checkbox
        let renderer2 = gtk4::CellRendererToggle::new();
        renderer2.set_activatable(true);
        let column2 = gtk4::TreeViewColumn::new();
        column2.set_title("Default");
        column2.set_min_width(60);
        column2.pack_start(&renderer2, false);
        column2.add_attribute(&renderer2, "active", 2);

        // Connect toggle signal for Default
        let sender_clone = sender.clone();
        let tree_weak = tree.downgrade();
        renderer2.connect_toggled(move |_renderer, path| {
            if let Some(tree) = tree_weak.upgrade() {
                if let Some(model) = tree.model() {
                    if let Some(store) = model.downcast_ref::<gtk4::ListStore>() {
                        if let Some(iter) = store.iter(&path) {
                            // Get the original index from column 5
                            let idx: u32 = store.get(&iter, 5);
                            sender_clone.input(ManualSelectionMsg::ToggleTrackDefault {
                                final_index: idx as usize,
                            });
                        }
                    }
                }
            }
        });
        tree.append_column(&column2);

        // Column 3: Forced checkbox
        let renderer3 = gtk4::CellRendererToggle::new();
        renderer3.set_activatable(true);
        let column3 = gtk4::TreeViewColumn::new();
        column3.set_title("Forced");
        column3.set_min_width(60);
        column3.pack_start(&renderer3, false);
        column3.add_attribute(&renderer3, "active", 3);

        // Connect toggle signal for Forced
        let sender_clone = sender.clone();
        let tree_weak = tree.downgrade();
        renderer3.connect_toggled(move |_renderer, path| {
            if let Some(tree) = tree_weak.upgrade() {
                if let Some(model) = tree.model() {
                    if let Some(store) = model.downcast_ref::<gtk4::ListStore>() {
                        if let Some(iter) = store.iter(&path) {
                            // Get the original index from column 5
                            let idx: u32 = store.get(&iter, 5);
                            sender_clone.input(ManualSelectionMsg::ToggleTrackForced {
                                final_index: idx as usize,
                            });
                        }
                    }
                }
            }
        });
        tree.append_column(&column3);

        // Column 4: Source
        let renderer4 = gtk4::CellRendererText::new();
        let column4 = gtk4::TreeViewColumn::new();
        column4.set_title("Source");
        column4.set_min_width(80);
        column4.pack_start(&renderer4, false);
        column4.add_attribute(&renderer4, "text", 4);
        tree.append_column(&column4);
    }

    /// Set up drop target for accepting tracks from source lists
    fn setup_drop_target(tree: &gtk4::TreeView, sender: ComponentSender<Self>) {
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

        tree.add_controller(drop_target);
    }

    /// Set up selection handling for the final TreeView
    fn setup_selection_handling(tree: &gtk4::TreeView, sender: ComponentSender<Self>) {
        let selection = tree.selection();
        selection.set_mode(gtk4::SelectionMode::Single);

        selection.connect_changed(move |selection| {
            if let Some((model, iter)) = selection.selected() {
                // Get the row index from path - path() returns TreePath directly
                let path = model.path(&iter);
                let indices = path.indices();
                if !indices.is_empty() {
                    let idx = indices[0];
                    sender.input(ManualSelectionMsg::FinalTrackSelected {
                        final_index: idx as usize,
                    });
                }
            }
        });
    }

    /// Set up right-click context menu for final TreeView
    fn setup_context_menu(tree: &gtk4::TreeView, sender: ComponentSender<Self>) {
        // Use GestureClick for right-click detection
        let gesture = gtk4::GestureClick::new();
        gesture.set_button(3); // Right mouse button

        let tree_weak = tree.downgrade();
        let sender_clone = sender.clone();

        gesture.connect_pressed(move |gesture, _n_press, x, y| {
            let Some(tree) = tree_weak.upgrade() else {
                return;
            };

            // Get path at click position
            if let Some((Some(path), _, _, _)) = tree.path_at_pos(x as i32, y as i32) {
                // Select the row
                tree.selection().select_path(&path);

                // indices() returns Slice<i32> directly
                let indices = path.indices();
                if !indices.is_empty() {
                    let idx = indices[0];
                    // Create and show popover menu
                    let menu = Self::create_track_context_menu(idx as usize, sender_clone.clone());
                    let rect = gdk::Rectangle::new(x as i32, y as i32, 1, 1);
                    menu.set_pointing_to(Some(&rect));
                    menu.set_parent(&tree);
                    menu.popup();
                }
            }

            gesture.set_state(gtk4::EventSequenceState::Claimed);
        });

        tree.add_controller(gesture);
    }

    /// Create context menu for a track
    fn create_track_context_menu(index: usize, sender: ComponentSender<Self>) -> gtk4::PopoverMenu {
        let menu_model = gio::Menu::new();

        // Settings section
        let settings_section = gio::Menu::new();
        settings_section.append(
            Some("Track Settings..."),
            Some(&format!("track.settings.{}", index)),
        );
        menu_model.append_section(None, &settings_section);

        // Movement section
        let move_section = gio::Menu::new();
        move_section.append(Some("Move Up"), Some(&format!("track.move-up.{}", index)));
        move_section.append(
            Some("Move Down"),
            Some(&format!("track.move-down.{}", index)),
        );
        menu_model.append_section(None, &move_section);

        // Delete section
        let delete_section = gio::Menu::new();
        delete_section.append(Some("Remove"), Some(&format!("track.remove.{}", index)));
        menu_model.append_section(None, &delete_section);

        let popover = gtk4::PopoverMenu::from_model(Some(&menu_model));
        popover.set_has_arrow(false);

        // Connect actions
        let action_group = gio::SimpleActionGroup::new();

        // Settings action
        let settings_action = gio::SimpleAction::new(&format!("settings.{}", index), None);
        let sender_clone = sender.clone();
        settings_action.connect_activate(move |_, _| {
            sender_clone.input(ManualSelectionMsg::OpenTrackSettings { final_index: index });
        });
        action_group.add_action(&settings_action);

        // Move up action
        let move_up_action = gio::SimpleAction::new(&format!("move-up.{}", index), None);
        let sender_clone = sender.clone();
        move_up_action.connect_activate(move |_, _| {
            sender_clone.input(ManualSelectionMsg::MoveTrackUp { final_index: index });
        });
        action_group.add_action(&move_up_action);

        // Move down action
        let move_down_action = gio::SimpleAction::new(&format!("move-down.{}", index), None);
        let sender_clone = sender.clone();
        move_down_action.connect_activate(move |_, _| {
            sender_clone.input(ManualSelectionMsg::MoveTrackDown { final_index: index });
        });
        action_group.add_action(&move_down_action);

        // Remove action
        let remove_action = gio::SimpleAction::new(&format!("remove.{}", index), None);
        let sender_clone = sender.clone();
        remove_action.connect_activate(move |_, _| {
            sender_clone.input(ManualSelectionMsg::RemoveTrackFromFinal { final_index: index });
        });
        action_group.add_action(&remove_action);

        popover.insert_action_group("track", Some(&action_group));

        popover
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

    /// Refresh the final output list
    fn refresh_final_list(tree: &gtk4::TreeView, model: &ManualSelectionModel) {
        let store = gtk4::ListStore::new(&[
            glib::Type::STRING, // 0: Type icon
            glib::Type::STRING, // 1: Track description
            glib::Type::BOOL,   // 2: Default checkbox
            glib::Type::BOOL,   // 3: Forced checkbox
            glib::Type::STRING, // 4: Source
            glib::Type::U32,    // 5: Hidden original index
        ]);

        for (i, track) in model.final_tracks.iter().enumerate() {
            let icon = logic::track_type_icon(track.data.track_type);
            let desc = track.info.summary();
            let is_default = track.data.is_default;
            let is_forced = track.data.is_forced;
            let source = track.data.source_key.clone();

            let iter = store.append();
            store.set(
                &iter,
                &[
                    (0, &icon),
                    (1, &desc),
                    (2, &is_default),
                    (3, &is_forced),
                    (4, &source),
                    (5, &(i as u32)), // Store original index
                ],
            );
        }

        tree.set_model(Some(&store));
    }

    /// Sync the order from TreeView back to model (after drag reordering)
    fn sync_order_from_tree(&mut self, root: &gtk4::Window) {
        let Some(tree) = Self::find_widget_by_type::<gtk4::TreeView>(root) else {
            return;
        };

        let Some(model) = tree.model() else {
            return;
        };

        // Read the current order of original indices from the TreeView
        // Column 5 contains the original index
        let mut new_order: Vec<usize> = Vec::new();
        let mut iter = model.iter_first();
        while let Some(it) = iter {
            if let Ok(idx) = model.get::<u32>(&it, 5).try_into() {
                new_order.push(idx);
            }
            iter = if model.iter_next(&it) { Some(it) } else { None };
        }

        // Only reorder if something changed
        if new_order.len() != self.model.final_tracks.len() {
            return;
        }

        // Check if order actually changed
        let is_same = new_order.iter().enumerate().all(|(i, &v)| v == i);
        if is_same {
            return;
        }

        // Reorder the model's final_tracks based on new order
        let old_tracks = std::mem::take(&mut self.model.final_tracks);
        for &idx in &new_order {
            if idx < old_tracks.len() {
                self.model.final_tracks.push(old_tracks[idx].clone());
            }
        }

        // Update user_order_index
        for (i, track) in self.model.final_tracks.iter_mut().enumerate() {
            track.data.user_order_index = i;
        }
    }

    /// Refresh the final tree from model data
    fn refresh_final_tree(&self, root: &gtk4::Window) {
        // Find the final tree in the widget hierarchy
        if let Some(tree) = Self::find_widget_by_type::<gtk4::TreeView>(root) {
            Self::refresh_final_list(&tree, &self.model);
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

        let lang_combo = gtk4::ComboBoxText::new();

        // Common ISO 639-2 language codes used by mkvmerge
        let languages = [
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

        for (code, name) in &languages {
            let display = if code.is_empty() {
                if let Some(ref orig) = original_lang {
                    format!("{} (current: {})", name, orig)
                } else {
                    name.to_string()
                }
            } else {
                format!("{} ({})", name, code)
            };
            lang_combo.append(Some(code), &display);
        }

        // Set active based on current custom_lang
        match &current_lang {
            Some(lang) => {
                // Try to find matching language code
                let found = languages.iter().position(|(code, _)| code == lang);
                if let Some(idx) = found {
                    lang_combo.set_active(Some(idx as u32));
                } else {
                    lang_combo.set_active(Some(0)); // Default to "Keep Original"
                }
            }
            None => {
                lang_combo.set_active(Some(0)); // "Keep Original"
            }
        }

        lang_box.append(&lang_combo);
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
                // Get language selection
                let lang = lang_combo
                    .active_id()
                    .map(|s| s.to_string())
                    .filter(|s| !s.is_empty());

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
