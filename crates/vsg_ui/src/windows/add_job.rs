//! Add job dialog component.
//!
//! Dialog for adding new jobs to the queue by specifying source files.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use gtk::glib;
use gtk::prelude::*;
use libadwaita::prelude::*;
use relm4::prelude::*;
use relm4::{Component, ComponentParts, ComponentSender};

use vsg_core::jobs::JobQueue;
use vsg_core::jobs::JobQueueEntry;

/// Output messages from the add job dialog.
#[derive(Debug)]
pub enum AddJobOutput {
    JobsAdded(usize),
    Cancelled,
}

/// Input messages for the add job dialog.
#[derive(Debug)]
pub enum AddJobMsg {
    // Source management
    SourceChanged(usize, String),
    BrowseSource(usize),
    FileSelected(usize, Option<PathBuf>),
    AddSource,
    RemoveSource(usize),

    // Actions
    FindAndAddJobs,
    JobsDiscovered(usize),
    DiscoveryFailed(String),

    // Dialog
    Cancel,
}

/// Add job dialog state.
pub struct AddJobDialog {
    job_queue: Arc<Mutex<JobQueue>>,
    sources: Vec<String>,
    error_text: String,
    is_finding: bool,
    sources_box: Option<gtk::Box>,
}

#[relm4::component(pub)]
impl Component for AddJobDialog {
    type Init = Arc<Mutex<JobQueue>>;
    type Input = AddJobMsg;
    type Output = AddJobOutput;
    type CommandOutput = ();

    view! {
        adw::Window {
            set_title: Some("Add Jobs"),
            set_default_width: 600,
            set_default_height: 400,
            set_modal: true,

            #[wrap(Some)]
            set_content = &gtk::Box {
                set_orientation: gtk::Orientation::Vertical,

                adw::HeaderBar {
                    #[wrap(Some)]
                    set_title_widget = &gtk::Label {
                        set_label: "Add Jobs",
                    },
                },

                gtk::Box {
                    set_orientation: gtk::Orientation::Vertical,
                    set_spacing: 12,
                    set_margin_all: 16,
                    set_vexpand: true,

                    gtk::Label {
                        set_label: "Specify source files. Source 1 is the reference (video track source).",
                        set_xalign: 0.0,
                        set_wrap: true,
                    },

                    // Source list
                    gtk::ScrolledWindow {
                        set_vexpand: true,
                        set_hexpand: true,

                        #[name = "sources_box"]
                        gtk::Box {
                            set_orientation: gtk::Orientation::Vertical,
                            set_spacing: 8,
                        },
                    },

                    // Add source button
                    gtk::Box {
                        set_orientation: gtk::Orientation::Horizontal,

                        #[name = "add_source_btn"]
                        gtk::Button {
                            set_label: "Add Another Source",
                        },
                    },

                    // Error text
                    gtk::Label {
                        #[watch]
                        set_label: &model.error_text,
                        #[watch]
                        set_visible: !model.error_text.is_empty(),
                        set_xalign: 0.0,
                        add_css_class: "error",
                    },

                    // Dialog buttons
                    gtk::Box {
                        set_orientation: gtk::Orientation::Horizontal,
                        set_spacing: 8,
                        set_halign: gtk::Align::End,

                        #[name = "find_btn"]
                        gtk::Button {
                            #[watch]
                            set_label: if model.is_finding { "Finding..." } else { "Find & Add Jobs" },
                            #[watch]
                            set_sensitive: !model.is_finding,
                            add_css_class: "suggested-action",
                        },

                        #[name = "cancel_btn"]
                        gtk::Button {
                            set_label: "Cancel",
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
        let mut model = AddJobDialog {
            job_queue: init,
            // Initialize with 3 sources (Source 1, Source 2, Source 3)
            sources: vec![String::new(), String::new(), String::new()],
            error_text: String::new(),
            is_finding: false,
            sources_box: None,
        };

        let widgets = view_output!();

        // Store reference to sources_box for later rebuilds
        model.sources_box = Some(widgets.sources_box.clone());

        // Build initial source rows
        Self::rebuild_sources(&model, &widgets.sources_box, &sender);

        // Manually connect ALL buttons to avoid panic if component is destroyed
        // Using input_sender.send() which returns Result instead of panicking

        // Add Another Source button
        let sender_clone = sender.clone();
        widgets.add_source_btn.connect_clicked(move |_| {
            eprintln!("[AddJob] Add Source button clicked");
            sender_clone.input(AddJobMsg::AddSource);
        });

        // Find & Add Jobs button
        let sender_clone = sender.clone();
        widgets.find_btn.connect_clicked(move |_| {
            eprintln!("[AddJob] Find & Add Jobs button clicked");
            sender_clone.input(AddJobMsg::FindAndAddJobs);
        });

        // Cancel button - defer output to avoid panic when component is destroyed in handler
        let output_sender = sender.output_sender().clone();
        let root_clone = root.clone();
        widgets.cancel_btn.connect_clicked(move |_| {
            eprintln!("[AddJob] Cancel button clicked");
            root_clone.close();
            let sender = output_sender.clone();
            glib::idle_add_local_once(move || {
                let _ = sender.send(AddJobOutput::Cancelled);
            });
        });

        // Window close button
        let output_sender = sender.output_sender().clone();
        root.connect_close_request(move |_| {
            let sender = output_sender.clone();
            glib::idle_add_local_once(move || {
                let _ = sender.send(AddJobOutput::Cancelled);
            });
            glib::Propagation::Proceed
        });

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, root: &Self::Root) {
        match msg {
            AddJobMsg::SourceChanged(idx, path) => {
                if idx < self.sources.len() {
                    self.sources[idx] = path;
                }
            }

            AddJobMsg::BrowseSource(idx) => {
                let input_sender = sender.input_sender().clone();
                let root = root.clone();
                relm4::spawn_local(async move {
                    let dialog = gtk::FileDialog::builder()
                        .title("Select Source File")
                        .modal(true)
                        .build();

                    if let Ok(file) = dialog.open_future(Some(&root)).await {
                        // Use send() which returns Result instead of panicking
                        let _ = input_sender.send(AddJobMsg::FileSelected(idx, file.path()));
                    }
                });
            }

            AddJobMsg::FileSelected(idx, path) => {
                if let Some(p) = path {
                    if idx < self.sources.len() {
                        self.sources[idx] = p.to_string_lossy().to_string();
                        // Rebuild to update entry text
                        if let Some(ref sources_box) = self.sources_box {
                            Self::rebuild_sources(self, sources_box, &sender);
                        }
                    }
                }
            }

            AddJobMsg::AddSource => {
                if self.sources.len() < 10 {
                    self.sources.push(String::new());
                    if let Some(ref sources_box) = self.sources_box {
                        Self::rebuild_sources(self, sources_box, &sender);
                    }
                }
            }

            AddJobMsg::RemoveSource(idx) => {
                if self.sources.len() > 2 && idx < self.sources.len() {
                    self.sources.remove(idx);
                    if let Some(ref sources_box) = self.sources_box {
                        Self::rebuild_sources(self, sources_box, &sender);
                    }
                }
            }

            AddJobMsg::FindAndAddJobs => {
                self.error_text.clear();

                // Validate that at least 2 sources are specified
                let valid_sources: Vec<&String> =
                    self.sources.iter().filter(|s| !s.is_empty()).collect();

                if valid_sources.len() < 2 {
                    self.error_text = "At least 2 source files are required.".to_string();
                    return;
                }

                self.is_finding = true;

                // Get input sender for async use (won't panic if component is destroyed)
                let input_sender = sender.input_sender().clone();
                let sources = self.sources.clone();
                let job_queue = self.job_queue.clone();

                relm4::spawn_local(async move {
                    // Simulate discovery
                    tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;

                    // Create a job from the sources
                    let valid: Vec<PathBuf> = sources
                        .iter()
                        .filter(|s| !s.is_empty())
                        .map(PathBuf::from)
                        .collect();

                    if !valid.is_empty() {
                        let mut queue = job_queue.lock().unwrap();
                        // Create a basic job entry
                        let name = valid
                            .first()
                            .and_then(|p| p.file_stem())
                            .map(|s| s.to_string_lossy().to_string())
                            .unwrap_or_else(|| "New Job".to_string());

                        let mut sources_map = std::collections::HashMap::new();
                        for (i, path) in valid.iter().enumerate() {
                            sources_map.insert(vsg_core::models::SourceIndex::new(i + 1), path.clone());
                        }

                        // Generate a unique ID for the job
                        let id = uuid::Uuid::new_v4().to_string();
                        let entry = JobQueueEntry::new(id, name, sources_map);
                        queue.add(entry);
                        // Use send() which returns Result instead of panicking
                        let _ = input_sender.send(AddJobMsg::JobsDiscovered(1));
                    } else {
                        let _ = input_sender.send(AddJobMsg::DiscoveryFailed(
                            "No valid source files.".to_string(),
                        ));
                    }
                });
            }

            AddJobMsg::JobsDiscovered(count) => {
                self.is_finding = false;
                // Defer the output to avoid panic when controller is dropped
                let output_sender = sender.output_sender().clone();
                glib::idle_add_local_once(move || {
                    let _ = output_sender.send(AddJobOutput::JobsAdded(count));
                });
            }

            AddJobMsg::DiscoveryFailed(error) => {
                self.is_finding = false;
                self.error_text = error;
            }

            AddJobMsg::Cancel => {
                // Note: Cancel button is now connected directly in init to avoid panic
                // This handler is kept for completeness but should not be called
            }
        }
    }
}

impl AddJobDialog {
    fn rebuild_sources(model: &AddJobDialog, container: &gtk::Box, sender: &ComponentSender<Self>) {
        // Clear existing children
        while let Some(child) = container.first_child() {
            container.remove(&child);
        }

        for (idx, path) in model.sources.iter().enumerate() {
            let row = gtk::Box::builder()
                .orientation(gtk::Orientation::Horizontal)
                .spacing(8)
                .build();

            let label_text = if idx == 0 {
                "Source 1 (Reference):".to_string()
            } else {
                format!("Source {}:", idx + 1)
            };

            let label = gtk::Label::builder()
                .label(&label_text)
                .width_chars(18)
                .xalign(0.0)
                .build();

            let entry = gtk::Entry::builder()
                .hexpand(true)
                .text(path)
                .placeholder_text("Drop file here or browse...")
                .build();

            let sender_clone = sender.clone();
            let idx_clone = idx;
            entry.connect_changed(move |e| {
                sender_clone.input(AddJobMsg::SourceChanged(idx_clone, e.text().to_string()));
            });

            let browse_btn = gtk::Button::builder().label("Browse...").build();

            let sender_clone = sender.clone();
            browse_btn.connect_clicked(move |_| {
                eprintln!("[AddJob] Browse button clicked for source {}", idx);
                sender_clone.input(AddJobMsg::BrowseSource(idx));
            });

            row.append(&label);
            row.append(&entry);
            row.append(&browse_btn);

            // Add remove button for sources > 2
            if model.sources.len() > 2 {
                let remove_btn = gtk::Button::builder()
                    .icon_name("list-remove-symbolic")
                    .build();

                let sender_clone = sender.clone();
                remove_btn.connect_clicked(move |_| {
                    eprintln!("[AddJob] Remove button clicked for source {}", idx);
                    sender_clone.input(AddJobMsg::RemoveSource(idx));
                });

                row.append(&remove_btn);
            }

            container.append(&row);
        }
    }
}
