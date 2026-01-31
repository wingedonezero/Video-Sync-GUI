//! Job queue dialog component.
//!
//! Shows the list of queued jobs with controls to manage and process them.

use std::sync::{Arc, Mutex};

use gtk::glib;
use gtk::prelude::*;
use libadwaita::prelude::*;
use relm4::prelude::*;
use relm4::{Component, ComponentParts, ComponentSender};

use vsg_core::jobs::{JobQueue, JobQueueEntry, JobQueueStatus, LayoutManager};
use vsg_core::models::SourceIndex;

/// Output messages from the job queue dialog.
#[derive(Debug)]
pub enum JobQueueOutput {
    StartProcessing(Vec<JobQueueEntry>),
    OpenManualSelection(usize),
    OpenAddJob,
    Closed,
}

/// Input messages for the job queue dialog.
#[derive(Debug)]
pub enum JobQueueMsg {
    // Job selection - supports Ctrl/Shift+click
    SelectJob(usize, bool, bool), // index, ctrl_pressed, shift_pressed
    SelectionChanged(Vec<usize>),
    DeselectAll,

    // Job actions
    AddJobs,
    RemoveSelected,
    MoveUp,
    MoveDown,
    ConfigureJob(usize),
    CopyLayout(usize),
    CopySelectedLayout,
    PasteLayout,

    // Processing
    StartProcessing,

    // Dialog
    Close,

    // Refresh
    RefreshList,
}

/// Job queue dialog state.
pub struct JobQueueDialog {
    job_queue: Arc<Mutex<JobQueue>>,
    layout_manager: Arc<Mutex<LayoutManager>>,
    selected_indices: Vec<usize>,
    last_selected_idx: Option<usize>, // For shift-select range
    clipboard_layout: Option<String>,
    status_text: String,
    job_list: Option<gtk::ListBox>, // Stored for list refresh
}

/// A job row for display.
#[derive(Debug, Clone)]
struct JobRow {
    index: usize,
    name: String,
    source1_name: String,
    source_count: usize,
    status: String,
}

impl JobQueueDialog {
    fn get_jobs(&self) -> Vec<JobRow> {
        let queue = self.job_queue.lock().unwrap();
        queue
            .jobs()
            .iter()
            .enumerate()
            .map(|(idx, job)| {
                let status_str = match job.status {
                    JobQueueStatus::Pending => "Not Configured",
                    JobQueueStatus::Configured => "Configured",
                    JobQueueStatus::Processing => "Processing",
                    JobQueueStatus::Complete => "Complete",
                    JobQueueStatus::Error => "Error",
                };

                let source1_name = job
                    .sources
                    .get(&SourceIndex::source1())
                    .and_then(|p| p.file_name())
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_else(|| "-".to_string());

                JobRow {
                    index: idx,
                    name: job.name.clone(),
                    source1_name,
                    source_count: job.sources.len(),
                    status: status_str.to_string(),
                }
            })
            .collect()
    }
}

#[relm4::component(pub)]
impl Component for JobQueueDialog {
    type Init = (Arc<Mutex<JobQueue>>, Arc<Mutex<LayoutManager>>);
    type Input = JobQueueMsg;
    type Output = JobQueueOutput;
    type CommandOutput = ();

    view! {
        adw::Window {
            set_title: Some("Job Queue"),
            set_default_width: 900,
            set_default_height: 600,
            set_modal: true,

            #[wrap(Some)]
            set_content = &gtk::Box {
                set_orientation: gtk::Orientation::Vertical,

                adw::HeaderBar {
                    #[wrap(Some)]
                    set_title_widget = &gtk::Label {
                        set_label: "Job Queue",
                    },
                },

                gtk::Box {
                    set_orientation: gtk::Orientation::Vertical,
                    set_spacing: 12,
                    set_margin_all: 16,
                    set_vexpand: true,

                    // Action buttons
                    gtk::Box {
                        set_orientation: gtk::Orientation::Horizontal,
                        set_spacing: 8,

                        #[name = "add_jobs_btn"]
                        gtk::Button {
                            set_label: "Add Job(s)...",
                        },

                        #[name = "remove_btn"]
                        gtk::Button {
                            set_label: "Remove Selected",
                        },

                        gtk::Separator {
                            set_orientation: gtk::Orientation::Vertical,
                        },

                        #[name = "move_up_btn"]
                        gtk::Button {
                            set_label: "Move Up",
                        },

                        #[name = "move_down_btn"]
                        gtk::Button {
                            set_label: "Move Down",
                        },

                        gtk::Separator {
                            set_orientation: gtk::Orientation::Vertical,
                        },

                        #[name = "copy_layout_btn"]
                        gtk::Button {
                            set_label: "Copy Layout",
                            #[watch]
                            set_sensitive: model.selected_indices.len() == 1,
                        },

                        #[name = "paste_layout_btn"]
                        gtk::Button {
                            set_label: "Paste Layout",
                            #[watch]
                            set_sensitive: model.clipboard_layout.is_some() && !model.selected_indices.is_empty(),
                        },
                    },

                    // Job list
                    gtk::Frame {
                        set_vexpand: true,

                        gtk::ScrolledWindow {
                            set_vexpand: true,
                            set_hexpand: true,

                            #[name = "job_list"]
                            gtk::ListBox {
                                set_selection_mode: gtk::SelectionMode::Multiple,
                                add_css_class: "boxed-list",
                                // connect_row_activated connected manually in init
                            },
                        },
                    },

                    // Status text
                    gtk::Label {
                        #[watch]
                        set_label: if model.status_text.is_empty() {
                            "Click to select, double-click to configure track layout."
                        } else {
                            &model.status_text
                        },
                        set_xalign: 0.0,
                    },

                    // Dialog buttons
                    gtk::Box {
                        set_orientation: gtk::Orientation::Horizontal,
                        set_spacing: 8,
                        set_halign: gtk::Align::End,

                        #[name = "start_btn"]
                        gtk::Button {
                            set_label: "Start Processing",
                            add_css_class: "suggested-action",
                            // Connected manually in init to avoid panic
                        },

                        #[name = "close_btn"]
                        gtk::Button {
                            set_label: "Close",
                            // Connected manually in init to avoid panic
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
        let (job_queue, layout_manager) = init;
        let mut model = JobQueueDialog {
            job_queue,
            layout_manager,
            selected_indices: Vec::new(),
            last_selected_idx: None,
            clipboard_layout: None,
            status_text: String::new(),
            job_list: None,
        };

        let widgets = view_output!();

        // Store job_list reference for refreshing
        model.job_list = Some(widgets.job_list.clone());

        // Populate the list
        Self::populate_list(&model, &widgets.job_list, &sender);

        // Manually connect ALL buttons to avoid panic if component is destroyed
        // Using input_sender.send() which returns Result instead of panicking

        // Action buttons
        let sender_clone = sender.clone();
        widgets.add_jobs_btn.connect_clicked(move |_| {
            eprintln!("[JobQueue] Add Jobs button clicked");
            sender_clone.input(JobQueueMsg::AddJobs);
        });

        let sender_clone = sender.clone();
        widgets.remove_btn.connect_clicked(move |_| {
            eprintln!("[JobQueue] Remove Selected button clicked");
            sender_clone.input(JobQueueMsg::RemoveSelected);
        });

        let sender_clone = sender.clone();
        widgets.move_up_btn.connect_clicked(move |_| {
            eprintln!("[JobQueue] Move Up button clicked");
            sender_clone.input(JobQueueMsg::MoveUp);
        });

        let sender_clone = sender.clone();
        widgets.move_down_btn.connect_clicked(move |_| {
            eprintln!("[JobQueue] Move Down button clicked");
            sender_clone.input(JobQueueMsg::MoveDown);
        });

        let sender_clone = sender.clone();
        widgets.copy_layout_btn.connect_clicked(move |_| {
            eprintln!("[JobQueue] Copy Layout button clicked");
            sender_clone.input(JobQueueMsg::CopySelectedLayout);
        });

        let sender_clone = sender.clone();
        widgets.paste_layout_btn.connect_clicked(move |_| {
            eprintln!("[JobQueue] Paste Layout button clicked");
            sender_clone.input(JobQueueMsg::PasteLayout);
        });

        // Start Processing button
        let sender_clone = sender.clone();
        widgets.start_btn.connect_clicked(move |_| {
            eprintln!("[JobQueue] Start Processing button clicked");
            sender_clone.input(JobQueueMsg::StartProcessing);
        });

        // Close button - defer output to avoid panic when component is destroyed in handler
        let output_sender = sender.output_sender().clone();
        let root_clone = root.clone();
        widgets.close_btn.connect_clicked(move |_| {
            eprintln!("[JobQueue] Close button clicked");
            root_clone.close();
            let sender = output_sender.clone();
            glib::idle_add_local_once(move || {
                let _ = sender.send(JobQueueOutput::Closed);
            });
        });

        // Window close button
        let output_sender = sender.output_sender().clone();
        root.connect_close_request(move |_| {
            let sender = output_sender.clone();
            glib::idle_add_local_once(move || {
                let _ = sender.send(JobQueueOutput::Closed);
            });
            glib::Propagation::Proceed
        });

        // ListBox row activation
        let sender_clone = sender.clone();
        widgets.job_list.connect_row_activated(move |_, row| {
            let idx = row.index() as usize;
            sender_clone.input(JobQueueMsg::ConfigureJob(idx));
        });

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, _root: &Self::Root) {
        match msg {
            JobQueueMsg::SelectJob(idx, ctrl_pressed, shift_pressed) => {
                let job_count = {
                    let queue = self.job_queue.lock().unwrap();
                    queue.jobs().len()
                };

                if shift_pressed && self.last_selected_idx.is_some() {
                    // Shift+click: select range from last to current
                    let last = self.last_selected_idx.unwrap();
                    let start = last.min(idx);
                    let end = last.max(idx);

                    if !ctrl_pressed {
                        // Without Ctrl, replace selection with range
                        self.selected_indices.clear();
                    }

                    for i in start..=end {
                        if i < job_count && !self.selected_indices.contains(&i) {
                            self.selected_indices.push(i);
                        }
                    }
                } else if ctrl_pressed {
                    // Ctrl+click: toggle selection
                    if let Some(pos) = self.selected_indices.iter().position(|&x| x == idx) {
                        self.selected_indices.remove(pos);
                    } else if idx < job_count {
                        self.selected_indices.push(idx);
                    }
                    self.last_selected_idx = Some(idx);
                } else {
                    // Normal click: select only this item
                    self.selected_indices.clear();
                    if idx < job_count {
                        self.selected_indices.push(idx);
                    }
                    self.last_selected_idx = Some(idx);
                }

                // Keep indices sorted for consistent behavior
                self.selected_indices.sort();
            }

            JobQueueMsg::SelectionChanged(indices) => {
                self.selected_indices = indices;
                self.selected_indices.sort();
                if let Some(&last) = self.selected_indices.last() {
                    self.last_selected_idx = Some(last);
                }
            }

            JobQueueMsg::DeselectAll => {
                self.selected_indices.clear();
                self.last_selected_idx = None;
            }

            JobQueueMsg::AddJobs => {
                // Defer output because parent closes this dialog when it receives OpenAddJob
                let output_sender = sender.output_sender().clone();
                glib::idle_add_local_once(move || {
                    let _ = output_sender.send(JobQueueOutput::OpenAddJob);
                });
            }

            JobQueueMsg::RemoveSelected => {
                if !self.selected_indices.is_empty() {
                    {
                        let mut queue = self.job_queue.lock().unwrap();
                        // Remove in reverse order to maintain indices
                        let mut indices: Vec<usize> = self.selected_indices.clone();
                        indices.sort();
                        indices.reverse();
                        for idx in indices {
                            queue.remove(idx);
                        }
                    }
                    self.selected_indices.clear();
                    self.status_text = "Jobs removed.".to_string();
                    // Refresh the list
                    if let Some(ref list_box) = self.job_list {
                        Self::populate_list(self, list_box, &sender);
                    }
                }
            }

            JobQueueMsg::MoveUp => {
                if let Some(&idx) = self.selected_indices.first() {
                    if idx > 0 {
                        {
                            let mut queue = self.job_queue.lock().unwrap();
                            queue.move_up(&[idx]);
                        }
                        self.selected_indices = vec![idx - 1];
                        // Refresh the list
                        if let Some(ref list_box) = self.job_list {
                            Self::populate_list(self, list_box, &sender);
                        }
                    }
                }
            }

            JobQueueMsg::MoveDown => {
                if let Some(&idx) = self.selected_indices.first() {
                    let len = {
                        let queue = self.job_queue.lock().unwrap();
                        queue.jobs().len()
                    };
                    if idx < len.saturating_sub(1) {
                        {
                            let mut queue = self.job_queue.lock().unwrap();
                            queue.move_down(&[idx]);
                        }
                        self.selected_indices = vec![idx + 1];
                        // Refresh the list
                        if let Some(ref list_box) = self.job_list {
                            Self::populate_list(self, list_box, &sender);
                        }
                    }
                }
            }

            JobQueueMsg::ConfigureJob(idx) => {
                let output_sender = sender.output_sender().clone();
                glib::idle_add_local_once(move || {
                    let _ = output_sender.send(JobQueueOutput::OpenManualSelection(idx));
                });
            }

            JobQueueMsg::CopyLayout(idx) => {
                let queue = self.job_queue.lock().unwrap();
                if let Some(job) = queue.jobs().get(idx) {
                    // Serialize layout to clipboard
                    if let Ok(json) = serde_json::to_string(&job.layout) {
                        self.clipboard_layout = Some(json);
                        self.status_text = "Layout copied.".to_string();
                    }
                }
            }

            JobQueueMsg::CopySelectedLayout => {
                if let Some(&idx) = self.selected_indices.first() {
                    let queue = self.job_queue.lock().unwrap();
                    if let Some(job) = queue.jobs().get(idx) {
                        if let Ok(json) = serde_json::to_string(&job.layout) {
                            self.clipboard_layout = Some(json);
                            self.status_text = "Layout copied.".to_string();
                        }
                    }
                }
            }

            JobQueueMsg::PasteLayout => {
                if let Some(ref layout_json) = self.clipboard_layout {
                    if let Ok(layout) = serde_json::from_str::<Option<vsg_core::jobs::ManualLayout>>(layout_json) {
                        let mut pasted_count = 0;
                        {
                            let mut queue = self.job_queue.lock().unwrap();
                            let lm = self.layout_manager.lock().unwrap();

                            for &idx in &self.selected_indices {
                                if let Some(job) = queue.get_mut(idx) {
                                    // Save layout to disk
                                    if let Some(ref layout) = layout {
                                        if let Err(e) = lm.save_layout_with_metadata(
                                            &job.layout_id,
                                            &job.sources,
                                            layout,
                                        ) {
                                            tracing::error!(
                                                "Failed to save layout for job {}: {}",
                                                job.name,
                                                e
                                            );
                                        }
                                    }
                                    job.layout = layout.clone();
                                    job.status = JobQueueStatus::Configured;
                                    pasted_count += 1;
                                }
                            }

                            // Save queue to persist status changes
                            if let Err(e) = queue.save() {
                                tracing::warn!("Failed to save queue: {}", e);
                            }
                        }
                        self.status_text = format!("Layout pasted to {} job(s).", pasted_count);
                        // Refresh the list to show updated status
                        if let Some(ref list_box) = self.job_list {
                            Self::populate_list(self, list_box, &sender);
                        }
                    }
                }
            }

            JobQueueMsg::StartProcessing => {
                let queue = self.job_queue.lock().unwrap();
                let jobs = queue.jobs();

                if jobs.is_empty() {
                    self.status_text = "No jobs in queue.".to_string();
                    return;
                }

                // Check that ALL jobs are configured - block if any aren't
                let unconfigured: Vec<_> = jobs
                    .iter()
                    .enumerate()
                    .filter(|(_, job)| job.status != JobQueueStatus::Configured)
                    .collect();

                if !unconfigured.is_empty() {
                    let count = unconfigured.len();
                    let first_unconfigured = unconfigured.first().map(|(i, _)| i + 1).unwrap_or(1);
                    self.status_text = format!(
                        "Cannot process: {} job(s) not configured. First: Job #{}. Double-click to configure.",
                        count, first_unconfigured
                    );
                    return;
                }

                // All jobs configured - collect and start processing
                let configured_jobs: Vec<JobQueueEntry> = jobs.to_vec();
                // Defer output to avoid panic when controller is dropped while in click handler
                let output_sender = sender.output_sender().clone();
                glib::idle_add_local_once(move || {
                    let _ = output_sender.send(JobQueueOutput::StartProcessing(configured_jobs));
                });
            }

            JobQueueMsg::Close => {
                // Note: Close button is now connected directly in init to avoid panic
                // This handler is kept for completeness but should not be called
            }

            JobQueueMsg::RefreshList => {
                // Refresh the list
                if let Some(ref list_box) = self.job_list {
                    Self::populate_list(self, list_box, &sender);
                }
            }
        }
    }
}

impl JobQueueDialog {
    fn populate_list(model: &JobQueueDialog, list_box: &gtk::ListBox, sender: &ComponentSender<Self>) {
        // Remove all existing rows
        while let Some(child) = list_box.first_child() {
            list_box.remove(&child);
        }

        let jobs = model.get_jobs();

        if jobs.is_empty() {
            let row = adw::ActionRow::builder()
                .title("No jobs in queue")
                .subtitle("Click 'Add Job(s)...' to add jobs")
                .build();
            list_box.append(&row);
        } else {
            for job in jobs {
                let status_icon = match job.status.as_str() {
                    "Configured" => "emblem-ok-symbolic",
                    "Complete" => "emblem-default-symbolic",
                    "Error" => "dialog-error-symbolic",
                    "Processing" => "emblem-synchronizing-symbolic",
                    _ => "radio-symbolic-disabled",
                };

                let row = adw::ActionRow::builder()
                    .title(&job.name)
                    .subtitle(&format!(
                        "{} | {} source(s) | {}",
                        job.source1_name, job.source_count, job.status
                    ))
                    .activatable(true)
                    .build();

                // Add selection styling if selected
                if model.selected_indices.contains(&job.index) {
                    row.add_css_class("selected");
                }

                let icon = gtk::Image::from_icon_name(status_icon);
                row.add_prefix(&icon);

                // Add click gesture for selection with Ctrl/Shift support
                let gesture = gtk::GestureClick::new();
                let sender_clone = sender.clone();
                let job_idx = job.index;
                gesture.connect_pressed(move |gesture, _n_press, _x, _y| {
                    let modifiers = gesture.current_event_state();
                    let ctrl = modifiers.contains(gtk::gdk::ModifierType::CONTROL_MASK);
                    let shift = modifiers.contains(gtk::gdk::ModifierType::SHIFT_MASK);
                    sender_clone.input(JobQueueMsg::SelectJob(job_idx, ctrl, shift));
                });
                row.add_controller(gesture);

                // Configure button
                let configure_btn = gtk::Button::builder()
                    .label("Configure")
                    .valign(gtk::Align::Center)
                    .build();

                let sender_clone = sender.clone();
                let cfg_idx = job.index;
                configure_btn.connect_clicked(move |_| {
                    sender_clone.input(JobQueueMsg::ConfigureJob(cfg_idx));
                });

                row.add_suffix(&configure_btn);

                list_box.append(&row);
            }
        }
    }
}
