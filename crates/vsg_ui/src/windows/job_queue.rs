//! Job Queue dialog view.

use cosmic::iced::{Alignment, Color, Length};
use cosmic::prelude::*;
use cosmic::{widget, Element};

use crate::app::{App, Message};
use crate::theme::{colors, status};

pub fn view(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let jobs = app.job_queue.lock().unwrap();
    let job_list: Vec<_> = jobs.jobs().iter().cloned().collect();
    drop(jobs);

    let mut content = widget::column()
        .push(widget::text::title3("Job Queue"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())));

    if !app.job_queue_status.is_empty() {
        content = content.push(widget::text::body(&app.job_queue_status));
    }

    content = content
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(table_header())
        .push(
            widget::container(
                widget::scrollable(
                    job_list.iter().enumerate().fold(
                        widget::column().spacing(1),
                        |col, (idx, job)| {
                            col.push(job_row(
                                idx,
                                &job.name,
                                &job.source_display("Source 1", 35),
                                &job.source_display("Source 2", 35),
                                &job.source_display("Source 3", 25),
                                job.status.as_str(),
                                app.selected_job_indices.contains(&idx),
                            ))
                        }
                    )
                )
                .height(Length::Fill)
            )
            .height(Length::FillPortion(1))
        );

    if job_list.is_empty() {
        content = content.push(
            widget::container(
                widget::column()
                    .push(widget::vertical_space().height(Length::Fixed(spacing.space_xl.into())))
                    .push(widget::text::body("No jobs in queue"))
                    .push(widget::text::caption("Click 'Add Job(s)...' to add jobs"))
                    .align_x(Alignment::Center)
            )
            .width(Length::Fill)
        );
    }

    content = content
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_m.into())))
        .push(action_buttons(app))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(dialog_buttons(app, job_list.len()))
        .spacing(spacing.space_xxs)
        .padding(spacing.space_l);

    widget::container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}

fn table_header() -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    widget::row()
        .push(widget::text::caption("#").width(Length::Fixed(30.0)))
        .push(widget::text::caption("Job Name").width(Length::Fixed(150.0)))
        .push(widget::text::caption("Source 1 (Reference)").width(Length::FillPortion(1)))
        .push(widget::text::caption("Source 2").width(Length::FillPortion(1)))
        .push(widget::text::caption("Source 3").width(Length::Fixed(120.0)))
        .push(widget::text::caption("Status").width(Length::Fixed(90.0)))
        .spacing(spacing.space_xxs)
        .padding([spacing.space_xxs, spacing.space_s])
        .into()
}

fn job_row(
    idx: usize,
    name: &str,
    source1: &str,
    source2: &str,
    source3: &str,
    job_status: &str,
    is_selected: bool,
) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let _bg_color = if is_selected { colors::SELECTED } else { Color::TRANSPARENT };
    let _status_color = status::for_status(job_status);

    let source3_display = if source3.is_empty() { "-" } else { source3 };

    // Create a summary string for the row button
    let row_summary = format!(
        "{}. {} | {} | {} | {} | {}",
        idx + 1,
        name,
        truncate_str(source1, 25),
        truncate_str(source2, 25),
        truncate_str(source3_display, 15),
        job_status
    );

    let marker = if is_selected { "> " } else { "  " };
    let label = format!("{}{}", marker, row_summary);

    widget::button::text(label)
        .on_press(Message::JobRowSelected(idx, !is_selected))
        .width(Length::Fill)
        .into()
}

fn truncate_str(s: &str, max_len: usize) -> String {
    if s.len() <= max_len {
        s.to_string()
    } else {
        format!("{}...", &s[..max_len.saturating_sub(3)])
    }
}

fn action_buttons(app: &App) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let has_selection = !app.selected_job_indices.is_empty();

    let mut add_btn = widget::button::standard("Add Job(s)...");
    if !app.is_processing {
        add_btn = add_btn.on_press(Message::AddJobsClicked);
    }

    let mut up_btn = widget::button::standard("Move Up");
    if !app.is_processing && has_selection {
        up_btn = up_btn.on_press(Message::MoveJobsUp);
    }

    let mut down_btn = widget::button::standard("Move Down");
    if !app.is_processing && has_selection {
        down_btn = down_btn.on_press(Message::MoveJobsDown);
    }

    let mut remove_btn = widget::button::standard("Remove Selected");
    if !app.is_processing && has_selection {
        remove_btn = remove_btn.on_press(Message::RemoveSelectedJobs);
    }

    widget::row()
        .push(add_btn)
        .push(widget::horizontal_space())
        .push(up_btn)
        .push(down_btn)
        .push(remove_btn)
        .spacing(spacing.space_s)
        .into()
}

fn dialog_buttons(app: &App, job_count: usize) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let mut cancel_btn = widget::button::standard("Cancel");
    if !app.is_processing {
        cancel_btn = cancel_btn.on_press(Message::CloseJobQueue);
    }

    let process_label = if app.is_processing { "Processing..." } else { "Start Processing Queue" };
    let mut process_btn = widget::button::suggested(process_label);
    if !app.is_processing && job_count > 0 {
        process_btn = process_btn.on_press(Message::StartProcessing);
    }

    widget::row()
        .push(widget::horizontal_space())
        .push(cancel_btn)
        .push(process_btn)
        .spacing(spacing.space_s)
        .into()
}
