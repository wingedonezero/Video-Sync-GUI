//! Main COSMIC Application
//!
//! Implements the cosmic::Application trait for Video Sync GUI

use cosmic::app::{Core, Task};
use cosmic::iced::widget::text;
use cosmic::iced::{Alignment, Length};
use cosmic::widget::{self, container, text_input};
use cosmic::{Application, Element};
use std::path::PathBuf;

use crate::config::AppConfig;
use crate::pages::{self, PageId};
use crate::dialogs;

/// Application ID following reverse-DNS convention
const APP_ID: &str = "io.github.wingedonezero.VideoSyncGui";

/// Application state
pub struct App {
    /// COSMIC runtime core
    core: Core,
    /// Navigation model for the nav bar
    nav: widget::segmented_button::SingleSelectModel,
    /// Current page
    current_page: PageId,
    /// Application configuration
    config: AppConfig,
    /// Python runtime state
    python_state: PythonState,
    /// Main window state
    main_state: MainWindowState,
    /// Active dialog (if any)
    active_dialog: Option<DialogType>,
    /// Log output
    log_output: String,
    /// Status message
    status: String,
    /// Progress (0-100)
    progress: u8,
    /// Job is running
    job_running: bool,
}

/// State of the Python runtime bootstrap
#[derive(Debug, Clone, Default)]
pub enum PythonState {
    #[default]
    NotStarted,
    Downloading { percent: u8 },
    Extracting,
    CreatingVenv,
    InstallingDeps,
    Ready,
    Error(String),
}

/// Main window state (input fields, etc.)
#[derive(Debug, Clone, Default)]
pub struct MainWindowState {
    /// Source 1 (Reference) path
    pub ref_input: String,
    /// Source 2 path
    pub sec_input: String,
    /// Source 3 path
    pub ter_input: String,
    /// Archive logs checkbox
    pub archive_logs: bool,
    /// Delay results
    pub delays: Vec<Option<f64>>,
}

/// Types of dialogs that can be shown
#[derive(Debug, Clone)]
pub enum DialogType {
    Settings,
    JobQueue,
    AddJob,
    ManualSelection,
}

/// Application messages
#[derive(Debug, Clone)]
pub enum Message {
    // Navigation
    NavSelect(widget::segmented_button::Entity),

    // Python bootstrap
    BootstrapProgress(PythonState),
    BootstrapComplete,
    BootstrapError(String),

    // Main window actions
    RefInputChanged(String),
    SecInputChanged(String),
    TerInputChanged(String),
    BrowseRef,
    BrowseSec,
    BrowseTer,
    ArchiveLogsToggled(bool),
    OpenSettings,
    OpenJobQueue,
    StartAnalyzeOnly,

    // Dialog actions
    CloseDialog,
    SettingsSaved,

    // Job progress
    JobProgress { percent: u8, message: String },
    JobComplete { success: bool, message: String },

    // Log updates
    LogMessage(String),

    // File dialog results
    FileSelected { target: FileTarget, path: PathBuf },

    // System
    None,
}

/// Target for file selection
#[derive(Debug, Clone)]
pub enum FileTarget {
    Reference,
    Secondary,
    Tertiary,
}

/// Application startup flags
#[derive(Debug, Clone, Default)]
pub struct Flags {
    /// Path to config file (optional)
    pub config_path: Option<PathBuf>,
}

impl Application for App {
    type Executor = cosmic::executor::Default;
    type Flags = Flags;
    type Message = Message;

    const APP_ID: &'static str = APP_ID;

    fn core(&self) -> &Core {
        &self.core
    }

    fn core_mut(&mut self) -> &mut Core {
        &mut self.core
    }

    fn init(core: Core, _flags: Self::Flags) -> (Self, Task<Self::Message>) {
        // Set up navigation
        let mut nav = widget::segmented_button::SingleSelectModel::default();
        nav.insert()
            .text("Main")
            .data(PageId::Main)
            .activate();

        let config = AppConfig::load();

        let app = Self {
            core,
            nav,
            current_page: PageId::Main,
            config,
            python_state: PythonState::NotStarted,
            main_state: MainWindowState::default(),
            active_dialog: None,
            log_output: String::new(),
            status: "Ready".to_string(),
            progress: 0,
            job_running: false,
        };

        // Start Python bootstrap in background
        let bootstrap_task = Task::perform(
            async {
                // In a real implementation, this would call the bootstrap
                // For now, simulate ready state
                tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
                Message::BootstrapComplete
            },
            |msg| msg,
        );

        (app, bootstrap_task)
    }

    fn header_start(&self) -> Vec<Element<Self::Message>> {
        vec![]
    }

    fn header_center(&self) -> Vec<Element<Self::Message>> {
        vec![text("Video/Audio Sync & Merge").size(16).into()]
    }

    fn header_end(&self) -> Vec<Element<Self::Message>> {
        vec![]
    }

    fn view(&self) -> Element<Self::Message> {
        // Check Python state first
        if !matches!(self.python_state, PythonState::Ready) {
            return self.view_bootstrap();
        }

        // Main application view
        let content = match self.current_page {
            PageId::Main => self.view_main(),
            PageId::Settings => self.view_settings_page(),
        };

        // Wrap in container with padding
        container(content)
            .width(Length::Fill)
            .height(Length::Fill)
            .padding(16)
            .into()
    }

    fn update(&mut self, message: Self::Message) -> Task<Self::Message> {
        match message {
            Message::NavSelect(entity) => {
                self.nav.activate(entity);
                if let Some(page) = self.nav.data::<PageId>(entity) {
                    self.current_page = page.clone();
                }
            }

            Message::BootstrapProgress(state) => {
                self.python_state = state;
            }

            Message::BootstrapComplete => {
                self.python_state = PythonState::Ready;
                self.log("Python runtime ready.");
            }

            Message::BootstrapError(error) => {
                self.python_state = PythonState::Error(error.clone());
                self.log(&format!("Bootstrap error: {}", error));
            }

            Message::RefInputChanged(value) => {
                self.main_state.ref_input = value;
            }

            Message::SecInputChanged(value) => {
                self.main_state.sec_input = value;
            }

            Message::TerInputChanged(value) => {
                self.main_state.ter_input = value;
            }

            Message::BrowseRef => {
                // TODO: Open file dialog
                self.log("Browse for reference file...");
            }

            Message::BrowseSec => {
                self.log("Browse for secondary file...");
            }

            Message::BrowseTer => {
                self.log("Browse for tertiary file...");
            }

            Message::ArchiveLogsToggled(checked) => {
                self.main_state.archive_logs = checked;
                self.config.archive_logs_on_batch_completion = checked;
            }

            Message::OpenSettings => {
                self.active_dialog = Some(DialogType::Settings);
            }

            Message::OpenJobQueue => {
                self.active_dialog = Some(DialogType::JobQueue);
            }

            Message::StartAnalyzeOnly => {
                if self.main_state.ref_input.is_empty() || self.main_state.sec_input.is_empty() {
                    self.log("Error: Please select reference and secondary files.");
                    return Task::none();
                }

                self.job_running = true;
                self.status = "Analyzing...".to_string();
                self.progress = 0;
                self.log(&format!(
                    "Starting analysis: {} vs {}",
                    self.main_state.ref_input, self.main_state.sec_input
                ));

                // TODO: Start actual analysis
            }

            Message::CloseDialog => {
                self.active_dialog = None;
            }

            Message::SettingsSaved => {
                if let Err(e) = self.config.save() {
                    self.log(&format!("Failed to save settings: {}", e));
                } else {
                    self.log("Settings saved.");
                }
                self.active_dialog = None;
            }

            Message::JobProgress { percent, message } => {
                self.progress = percent;
                self.status = message.clone();
                self.log(&message);
            }

            Message::JobComplete { success, message } => {
                self.job_running = false;
                self.progress = if success { 100 } else { 0 };
                self.status = if success { "Complete" } else { "Failed" }.to_string();
                self.log(&message);
            }

            Message::LogMessage(msg) => {
                self.log(&msg);
            }

            Message::FileSelected { target, path } => {
                let path_str = path.to_string_lossy().to_string();
                match target {
                    FileTarget::Reference => self.main_state.ref_input = path_str,
                    FileTarget::Secondary => self.main_state.sec_input = path_str,
                    FileTarget::Tertiary => self.main_state.ter_input = path_str,
                }
            }

            Message::None => {}
        }

        Task::none()
    }

    fn subscription(&self) -> cosmic::iced::Subscription<Self::Message> {
        cosmic::iced::Subscription::none()
    }

    fn on_close_requested(&self, _id: cosmic::iced::window::Id) -> Option<Message> {
        None
    }
}

impl App {
    /// Add a log message
    fn log(&mut self, message: &str) {
        use std::fmt::Write;
        let timestamp = chrono::Local::now().format("%H:%M:%S");
        writeln!(&mut self.log_output, "[{}] {}", timestamp, message).ok();
    }

    /// View during Python bootstrap
    fn view_bootstrap(&self) -> Element<Message> {
        let status_text = match &self.python_state {
            PythonState::NotStarted => "Initializing...".to_string(),
            PythonState::Downloading { percent } => {
                format!("Downloading Python runtime... {}%", percent)
            }
            PythonState::Extracting => "Extracting Python...".to_string(),
            PythonState::CreatingVenv => "Creating virtual environment...".to_string(),
            PythonState::InstallingDeps => "Installing dependencies...".to_string(),
            PythonState::Ready => "Ready!".to_string(),
            PythonState::Error(e) => format!("Error: {}", e),
        };

        let progress_percent = match &self.python_state {
            PythonState::NotStarted => 0.0,
            PythonState::Downloading { percent } => *percent as f32 * 0.5, // 0-50%
            PythonState::Extracting => 55.0,
            PythonState::CreatingVenv => 70.0,
            PythonState::InstallingDeps => 85.0,
            PythonState::Ready => 100.0,
            PythonState::Error(_) => 0.0,
        };

        let content = column![
            text("Video Sync GUI").size(24),
            text("Setting up Python runtime...").size(14),
            widget::progress_bar(0.0..=100.0, progress_percent)
                .width(Length::Fixed(400.0)),
            text(&status_text).size(12),
        ]
        .spacing(16)
        .align_x(Alignment::Center);

        container(content)
            .width(Length::Fill)
            .height(Length::Fill)
            .align_x(Alignment::Center)
            .align_y(Alignment::Center)
            .into()
    }

    /// Main page view
    fn view_main(&self) -> Element<Message> {
        // Settings button row
        let settings_row = widget::row()
            .push(widget::button::standard(text("Settings..."))
                .on_press(Message::OpenSettings))
            .push(widget::horizontal_space())
            .spacing(8);

        // Main workflow group
        let workflow_content = widget::column()
            .push(widget::button::standard(text("Open Job Queue for Merging..."))
                .on_press(Message::OpenJobQueue)
                .width(Length::Fill)
                .class(cosmic::theme::Button::Suggested))
            .push(widget::checkbox(
                "Archive logs to a zip file on batch completion",
                self.main_state.archive_logs
            )
            .on_toggle(Message::ArchiveLogsToggled))
            .spacing(8);

        let workflow_group = self.group_box("Main Workflow", workflow_content);

        // Quick analysis group
        let analysis_content = widget::column()
            .push(self.file_input_row("Source 1 (Reference):", &self.main_state.ref_input,
                Message::RefInputChanged, Message::BrowseRef))
            .push(self.file_input_row("Source 2:", &self.main_state.sec_input,
                Message::SecInputChanged, Message::BrowseSec))
            .push(self.file_input_row("Source 3:", &self.main_state.ter_input,
                Message::TerInputChanged, Message::BrowseTer))
            .push(widget::row()
                .push(widget::horizontal_space())
                .push(widget::button::standard(text("Analyze Only"))
                    .on_press(Message::StartAnalyzeOnly)))
            .spacing(8);

        let analysis_group = self.group_box("Quick Analysis (Analyze Only)", analysis_content);

        // Status row
        let status_row = widget::row()
            .push(text("Status:"))
            .push(text(&self.status).width(Length::Fill))
            .push(widget::progress_bar(0.0..=100.0, self.progress as f32)
                .width(Length::Fixed(200.0)))
            .spacing(8)
            .align_y(Alignment::Center);

        // Results group
        let mut results_row = widget::row().spacing(16);
        for (i, delay) in self.main_state.delays.iter().enumerate() {
            let delay_text = match delay {
                Some(d) => format!("{:.2} ms", d),
                None => "—".to_string(),
            };
            results_row = results_row.push(text(format!("Source {} Delay:", i + 2)));
            results_row = results_row.push(text(&delay_text));
        }
        // If no delays yet, show placeholders
        if self.main_state.delays.is_empty() {
            results_row = widget::row()
                .push(text("Source 2 Delay:"))
                .push(text("—"))
                .push(text("Source 3 Delay:"))
                .push(text("—"))
                .push(text("Source 4 Delay:"))
                .push(text("—"))
                .spacing(16);
        }

        let results_group = self.group_box("Latest Job Results", results_row);

        // Log group - using scrollable text as a simpler alternative to text_editor
        let log_viewer = widget::scrollable(
            text(&self.log_output).size(12)
        )
        .height(Length::Fill);

        let log_group = self.group_box("Log", log_viewer);

        // Assemble main layout
        widget::column()
            .push(settings_row)
            .push(workflow_group)
            .push(analysis_group)
            .push(status_row)
            .push(results_group)
            .push(log_group)
            .spacing(12)
            .width(Length::Fill)
            .height(Length::Fill)
            .into()
    }

    /// Settings page view (placeholder)
    fn view_settings_page(&self) -> Element<Message> {
        widget::column()
            .push(text("Settings").size(20))
            .push(text("Settings dialog will be implemented here"))
            .spacing(16)
            .into()
    }

    /// Create a group box with a title
    fn group_box<'a>(
        &self,
        title: &str,
        content: impl Into<Element<'a, Message>>,
    ) -> Element<'a, Message> {
        let header = text(title).size(14);

        column![
            header,
            container(content)
                .padding(12)
                .width(Length::Fill)
                .style(cosmic::theme::Container::Card),
        ]
        .spacing(4)
        .into()
    }

    /// Create a file input row with label, text input, and browse button
    fn file_input_row<'a, F>(
        &self,
        label: &str,
        value: &str,
        on_change: F,
        on_browse: Message,
    ) -> Element<'a, Message>
    where
        F: Fn(String) -> Message + 'a,
    {
        widget::row()
            .push(text(label).width(Length::Fixed(150.0)))
            .push(text_input("", value)
                .on_input(on_change)
                .width(Length::Fill))
            .push(widget::button::standard(text("Browse..."))
                .on_press(on_browse))
            .spacing(8)
            .align_y(Alignment::Center)
            .into()
    }
}
