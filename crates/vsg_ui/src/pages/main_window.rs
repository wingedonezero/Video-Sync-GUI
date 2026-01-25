//! Main window view.
//!
//! This is the primary application view with source inputs,
//! analysis controls, and log panel.

use cosmic::iced::{Alignment, Length};
use cosmic::prelude::*;
use cosmic::{widget, Element};

use crate::app::{App, Message};

/// Build the main window view.
pub fn view(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let content = widget::column()
        .push(header_row(app))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_m.into())))
        .push(quick_analysis_section(app))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_m.into())))
        .push(results_section(app))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_m.into())))
        .push(log_section(app))
        .push(status_bar(app))
        .spacing(spacing.space_xxs)
        .padding(spacing.space_m);

    widget::container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}

/// Header row with Settings and Job Queue buttons.
fn header_row(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    widget::row()
        .push(
            widget::button::standard("Settings")
                .on_press(Message::OpenSettings)
        )
        .push(widget::horizontal_space().width(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::button::standard("Open Job Queue for Merging")
                .on_press(Message::OpenJobQueue)
        )
        .push(widget::horizontal_space())
        .push(
            widget::checkbox("Archive logs", app.archive_logs)
                .on_toggle(Message::ArchiveLogsChanged)
        )
        .spacing(spacing.space_s)
        .align_y(Alignment::Center)
        .into()
}

/// Quick Analysis section with source inputs.
fn quick_analysis_section(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let section_header = widget::text::title4("Quick Analysis");

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

    let analyze_label = if app.is_analyzing { "Analyzing..." } else { "Analyze Only" };
    let analyze_button = if app.is_analyzing {
        widget::button::standard(analyze_label)
    } else {
        widget::button::suggested(analyze_label)
            .on_press(Message::AnalyzeOnly)
    };

    let content = widget::column()
        .push(section_header)
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(source1_row)
        .push(source2_row)
        .push(source3_row)
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::row()
                .push(widget::horizontal_space())
                .push(analyze_button)
        )
        .spacing(spacing.space_xxs);

    widget::container(content)
        .padding(spacing.space_s)
        .into()
}

/// Single source input row with label, text input, and browse button.
fn source_input_row<'a>(
    label: &'a str,
    path: &'a str,
    source_idx: usize,
    enabled: bool,
) -> Element<'a, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let browse_button = if enabled {
        widget::button::standard("Browse")
            .on_press(Message::BrowseSource(source_idx))
    } else {
        widget::button::standard("Browse")
    };

    widget::row()
        .push(
            widget::text::body(label)
                .width(Length::Fixed(150.0))
        )
        .push(
            widget::text_input::text_input("Drop file here or browse...", path)
                .on_input(move |s| Message::SourcePathChanged(source_idx, s))
                .width(Length::Fill)
        )
        .push(browse_button)
        .spacing(spacing.space_s)
        .align_y(Alignment::Center)
        .into()
}

/// Results section showing delay values.
fn results_section(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let section_header = widget::text::title4("Latest Job Results");

    let delay2_text = if app.delay_source2.is_empty() { "-" } else { &app.delay_source2 };
    let delay3_text = if app.delay_source3.is_empty() { "-" } else { &app.delay_source3 };

    let delay2_row = widget::row()
        .push(widget::text::body("Source 2 Delay:").width(Length::Fixed(150.0)))
        .push(widget::text::body(delay2_text))
        .spacing(spacing.space_s);

    let delay3_row = widget::row()
        .push(widget::text::body("Source 3 Delay:").width(Length::Fixed(150.0)))
        .push(widget::text::body(delay3_text))
        .spacing(spacing.space_s);

    let content = widget::column()
        .push(section_header)
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(delay2_row)
        .push(delay3_row)
        .spacing(spacing.space_xxs);

    widget::container(content)
        .padding(spacing.space_s)
        .into()
}

/// Log section with scrollable text area.
fn log_section(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let section_header = widget::text::title4("Log");

    let log_content = widget::text::body(&app.log_text);

    let scroll = widget::scrollable(
        widget::container(log_content)
            .padding(spacing.space_s)
            .width(Length::Fill)
    )
    .height(Length::FillPortion(1));

    let content = widget::column()
        .push(section_header)
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::container(scroll)
                .width(Length::Fill)
                .height(Length::FillPortion(1))
        )
        .spacing(spacing.space_xxs);

    widget::container(content)
        .padding(spacing.space_s)
        .height(Length::FillPortion(1))
        .into()
}

/// Status bar at the bottom.
fn status_bar(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let status = widget::text::body(&app.status_text);

    let progress = widget::progress_bar(0.0..=100.0, app.progress_value)
        .width(Length::Fixed(200.0))
        .height(Length::Fixed(8.0));

    widget::row()
        .push(status)
        .push(widget::horizontal_space())
        .push(progress)
        .spacing(spacing.space_m)
        .padding([spacing.space_s, 0])
        .align_y(Alignment::Center)
        .into()
}
