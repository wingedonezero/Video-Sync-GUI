//! Job queue window view.
//!
//! Shows the list of queued jobs with controls to manage and process them.

use iced::widget::{button, checkbox, column, container, row, scrollable, text, Space};
use iced::{Alignment, Element, Length};

use crate::app::{App, Message};

/// Build the job queue window view.
pub fn view(app: &App) -> Element<'_, Message> {
    // Get jobs from queue
    let jobs: Vec<_> = {
        let q = app.job_queue.lock().unwrap();
        q.jobs()
            .iter()
            .enumerate()
            .map(|(idx, job)| {
                let status = if job.layout.is_some() {
                    "Configured"
                } else {
                    "Not Configured"
                };
                (idx, job.name.clone(), status.to_string(), job.sources.len())
            })
            .collect()
    };

    // Header
    let header = row![
        text("Job Queue").size(24),
        Space::new().width(Length::Fill),
        text(format!("{} job(s)", jobs.len())).size(14),
    ]
    .align_y(Alignment::Center);

    // Job list header
    let list_header = row![
        Space::new().width(30), // checkbox column
        text("Name").width(Length::FillPortion(3)),
        text("Sources").width(Length::FillPortion(1)),
        text("Status").width(Length::FillPortion(2)),
    ]
    .spacing(8)
    .padding([4, 8]);

    // Job rows
    let job_rows: Vec<Element<'_, Message>> = jobs
        .into_iter()
        .map(|(idx, name, status, source_count)| {
            let is_selected = app.selected_job_indices.contains(&idx);

            row![
                checkbox(is_selected).on_toggle(move |checked| Message::JobRowSelected(idx, checked)),
                text(name).width(Length::FillPortion(3)),
                text(format!("{}", source_count)).width(Length::FillPortion(1)),
                text(status).width(Length::FillPortion(2)),
            ]
            .spacing(8)
            .padding([4, 8])
            .into()
        })
        .collect();

    let job_list: Element<'_, Message> = if job_rows.is_empty() {
        container(
            text("No jobs in queue. Click 'Add Job(s)...' to add jobs.")
                .size(14)
        )
        .padding(20)
        .width(Length::Fill)
        .center_x(Length::Fill)
        .into()
    } else {
        scrollable(column(job_rows).spacing(2))
            .height(Length::Fill)
            .into()
    };

    // Action buttons row
    let action_buttons = row![
        button("Add Job(s)...").on_press(Message::OpenAddJob),
        button("Remove Selected").on_press(Message::RemoveSelectedJobs),
        Space::new().width(16),
        button("Move Up").on_press(Message::MoveJobsUp),
        button("Move Down").on_press(Message::MoveJobsDown),
    ]
    .spacing(8);

    // Status text
    let status = if app.job_queue_status.is_empty() {
        text("Double-click a job to configure its track layout.").size(13)
    } else {
        text(&app.job_queue_status).size(13)
    };

    // Dialog buttons
    let dialog_buttons = row![
        Space::new().width(Length::Fill),
        button("Start Processing").on_press(Message::StartProcessing),
        button("Close").on_press(Message::CloseJobQueue),
    ]
    .spacing(8);

    let content = column![
        header,
        Space::new().height(12),
        action_buttons,
        Space::new().height(8),
        container(
            column![list_header, job_list]
        )
        .style(container::bordered_box)
        .height(Length::Fill),
        Space::new().height(8),
        status,
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
