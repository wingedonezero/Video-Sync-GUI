//! Main application window
//!
//! Layout matches the Python/PySide version:
//! - Settings button (top)
//! - Main Workflow group (Job Queue button, archive checkbox)
//! - Quick Analysis group (3 source inputs, Analyze button)
//! - Status bar with progress
//! - Latest Job Results (delay displays)
//! - Log output

mod logic;
mod messages;
mod model;

pub use messages::{AnalysisResult, MainWindowMsg};
pub use model::MainWindowModel;

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use gtk4::prelude::*;
use relm4::prelude::*;

use vsg_core::config::ConfigManager;

use crate::components::{FileInput, FileInputInit, FileInputOutput, LogView, LogViewMsg};

/// Main window component
pub struct MainWindow {
    model: MainWindowModel,
    config: Arc<Mutex<ConfigManager>>,

    // Child components
    source1_input: Controller<FileInput>,
    source2_input: Controller<FileInput>,
    source3_input: Controller<FileInput>,
    log_view: Controller<LogView>,
}

#[relm4::component(pub)]
impl Component for MainWindow {
    type Init = Arc<Mutex<ConfigManager>>;
    type Input = MainWindowMsg;
    type Output = ();
    type CommandOutput = MainWindowMsg;

    view! {
        gtk4::ApplicationWindow {
            set_title: Some("Video/Audio Sync & Merge"),
            set_default_width: 1000,
            set_default_height: 600,

            gtk4::Box {
                set_orientation: gtk4::Orientation::Vertical,
                set_margin_all: 12,
                set_spacing: 12,

                // === Top row: Settings button ===
                gtk4::Box {
                    set_orientation: gtk4::Orientation::Horizontal,

                    gtk4::Button {
                        set_label: "Settings…",
                        connect_clicked => MainWindowMsg::OpenSettings,
                    },
                },

                // === Main Workflow Group ===
                gtk4::Frame {
                    set_label: Some("Main Workflow"),

                    gtk4::Box {
                        set_orientation: gtk4::Orientation::Vertical,
                        set_margin_all: 12,
                        set_spacing: 8,

                        gtk4::Button {
                            set_label: "Open Job Queue for Merging...",
                            add_css_class: "suggested-action",
                            connect_clicked => MainWindowMsg::OpenJobQueue,
                        },

                        gtk4::CheckButton {
                            set_label: Some("Archive logs to a zip file on batch completion"),
                            set_active: model.model.archive_logs_on_completion,
                            connect_toggled[sender] => move |btn| {
                                sender.input(MainWindowMsg::ToggleArchiveLogs(btn.is_active()));
                            },
                        },
                    },
                },

                // === Quick Analysis Group ===
                gtk4::Frame {
                    set_label: Some("Quick Analysis (Analyze Only)"),

                    gtk4::Box {
                        set_orientation: gtk4::Orientation::Vertical,
                        set_margin_all: 12,
                        set_spacing: 8,

                        // Source inputs (from child components)
                        model.source1_input.widget().clone(),
                        model.source2_input.widget().clone(),
                        model.source3_input.widget().clone(),

                        // Analyze button (right-aligned)
                        gtk4::Box {
                            set_orientation: gtk4::Orientation::Horizontal,
                            set_halign: gtk4::Align::End,

                            #[name = "analyze_btn"]
                            gtk4::Button {
                                set_label: "Analyze Only",
                                set_sensitive: model.model.can_run_analysis(),
                                connect_clicked => MainWindowMsg::RunAnalysis,
                            },
                        },
                    },
                },

                // === Status and Progress ===
                gtk4::Box {
                    set_orientation: gtk4::Orientation::Horizontal,
                    set_spacing: 12,

                    gtk4::Label {
                        set_label: "Status:",
                    },

                    gtk4::Label {
                        #[watch]
                        set_label: &model.model.status_message,
                        set_hexpand: true,
                        set_xalign: 0.0,
                    },

                    #[name = "progress_bar"]
                    gtk4::ProgressBar {
                        set_width_request: 200,
                        #[watch]
                        set_fraction: model.model.progress,
                        set_show_text: true,
                    },
                },

                // === Latest Job Results ===
                gtk4::Frame {
                    set_label: Some("Latest Job Results"),

                    gtk4::Box {
                        set_orientation: gtk4::Orientation::Horizontal,
                        set_margin_all: 12,
                        set_spacing: 24,

                        gtk4::Box {
                            set_orientation: gtk4::Orientation::Horizontal,
                            set_spacing: 8,
                            gtk4::Label { set_label: "Source 2 Delay:" },
                            gtk4::Label {
                                #[watch]
                                set_label: &MainWindowModel::format_delay(model.model.source2_delay_ms),
                            },
                        },

                        gtk4::Box {
                            set_orientation: gtk4::Orientation::Horizontal,
                            set_spacing: 8,
                            gtk4::Label { set_label: "Source 3 Delay:" },
                            gtk4::Label {
                                #[watch]
                                set_label: &MainWindowModel::format_delay(model.model.source3_delay_ms),
                            },
                        },

                        gtk4::Box {
                            set_orientation: gtk4::Orientation::Horizontal,
                            set_spacing: 8,
                            gtk4::Label { set_label: "Source 4 Delay:" },
                            gtk4::Label {
                                #[watch]
                                set_label: &MainWindowModel::format_delay(model.model.source4_delay_ms),
                            },
                        },
                    },
                },

                // === Log Output ===
                gtk4::Frame {
                    set_label: Some("Log"),
                    set_vexpand: true,

                    model.log_view.widget().clone(),
                },
            },
        }
    }

    fn init(
        config: Self::Init,
        root: Self::Root,
        sender: ComponentSender<Self>,
    ) -> ComponentParts<Self> {
        // Load initial paths from config
        let (source1_path, source2_path, source3_path) = {
            let cfg = config.lock().unwrap();
            let settings = cfg.settings();
            (
                settings.paths.last_source1_path.clone(),
                settings.paths.last_source2_path.clone(),
                String::new(), // Source 3 not persisted in settings
            )
        };

        // Create source input components
        let source1_input = FileInput::builder()
            .launch(FileInputInit {
                label: "Source 1 (Reference):".to_string(),
                initial_path: source1_path.clone(),
            })
            .forward(sender.input_sender(), |msg| match msg {
                FileInputOutput::PathChanged(path) => {
                    MainWindowMsg::SourcePathChanged { index: 0, path }
                }
                FileInputOutput::BrowseRequested => MainWindowMsg::BrowseSource(0),
            });

        let source2_input = FileInput::builder()
            .launch(FileInputInit {
                label: "Source 2:".to_string(),
                initial_path: source2_path.clone(),
            })
            .forward(sender.input_sender(), |msg| match msg {
                FileInputOutput::PathChanged(path) => {
                    MainWindowMsg::SourcePathChanged { index: 1, path }
                }
                FileInputOutput::BrowseRequested => MainWindowMsg::BrowseSource(1),
            });

        let source3_input = FileInput::builder()
            .launch(FileInputInit {
                label: "Source 3:".to_string(),
                initial_path: source3_path.clone(),
            })
            .forward(sender.input_sender(), |msg| match msg {
                FileInputOutput::PathChanged(path) => {
                    MainWindowMsg::SourcePathChanged { index: 2, path }
                }
                FileInputOutput::BrowseRequested => MainWindowMsg::BrowseSource(2),
            });

        // Create log view
        let log_view = LogView::builder().launch(()).detach();

        let mut model = MainWindowModel::new();
        model.source1_path = source1_path;
        model.source2_path = source2_path;
        model.source3_path = source3_path;

        let model = MainWindow {
            model,
            config,
            source1_input,
            source2_input,
            source3_input,
            log_view,
        };

        let widgets = view_output!();

        // Log startup message
        model.log_view.emit(LogViewMsg::Append(format!(
            "Video Sync GUI started. Core version: {}",
            vsg_core::version()
        )));

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, _root: &Self::Root) {
        match msg {
            MainWindowMsg::OpenSettings => {
                self.log_view.emit(LogViewMsg::Append(
                    "Settings dialog not implemented yet.".to_string(),
                ));
            }

            MainWindowMsg::OpenJobQueue => {
                self.log_view.emit(LogViewMsg::Append(
                    "Job Queue dialog not implemented yet.".to_string(),
                ));
            }

            MainWindowMsg::ToggleArchiveLogs(checked) => {
                self.model.archive_logs_on_completion = checked;
            }

            MainWindowMsg::SourcePathChanged { index, path } => {
                self.model.set_source_path(index, path);
            }

            MainWindowMsg::BrowseSource(index) => {
                let sender = sender.clone();
                relm4::spawn_local(async move {
                    let dialog = gtk4::FileDialog::builder()
                        .title("Select File or Directory")
                        .modal(true)
                        .build();

                    // Open file dialog asynchronously
                    match dialog.open_future(None::<&gtk4::Window>).await {
                        Ok(file) => {
                            if let Some(path) = file.path() {
                                sender.input(MainWindowMsg::BrowseResult {
                                    index,
                                    path: Some(path.to_string_lossy().to_string()),
                                });
                            }
                        }
                        Err(_) => {
                            // User cancelled or error
                            sender.input(MainWindowMsg::BrowseResult { index, path: None });
                        }
                    }
                });
            }

            MainWindowMsg::BrowseResult { index, path } => {
                if let Some(path) = path {
                    self.model.set_source_path(index, path.clone());
                    // Update the input component
                    match index {
                        0 => self.source1_input.emit(
                            crate::components::file_input::FileInputMsg::TextChanged(path),
                        ),
                        1 => self.source2_input.emit(
                            crate::components::file_input::FileInputMsg::TextChanged(path),
                        ),
                        2 => self.source3_input.emit(
                            crate::components::file_input::FileInputMsg::TextChanged(path),
                        ),
                        _ => {}
                    }
                }
            }

            MainWindowMsg::RunAnalysis => {
                if !self.model.can_run_analysis() {
                    self.log_view.emit(LogViewMsg::Append(
                        "Cannot run analysis: Source 1 and Source 2 are required.".to_string(),
                    ));
                    return;
                }

                self.model.start_analysis();
                self.log_view
                    .emit(LogViewMsg::Append("Starting analysis...".to_string()));

                // Get paths for worker
                let source1 = PathBuf::from(&self.model.source1_path);
                let source2 = PathBuf::from(&self.model.source2_path);
                let source3 = if self.model.source3_path.is_empty() {
                    None
                } else {
                    Some(PathBuf::from(&self.model.source3_path))
                };

                // Get config for worker
                let config = self.config.clone();

                // Spawn analysis worker
                sender.spawn_command(move |cmd_sender| {
                    crate::workers::run_analysis(source1, source2, source3, config, cmd_sender);
                });
            }

            MainWindowMsg::AnalysisProgress { progress, message } => {
                self.model.set_progress(progress, &message);
            }

            MainWindowMsg::AnalysisLog(message) => {
                self.log_view.emit(LogViewMsg::Append(message));
            }

            MainWindowMsg::AnalysisComplete(result) => {
                match result {
                    Ok(analysis_result) => {
                        self.model.finish_analysis(true);

                        // Update delay displays (Delays uses HashMap<String, i64>)
                        if let Some(&delay_ms) =
                            analysis_result.delays.source_delays_ms.get("Source 2")
                        {
                            self.model.source2_delay_ms = Some(delay_ms as f64);
                        }
                        if let Some(&delay_ms) =
                            analysis_result.delays.source_delays_ms.get("Source 3")
                        {
                            self.model.source3_delay_ms = Some(delay_ms as f64);
                        }
                        if let Some(&delay_ms) =
                            analysis_result.delays.source_delays_ms.get("Source 4")
                        {
                            self.model.source4_delay_ms = Some(delay_ms as f64);
                        }

                        self.log_view.emit(LogViewMsg::Append(format!(
                            "Analysis complete! Source 2: {}, Source 3: {}",
                            MainWindowModel::format_delay(self.model.source2_delay_ms),
                            MainWindowModel::format_delay(self.model.source3_delay_ms),
                        )));
                    }
                    Err(error) => {
                        self.model.finish_analysis(false);
                        self.log_view
                            .emit(LogViewMsg::Append(format!("Analysis failed: {}", error)));
                    }
                }
            }
        }
    }

    fn update_cmd(
        &mut self,
        msg: Self::CommandOutput,
        sender: ComponentSender<Self>,
        _root: &Self::Root,
    ) {
        // Forward command outputs as regular inputs
        sender.input(msg);
    }
}
