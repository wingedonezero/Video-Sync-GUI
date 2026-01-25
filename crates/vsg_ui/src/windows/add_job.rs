//! Add job window view.
//!
//! Dialog for adding new jobs to the queue by specifying source files.

use iced::widget::{button, column, container, row, scrollable, text, text_input, Space};
use iced::{Alignment, Element, Length};

use crate::app::{App, Message};

/// Build the add job window view.
pub fn view(app: &App) -> Element<'_, Message> {
    // Header
    let header = text("Add Jobs").size(24);

    let description = text(
        "Specify source files. Source 1 is the reference (video track source)."
    ).size(13);

    // Source input rows
    let source_rows: Vec<Element<'_, Message>> = app
        .add_job_sources
        .iter()
        .enumerate()
        .map(|(idx, path)| {
            let label = if idx == 0 {
                "Source 1 (Reference):".to_string()
            } else {
                format!("Source {}:", idx + 1)
            };

            row![
                text(label).width(140),
                text_input("Drop file here or browse...", path)
                    .on_input(move |s| Message::AddJobSourceChanged(idx, s))
                    .width(Length::Fill),
                button("Browse...").on_press(Message::AddJobBrowseSource(idx)),
            ]
            .spacing(8)
            .align_y(Alignment::Center)
            .into()
        })
        .collect();

    let sources_list = scrollable(
        column(source_rows).spacing(8)
    )
    .height(Length::Fill);

    // Add source button
    let add_source_btn = button("Add Another Source").on_press(Message::AddSource);

    // Error message
    let error_text: Element<'_, Message> = if app.add_job_error.is_empty() {
        Space::new().height(20).into()
    } else {
        text(&app.add_job_error)
            .size(13)
            .color([0.9, 0.3, 0.3])
            .into()
    };

    // Dialog buttons
    let find_btn = if app.is_finding_jobs {
        button("Finding...").width(120)
    } else {
        button("Find & Add Jobs")
            .on_press(Message::FindAndAddJobs)
            .width(120)
    };

    let dialog_buttons = row![
        Space::new().width(Length::Fill),
        find_btn,
        button("Cancel").on_press(Message::CloseAddJob),
    ]
    .spacing(8);

    let content = column![
        header,
        Space::new().height(8),
        description,
        Space::new().height(12),
        sources_list,
        Space::new().height(8),
        add_source_btn,
        Space::new().height(8),
        error_text,
        Space::new().height(12),
        dialog_buttons,
    ]
    .spacing(4)
    .padding(16);

    container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}
