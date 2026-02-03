//! File input component with drag-drop and paste support
//!
//! Supports:
//! - Text entry for path
//! - Browse button (via message to parent)
//! - Drag-drop from file managers (including Dolphin on Wayland)

use gtk4::gdk;
use gtk4::gio;
use gtk4::prelude::*;
use relm4::prelude::*;

/// Input message for FileInput component
#[derive(Debug)]
pub enum FileInputMsg {
    /// User typed in the entry (from connect_changed)
    TextChanged(String),
    /// User clicked browse button
    BrowseClicked,
    /// File was dropped onto the widget
    FileDropped(String),
    /// Set text programmatically (from parent, e.g., browse result)
    SetText(String),
}

/// Output message sent to parent
#[derive(Debug)]
pub enum FileInputOutput {
    /// Path changed (from typing, drop, or paste)
    PathChanged(String),
    /// Browse button was clicked
    BrowseRequested,
}

/// Initialization parameters
pub struct FileInputInit {
    /// Label text (e.g., "Source 1 (Reference):")
    pub label: String,
    /// Initial path value
    pub initial_path: String,
}

/// File input component model
pub struct FileInput {
    path: String,
    label: String,
    /// Flag to prevent feedback loop when we programmatically set text
    updating_entry: bool,
    /// Reference to entry widget for manual updates
    entry: gtk4::Entry,
}

#[relm4::component(pub)]
impl Component for FileInput {
    type Init = FileInputInit;
    type Input = FileInputMsg;
    type Output = FileInputOutput;
    type CommandOutput = ();

    view! {
        #[root]
        gtk4::Box {
            set_orientation: gtk4::Orientation::Horizontal,
            set_spacing: 8,

            // Label
            gtk4::Label {
                set_label: &model.label,
                set_width_chars: 18,
                set_xalign: 0.0,
            },

            // Entry - NO #[watch] to avoid feedback loops
            model.entry.clone() {},

            // Browse button
            gtk4::Button {
                set_label: "Browse…",
                connect_clicked => FileInputMsg::BrowseClicked,
            },
        }
    }

    fn init(
        init: Self::Init,
        root: Self::Root,
        sender: ComponentSender<Self>,
    ) -> ComponentParts<Self> {
        // Create entry widget manually so we can store reference
        let entry = gtk4::Entry::builder()
            .hexpand(true)
            .placeholder_text("Enter path or drag file here...")
            .build();

        // Set initial text
        if !init.initial_path.is_empty() {
            entry.set_text(&init.initial_path);
        }

        // Connect changed signal
        let sender_clone = sender.clone();
        entry.connect_changed(move |e| {
            sender_clone.input(FileInputMsg::TextChanged(e.text().to_string()));
        });

        let model = FileInput {
            path: init.initial_path,
            label: init.label,
            updating_entry: false,
            entry: entry.clone(),
        };

        let widgets = view_output!();

        // Set up drag-drop on the ROOT widget
        let drop_target = gtk4::DropTarget::new(
            gio::File::static_type(),
            gdk::DragAction::COPY | gdk::DragAction::MOVE | gdk::DragAction::LINK,
        );
        drop_target.set_types(&[gio::File::static_type(), gdk::FileList::static_type()]);

        let sender_for_drop = sender.clone();
        drop_target.connect_drop(move |_target, value, _x, _y| {
            eprintln!("[DragDrop] Drop received! Value type: {:?}", value.type_());

            let path_str = if let Ok(file) = value.get::<gio::File>() {
                file.path().map(|p| p.to_string_lossy().to_string())
            } else if let Ok(file_list) = value.get::<gdk::FileList>() {
                file_list
                    .files()
                    .first()
                    .and_then(|f| f.path())
                    .map(|p| p.to_string_lossy().to_string())
            } else {
                None
            };

            if let Some(path) = path_str {
                eprintln!("[DragDrop] File path: {:?}", path);
                let sender = sender_for_drop.clone();
                relm4::spawn_local(async move {
                    sender.input(FileInputMsg::FileDropped(path));
                });
                return true;
            }

            eprintln!("[DragDrop] Could not extract file path");
            false
        });

        root.add_controller(drop_target);

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, _root: &Self::Root) {
        match msg {
            FileInputMsg::TextChanged(text) => {
                // Ignore if we're the ones who set the text (prevents loop)
                if self.updating_entry {
                    return;
                }
                if text != self.path {
                    self.path = text.clone();
                    let _ = sender.output(FileInputOutput::PathChanged(text));
                }
            }
            FileInputMsg::BrowseClicked => {
                let _ = sender.output(FileInputOutput::BrowseRequested);
            }
            FileInputMsg::FileDropped(path) => {
                eprintln!("[FileInput] FileDropped handler: {:?}", path);
                if path != self.path {
                    self.path = path.clone();
                    // Set flag, update entry, clear flag
                    self.updating_entry = true;
                    self.entry.set_text(&path);
                    self.updating_entry = false;
                    eprintln!("[FileInput] Entry updated, emitting PathChanged");
                    let _ = sender.output(FileInputOutput::PathChanged(path));
                }
            }
            FileInputMsg::SetText(text) => {
                if text != self.path {
                    self.path = text.clone();
                    self.updating_entry = true;
                    self.entry.set_text(&text);
                    self.updating_entry = false;
                    let _ = sender.output(FileInputOutput::PathChanged(text));
                }
            }
        }
    }
}
