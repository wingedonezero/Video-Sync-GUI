//! Job Queue dialog view.

use cosmic::iced::alignment::Vertical;
use cosmic::iced::{Color, Length};
use cosmic::widget::{self, button, column, container, horizontal_space, row, scrollable, text, vertical_space};
use cosmic::Element;

use crate::app::{App, Message};
use crate::theme::{colors, font, spacing, status};

pub fn view(app: &App) -> Element<Message> {
    let jobs = app.job_queue.lock().unwrap();
    let job_list: Vec<_> = jobs.jobs().iter().cloned().collect();
    drop(jobs);

    let content = column![
        text("Job Queue").size(font::HEADER),
        vertical_space().height(spacing::SM),
        if !app.job_queue_status.is_empty() {
            container(text(&app.job_queue_status).size(font::NORMAL)).into()
        } else {
            container(text("")).into()
        },
        vertical_space().height(spacing::SM),
        table_header(),
        container(
            scrollable(
                column(
                    job_list.iter().enumerate().map(|(idx, job)| {
                        job_row(idx, &job.name, &job.source_display("Source 1", 35),
                            &job.source_display("Source 2", 35), &job.source_display("Source 3", 25),
                            job.status.as_str(), app.selected_job_indices.contains(&idx))
                    }).collect()
                ).spacing(1)
            ).height(Length::Fill)
        ).height(Length::FillPortion(1)),
        if job_list.is_empty() {
            container(column![
                vertical_space().height(spacing::XL),
                text("No jobs in queue").size(font::MD),
                text("Click 'Add Job(s)...' to add jobs").size(font::SM),
            ].align_x(cosmic::iced::Alignment::Center)).width(Length::Fill).into()
        } else {
            container(text("")).into()
        },
        vertical_space().height(spacing::MD),
        action_buttons(app),
        vertical_space().height(spacing::SM),
        dialog_buttons(app, job_list.len()),
    ].spacing(spacing::XS).padding(spacing::LG);

    container(content).width(Length::Fill).height(Length::Fill).into()
}

fn table_header() -> Element<'static, Message> {
    row![
        text("#").size(font::SM).width(Length::Fixed(30.0)),
        text("Job Name").size(font::SM).width(Length::Fixed(150.0)),
        text("Source 1 (Reference)").size(font::SM).width(Length::FillPortion(1)),
        text("Source 2").size(font::SM).width(Length::FillPortion(1)),
        text("Source 3").size(font::SM).width(Length::Fixed(120.0)),
        text("Status").size(font::SM).width(Length::Fixed(90.0)),
    ].spacing(spacing::XS).padding([spacing::XS, spacing::SM]).into()
}

fn job_row(idx: usize, name: &str, source1: &str, source2: &str, source3: &str,
    job_status: &str, is_selected: bool) -> Element<'static, Message> {
    let bg_color = if is_selected { colors::SELECTED } else { Color::TRANSPARENT };
    let status_color = status::for_status(job_status);

    let row_content = row![
        text(format!("{}", idx + 1)).size(font::NORMAL).width(Length::Fixed(30.0)),
        text(name.to_string()).size(font::NORMAL).width(Length::Fixed(150.0)),
        text(source1.to_string()).size(font::SM).width(Length::FillPortion(1)),
        text(source2.to_string()).size(font::SM).width(Length::FillPortion(1)),
        text(if source3.is_empty() { "-" } else { source3 }.to_string()).size(font::SM).width(Length::Fixed(120.0)),
        container(text(job_status.to_string()).size(font::SM)).width(Length::Fixed(90.0)).padding([2, spacing::XS]),
    ].spacing(spacing::XS).padding([spacing::XS, spacing::SM]).align_y(Vertical::Center);

    let row_button = button(row_content).on_press(Message::JobRowSelected(idx, !is_selected)).padding(0);
    container(row_button).width(Length::Fill).into()
}

fn action_buttons(app: &App) -> Element<Message> {
    let has_selection = !app.selected_job_indices.is_empty();
    row![
        button(text("Add Job(s)...").size(font::NORMAL))
            .on_press_maybe(if app.is_processing { None } else { Some(Message::AddJobsClicked) })
            .padding([spacing::SM, spacing::LG]),
        horizontal_space(),
        button(text("Move Up").size(font::NORMAL))
            .on_press_maybe(if !app.is_processing && has_selection { Some(Message::MoveJobsUp) } else { None })
            .padding([spacing::SM, spacing::MD]),
        button(text("Move Down").size(font::NORMAL))
            .on_press_maybe(if !app.is_processing && has_selection { Some(Message::MoveJobsDown) } else { None })
            .padding([spacing::SM, spacing::MD]),
        button(text("Remove Selected").size(font::NORMAL))
            .on_press_maybe(if !app.is_processing && has_selection { Some(Message::RemoveSelectedJobs) } else { None })
            .padding([spacing::SM, spacing::MD]),
    ].spacing(spacing::SM).into()
}

fn dialog_buttons(app: &App, job_count: usize) -> Element<Message> {
    row![
        horizontal_space(),
        button(text("Cancel").size(font::NORMAL))
            .on_press_maybe(if app.is_processing { None } else { Some(Message::CloseJobQueue) })
            .padding([spacing::SM, spacing::LG]),
        button(text(if app.is_processing { "Processing..." } else { "Start Processing Queue" }).size(font::NORMAL))
            .on_press_maybe(if !app.is_processing && job_count > 0 { Some(Message::StartProcessing) } else { None })
            .padding([spacing::SM, spacing::LG]),
    ].spacing(spacing::SM).into()
}
