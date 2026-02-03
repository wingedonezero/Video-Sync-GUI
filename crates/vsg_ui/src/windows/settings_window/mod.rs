//! Settings dialog window
//!
//! 5 tabs matching PySide layout:
//! - Storage (paths)
//! - Analysis (correlation, delay selection)
//! - Chapters
//! - Merge Behavior
//! - Logging

mod logic;
mod messages;
mod model;

pub use messages::{PathField, SettingsMsg, SettingsOutput};
pub use model::SettingsModel;

use std::sync::{Arc, Mutex};

use gtk4::prelude::*;
use relm4::prelude::*;

use vsg_core::config::ConfigManager;
use vsg_core::models::{
    AnalysisMode, CorrelationMethod, DelaySelectionMode, FilteringMethod, SnapMode, SyncMode,
};

use logic::*;

/// Settings window initialization
pub struct SettingsInit {
    pub config: Arc<Mutex<ConfigManager>>,
    pub parent: Option<gtk4::Window>,
}

/// Widgets that need to be stored for value updates
pub struct SettingsWidgets {
    // Storage tab
    output_folder_entry: gtk4::Entry,
    temp_root_entry: gtk4::Entry,
    logs_folder_entry: gtk4::Entry,
}

/// Settings dialog component
pub struct SettingsWindow {
    model: SettingsModel,
    config: Arc<Mutex<ConfigManager>>,
    widgets: SettingsWidgets,
}

#[relm4::component(pub)]
impl Component for SettingsWindow {
    type Init = SettingsInit;
    type Input = SettingsMsg;
    type Output = SettingsOutput;
    type CommandOutput = ();

    view! {
        gtk4::Window {
            set_title: Some("Settings"),
            set_default_width: 700,
            set_default_height: 600,
            set_modal: true,
            set_resizable: true,

            gtk4::Box {
                set_orientation: gtk4::Orientation::Vertical,
                set_margin_all: 12,
                set_spacing: 12,

                #[name = "notebook"]
                gtk4::Notebook {
                    set_vexpand: true,
                },

                // Button row
                gtk4::Box {
                    set_orientation: gtk4::Orientation::Horizontal,
                    set_spacing: 12,
                    set_halign: gtk4::Align::End,

                    gtk4::Button {
                        set_label: "Cancel",
                        connect_clicked => SettingsMsg::Cancel,
                    },

                    gtk4::Button {
                        set_label: "Save",
                        add_css_class: "suggested-action",
                        connect_clicked => SettingsMsg::Save,
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
        // Load settings from config
        let (paths, logging, analysis, chapters, postprocess) = {
            let cfg = init.config.lock().unwrap();
            let s = cfg.settings();
            (
                s.paths.clone(),
                s.logging.clone(),
                s.analysis.clone(),
                s.chapters.clone(),
                s.postprocess.clone(),
            )
        };

        // Create entry widgets for storage tab
        let output_folder_entry = gtk4::Entry::builder()
            .hexpand(true)
            .text(&paths.output_folder)
            .build();

        let temp_root_entry = gtk4::Entry::builder()
            .hexpand(true)
            .text(&paths.temp_root)
            .build();

        let logs_folder_entry = gtk4::Entry::builder()
            .hexpand(true)
            .text(&paths.logs_folder)
            .build();

        // Connect entry changed signals
        {
            let sender = sender.clone();
            output_folder_entry.connect_changed(move |e| {
                sender.input(SettingsMsg::SetOutputFolder(e.text().to_string()));
            });
        }
        {
            let sender = sender.clone();
            temp_root_entry.connect_changed(move |e| {
                sender.input(SettingsMsg::SetTempRoot(e.text().to_string()));
            });
        }
        {
            let sender = sender.clone();
            logs_folder_entry.connect_changed(move |e| {
                sender.input(SettingsMsg::SetLogsFolder(e.text().to_string()));
            });
        }

        let stored_widgets = SettingsWidgets {
            output_folder_entry: output_folder_entry.clone(),
            temp_root_entry: temp_root_entry.clone(),
            logs_folder_entry: logs_folder_entry.clone(),
        };

        let model_data = SettingsModel::from_settings(
            paths.clone(),
            logging.clone(),
            analysis.clone(),
            chapters.clone(),
            postprocess.clone(),
        );

        let model = SettingsWindow {
            model: model_data,
            config: init.config,
            widgets: stored_widgets,
        };

        // Set parent window
        if let Some(parent) = init.parent {
            root.set_transient_for(Some(&parent));
        }

        let widgets = view_output!();

        // Build and add tabs to notebook
        let notebook = &widgets.notebook;

        // === Tab 1: Storage ===
        let storage_page = build_storage_tab(
            &output_folder_entry,
            &temp_root_entry,
            &logs_folder_entry,
            &sender,
        );
        notebook.append_page(&storage_page, Some(&gtk4::Label::new(Some("Storage"))));

        // === Tab 2: Analysis ===
        let analysis_page = build_analysis_tab(&analysis, &sender);
        notebook.append_page(&analysis_page, Some(&gtk4::Label::new(Some("Analysis"))));

        // === Tab 3: Chapters ===
        let chapters_page = build_chapters_tab(&chapters, &sender);
        notebook.append_page(&chapters_page, Some(&gtk4::Label::new(Some("Chapters"))));

        // === Tab 4: Merge Behavior ===
        let merge_page = build_merge_tab(&postprocess, &sender);
        notebook.append_page(&merge_page, Some(&gtk4::Label::new(Some("Merge Behavior"))));

        // === Tab 5: Logging ===
        let logging_page = build_logging_tab(&logging, &sender);
        notebook.append_page(&logging_page, Some(&gtk4::Label::new(Some("Logging"))));

        // Show the window
        root.present();

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, root: &Self::Root) {
        self.model.mark_modified();

        match msg {
            // Storage tab
            SettingsMsg::SetOutputFolder(v) => self.model.paths.output_folder = v,
            SettingsMsg::SetTempRoot(v) => self.model.paths.temp_root = v,
            SettingsMsg::SetLogsFolder(v) => self.model.paths.logs_folder = v,

            SettingsMsg::BrowseOutputFolder => {
                self.browse_folder(PathField::OutputFolder, sender.clone());
            }
            SettingsMsg::BrowseTempRoot => {
                self.browse_folder(PathField::TempRoot, sender.clone());
            }
            SettingsMsg::BrowseLogsFolder => {
                self.browse_folder(PathField::LogsFolder, sender.clone());
            }
            SettingsMsg::BrowseResult { field, path } => {
                if let Some(path) = path {
                    match field {
                        PathField::OutputFolder => {
                            self.model.paths.output_folder = path.clone();
                            self.widgets.output_folder_entry.set_text(&path);
                        }
                        PathField::TempRoot => {
                            self.model.paths.temp_root = path.clone();
                            self.widgets.temp_root_entry.set_text(&path);
                        }
                        PathField::LogsFolder => {
                            self.model.paths.logs_folder = path.clone();
                            self.widgets.logs_folder_entry.set_text(&path);
                        }
                    }
                }
            }

            // Analysis tab
            SettingsMsg::SetAnalysisMode(v) => self.model.analysis.mode = v,
            SettingsMsg::SetCorrelationMethod(v) => self.model.analysis.correlation_method = v,
            SettingsMsg::SetLangSource1(v) => {
                self.model.analysis.lang_source1 = if v.is_empty() { None } else { Some(v) }
            }
            SettingsMsg::SetLangOthers(v) => {
                self.model.analysis.lang_others = if v.is_empty() { None } else { Some(v) }
            }
            SettingsMsg::SetChunkCount(v) => self.model.analysis.chunk_count = v,
            SettingsMsg::SetChunkDuration(v) => self.model.analysis.chunk_duration = v,
            SettingsMsg::SetMinMatchPct(v) => self.model.analysis.min_match_pct = v,
            SettingsMsg::SetMinAcceptedChunks(v) => self.model.analysis.min_accepted_chunks = v,
            SettingsMsg::SetScanStartPct(v) => self.model.analysis.scan_start_pct = v,
            SettingsMsg::SetScanEndPct(v) => self.model.analysis.scan_end_pct = v,
            SettingsMsg::ToggleUseSoxr(v) => self.model.analysis.use_soxr = v,
            SettingsMsg::ToggleAudioPeakFit(v) => self.model.analysis.audio_peak_fit = v,
            SettingsMsg::SetFilteringMethod(v) => self.model.analysis.filtering_method = v,
            SettingsMsg::SetFilterLowCutoff(v) => self.model.analysis.filter_low_cutoff_hz = v,
            SettingsMsg::SetFilterHighCutoff(v) => self.model.analysis.filter_high_cutoff_hz = v,
            SettingsMsg::ToggleMultiCorrelation(v) => {
                self.model.analysis.multi_correlation_enabled = v
            }
            SettingsMsg::ToggleMultiCorrScc(v) => self.model.analysis.multi_corr_scc = v,
            SettingsMsg::ToggleMultiCorrGccPhat(v) => self.model.analysis.multi_corr_gcc_phat = v,
            SettingsMsg::ToggleMultiCorrGccScot(v) => self.model.analysis.multi_corr_gcc_scot = v,
            SettingsMsg::ToggleMultiCorrWhitened(v) => self.model.analysis.multi_corr_whitened = v,
            SettingsMsg::SetDelaySelectionMode(v) => self.model.analysis.delay_selection_mode = v,
            SettingsMsg::SetFirstStableMinChunks(v) => {
                self.model.analysis.first_stable_min_chunks = v
            }
            SettingsMsg::ToggleFirstStableSkipUnstable(v) => {
                self.model.analysis.first_stable_skip_unstable = v
            }
            SettingsMsg::SetEarlyClusterWindow(v) => self.model.analysis.early_cluster_window = v,
            SettingsMsg::SetEarlyClusterThreshold(v) => {
                self.model.analysis.early_cluster_threshold = v
            }
            SettingsMsg::SetSyncMode(v) => self.model.analysis.sync_mode = v,

            // Chapters tab
            SettingsMsg::ToggleChapterRename(v) => self.model.chapters.rename = v,
            SettingsMsg::ToggleSnapEnabled(v) => self.model.chapters.snap_enabled = v,
            SettingsMsg::SetSnapMode(v) => self.model.chapters.snap_mode = v,
            SettingsMsg::SetSnapThreshold(v) => self.model.chapters.snap_threshold_ms = v,
            SettingsMsg::ToggleSnapStartsOnly(v) => self.model.chapters.snap_starts_only = v,

            // Merge tab
            SettingsMsg::ToggleDisableTrackStatsTags(v) => {
                self.model.postprocess.disable_track_stats_tags = v
            }
            SettingsMsg::ToggleDisableHeaderCompression(v) => {
                self.model.postprocess.disable_header_compression = v
            }
            SettingsMsg::ToggleApplyDialogNorm(v) => self.model.postprocess.apply_dialog_norm = v,

            // Logging tab
            SettingsMsg::ToggleCompact(v) => self.model.logging.compact = v,
            SettingsMsg::ToggleAutoscroll(v) => self.model.logging.autoscroll = v,
            SettingsMsg::SetErrorTail(v) => self.model.logging.error_tail = v,
            SettingsMsg::SetProgressStep(v) => self.model.logging.progress_step = v,
            SettingsMsg::ToggleShowOptionsPretty(v) => self.model.logging.show_options_pretty = v,
            SettingsMsg::ToggleShowOptionsJson(v) => self.model.logging.show_options_json = v,
            SettingsMsg::ToggleArchiveLogs(v) => self.model.logging.archive_logs = v,

            // Dialog actions
            SettingsMsg::Save => {
                self.save_settings();
                let _ = sender.output(SettingsOutput::Saved);
                root.close();
            }
            SettingsMsg::Cancel => {
                let _ = sender.output(SettingsOutput::Cancelled);
                root.close();
            }
        }
    }
}

impl SettingsWindow {
    fn browse_folder(&self, field: PathField, sender: ComponentSender<Self>) {
        relm4::spawn_local(async move {
            let dialog = gtk4::FileDialog::builder()
                .title("Select Folder")
                .modal(true)
                .build();

            match dialog.select_folder_future(None::<&gtk4::Window>).await {
                Ok(file) => {
                    if let Some(path) = file.path() {
                        sender.input(SettingsMsg::BrowseResult {
                            field,
                            path: Some(path.to_string_lossy().to_string()),
                        });
                    }
                }
                Err(_) => {
                    sender.input(SettingsMsg::BrowseResult { field, path: None });
                }
            }
        });
    }

    fn save_settings(&self) {
        let mut cfg = self.config.lock().unwrap();
        let settings = cfg.settings_mut();

        // Copy all settings from model
        settings.paths = self.model.paths.clone();
        settings.logging = self.model.logging.clone();
        settings.analysis = self.model.analysis.clone();
        settings.chapters = self.model.chapters.clone();
        settings.postprocess = self.model.postprocess.clone();

        // Save to file
        if let Err(e) = cfg.save() {
            tracing::error!("Failed to save settings: {}", e);
        }
    }
}

// === Tab Builder Functions ===

fn build_storage_tab(
    output_folder_entry: &gtk4::Entry,
    temp_root_entry: &gtk4::Entry,
    logs_folder_entry: &gtk4::Entry,
    sender: &ComponentSender<SettingsWindow>,
) -> gtk4::Box {
    let page = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(12)
        .margin_bottom(12)
        .margin_start(12)
        .margin_end(12)
        .spacing(12)
        .build();

    // Description
    let desc = gtk4::Label::builder()
        .label("Configure file storage locations")
        .xalign(0.0)
        .css_classes(["dim-label"])
        .build();
    page.append(&desc);

    // Output Folder row
    output_folder_entry.set_tooltip_text(Some("Directory where merged output files will be saved"));
    let row1 = create_path_row_with_tooltip(
        "Output Folder:",
        "Directory for merged output files",
        output_folder_entry.clone(),
        {
            let sender = sender.clone();
            move || sender.input(SettingsMsg::BrowseOutputFolder)
        },
    );
    page.append(&row1);

    // Temp Root row
    temp_root_entry.set_tooltip_text(Some(
        "Root directory for temporary working files during processing",
    ));
    let row2 = create_path_row_with_tooltip(
        "Temp Root:",
        "Root directory for temporary files during processing",
        temp_root_entry.clone(),
        {
            let sender = sender.clone();
            move || sender.input(SettingsMsg::BrowseTempRoot)
        },
    );
    page.append(&row2);

    // Logs Folder row
    logs_folder_entry.set_tooltip_text(Some("Directory where job logs are saved"));
    let row3 = create_path_row_with_tooltip(
        "Logs Folder:",
        "Directory for job log files",
        logs_folder_entry.clone(),
        {
            let sender = sender.clone();
            move || sender.input(SettingsMsg::BrowseLogsFolder)
        },
    );
    page.append(&row3);

    page
}

fn create_path_row_with_tooltip<F: Fn() + 'static>(
    label: &str,
    tooltip: &str,
    entry: gtk4::Entry,
    on_browse: F,
) -> gtk4::Box {
    let row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();

    let lbl = gtk4::Label::builder()
        .label(label)
        .width_chars(15)
        .xalign(0.0)
        .tooltip_text(tooltip)
        .build();
    row.append(&lbl);

    row.append(&entry);

    let btn = gtk4::Button::builder().label("Browse...").build();
    btn.connect_clicked(move |_| on_browse());
    row.append(&btn);

    row
}

fn build_analysis_tab(
    analysis: &vsg_core::config::AnalysisSettings,
    sender: &ComponentSender<SettingsWindow>,
) -> gtk4::ScrolledWindow {
    let scroll = gtk4::ScrolledWindow::builder()
        .hscrollbar_policy(gtk4::PolicyType::Never)
        .vscrollbar_policy(gtk4::PolicyType::Automatic)
        .build();

    let page = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(12)
        .margin_bottom(12)
        .margin_start(12)
        .margin_end(12)
        .spacing(12)
        .build();

    // === Analysis Mode Frame ===
    let mode_frame = gtk4::Frame::builder().label("Analysis Mode").build();
    let mode_box = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(8)
        .margin_bottom(8)
        .margin_start(8)
        .margin_end(8)
        .spacing(8)
        .build();

    let mode_row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();
    let mode_label = gtk4::Label::builder()
        .label("Mode:")
        .width_chars(18)
        .xalign(0.0)
        .build();
    mode_label.set_tooltip_text(Some(
        "Choose between audio correlation (compares audio waveforms) or video diff analysis",
    ));
    mode_row.append(&mode_label);
    let mode_combo = gtk4::DropDown::builder()
        .model(&gtk4::StringList::new(&["Audio Correlation", "Video Diff"]))
        .hexpand(true)
        .tooltip_text("Audio Correlation: Cross-correlate audio waveforms to find sync offset\nVideo Diff: Compare video frames (experimental)")
        .build();
    let mode_idx = match analysis.mode {
        AnalysisMode::AudioCorrelation => 0,
        AnalysisMode::VideoDiff => 1,
    };
    mode_combo.set_selected(mode_idx);
    {
        let sender = sender.clone();
        mode_combo.connect_selected_notify(move |dd| {
            let mode = match dd.selected() {
                0 => AnalysisMode::AudioCorrelation,
                _ => AnalysisMode::VideoDiff,
            };
            sender.input(SettingsMsg::SetAnalysisMode(mode));
        });
    }
    mode_row.append(&mode_combo);
    mode_box.append(&mode_row);
    mode_frame.set_child(Some(&mode_box));
    page.append(&mode_frame);

    // === Correlation Frame ===
    let corr_frame = gtk4::Frame::builder().label("Correlation").build();
    let corr_box = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(8)
        .margin_bottom(8)
        .margin_start(8)
        .margin_end(8)
        .spacing(8)
        .build();

    // Correlation method dropdown
    let method_row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();
    let method_label = gtk4::Label::builder()
        .label("Method:")
        .width_chars(18)
        .xalign(0.0)
        .build();
    method_label.set_tooltip_text(Some("Algorithm used to correlate audio signals"));
    method_row.append(&method_label);
    let method_combo = gtk4::DropDown::builder()
        .model(&gtk4::StringList::new(&[
            "Standard Correlation (SCC)",
            "Phase Correlation (GCC-PHAT)",
            "GCC-SCOT",
            "Whitened Cross-Correlation",
        ]))
        .hexpand(true)
        .tooltip_text("SCC: Standard cross-correlation, good general purpose\nGCC-PHAT: Phase transform, sharp peaks, noise resistant\nGCC-SCOT: Smoothed coherence, balanced\nWhitened: Robust to spectral differences")
        .build();
    method_combo.set_selected(correlation_method_index(&analysis.correlation_method));
    {
        let sender = sender.clone();
        method_combo.connect_selected_notify(move |dd| {
            let method = match dd.selected() {
                0 => CorrelationMethod::Scc,
                1 => CorrelationMethod::GccPhat,
                2 => CorrelationMethod::GccScot,
                _ => CorrelationMethod::Whitened,
            };
            sender.input(SettingsMsg::SetCorrelationMethod(method));
        });
    }
    method_row.append(&method_combo);
    corr_box.append(&method_row);

    // Language filters
    let lang1_row = create_entry_row_with_tooltip(
        "Source 1 Language:",
        analysis.lang_source1.as_deref().unwrap_or(""),
        "e.g., eng (empty = auto)",
        "ISO 639-2 language code for source 1 audio track selection (e.g., eng, jpn, deu)",
        {
            let sender = sender.clone();
            move |text| sender.input(SettingsMsg::SetLangSource1(text))
        },
    );
    corr_box.append(&lang1_row);

    let lang2_row = create_entry_row_with_tooltip(
        "Other Languages:",
        analysis.lang_others.as_deref().unwrap_or(""),
        "e.g., jpn (empty = auto)",
        "ISO 639-2 language code for other sources' audio track selection",
        {
            let sender = sender.clone();
            move |text| sender.input(SettingsMsg::SetLangOthers(text))
        },
    );
    corr_box.append(&lang2_row);

    corr_frame.set_child(Some(&corr_box));
    page.append(&corr_frame);

    // === Chunk Settings Frame ===
    let chunk_frame = gtk4::Frame::builder().label("Chunk Settings").build();
    let chunk_box = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(8)
        .margin_bottom(8)
        .margin_start(8)
        .margin_end(8)
        .spacing(8)
        .build();

    chunk_box.append(&create_spin_row_with_tooltip(
        "Chunk Count:",
        analysis.chunk_count as f64,
        1.0,
        100.0,
        1.0,
        0,
        "Number of audio segments to analyze. More chunks = more accurate but slower",
        {
            let sender = sender.clone();
            move |v| sender.input(SettingsMsg::SetChunkCount(v as u32))
        },
    ));

    chunk_box.append(&create_spin_row_with_tooltip(
        "Chunk Duration (s):",
        analysis.chunk_duration as f64,
        5.0,
        120.0,
        1.0,
        0,
        "Duration of each audio chunk in seconds. Longer = more context but slower",
        {
            let sender = sender.clone();
            move |v| sender.input(SettingsMsg::SetChunkDuration(v as u32))
        },
    ));

    chunk_box.append(&create_spin_row_with_tooltip(
        "Min Match %:",
        analysis.min_match_pct,
        0.0,
        100.0,
        0.5,
        1,
        "Minimum correlation percentage to accept a chunk result. Lower = more lenient",
        {
            let sender = sender.clone();
            move |v| sender.input(SettingsMsg::SetMinMatchPct(v))
        },
    ));

    chunk_box.append(&create_spin_row_with_tooltip(
        "Min Accepted Chunks:",
        analysis.min_accepted_chunks as f64,
        1.0,
        50.0,
        1.0,
        0,
        "Minimum number of chunks that must pass for valid analysis",
        {
            let sender = sender.clone();
            move |v| sender.input(SettingsMsg::SetMinAcceptedChunks(v as u32))
        },
    ));

    // Scan range row
    let scan_row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();
    let scan_label = gtk4::Label::builder()
        .label("Scan Range (%):")
        .width_chars(18)
        .xalign(0.0)
        .build();
    scan_label.set_tooltip_text(Some(
        "Percentage of file to scan. Avoids intros/credits (e.g., 5-95%)",
    ));
    scan_row.append(&scan_label);
    let scan_start = gtk4::SpinButton::builder()
        .adjustment(&gtk4::Adjustment::new(
            analysis.scan_start_pct,
            0.0,
            100.0,
            1.0,
            5.0,
            0.0,
        ))
        .tooltip_text("Start position as percentage of file duration")
        .build();
    {
        let sender = sender.clone();
        scan_start
            .connect_value_changed(move |s| sender.input(SettingsMsg::SetScanStartPct(s.value())));
    }
    scan_row.append(&scan_start);
    scan_row.append(&gtk4::Label::new(Some("to")));
    let scan_end = gtk4::SpinButton::builder()
        .adjustment(&gtk4::Adjustment::new(
            analysis.scan_end_pct,
            0.0,
            100.0,
            1.0,
            5.0,
            0.0,
        ))
        .tooltip_text("End position as percentage of file duration")
        .build();
    {
        let sender = sender.clone();
        scan_end
            .connect_value_changed(move |s| sender.input(SettingsMsg::SetScanEndPct(s.value())));
    }
    scan_row.append(&scan_end);
    chunk_box.append(&scan_row);

    chunk_frame.set_child(Some(&chunk_box));
    page.append(&chunk_frame);

    // === Audio Processing Frame ===
    let audio_frame = gtk4::Frame::builder().label("Audio Processing").build();
    let audio_box = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(8)
        .margin_bottom(8)
        .margin_start(8)
        .margin_end(8)
        .spacing(8)
        .build();

    let soxr_check = gtk4::CheckButton::builder()
        .label("Use SOXR high-quality resampling")
        .active(analysis.use_soxr)
        .tooltip_text("Use high-quality SOXR resampler via FFmpeg for better audio quality")
        .build();
    {
        let sender = sender.clone();
        soxr_check
            .connect_toggled(move |b| sender.input(SettingsMsg::ToggleUseSoxr(b.is_active())));
    }
    audio_box.append(&soxr_check);

    let peak_check = gtk4::CheckButton::builder()
        .label("Use quadratic peak fitting")
        .active(analysis.audio_peak_fit)
        .tooltip_text("Interpolate correlation peak for sub-sample accuracy (recommended)")
        .build();
    {
        let sender = sender.clone();
        peak_check
            .connect_toggled(move |b| sender.input(SettingsMsg::ToggleAudioPeakFit(b.is_active())));
    }
    audio_box.append(&peak_check);

    // Filtering dropdown
    let filter_row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();
    let filter_label = gtk4::Label::builder()
        .label("Filtering:")
        .width_chars(18)
        .xalign(0.0)
        .build();
    filter_label.set_tooltip_text(Some("Apply frequency filter before correlation"));
    filter_row.append(&filter_label);
    let filter_combo = gtk4::DropDown::builder()
        .model(&gtk4::StringList::new(&["None", "Low Pass", "Band Pass", "High Pass"]))
        .hexpand(true)
        .tooltip_text("None: No filtering\nLow Pass: Remove high frequencies\nBand Pass: Keep dialogue frequencies (300-3400Hz)\nHigh Pass: Remove low frequencies")
        .build();
    filter_combo.set_selected(filtering_method_index(&analysis.filtering_method));
    {
        let sender = sender.clone();
        filter_combo.connect_selected_notify(move |dd| {
            let method = match dd.selected() {
                0 => FilteringMethod::None,
                1 => FilteringMethod::LowPass,
                2 => FilteringMethod::BandPass,
                _ => FilteringMethod::HighPass,
            };
            sender.input(SettingsMsg::SetFilteringMethod(method));
        });
    }
    filter_row.append(&filter_combo);
    audio_box.append(&filter_row);

    // Filter cutoffs
    let cutoff_row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();
    let cutoff_label = gtk4::Label::builder()
        .label("Filter Cutoffs (Hz):")
        .width_chars(18)
        .xalign(0.0)
        .build();
    cutoff_label.set_tooltip_text(Some(
        "Frequency range for band-pass filter (default 300-3400Hz for dialogue)",
    ));
    cutoff_row.append(&cutoff_label);
    let low_spin = gtk4::SpinButton::builder()
        .adjustment(&gtk4::Adjustment::new(
            analysis.filter_low_cutoff_hz,
            20.0,
            5000.0,
            10.0,
            100.0,
            0.0,
        ))
        .tooltip_text("Low cutoff frequency in Hz")
        .build();
    {
        let sender = sender.clone();
        low_spin.connect_value_changed(move |s| {
            sender.input(SettingsMsg::SetFilterLowCutoff(s.value()))
        });
    }
    cutoff_row.append(&low_spin);
    cutoff_row.append(&gtk4::Label::new(Some("-")));
    let high_spin = gtk4::SpinButton::builder()
        .adjustment(&gtk4::Adjustment::new(
            analysis.filter_high_cutoff_hz,
            100.0,
            20000.0,
            100.0,
            500.0,
            0.0,
        ))
        .tooltip_text("High cutoff frequency in Hz")
        .build();
    {
        let sender = sender.clone();
        high_spin.connect_value_changed(move |s| {
            sender.input(SettingsMsg::SetFilterHighCutoff(s.value()))
        });
    }
    cutoff_row.append(&high_spin);
    audio_box.append(&cutoff_row);

    audio_frame.set_child(Some(&audio_box));
    page.append(&audio_frame);

    // === Delay Selection Frame ===
    let delay_frame = gtk4::Frame::builder().label("Delay Selection").build();
    let delay_box = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(8)
        .margin_bottom(8)
        .margin_start(8)
        .margin_end(8)
        .spacing(8)
        .build();

    // Selection mode dropdown
    let sel_mode_row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();
    let sel_mode_label = gtk4::Label::builder()
        .label("Selection Mode:")
        .width_chars(18)
        .xalign(0.0)
        .build();
    sel_mode_label.set_tooltip_text(Some(
        "How to select final delay from multiple chunk measurements",
    ));
    sel_mode_row.append(&sel_mode_label);
    let sel_mode_combo = gtk4::DropDown::builder()
        .model(&gtk4::StringList::new(&[
            "Mode (Most Common)",
            "Mode (Clustered)",
            "Mode (Early Cluster)",
            "First Stable",
            "Average",
        ]))
        .hexpand(true)
        .tooltip_text("Mode: Most common value\nClustered: Groups ±1ms values\nEarly Cluster: Prefers early file matches\nFirst Stable: First consistent segment\nAverage: Mean of all values")
        .build();
    sel_mode_combo.set_selected(delay_selection_mode_index(&analysis.delay_selection_mode));
    {
        let sender = sender.clone();
        sel_mode_combo.connect_selected_notify(move |dd| {
            let mode = match dd.selected() {
                0 => DelaySelectionMode::Mode,
                1 => DelaySelectionMode::ModeClustered,
                2 => DelaySelectionMode::ModeEarly,
                3 => DelaySelectionMode::FirstStable,
                _ => DelaySelectionMode::Average,
            };
            sender.input(SettingsMsg::SetDelaySelectionMode(mode));
        });
    }
    sel_mode_row.append(&sel_mode_combo);
    delay_box.append(&sel_mode_row);

    // Sync mode dropdown
    let sync_row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();
    let sync_label = gtk4::Label::builder()
        .label("Sync Mode:")
        .width_chars(18)
        .xalign(0.0)
        .build();
    sync_label.set_tooltip_text(Some("How to handle negative delays in output"));
    sync_row.append(&sync_label);
    let sync_combo = gtk4::DropDown::builder()
        .model(&gtk4::StringList::new(&["Positive Only (Shift all)", "Allow Negative"]))
        .hexpand(true)
        .tooltip_text("Positive Only: Shift all tracks so no negative delays (required for muxing audio)\nAllow Negative: Keep original delays (some players may not support)")
        .build();
    sync_combo.set_selected(sync_mode_index(&analysis.sync_mode));
    {
        let sender = sender.clone();
        sync_combo.connect_selected_notify(move |dd| {
            let mode = match dd.selected() {
                0 => SyncMode::PositiveOnly,
                _ => SyncMode::AllowNegative,
            };
            sender.input(SettingsMsg::SetSyncMode(mode));
        });
    }
    sync_row.append(&sync_combo);
    delay_box.append(&sync_row);

    // First Stable settings
    delay_box.append(&create_spin_row_with_tooltip(
        "First Stable Min:",
        analysis.first_stable_min_chunks as f64,
        1.0,
        20.0,
        1.0,
        0,
        "Minimum consecutive chunks with same delay to consider stable",
        {
            let sender = sender.clone();
            move |v| sender.input(SettingsMsg::SetFirstStableMinChunks(v as u32))
        },
    ));

    let skip_check = gtk4::CheckButton::builder()
        .label("Skip unstable segments")
        .active(analysis.first_stable_skip_unstable)
        .tooltip_text("Skip over segments that don't meet stability threshold")
        .build();
    {
        let sender = sender.clone();
        skip_check.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleFirstStableSkipUnstable(b.is_active()))
        });
    }
    delay_box.append(&skip_check);

    // Early Cluster settings
    delay_box.append(&create_spin_row_with_tooltip(
        "Early Cluster Window:",
        analysis.early_cluster_window as f64,
        1.0,
        50.0,
        1.0,
        0,
        "Number of early chunks to prioritize for Early Cluster mode",
        {
            let sender = sender.clone();
            move |v| sender.input(SettingsMsg::SetEarlyClusterWindow(v as u32))
        },
    ));

    delay_box.append(&create_spin_row_with_tooltip(
        "Early Threshold:",
        analysis.early_cluster_threshold as f64,
        1.0,
        50.0,
        1.0,
        0,
        "Minimum chunks in early window for cluster to be preferred",
        {
            let sender = sender.clone();
            move |v| sender.input(SettingsMsg::SetEarlyClusterThreshold(v as u32))
        },
    ));

    delay_frame.set_child(Some(&delay_box));
    page.append(&delay_frame);

    // === Multi-Correlation Frame ===
    let multi_frame = gtk4::Frame::builder()
        .label("Multi-Correlation (Compare All Methods)")
        .build();
    let multi_box = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(8)
        .margin_bottom(8)
        .margin_start(8)
        .margin_end(8)
        .spacing(8)
        .build();

    let multi_enable = gtk4::CheckButton::builder()
        .label("Enable multi-correlation comparison")
        .active(analysis.multi_correlation_enabled)
        .tooltip_text(
            "Run multiple correlation methods and compare results (for analysis/debugging)",
        )
        .build();
    {
        let sender = sender.clone();
        multi_enable.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleMultiCorrelation(b.is_active()))
        });
    }
    multi_box.append(&multi_enable);

    let methods_row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(16)
        .build();

    let scc_check = gtk4::CheckButton::builder()
        .label("SCC")
        .active(analysis.multi_corr_scc)
        .tooltip_text("Standard Cross-Correlation")
        .build();
    {
        let sender = sender.clone();
        scc_check
            .connect_toggled(move |b| sender.input(SettingsMsg::ToggleMultiCorrScc(b.is_active())));
    }
    methods_row.append(&scc_check);

    let phat_check = gtk4::CheckButton::builder()
        .label("GCC-PHAT")
        .active(analysis.multi_corr_gcc_phat)
        .tooltip_text("Generalized Cross-Correlation with Phase Transform")
        .build();
    {
        let sender = sender.clone();
        phat_check.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleMultiCorrGccPhat(b.is_active()))
        });
    }
    methods_row.append(&phat_check);

    let scot_check = gtk4::CheckButton::builder()
        .label("GCC-SCOT")
        .active(analysis.multi_corr_gcc_scot)
        .tooltip_text("GCC with Smoothed Coherence Transform")
        .build();
    {
        let sender = sender.clone();
        scot_check.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleMultiCorrGccScot(b.is_active()))
        });
    }
    methods_row.append(&scot_check);

    let whitened_check = gtk4::CheckButton::builder()
        .label("Whitened")
        .active(analysis.multi_corr_whitened)
        .tooltip_text("Whitened Cross-Correlation (robust to spectral differences)")
        .build();
    {
        let sender = sender.clone();
        whitened_check.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleMultiCorrWhitened(b.is_active()))
        });
    }
    methods_row.append(&whitened_check);

    multi_box.append(&methods_row);
    multi_frame.set_child(Some(&multi_box));
    page.append(&multi_frame);

    scroll.set_child(Some(&page));
    scroll
}

fn build_chapters_tab(
    chapters: &vsg_core::config::ChapterSettings,
    sender: &ComponentSender<SettingsWindow>,
) -> gtk4::Box {
    let page = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(12)
        .margin_bottom(12)
        .margin_start(12)
        .margin_end(12)
        .spacing(12)
        .build();

    let desc = gtk4::Label::builder()
        .label("Configure chapter handling")
        .xalign(0.0)
        .css_classes(["dim-label"])
        .build();
    page.append(&desc);

    let rename_check = gtk4::CheckButton::builder()
        .label("Rename chapters")
        .active(chapters.rename)
        .tooltip_text("Rename chapters to standard format (Chapter 01, Chapter 02, etc.)")
        .build();
    {
        let sender = sender.clone();
        rename_check.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleChapterRename(b.is_active()))
        });
    }
    page.append(&rename_check);

    // Keyframe Snapping frame
    let snap_frame = gtk4::Frame::builder().label("Keyframe Snapping").build();
    let snap_box = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(8)
        .margin_bottom(8)
        .margin_start(8)
        .margin_end(8)
        .spacing(8)
        .build();

    let snap_enable = gtk4::CheckButton::builder()
        .label("Enable chapter snapping to keyframes")
        .active(chapters.snap_enabled)
        .tooltip_text("Adjust chapter markers to align with video keyframes for clean seeking")
        .build();
    {
        let sender = sender.clone();
        snap_enable
            .connect_toggled(move |b| sender.input(SettingsMsg::ToggleSnapEnabled(b.is_active())));
    }
    snap_box.append(&snap_enable);

    // Snap mode dropdown
    let snap_mode_row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();
    let snap_mode_label = gtk4::Label::builder()
        .label("Snap Mode:")
        .width_chars(15)
        .xalign(0.0)
        .build();
    snap_mode_label.set_tooltip_text(Some(
        "Which keyframe to snap to relative to chapter position",
    ));
    snap_mode_row.append(&snap_mode_label);
    let snap_mode_combo = gtk4::DropDown::builder()
        .model(&gtk4::StringList::new(&["Previous", "Nearest", "Next"]))
        .hexpand(true)
        .tooltip_text("Previous: Snap to keyframe before chapter\nNearest: Snap to closest keyframe\nNext: Snap to keyframe after chapter")
        .build();
    snap_mode_combo.set_selected(snap_mode_index(&chapters.snap_mode));
    {
        let sender = sender.clone();
        snap_mode_combo.connect_selected_notify(move |dd| {
            let mode = match dd.selected() {
                0 => SnapMode::Previous,
                1 => SnapMode::Nearest,
                _ => SnapMode::Next,
            };
            sender.input(SettingsMsg::SetSnapMode(mode));
        });
    }
    snap_mode_row.append(&snap_mode_combo);
    snap_box.append(&snap_mode_row);

    snap_box.append(&create_spin_row_with_tooltip(
        "Snap Threshold (ms):",
        chapters.snap_threshold_ms as f64,
        0.0,
        5000.0,
        10.0,
        0,
        "Maximum distance in milliseconds to search for keyframe",
        {
            let sender = sender.clone();
            move |v| sender.input(SettingsMsg::SetSnapThreshold(v as u32))
        },
    ));

    let starts_only = gtk4::CheckButton::builder()
        .label("Snap chapter starts only (not ends)")
        .active(chapters.snap_starts_only)
        .tooltip_text("Only snap chapter start times, leave end times unchanged")
        .build();
    {
        let sender = sender.clone();
        starts_only.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleSnapStartsOnly(b.is_active()))
        });
    }
    snap_box.append(&starts_only);

    snap_frame.set_child(Some(&snap_box));
    page.append(&snap_frame);

    page
}

fn build_merge_tab(
    postprocess: &vsg_core::config::PostProcessSettings,
    sender: &ComponentSender<SettingsWindow>,
) -> gtk4::Box {
    let page = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(12)
        .margin_bottom(12)
        .margin_start(12)
        .margin_end(12)
        .spacing(12)
        .build();

    let desc = gtk4::Label::builder()
        .label("Configure mkvmerge output options")
        .xalign(0.0)
        .css_classes(["dim-label"])
        .build();
    page.append(&desc);

    let stats_check = gtk4::CheckButton::builder()
        .label("Disable track statistics tags")
        .active(postprocess.disable_track_stats_tags)
        .tooltip_text("Don't write track statistics tags (duration, bitrate, etc.) to output file")
        .build();
    {
        let sender = sender.clone();
        stats_check.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleDisableTrackStatsTags(b.is_active()))
        });
    }
    page.append(&stats_check);

    let compression_check = gtk4::CheckButton::builder()
        .label("Disable header compression")
        .active(postprocess.disable_header_compression)
        .tooltip_text("Disable header compression for all tracks (recommended for compatibility)")
        .build();
    {
        let sender = sender.clone();
        compression_check.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleDisableHeaderCompression(b.is_active()))
        });
    }
    page.append(&compression_check);

    let norm_check = gtk4::CheckButton::builder()
        .label("Apply dialog normalization gain")
        .active(postprocess.apply_dialog_norm)
        .tooltip_text("Apply dialog normalization gain adjustment to audio tracks")
        .build();
    {
        let sender = sender.clone();
        norm_check.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleApplyDialogNorm(b.is_active()))
        });
    }
    page.append(&norm_check);

    page
}

fn build_logging_tab(
    logging: &vsg_core::config::LoggingSettings,
    sender: &ComponentSender<SettingsWindow>,
) -> gtk4::Box {
    let page = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Vertical)
        .margin_top(12)
        .margin_bottom(12)
        .margin_start(12)
        .margin_end(12)
        .spacing(12)
        .build();

    let desc = gtk4::Label::builder()
        .label("Configure logging behavior")
        .xalign(0.0)
        .css_classes(["dim-label"])
        .build();
    page.append(&desc);

    let compact_check = gtk4::CheckButton::builder()
        .label("Use compact log format")
        .active(logging.compact)
        .tooltip_text("Use shorter, more compact log messages")
        .build();
    {
        let sender = sender.clone();
        compact_check
            .connect_toggled(move |b| sender.input(SettingsMsg::ToggleCompact(b.is_active())));
    }
    page.append(&compact_check);

    let autoscroll_check = gtk4::CheckButton::builder()
        .label("Auto-scroll log output")
        .active(logging.autoscroll)
        .tooltip_text("Automatically scroll to show latest log messages")
        .build();
    {
        let sender = sender.clone();
        autoscroll_check
            .connect_toggled(move |b| sender.input(SettingsMsg::ToggleAutoscroll(b.is_active())));
    }
    page.append(&autoscroll_check);

    page.append(&create_spin_row_with_tooltip(
        "Error tail lines:",
        logging.error_tail as f64,
        1.0,
        200.0,
        1.0,
        0,
        "Number of error log lines to show in error summary",
        {
            let sender = sender.clone();
            move |v| sender.input(SettingsMsg::SetErrorTail(v as u32))
        },
    ));

    page.append(&create_spin_row_with_tooltip(
        "Progress step %:",
        logging.progress_step as f64,
        1.0,
        100.0,
        1.0,
        0,
        "Progress update frequency (lower = more frequent updates)",
        {
            let sender = sender.clone();
            move |v| sender.input(SettingsMsg::SetProgressStep(v as u32))
        },
    ));

    let pretty_check = gtk4::CheckButton::builder()
        .label("Show mkvmerge options (pretty)")
        .active(logging.show_options_pretty)
        .tooltip_text("Log mkvmerge command options in human-readable format")
        .build();
    {
        let sender = sender.clone();
        pretty_check.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleShowOptionsPretty(b.is_active()))
        });
    }
    page.append(&pretty_check);

    let json_check = gtk4::CheckButton::builder()
        .label("Show mkvmerge options (JSON)")
        .active(logging.show_options_json)
        .tooltip_text("Log mkvmerge command options as JSON (for debugging)")
        .build();
    {
        let sender = sender.clone();
        json_check.connect_toggled(move |b| {
            sender.input(SettingsMsg::ToggleShowOptionsJson(b.is_active()))
        });
    }
    page.append(&json_check);

    let archive_check = gtk4::CheckButton::builder()
        .label("Archive logs after job completion")
        .active(logging.archive_logs)
        .tooltip_text("Save job logs to logs folder after completion")
        .build();
    {
        let sender = sender.clone();
        archive_check
            .connect_toggled(move |b| sender.input(SettingsMsg::ToggleArchiveLogs(b.is_active())));
    }
    page.append(&archive_check);

    page
}

// Helper to create a row with label, entry, and tooltip
fn create_entry_row_with_tooltip<F: Fn(String) + 'static>(
    label: &str,
    initial: &str,
    placeholder: &str,
    tooltip: &str,
    on_change: F,
) -> gtk4::Box {
    let row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();

    let lbl = gtk4::Label::builder()
        .label(label)
        .width_chars(18)
        .xalign(0.0)
        .tooltip_text(tooltip)
        .build();
    row.append(&lbl);

    let entry = gtk4::Entry::builder()
        .hexpand(true)
        .text(initial)
        .placeholder_text(placeholder)
        .tooltip_text(tooltip)
        .build();
    entry.connect_changed(move |e| on_change(e.text().to_string()));
    row.append(&entry);

    row
}

// Helper to create a row with label, spin button, and tooltip
fn create_spin_row_with_tooltip<F: Fn(f64) + 'static>(
    label: &str,
    value: f64,
    min: f64,
    max: f64,
    step: f64,
    digits: u32,
    tooltip: &str,
    on_change: F,
) -> gtk4::Box {
    let row = gtk4::Box::builder()
        .orientation(gtk4::Orientation::Horizontal)
        .spacing(8)
        .build();

    let lbl = gtk4::Label::builder()
        .label(label)
        .width_chars(18)
        .xalign(0.0)
        .tooltip_text(tooltip)
        .build();
    row.append(&lbl);

    let spin = gtk4::SpinButton::builder()
        .adjustment(&gtk4::Adjustment::new(
            value,
            min,
            max,
            step,
            step * 5.0,
            0.0,
        ))
        .digits(digits)
        .hexpand(true)
        .tooltip_text(tooltip)
        .build();
    spin.connect_value_changed(move |s| on_change(s.value()));
    row.append(&spin);

    row
}
