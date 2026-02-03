//! File input component with drag-drop and paste support
//!
//! Supports:
//! - Text entry for path
//! - Browse button (via message to parent)
//! - Drag-drop from file managers (including Dolphin on Wayland)
//! - Ctrl+V paste from clipboard

use gtk4::gdk;
use gtk4::gio;
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
    /// Set text programmatically (from parent)
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
}

#[relm4::component(pub)]
impl Component for FileInput {
    type Init = FileInputInit;
    type Input = FileInputMsg;
    type Output = FileInputOutput;
    type CommandOutput = ();

    view! {
        #[root]
        #[name = "root_box"]
        gtk4::Box {
            set_orientation: gtk4::Orientation::Horizontal,
            set_spacing: 8,

            // Label
            gtk4::Label {
                set_label: &model.label,
                set_width_chars: 18,
                set_xalign: 0.0,
            },

            // Entry
            #[name = "entry"]
            gtk4::Entry {
                set_hexpand: true,
                #[watch]
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

        // Set up drag-drop on the ROOT BOX (not the entry - avoids conflicts)
        // Try both gio::File (single file) and gdk::FileList (multiple files)
        // Use ALL actions for maximum compatibility with different file managers
        let drop_target = gtk4::DropTarget::new(
            gio::File::static_type(),
            gdk::DragAction::COPY | gdk::DragAction::MOVE | gdk::DragAction::LINK,
        );

        // Also accept FileList
        drop_target.set_types(&[gio::File::static_type(), gdk::FileList::static_type()]);

        let sender_clone = sender.clone();
        drop_target.connect_drop(move |_target, value, _x, _y| {
            eprintln!("[DragDrop] Drop received! Value type: {:?}", value.type_());

            // Try gio::File first (single file from most file managers)
            if let Ok(file) = value.get::<gio::File>() {
                if let Some(path) = file.path() {
                    let path_str = path.to_string_lossy().to_string();
                    eprintln!("[DragDrop] Got gio::File path: {:?}", path_str);

                    let sender = sender_clone.clone();
                    gtk4::glib::idle_add_local_once(move || {
                        sender.input(FileInputMsg::FileDropped(path_str));
                    });
                    return true;
                }
            }

            // Try gdk::FileList (multiple files)
            if let Ok(file_list) = value.get::<gdk::FileList>() {
                let files = file_list.files();
                eprintln!("[DragDrop] Got FileList with {} files", files.len());
                if let Some(file) = files.first() {
                    if let Some(path) = file.path() {
                        let path_str = path.to_string_lossy().to_string();
                        eprintln!("[DragDrop] FileList path: {:?}", path_str);

                        let sender = sender_clone.clone();
                        gtk4::glib::idle_add_local_once(move || {
                            sender.input(FileInputMsg::FileDropped(path_str));
                        });
                        return true;
                    }
                }
            }

            eprintln!("[DragDrop] Could not extract file path from value");
            false
        });

        // Add to the root box, not the entry
        widgets.root_box.add_controller(drop_target);

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, _root: &Self::Root) {
        match msg {
            FileInputMsg::TextChanged(text) => {
                // Only emit if actually changed (avoid loops from #[watch] set_text)
                if text != self.path {
                    self.path = text.clone();
                    let _ = sender.output(FileInputOutput::PathChanged(text));
                }
            }
            FileInputMsg::BrowseClicked => {
                let _ = sender.output(FileInputOutput::BrowseRequested);
            }
            FileInputMsg::FileDropped(path) => {
                // Update model - #[watch] will update the Entry widget
                self.path = path.clone();
                let _ = sender.output(FileInputOutput::PathChanged(path));
            }
            FileInputMsg::SetText(text) => {
                // Set text programmatically (e.g., from browse result)
                if text != self.path {
                    self.path = text.clone();
                    let _ = sender.output(FileInputOutput::PathChanged(text));
                }
            }
        }
    }
}
