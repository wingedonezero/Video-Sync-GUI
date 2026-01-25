//! Main window view.
//!
//! This is the primary application view with source inputs,
//! analysis controls, and log panel.

use cosmic::iced::alignment::{Horizontal, Vertical};
use cosmic::iced::{Length, Padding};
use cosmic::widget::{self, button, checkbox, column, container, horizontal_space, progress_bar, row, scrollable, text, text_input, vertical_space};
use cosmic::Element;

use crate::app::{App, Message};
use crate::theme::{colors, font, spacing};

/// Build the main window view.
pub fn view(app: &App) -> Element<Message> {
    let content = column![
        // Header with buttons
        header_row(app),
        vertical_space().height(spacing::MD),
        // Quick Analysis section
        quick_analysis_section(app),
        vertical_space().height(spacing::MD),
        // Latest Job Results
        results_section(app),
        vertical_space().height(spacing::MD),
        // Log panel
        log_section(app),
        // Status bar
        status_bar(app),
    ]
    .spacing(spacing::XS)
    .padding(spacing::LG);

    container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}

/// Header row with Settings and Job Queue buttons.
fn header_row(app: &App) -> Element<Message> {
    row![
        button(text("Settings").size(font::NORMAL))
            .on_press(Message::OpenSettings)
            .padding([spacing::SM, spacing::LG]),
        horizontal_space().width(spacing::SM),
        button(text("Open Job Queue for Merging").size(font::NORMAL))
            .on_press(Message::OpenJobQueue)
            .padding([spacing::SM, spacing::LG]),
        horizontal_space(),
        checkbox("Archive logs", app.archive_logs)
            .on_toggle(Message::ArchiveLogsChanged)
            .text_size(font::NORMAL),
    ]
    .spacing(spacing::SM)
    .align_y(Vertical::Center)
    .into()
}

/// Quick Analysis section with source inputs.
fn quick_analysis_section(app: &App) -> Element<Message> {
    let section_header = text("Quick Analysis")
        .size(font::LG);

    let source1_row = source_input_row(
        "Source 1 (Reference):",
        &app.source1_path,
        1,
        !app.is_analyzing,
    );

    let source2_row = source_input_row(
        "Source 2:",
        &app.source2_path,
        2,
        !app.is_analyzing,
    );

    let source3_row = source_input_row(
        "Source 3:",
        &app.source3_path,
        3,
        !app.is_analyzing,
    );

    let analyze_button = button(
        text(if app.is_analyzing { "Analyzing..." } else { "Analyze Only" })
            .size(font::NORMAL)
    )
    .on_press_maybe(if app.is_analyzing { None } else { Some(Message::AnalyzeOnly) })
    .padding([spacing::SM, spacing::XL]);

    let content = column![
        section_header,
        vertical_space().height(spacing::SM),
        source1_row,
        source2_row,
        source3_row,
        vertical_space().height(spacing::SM),
        row![
            horizontal_space(),
            analyze_button,
        ],
    ]
    .spacing(spacing::XS);

    container(content)
        .padding(spacing::MD)
        .into()
}

/// Single source input row with label, text input, and browse button.
fn source_input_row(
    label: &str,
    path: &str,
    source_idx: usize,
    enabled: bool,
) -> Element<Message> {
    row![
        text(label)
            .size(font::NORMAL)
            .width(Length::Fixed(150.0)),
        text_input("Drop file here or browse...", path)
            .on_input(move |s| Message::SourcePathChanged(source_idx, s))
            .width(Length::Fill)
            .size(font::NORMAL),
        button(text("Browse").size(font::SM))
            .on_press_maybe(if enabled { Some(Message::BrowseSource(source_idx)) } else { None })
            .padding([spacing::XS, spacing::SM]),
    ]
    .spacing(spacing::SM)
    .align_y(Vertical::Center)
    .into()
}

/// Results section showing delay values.
fn results_section(app: &App) -> Element<Message> {
    let section_header = text("Latest Job Results")
        .size(font::LG);

    let delay2_row = row![
        text("Source 2 Delay:")
            .size(font::NORMAL)
            .width(Length::Fixed(150.0)),
        text(if app.delay_source2.is_empty() { "-" } else { &app.delay_source2 })
            .size(font::NORMAL),
    ]
    .spacing(spacing::SM);

    let delay3_row = row![
        text("Source 3 Delay:")
            .size(font::NORMAL)
            .width(Length::Fixed(150.0)),
        text(if app.delay_source3.is_empty() { "-" } else { &app.delay_source3 })
            .size(font::NORMAL),
    ]
    .spacing(spacing::SM);

    let content = column![
        section_header,
        vertical_space().height(spacing::SM),
        delay2_row,
        delay3_row,
    ]
    .spacing(spacing::XS);

    container(content)
        .padding(spacing::MD)
        .into()
}

/// Log section with scrollable text area.
fn log_section(app: &App) -> Element<Message> {
    let section_header = text("Log")
        .size(font::LG);

    let log_content = text(&app.log_text)
        .size(font::SM);

    let scroll = scrollable(
        container(log_content)
            .padding(spacing::SM)
            .width(Length::Fill)
    )
    .height(Length::FillPortion(1));

    let content = column![
        section_header,
        vertical_space().height(spacing::SM),
        container(scroll)
            .width(Length::Fill)
            .height(Length::FillPortion(1)),
    ]
    .spacing(spacing::XS);

    container(content)
        .padding(spacing::MD)
        .height(Length::FillPortion(1))
        .into()
}

/// Status bar at the bottom.
fn status_bar(app: &App) -> Element<Message> {
    let status = text(&app.status_text)
        .size(font::SM);

    let progress = progress_bar(0.0..=100.0, app.progress_value)
        .width(Length::Fixed(200.0))
        .height(8);

    row![
        status,
        horizontal_space(),
        progress,
    ]
    .spacing(spacing::MD)
    .padding([spacing::SM, 0])
    .align_y(Vertical::Center)
    .into()
}
