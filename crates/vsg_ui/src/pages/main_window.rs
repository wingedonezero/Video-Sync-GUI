//! Main window view.
//!
//! This is the primary application view with source inputs,
//! analysis controls, and log panel.

use iced::widget::{
    button, checkbox, column, container, progress_bar, row, scrollable, text, text_input, Column,
    Space,
};
use iced::{Alignment, Element, Length};

use crate::app::{App, Message};

/// Build the main window view.
pub fn view(app: &App) -> Element<Message> {
    let content = column![
        header_row(app),
        Space::new().height(12),
        main_workflow_section(),
        Space::new().height(12),
        quick_analysis_section(app),
        Space::new().height(12),
        results_section(app),
        Space::new().height(12),
        log_section(app),
        status_bar(app),
    ]
    .spacing(4)
    .padding(16);

    container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}

/// Header row with Settings button and archive logs checkbox.
fn header_row(app: &App) -> Element<Message> {
    row![
        button("Settings...").on_press(Message::OpenSettings),
        Space::new().width(Length::Fill),
        checkbox(app.archive_logs)
            .label("Archive logs to zip on batch completion")
            .on_toggle(Message::ArchiveLogsChanged),
    ]
    .spacing(8)
    .align_y(Alignment::Center)
    .into()
}

/// Main Workflow section with Job Queue button.
fn main_workflow_section() -> Element<'static, Message> {
    let section_header = text("Main Workflow").size(18);

    let queue_button = button("Open Job Queue for Merging...")
        .on_press(Message::OpenJobQueue)
        .padding([8, 16]);

    let content = column![section_header, Space::new().height(8), queue_button,].spacing(4);

    container(content)
        .padding(12)
        .style(container::bordered_box)
        .width(Length::Fill)
        .into()
}

/// Quick Analysis section with source inputs.
fn quick_analysis_section(app: &App) -> Element<Message> {
    let section_header = text("Quick Analysis (Analyze Only)").size(18);

    let source1_row = source_input_row(
        "Source 1 (Reference):",
        &app.source1_path,
        1,
        !app.is_analyzing,
    );

    let source2_row = source_input_row("Source 2:", &app.source2_path, 2, !app.is_analyzing);

    let source3_row = source_input_row("Source 3:", &app.source3_path, 3, !app.is_analyzing);

    let analyze_label = if app.is_analyzing {
        "Analyzing..."
    } else {
        "Analyze Only"
    };

    let analyze_button = if app.is_analyzing {
        button(analyze_label).padding([8, 16])
    } else {
        button(analyze_label)
            .on_press(Message::AnalyzeOnly)
            .padding([8, 16])
    };

    let content = column![
        section_header,
        Space::new().height(8),
        source1_row,
        source2_row,
        source3_row,
        Space::new().height(8),
        row![Space::new().width(Length::Fill), analyze_button],
    ]
    .spacing(4);

    container(content)
        .padding(12)
        .style(container::bordered_box)
        .width(Length::Fill)
        .into()
}

/// Single source input row with label, text input, and browse button.
fn source_input_row<'a>(
    label: &'a str,
    path: &'a str,
    source_idx: usize,
    enabled: bool,
) -> Element<'a, Message> {
    let label_text = text(label).width(150);

    let input = text_input("Drop file here or browse...", path)
        .on_input(move |s| Message::SourcePathChanged(source_idx, s))
        .width(Length::Fill);

    let browse_button = if enabled {
        button("Browse...").on_press(Message::BrowseSource(source_idx))
    } else {
        button("Browse...")
    };

    row![label_text, input, browse_button]
        .spacing(8)
        .align_y(Alignment::Center)
        .into()
}

/// Results section showing delay values.
fn results_section(app: &App) -> Element<Message> {
    let section_header = text("Latest Job Results").size(18);

    let delay2_text = if app.delay_source2.is_empty() {
        "-".to_string()
    } else {
        app.delay_source2.clone()
    };
    let delay3_text = if app.delay_source3.is_empty() {
        "-".to_string()
    } else {
        app.delay_source3.clone()
    };

    let delays_row = row![
        text("Source 2 Delay:"),
        text(delay2_text),
        Space::new().width(40),
        text("Source 3 Delay:"),
        text(delay3_text),
        Space::new().width(Length::Fill),
    ]
    .spacing(8);

    let content = column![section_header, Space::new().height(8), delays_row,].spacing(4);

    container(content)
        .padding(12)
        .style(container::bordered_box)
        .width(Length::Fill)
        .into()
}

/// Log section with scrollable text area.
fn log_section(app: &App) -> Element<Message> {
    let section_header = text("Log").size(18);

    let log_content = text(app.log_text.clone()).font(iced::Font::MONOSPACE);

    let scroll = scrollable(container(log_content).padding(8).width(Length::Fill))
        .height(Length::FillPortion(1));

    let content: Column<Message> = column![
        section_header,
        Space::new().height(8),
        container(scroll)
            .width(Length::Fill)
            .height(Length::FillPortion(1))
            .style(container::bordered_box),
    ]
    .spacing(4);

    container(content)
        .padding(12)
        .height(Length::FillPortion(1))
        .into()
}

/// Status bar at the bottom.
fn status_bar(app: &App) -> Element<Message> {
    let status = text(app.status_text.clone());

    let progress = progress_bar(0.0..=100.0, app.progress_value);

    row![
        text("Status:"),
        status,
        Space::new().width(Length::Fill),
        container(progress).width(200).height(8),
    ]
    .spacing(8)
    .padding([8, 0])
    .align_y(Alignment::Center)
    .into()
}
