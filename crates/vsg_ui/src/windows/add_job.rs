//! Add Job dialog view.

use cosmic::iced::alignment::Vertical;
use cosmic::iced::Length;
use cosmic::widget::{self, button, column, container, horizontal_space, row, scrollable, text, text_input, vertical_space};
use cosmic::Element;

use crate::app::{App, Message};
use crate::theme::{font, spacing};

pub fn view(app: &App) -> Element<Message> {
    let content = column![
        text("Add Job(s)").size(font::HEADER),
        vertical_space().height(spacing::SM),
        if !app.add_job_error.is_empty() {
            container(text(&app.add_job_error).size(font::NORMAL)).into()
        } else {
            container(text("")).into()
        },
        vertical_space().height(spacing::SM),
        scrollable(
            column(
                app.add_job_sources.iter().enumerate().map(|(idx, path)| {
                    source_input_row(idx, path, !app.is_finding_jobs)
                }).collect()
            ).spacing(spacing::SM)
        ).height(Length::Fill),
        vertical_space().height(spacing::SM),
        row![
            button(text("+ Add Source").size(font::NORMAL))
                .on_press_maybe(if !app.is_finding_jobs && app.add_job_sources.len() < 10 {
                    Some(Message::AddSource)
                } else { None })
                .padding([spacing::SM, spacing::MD]),
            horizontal_space(),
        ],
        vertical_space().height(spacing::MD),
        row![
            horizontal_space(),
            button(text("Cancel").size(font::NORMAL))
                .on_press_maybe(if app.is_finding_jobs { None } else { Some(Message::CloseAddJob) })
                .padding([spacing::SM, spacing::LG]),
            button(text(if app.is_finding_jobs { "Finding..." } else { "Find and Add Jobs" }).size(font::NORMAL))
                .on_press_maybe(if app.is_finding_jobs { None } else { Some(Message::FindAndAddJobs) })
                .padding([spacing::SM, spacing::LG]),
        ].spacing(spacing::SM),
    ].spacing(spacing::XS).padding(spacing::LG);

    container(content).width(Length::Fill).height(Length::Fill).into()
}

fn source_input_row(idx: usize, path: &str, enabled: bool) -> Element<'static, Message> {
    let label = if idx == 0 { "Source 1 (Reference):".to_string() } else { format!("Source {}:", idx + 1) };
    let path_owned = path.to_string();

    row![
        text(label).size(font::NORMAL).width(Length::Fixed(150.0)),
        text_input("Drop file here or browse...", &path_owned)
            .on_input(move |s| Message::AddJobSourceChanged(idx, s))
            .width(Length::Fill).size(font::NORMAL),
        button(text("Browse").size(font::SM))
            .on_press_maybe(if enabled { Some(Message::AddJobBrowseSource(idx)) } else { None })
            .padding([spacing::XS, spacing::SM]),
        if idx >= 2 {
            button(text("X").size(font::SM))
                .on_press_maybe(if enabled { Some(Message::RemoveSource(idx)) } else { None })
                .padding([spacing::XS, spacing::SM]).into()
        } else {
            horizontal_space().width(Length::Fixed(0.0)).into()
        },
    ].spacing(spacing::SM).align_y(Vertical::Center).into()
}
