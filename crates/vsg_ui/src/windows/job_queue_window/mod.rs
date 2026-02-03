//! Job queue window
//!
//! Displays the job queue with columns: #, Status, Sources
//! Allows adding/removing jobs, moving up/down, copying/pasting layouts.

// TreeView is deprecated in GTK 4.10 but we use it intentionally for simplicity
#![allow(deprecated)]

mod logic;
mod messages;
mod model;

#[allow(unused_imports)]
pub use messages::{DiscoveredJob, JobQueueMsg, JobQueueOutput};
pub use model::{JobDisplayEntry, JobQueueModel};

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use gtk4::prelude::*;
use gtk4::{gio, glib};
use relm4::prelude::*;

use vsg_core::config::ConfigManager;
use vsg_core::jobs::{
    FinalTrackEntry, JobQueue, JobQueueEntry, JobQueueStatus, LayoutManager, ManualLayout,
    TrackConfig,
};

use crate::windows::manual_selection_window::{
    ManualSelectionInit, ManualSelectionOutput, ManualSelectionWindow,
};

/// Initialization data for the job queue window
pub struct JobQueueInit {
    pub config: Arc<Mutex<ConfigManager>>,
    pub parent: Option<gtk4::Window>,
}

/// Job queue window component
#[allow(dead_code)]
pub struct JobQueueWindow {
    model: JobQueueModel,
    config: Arc<Mutex<ConfigManager>>,
    job_queue: JobQueue,
    layout_manager: LayoutManager,

    // GTK widgets for manual updates (will be used for future enhancements)
    list_store: gio::ListStore,

    // Manual selection dialog (spawned on demand)
    manual_selection_window: Option<Controller<ManualSelectionWindow>>,
    /// Index of job currently being configured
    configuring_job_index: Option<usize>,
}

#[relm4::component(pub)]
impl Component for JobQueueWindow {
    type Init = JobQueueInit;
    type Input = JobQueueMsg;
    type Output = JobQueueOutput;
    type CommandOutput = ();

    view! {
        gtk4::Window {
            set_title: Some("Job Queue"),
            set_default_width: 1200,
            set_default_height: 600,
            set_modal: true,

            gtk4::Box {
                set_orientation: gtk4::Orientation::Vertical,
                set_margin_all: 12,
                set_spacing: 12,

                // === Job list (using TreeView with ListStore) ===
                gtk4::ScrolledWindow {
                    set_vexpand: true,
                    set_hexpand: true,
                    set_min_content_height: 300,

                    #[name = "tree_view"]
                    gtk4::TreeView {
                        set_model: Some(&gtk4::TreeStore::new(&[
                            glib::Type::U32,    // Column 0: #
                            glib::Type::STRING, // Column 1: Status
                            glib::Type::STRING, // Column 2: Sources
                            glib::Type::STRING, // Column 3: Tooltip
                        ])),
                        set_headers_visible: true,
                        set_enable_search: false,
                        set_rubber_banding: true,
                    },
                },

                // === Button toolbar ===
                gtk4::Box {
                    set_orientation: gtk4::Orientation::Horizontal,
                    set_spacing: 8,

                    gtk4::Button {
                        set_label: "Add Job(s)...",
                        set_tooltip_text: Some("Add new jobs to the queue"),
                        connect_clicked => JobQueueMsg::AddJobs,
                    },

                    gtk4::Separator {
                        set_orientation: gtk4::Orientation::Vertical,
                    },

                    gtk4::Button {
                        set_label: "Move Up",
                        set_tooltip_text: Some("Move selected jobs up in the queue"),
                        connect_clicked => JobQueueMsg::MoveUp,
                    },

                    gtk4::Button {
                        set_label: "Move Down",
                        set_tooltip_text: Some("Move selected jobs down in the queue"),
                        connect_clicked => JobQueueMsg::MoveDown,
                    },

                    gtk4::Separator {
                        set_orientation: gtk4::Orientation::Vertical,
                    },

                    gtk4::Button {
                        set_label: "Copy Layout",
                        set_tooltip_text: Some("Copy layout from selected job"),
                        #[watch]
                        set_sensitive: model.model.can_copy_layout(),
                        connect_clicked => JobQueueMsg::CopyLayout,
                    },

                    gtk4::Button {
                        set_label: "Paste Layout",
                        set_tooltip_text: Some("Paste layout to selected jobs"),
                        #[watch]
                        set_sensitive: model.model.has_clipboard && model.model.has_selection(),
                        connect_clicked => JobQueueMsg::PasteLayout,
                    },

                    gtk4::Separator {
                        set_orientation: gtk4::Orientation::Vertical,
                    },

                    gtk4::Button {
                        set_label: "Configure...",
                        set_tooltip_text: Some("Open manual selection dialog for selected job"),
                        #[watch]
                        set_sensitive: model.model.single_selection().is_some(),
                        connect_clicked => JobQueueMsg::ConfigureSelected,
                    },

                    // Spacer
                    gtk4::Box {
                        set_hexpand: true,
                    },

                    gtk4::Button {
                        set_label: "Remove Selected",
                        set_tooltip_text: Some("Remove selected jobs from the queue"),
                        #[watch]
                        set_sensitive: model.model.has_selection(),
                        add_css_class: "destructive-action",
                        connect_clicked => JobQueueMsg::RemoveSelected,
                    },
                },

                // === Dialog buttons ===
                gtk4::Box {
                    set_orientation: gtk4::Orientation::Horizontal,
                    set_spacing: 8,
                    set_halign: gtk4::Align::End,

                    gtk4::Button {
                        set_label: "Cancel",
                        connect_clicked => JobQueueMsg::Cancel,
                    },

                    gtk4::Button {
                        set_label: "Start Processing Queue",
                        add_css_class: "suggested-action",
                        #[watch]
                        set_sensitive: !model.model.get_configured_job_ids().is_empty(),
                        connect_clicked => JobQueueMsg::StartProcessing,
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
        // Get temp folder from config for job queue persistence
        let temp_folder = {
            let cfg = init.config.lock().unwrap();
            PathBuf::from(&cfg.settings().paths.temp_root)
        };

        // Get layouts folder
        let layouts_folder = temp_folder.join("job_layouts");

        // Create job queue and layout manager
        let job_queue = JobQueue::new(&temp_folder);
        let layout_manager = LayoutManager::new(&layouts_folder);

        let model = JobQueueModel::new();
        let list_store = gio::ListStore::new::<glib::BoxedAnyObject>();

        let model = JobQueueWindow {
            model,
            config: init.config,
            job_queue,
            layout_manager,
            list_store,
            manual_selection_window: None,
            configuring_job_index: None,
        };

        let widgets = view_output!();

        // Set up TreeView columns after view is created
        Self::setup_tree_view(&widgets.tree_view, sender.clone());

        // Set selection mode to multiple
        let selection = widgets.tree_view.selection();
        selection.set_mode(gtk4::SelectionMode::Multiple);

        // Set up double-click handler
        {
            let sender_clone = sender.clone();
            widgets
                .tree_view
                .connect_row_activated(move |_tree, path, _col| {
                    if let Some(index) = path.indices().first() {
                        sender_clone.input(JobQueueMsg::JobDoubleClicked(*index as u32));
                    }
                });
        }

        // Set up selection change handler
        {
            let sender_clone = sender.clone();
            selection.connect_changed(move |sel: &gtk4::TreeSelection| {
                let mut indices = Vec::new();
                sel.selected_foreach(
                    |_model: &gtk4::TreeModel, path: &gtk4::TreePath, _iter: &gtk4::TreeIter| {
                        if let Some(index) = path.indices().first() {
                            indices.push(*index as u32);
                        }
                    },
                );
                sender_clone.input(JobQueueMsg::SelectionChanged(indices));
            });
        }

        // Set parent if provided
        if let Some(parent) = init.parent {
            root.set_transient_for(Some(&parent));
        }

        // Show the window
        root.present();

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, root: &Self::Root) {
        match msg {
            JobQueueMsg::AddJobs => {
                // Open add job dialog
                self.open_add_job_dialog(sender.clone(), root);
            }

            JobQueueMsg::JobsDiscovered(jobs) => {
                // Convert to JobQueueEntry and add to queue
                for job in jobs {
                    let entry = JobQueueEntry::new(job.id, job.name, job.sources);
                    self.job_queue.add(entry.clone());
                    self.model.jobs.push(JobDisplayEntry::from_entry(entry));
                }
                // Save queue state
                if let Err(e) = self.job_queue.save() {
                    tracing::error!("Failed to save queue: {}", e);
                }
                // Refresh the list view
                self.refresh_list_view(root);
            }

            JobQueueMsg::RemoveSelected => {
                // Remove from backend queue
                let indices: Vec<usize> = self
                    .model
                    .selected_indices
                    .iter()
                    .map(|&i| i as usize)
                    .collect();
                self.job_queue.remove_indices(indices.clone());
                // Remove from model
                self.model.remove_jobs(&self.model.selected_indices.clone());
                // Save queue state
                if let Err(e) = self.job_queue.save() {
                    tracing::error!("Failed to save queue: {}", e);
                }
                // Refresh
                self.refresh_list_view(root);
            }

            JobQueueMsg::MoveUp => {
                // Move in backend
                self.job_queue.move_up(
                    &self
                        .model
                        .selected_indices
                        .iter()
                        .map(|&i| i as usize)
                        .collect::<Vec<_>>(),
                );
                // Move in model
                let indices = self.model.selected_indices.clone();
                self.model.move_up(&indices);
                // Save and refresh
                if let Err(e) = self.job_queue.save() {
                    tracing::error!("Failed to save queue: {}", e);
                }
                self.refresh_list_view(root);
            }

            JobQueueMsg::MoveDown => {
                // Move in backend
                self.job_queue.move_down(
                    &self
                        .model
                        .selected_indices
                        .iter()
                        .map(|&i| i as usize)
                        .collect::<Vec<_>>(),
                );
                // Move in model
                let indices = self.model.selected_indices.clone();
                self.model.move_down(&indices);
                // Save and refresh
                if let Err(e) = self.job_queue.save() {
                    tracing::error!("Failed to save queue: {}", e);
                }
                self.refresh_list_view(root);
            }

            JobQueueMsg::ClearAll => {
                self.job_queue.clear();
                self.model.clear();
                if let Err(e) = self.job_queue.save() {
                    tracing::error!("Failed to save queue: {}", e);
                }
                self.refresh_list_view(root);
            }

            JobQueueMsg::CopyLayout => {
                if let Some(idx) = self.model.single_selection() {
                    if self.job_queue.copy_layout(idx) {
                        self.model.has_clipboard = true;
                        self.model.clipboard_source =
                            self.model.jobs.get(idx).map(|j| j.entry.id.clone());
                        tracing::info!("Copied layout from job at index {}", idx);
                    }
                }
            }

            JobQueueMsg::PasteLayout => {
                let indices: Vec<usize> = self
                    .model
                    .selected_indices
                    .iter()
                    .map(|&i| i as usize)
                    .collect();
                let count = self.job_queue.paste_layout(&indices);
                if count > 0 {
                    tracing::info!("Pasted layout to {} jobs", count);
                    // Sync status back to model
                    for idx in indices {
                        if let Some(backend_job) = self.job_queue.get(idx) {
                            if let Some(display_job) = self.model.jobs.get_mut(idx) {
                                display_job.entry.status = backend_job.status;
                                display_job.entry.layout = backend_job.layout.clone();
                            }
                        }
                    }
                    if let Err(e) = self.job_queue.save() {
                        tracing::error!("Failed to save queue: {}", e);
                    }
                    self.refresh_list_view(root);
                }
            }

            JobQueueMsg::ConfigureSelected => {
                if let Some(idx) = self.model.single_selection() {
                    if let Some(job) = self.model.jobs.get(idx) {
                        // Close existing dialog if open
                        self.manual_selection_window = None;
                        self.configuring_job_index = Some(idx);

                        // Get previous layout if any
                        let previous_layout = job.entry.layout.clone();

                        // Open manual selection dialog
                        let dialog = ManualSelectionWindow::builder()
                            .launch(ManualSelectionInit {
                                sources: job.entry.sources.clone(),
                                config: self.config.clone(),
                                previous_layout,
                                parent: None,
                            })
                            .forward(sender.input_sender(), move |msg| match msg {
                                ManualSelectionOutput::LayoutConfigured {
                                    layout,
                                    attachment_sources,
                                } => JobQueueMsg::LayoutConfigured {
                                    job_index: idx,
                                    layout,
                                    attachment_sources,
                                },
                                ManualSelectionOutput::Cancelled => {
                                    JobQueueMsg::LayoutConfigurationCancelled
                                }
                            });

                        self.manual_selection_window = Some(dialog);
                        tracing::info!("Opened manual selection dialog for job at index {}", idx);
                    }
                }
            }

            JobQueueMsg::LayoutConfigured {
                job_index,
                layout,
                attachment_sources,
            } => {
                self.manual_selection_window = None;
                self.configuring_job_index = None;

                // Convert UI layout to core ManualLayout
                if let Some(job) = self.model.jobs.get_mut(job_index) {
                    let core_layout = ManualLayout {
                        final_tracks: layout
                            .iter()
                            .enumerate()
                            .map(|(i, t)| {
                                use vsg_core::models::TrackType as CoreTrackType;
                                let core_type = match t.track_type {
                                    vsg_core::extraction::TrackType::Video => CoreTrackType::Video,
                                    vsg_core::extraction::TrackType::Audio => CoreTrackType::Audio,
                                    vsg_core::extraction::TrackType::Subtitles => {
                                        CoreTrackType::Subtitles
                                    }
                                };
                                FinalTrackEntry {
                                    track_id: t.track_id,
                                    source_key: t.source_key.clone(),
                                    track_type: core_type,
                                    config: TrackConfig {
                                        sync_to_source: t.sync_to_source.clone(),
                                        is_default: t.is_default,
                                        is_forced_display: t.is_forced,
                                        custom_name: t.custom_name.clone(),
                                        custom_lang: t.custom_lang.clone(),
                                        apply_track_name: t.apply_track_name,
                                    },
                                    user_order_index: i,
                                    position_in_source_type: t.position_in_source_type,
                                }
                            })
                            .collect(),
                        attachment_sources,
                    };

                    // Save layout to job_layouts folder (source of truth)
                    if let Err(e) = self.layout_manager.save_layout_with_metadata(
                        &job.entry.layout_id,
                        &job.entry.sources,
                        &core_layout,
                    ) {
                        tracing::error!("Failed to save layout to file: {}", e);
                        // Don't mark as configured if layout save failed
                        return;
                    }
                    tracing::info!(
                        "Saved layout to job_layouts/{}.json",
                        job.entry.layout_id
                    );

                    // Update UI model (in-memory only)
                    job.entry.layout = Some(core_layout);
                    job.entry.status = JobQueueStatus::Configured;

                    // Update backend queue status (layout is NOT stored in queue.json)
                    if let Some(backend_job) = self.job_queue.get_mut(job_index) {
                        backend_job.status = JobQueueStatus::Configured;
                        tracing::info!(
                            "Updated backend job {} status to Configured",
                            backend_job.id
                        );
                    } else {
                        tracing::error!(
                            "Backend job at index {} not found! Queue has {} jobs",
                            job_index,
                            self.job_queue.len()
                        );
                    }

                    // Save queue.json (status only, layout is in job_layouts/)
                    match self.job_queue.save() {
                        Ok(_) => {
                            tracing::info!(
                                "Saved queue.json with {} jobs",
                                self.job_queue.len()
                            );
                        }
                        Err(e) => {
                            tracing::error!("Failed to save queue: {}", e);
                        }
                    }

                    self.refresh_list_view(root);
                    tracing::info!("Job {} configured with {} tracks", job_index, layout.len());
                }
            }

            JobQueueMsg::LayoutConfigurationCancelled => {
                self.manual_selection_window = None;
                self.configuring_job_index = None;
                tracing::info!("Layout configuration cancelled");
            }

            JobQueueMsg::SelectionChanged(indices) => {
                self.model.selected_indices = indices;
            }

            JobQueueMsg::JobDoubleClicked(_index) => {
                // Open configure dialog on double-click
                sender.input(JobQueueMsg::ConfigureSelected);
            }

            JobQueueMsg::StartProcessing => {
                let job_ids = self.model.get_configured_job_ids();
                if !job_ids.is_empty() {
                    let _ = sender.output(JobQueueOutput::StartProcessing(job_ids));
                    root.close();
                }
            }

            JobQueueMsg::Cancel => {
                let _ = sender.output(JobQueueOutput::Cancelled);
                root.close();
            }

            JobQueueMsg::BrowseResult {
                source_index: _,
                paths: _,
            } => {
                // Handle browse result for add job dialog
                // This is handled by the add job dialog itself
            }
        }
    }
}

impl JobQueueWindow {
    /// Set up TreeView columns
    fn setup_tree_view(tree_view: &gtk4::TreeView, _sender: ComponentSender<Self>) {
        // Column 0: # (order number)
        let renderer0 = gtk4::CellRendererText::new();
        let column0 = gtk4::TreeViewColumn::new();
        column0.set_title("#");
        column0.set_resizable(false);
        column0.set_min_width(40);
        column0.pack_start(&renderer0, true);
        column0.add_attribute(&renderer0, "text", 0);
        tree_view.append_column(&column0);

        // Column 1: Status
        let renderer1 = gtk4::CellRendererText::new();
        let column1 = gtk4::TreeViewColumn::new();
        column1.set_title("Status");
        column1.set_resizable(true);
        column1.set_min_width(120);
        column1.pack_start(&renderer1, true);
        column1.add_attribute(&renderer1, "text", 1);
        tree_view.append_column(&column1);

        // Column 2: Sources
        let renderer2 = gtk4::CellRendererText::new();
        let column2 = gtk4::TreeViewColumn::new();
        column2.set_title("Sources");
        column2.set_resizable(true);
        column2.set_expand(true);
        column2.pack_start(&renderer2, true);
        column2.add_attribute(&renderer2, "text", 2);
        tree_view.append_column(&column2);

        // Enable tooltips
        tree_view.set_tooltip_column(3);
    }

    /// Refresh the list view from model data
    fn refresh_list_view(&self, root: &gtk4::Window) {
        // Get the TreeView from the root window
        if let Some(main_box) = root.child() {
            if let Some(main_box) = main_box.downcast_ref::<gtk4::Box>() {
                if let Some(scroll) = main_box.first_child() {
                    if let Some(scroll) = scroll.downcast_ref::<gtk4::ScrolledWindow>() {
                        if let Some(tree_view) = scroll.child() {
                            if let Some(tree_view) = tree_view.downcast_ref::<gtk4::TreeView>() {
                                self.populate_tree_store(tree_view);
                            }
                        }
                    }
                }
            }
        }
    }

    /// Populate the tree store with job data
    fn populate_tree_store(&self, tree_view: &gtk4::TreeView) {
        // Create a new tree store
        let store = gtk4::TreeStore::new(&[
            glib::Type::U32,    // Column 0: #
            glib::Type::STRING, // Column 1: Status
            glib::Type::STRING, // Column 2: Sources
            glib::Type::STRING, // Column 3: Tooltip
        ]);

        // Add rows for each job
        for (i, job) in self.model.jobs.iter().enumerate() {
            let iter = store.append(None);
            store.set(
                &iter,
                &[
                    (0, &((i + 1) as u32)),
                    (1, &job.status_display()),
                    (2, &job.sources_display),
                    (3, &job.sources_tooltip),
                ],
            );
        }

        // Set the model on the tree view
        tree_view.set_model(Some(&store));
    }

    /// Open the add job dialog
    fn open_add_job_dialog(&self, sender: ComponentSender<Self>, root: &gtk4::Window) {
        let dialog = gtk4::Dialog::builder()
            .title("Add Job(s) to Queue")
            .transient_for(root)
            .modal(true)
            .default_width(700)
            .default_height(300)
            .build();

        let content = dialog.content_area();
        content.set_margin_all(12);
        content.set_spacing(12);

        // Source inputs container
        let inputs_box = gtk4::Box::new(gtk4::Orientation::Vertical, 8);

        // Add initial source inputs
        let source_entries: Arc<Mutex<Vec<gtk4::Entry>>> = Arc::new(Mutex::new(Vec::new()));

        // Add Source 1 (Reference)
        {
            let row = Self::create_source_row("Source 1 (Reference):", &source_entries, 0, &dialog);
            inputs_box.append(&row);
        }

        // Add Source 2
        {
            let row = Self::create_source_row("Source 2:", &source_entries, 1, &dialog);
            inputs_box.append(&row);
        }

        // Scrolled window for inputs
        let scroll = gtk4::ScrolledWindow::builder()
            .hscrollbar_policy(gtk4::PolicyType::Never)
            .vscrollbar_policy(gtk4::PolicyType::Automatic)
            .vexpand(true)
            .child(&inputs_box)
            .build();

        content.append(&scroll);

        // Add Another Source button
        let entries_clone = source_entries.clone();
        let inputs_box_clone = inputs_box.clone();
        let dialog_clone = dialog.clone();
        let add_source_btn = gtk4::Button::with_label("Add Another Source");
        add_source_btn.connect_clicked(move |_| {
            let idx = entries_clone.lock().unwrap().len();
            let label = format!("Source {}:", idx + 1);
            let row = Self::create_source_row(&label, &entries_clone, idx, &dialog_clone);
            inputs_box_clone.append(&row);
        });
        content.append(&add_source_btn);

        // Dialog buttons
        dialog.add_button("Cancel", gtk4::ResponseType::Cancel);
        dialog.add_button("Find & Add Jobs", gtk4::ResponseType::Ok);

        // Handle response
        let entries_final = source_entries.clone();
        let sender_clone = sender.clone();
        dialog.connect_response(move |dlg, response| {
            if response == gtk4::ResponseType::Ok {
                // Collect paths from entries
                let entries = entries_final.lock().unwrap();
                let mut sources: HashMap<String, PathBuf> = HashMap::new();

                for (i, entry) in entries.iter().enumerate() {
                    let text = entry.text().to_string();
                    if !text.is_empty() {
                        sources.insert(format!("Source {}", i + 1), PathBuf::from(text));
                    }
                }

                // Validate Source 1 is present
                if !sources.contains_key("Source 1") {
                    // Show error
                    let error_dialog = gtk4::MessageDialog::builder()
                        .transient_for(dlg)
                        .modal(true)
                        .message_type(gtk4::MessageType::Error)
                        .buttons(gtk4::ButtonsType::Ok)
                        .text("Input Required")
                        .secondary_text("Source 1 (Reference) cannot be empty.")
                        .build();
                    error_dialog.connect_response(|d, _| d.close());
                    error_dialog.present();
                    return;
                }

                // Discover jobs
                match logic::discover_jobs_from_sources(sources) {
                    Ok(jobs) => {
                        let discovered = logic::convert_discovered_jobs(jobs);
                        sender_clone.input(JobQueueMsg::JobsDiscovered(discovered));
                        dlg.close();
                    }
                    Err(e) => {
                        let error_dialog = gtk4::MessageDialog::builder()
                            .transient_for(dlg)
                            .modal(true)
                            .message_type(gtk4::MessageType::Error)
                            .buttons(gtk4::ButtonsType::Ok)
                            .text("Error Discovering Jobs")
                            .secondary_text(&e)
                            .build();
                        error_dialog.connect_response(|d, _| d.close());
                        error_dialog.present();
                    }
                }
            } else {
                dlg.close();
            }
        });

        dialog.present();
    }

    /// Create a source input row
    fn create_source_row(
        label: &str,
        entries: &Arc<Mutex<Vec<gtk4::Entry>>>,
        _index: usize,
        dialog: &gtk4::Dialog,
    ) -> gtk4::Box {
        let row = gtk4::Box::new(gtk4::Orientation::Horizontal, 8);

        let label_widget = gtk4::Label::new(Some(label));
        label_widget.set_width_request(150);
        label_widget.set_xalign(0.0);
        row.append(&label_widget);

        let entry = gtk4::Entry::new();
        entry.set_hexpand(true);

        // Enable drag-drop on entry
        let drop_target =
            gtk4::DropTarget::new(gio::File::static_type(), gtk4::gdk::DragAction::COPY);
        let entry_clone = entry.clone();
        drop_target.connect_drop(move |_target, value, _x, _y| {
            if let Ok(file) = value.get::<gio::File>() {
                if let Some(path) = file.path() {
                    entry_clone.set_text(&path.to_string_lossy());
                    return true;
                }
            }
            false
        });
        entry.add_controller(drop_target);

        row.append(&entry);

        // Browse button
        let browse_btn = gtk4::Button::with_label("Browse...");
        let entry_browse = entry.clone();
        let dialog_clone = dialog.clone();
        browse_btn.connect_clicked(move |_| {
            let entry_inner = entry_browse.clone();
            let dialog = gtk4::FileDialog::builder()
                .title("Select Source File")
                .modal(true)
                .build();

            let dialog_parent = dialog_clone.clone();
            glib::spawn_future_local(async move {
                match dialog.open_future(Some(&dialog_parent)).await {
                    Ok(file) => {
                        if let Some(path) = file.path() {
                            entry_inner.set_text(&path.to_string_lossy());
                        }
                    }
                    Err(_) => {}
                }
            });
        });
        row.append(&browse_btn);

        // Store entry reference
        entries.lock().unwrap().push(entry);

        row
    }
}
