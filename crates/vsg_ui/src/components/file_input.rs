//! File input component with drag-drop and paste support
//!
//! Supports:
//! - Text entry for path
//! - Browse button (via message to parent)
//! - Drag-drop from file managers (including Dolphin on Wayland)
//! - Ctrl+V paste from clipboard

use gtk4::gdk;
use gtk4::prelude::*;
use relm4::prelude::*;

/// Input message for FileInput component
#[derive(Debug)]
pub enum FileInputMsg {
    /// User typed in the entry
    TextChanged(String),
    /// User clicked browse button
    BrowseClicked,
    /// File was dropped onto the entry
    FileDropped(String),
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
}

#[relm4::component(pub)]
impl Component for FileInput {
    type Init = FileInputInit;
    type Input = FileInputMsg;
    type Output = FileInputOutput;
    type CommandOutput = ();

    view! {
        gtk4::Box {
            set_orientation: gtk4::Orientation::Horizontal,
            set_spacing: 8,

            // Label
            gtk4::Label {
                set_label: &model.label,
                set_width_chars: 18,
                set_xalign: 0.0,
            },

            // Entry with drag-drop support
            #[name = "entry"]
            gtk4::Entry {
                set_hexpand: true,
                set_text: &model.path,
                set_placeholder_text: Some("Enter path or drag file here..."),

                // Text changed signal
                connect_changed[sender] => move |entry| {
                    sender.input(FileInputMsg::TextChanged(entry.text().to_string()));
                },
            },

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
        let model = FileInput {
            path: init.initial_path,
            label: init.label,
        };

        let widgets = view_output!();

        // Set up drag-drop on the entry
        // IMPORTANT: Use ACTION_MOVE for Dolphin/Qt compatibility on Wayland
        let drop_target = gtk4::DropTarget::new(
            gdk::FileList::static_type(),
            gdk::DragAction::COPY | gdk::DragAction::MOVE,
        );

        let sender_clone = sender.clone();
        drop_target.connect_drop(move |_target, value, _x, _y| {
            if let Ok(file_list) = value.get::<gdk::FileList>() {
                let files = file_list.files();
                if let Some(file) = files.first() {
                    if let Some(path) = file.path() {
                        sender_clone.input(FileInputMsg::FileDropped(
                            path.to_string_lossy().to_string(),
                        ));
                        return true;
                    }
                }
            }
            false
        });

        widgets.entry.add_controller(drop_target);

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, _root: &Self::Root) {
        match msg {
            FileInputMsg::TextChanged(text) => {
                // Only emit if actually changed (avoid loops)
                if text != self.path {
                    self.path = text.clone();
                    let _ = sender.output(FileInputOutput::PathChanged(text));
                }
            }
            FileInputMsg::BrowseClicked => {
                let _ = sender.output(FileInputOutput::BrowseRequested);
            }
            FileInputMsg::FileDropped(path) => {
                self.path = path.clone();
                let _ = sender.output(FileInputOutput::PathChanged(path));
            }
        }
    }
}
