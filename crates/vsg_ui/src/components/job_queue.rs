//! Job queue dialog component.
//!
//! Shows the list of queued jobs with controls to manage and process them.

use std::sync::{Arc, Mutex};

use gtk::prelude::*;
use relm4::prelude::*;
use relm4::{Component, ComponentParts, ComponentSender};

use vsg_core::jobs::{JobQueue, JobQueueEntry, JobQueueStatus};
use vsg_core::models::SourceIndex;

/// Output messages from the job queue dialog.
#[derive(Debug)]
pub enum JobQueueOutput {
    StartProcessing(Vec<JobQueueEntry>),
    OpenManualSelection(usize),
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
    selected_indices: Vec<usize>,
    last_selected_idx: Option<usize>, // For shift-select range
    clipboard_layout: Option<String>,
    status_text: String,
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
    type Init = Arc<Mutex<JobQueue>>;
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

                        gtk::Button {
                            set_label: "Add Job(s)...",
                            connect_clicked => JobQueueMsg::AddJobs,
                        },

                        gtk::Button {
                            set_label: "Remove Selected",
                            connect_clicked => JobQueueMsg::RemoveSelected,
                        },

                        gtk::Separator {
                            set_orientation: gtk::Orientation::Vertical,
                        },

                        gtk::Button {
                            set_label: "Move Up",
                            connect_clicked => JobQueueMsg::MoveUp,
                        },

                        gtk::Button {
                            set_label: "Move Down",
                            connect_clicked => JobQueueMsg::MoveDown,
                        },

                        gtk::Separator {
                            set_orientation: gtk::Orientation::Vertical,
                        },

                        gtk::Button {
                            set_label: "Copy Layout",
                            #[watch]
                            set_sensitive: model.selected_indices.len() == 1,
                            connect_clicked[sender, model] => move |_| {
                                if let Some(&idx) = model.selected_indices.first() {
                                    sender.input(JobQueueMsg::CopyLayout(idx));
                                }
                            },
                        },

                        gtk::Button {
                            set_label: "Paste Layout",
                            #[watch]
                            set_sensitive: model.clipboard_layout.is_some() && !model.selected_indices.is_empty(),
                            connect_clicked => JobQueueMsg::PasteLayout,
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

                                connect_row_activated[sender] => move |_, row| {
                                    let idx = row.index() as usize;
                                    sender.input(JobQueueMsg::ConfigureJob(idx));
                                },
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

                        gtk::Button {
                            set_label: "Start Processing",
                            add_css_class: "suggested-action",
                            connect_clicked => JobQueueMsg::StartProcessing,
                        },

                        gtk::Button {
                            set_label: "Close",
                            connect_clicked => JobQueueMsg::Close,
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
        let model = JobQueueDialog {
            job_queue: init,
            selected_indices: Vec::new(),
            last_selected_idx: None,
            clipboard_layout: None,
            status_text: String::new(),
        };

        let widgets = view_output!();

        // Populate the list
        Self::populate_list(&model, &widgets.job_list, &sender);

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, root: &Self::Root) {
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
                // This would typically open the AddJobDialog
                // For now, we'll just note it in the status
                self.status_text = "Add jobs dialog would open here.".to_string();
            }

            JobQueueMsg::RemoveSelected => {
                if !self.selected_indices.is_empty() {
                    let mut queue = self.job_queue.lock().unwrap();
                    // Remove in reverse order to maintain indices
                    let mut indices: Vec<usize> = self.selected_indices.clone();
                    indices.sort();
                    indices.reverse();
                    for idx in indices {
                        queue.remove(idx);
                    }
                    self.selected_indices.clear();
                    self.status_text = "Jobs removed.".to_string();
                }
            }

            JobQueueMsg::MoveUp => {
                if let Some(&idx) = self.selected_indices.first() {
                    if idx > 0 {
                        let mut queue = self.job_queue.lock().unwrap();
                        queue.swap(idx, idx - 1);
                        self.selected_indices = vec![idx - 1];
                    }
                }
            }

            JobQueueMsg::MoveDown => {
                if let Some(&idx) = self.selected_indices.first() {
                    let queue = self.job_queue.lock().unwrap();
                    if idx < queue.jobs().len() - 1 {
                        drop(queue);
                        let mut queue = self.job_queue.lock().unwrap();
                        queue.swap(idx, idx + 1);
                        self.selected_indices = vec![idx + 1];
                    }
                }
            }

            JobQueueMsg::ConfigureJob(idx) => {
                let _ = sender.output(JobQueueOutput::OpenManualSelection(idx));
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

            JobQueueMsg::PasteLayout => {
                if let Some(ref layout_json) = self.clipboard_layout {
                    if let Ok(layout) = serde_json::from_str(layout_json) {
                        let mut queue = self.job_queue.lock().unwrap();
                        for &idx in &self.selected_indices {
                            if let Some(job) = queue.jobs_mut().get_mut(idx) {
                                job.layout = layout;
                                job.status = JobQueueStatus::Configured;
                            }
                        }
                        self.status_text = "Layout pasted.".to_string();
                    }
                }
            }

            JobQueueMsg::StartProcessing => {
                let queue = self.job_queue.lock().unwrap();
                let jobs: Vec<JobQueueEntry> = queue
                    .jobs()
                    .iter()
                    .filter(|j| j.status == JobQueueStatus::Configured)
                    .cloned()
                    .collect();

                if jobs.is_empty() {
                    self.status_text = "No configured jobs to process.".to_string();
                } else {
                    let _ = sender.output(JobQueueOutput::StartProcessing(jobs));
                    root.close();
                }
            }

            JobQueueMsg::Close => {
                let _ = sender.output(JobQueueOutput::Closed);
                root.close();
            }

            JobQueueMsg::RefreshList => {
                // The list will be refreshed on update_view
            }
        }
    }

    fn update_view(&self, widgets: &mut Self::Widgets, sender: ComponentSender<Self>) {
        // Clear and repopulate the list
        Self::populate_list(self, &widgets.job_list, &sender);
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
                let sender_click = sender.clone();
                let job_idx = job.index;
                gesture.connect_pressed(move |gesture, _n_press, _x, _y| {
                    let modifiers = gesture.current_event_state();
                    let ctrl = modifiers.contains(gtk::gdk::ModifierType::CONTROL_MASK);
                    let shift = modifiers.contains(gtk::gdk::ModifierType::SHIFT_MASK);
                    sender_click.input(JobQueueMsg::SelectJob(job_idx, ctrl, shift));
                });
                row.add_controller(gesture);

                // Configure button
                let configure_btn = gtk::Button::builder()
                    .label("Configure")
                    .valign(gtk::Align::Center)
                    .build();

                let sender_cfg = sender.clone();
                let cfg_idx = job.index;
                configure_btn.connect_clicked(move |_| {
                    sender_cfg.input(JobQueueMsg::ConfigureJob(cfg_idx));
                });

                row.add_suffix(&configure_btn);

                list_box.append(&row);
            }
        }
    }
}
