//! Main window layout mirroring `python/vsg_qt/main_window/window.py`.

use cosmic::iced::{Alignment, Length};
use cosmic::widget::{self, progress_bar};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    UpdateReference(String),
    UpdateSecondary(String),
    UpdateTertiary(String),
    ToggleArchiveLogs(bool),
    BrowseReference,
    BrowseSecondary,
    BrowseTertiary,
    OpenSettings,
    OpenJobQueue,
    AnalyzeOnly,
}

#[derive(Clone, Debug)]
pub struct State {
    pub reference_path: String,
    pub secondary_path: String,
    pub tertiary_path: String,
    pub archive_logs: bool,
    pub status: String,
    pub progress: f32,
    pub delays: Vec<String>,
    pub log: String,
}

impl Default for State {
    fn default() -> Self {
        Self {
            reference_path: String::new(),
            secondary_path: String::new(),
            tertiary_path: String::new(),
            archive_logs: false,
            status: "Ready".to_string(),
            progress: 0.0,
            delays: vec!["—".to_string(), "—".to_string(), "—".to_string()],
            log: String::new(),
        }
    }
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::UpdateReference(value) => self.reference_path = value,
            Message::UpdateSecondary(value) => self.secondary_path = value,
            Message::UpdateTertiary(value) => self.tertiary_path = value,
            Message::ToggleArchiveLogs(value) => self.archive_logs = value,
            Message::BrowseReference
            | Message::BrowseSecondary
            | Message::BrowseTertiary
            | Message::OpenSettings
            | Message::OpenJobQueue
            | Message::AnalyzeOnly => {}
        }
    }
}

pub fn view(state: &State) -> Element<Message> {
    let top_row = widget::row()
        .push(common::button("Settings…", Message::OpenSettings))
        .push(widget::horizontal_space(Length::Fill));

    let workflow = common::section(
        "Main Workflow",
        widget::column()
            .spacing(8)
            .push(common::button(
                "Open Job Queue for Merging...",
                Message::OpenJobQueue,
            ))
            .push(common::checkbox(
                "Archive logs to a zip file on batch completion",
                state.archive_logs,
                Message::ToggleArchiveLogs,
            ))
            .into(),
    );

    let analysis = common::section(
        "Quick Analysis (Analyze Only)",
        widget::column()
            .spacing(12)
            .push(common::file_picker_input(
                "Source 1 (Reference):",
                &state.reference_path,
                Message::UpdateReference,
                Message::BrowseReference,
            ))
            .push(common::file_picker_input(
                "Source 2:",
                &state.secondary_path,
                Message::UpdateSecondary,
                Message::BrowseSecondary,
            ))
            .push(common::file_picker_input(
                "Source 3:",
                &state.tertiary_path,
                Message::UpdateTertiary,
                Message::BrowseTertiary,
            ))
            .push(
                widget::row()
                    .push(widget::horizontal_space(Length::Fill))
                    .push(common::button("Analyze Only", Message::AnalyzeOnly)),
            )
            .into(),
    );

    let status_row = widget::row()
        .spacing(12)
        .align_items(Alignment::Center)
        .push(widget::text::body("Status:"))
        .push(widget::text::body(&state.status).width(Length::FillPortion(3)))
        .push(progress_bar(0.0..=100.0, state.progress).width(Length::FillPortion(2)));

    let results = common::section(
        "Latest Job Results",
        widget::row()
            .spacing(16)
            .push(widget::text::body("Source 2 Delay:"))
            .push(widget::text::body(
                state
                    .delays
                    .get(0)
                    .map(String::as_str)
                    .unwrap_or("—"),
            ))
            .push(widget::text::body("Source 3 Delay:"))
            .push(widget::text::body(
                state
                    .delays
                    .get(1)
                    .map(String::as_str)
                    .unwrap_or("—"),
            ))
            .push(widget::text::body("Source 4 Delay:"))
            .push(widget::text::body(
                state
                    .delays
                    .get(2)
                    .map(String::as_str)
                    .unwrap_or("—"),
            ))
            .push(widget::horizontal_space(Length::Fill))
            .into(),
    );

    let log_section = common::section(
        "Log",
        widget::container(widget::text::monotext(
            if state.log.is_empty() {
                "Log output appears here."
            } else {
                &state.log
            },
        ))
            .height(Length::Units(200))
            .width(Length::Fill)
            .into(),
    );

    widget::column()
        .spacing(16)
        .padding(16)
        .push(top_row)
        .push(workflow)
        .push(analysis)
        .push(status_row)
        .push(results)
        .push(log_section)
        .into()
}
