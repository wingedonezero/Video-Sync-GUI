//! Job queue window view.
//!
//! Shows the list of queued jobs with controls to manage and process them.
//! Click row to select, double-click to configure.
//! Right-click for context menu (copy/paste layout).

use iced::widget::{button, column, container, row, scrollable, text, Space};
use iced::{Alignment, Background, Border, Color, Element, Length, Theme};
use iced_aw::ContextMenu;

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
                // Use the actual status field - it's set to Configured when layout is saved
                let status_str = match job.status {
                    vsg_core::jobs::JobQueueStatus::Pending => "○ Not Configured",
                    vsg_core::jobs::JobQueueStatus::Configured => "✓ Configured",
                    vsg_core::jobs::JobQueueStatus::Processing => "⟳ Processing",
                    vsg_core::jobs::JobQueueStatus::Complete => "✓ Complete",
                    vsg_core::jobs::JobQueueStatus::Error => "✗ Error",
                };
                // Get first source filename for display
                let source1_name = job.sources
                    .get("Source 1")
                    .and_then(|p| p.file_name())
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_else(|| "-".to_string());
                (idx, job.name.clone(), status_str.to_string(), job.sources.len(), source1_name)
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
    let list_header = container(
        row![
            text("Name").width(Length::FillPortion(3)),
            text("Source 1").width(Length::FillPortion(2)),
            text("Sources").width(Length::FillPortion(1)),
            text("Status").width(Length::FillPortion(2)),
            Space::new().width(80), // Configure button column
        ]
        .spacing(8)
        .padding([8, 12])
    )
    .style(|_theme: &Theme| container::Style {
        background: Some(Background::Color(Color::from_rgb(0.15, 0.15, 0.15))),
        ..Default::default()
    });

    // Job rows - clickable with selection highlighting
    let job_rows: Vec<Element<'_, Message>> = jobs
        .into_iter()
        .map(|(idx, name, status, source_count, source1_name)| {
            let is_selected = app.selected_job_indices.contains(&idx);

            // Row content - clone strings to avoid lifetime issues
            let row_content = row![
                text(name).width(Length::FillPortion(3)),
                text(source1_name).width(Length::FillPortion(2)).size(13),
                text(format!("{}", source_count)).width(Length::FillPortion(1)),
                text(status).width(Length::FillPortion(2)).size(13),
                button("Configure")
                    .on_press(Message::JobRowDoubleClicked(idx))
                    .width(80),
            ]
            .spacing(8)
            .align_y(Alignment::Center);

            // Wrap in button for click handling
            let row_button = button(row_content)
                .on_press(Message::JobRowClicked(idx))
                .width(Length::Fill)
                .padding([8, 12])
                .style(move |_theme, _status| {
                    if is_selected {
                        button::Style {
                            background: Some(Background::Color(Color::from_rgb(0.24, 0.35, 0.50))),
                            text_color: Color::WHITE,
                            border: Border::default(),
                            ..Default::default()
                        }
                    } else {
                        button::Style {
                            background: Some(Background::Color(Color::TRANSPARENT)),
                            text_color: Color::from_rgb(0.9, 0.9, 0.9),
                            border: Border::default(),
                            ..Default::default()
                        }
                    }
                });

            // Wrap with context menu for right-click actions
            let context_menu = ContextMenu::new(row_button, move || {
                container(
                    column![
                        button("Copy Layout")
                            .on_press(Message::CopyLayout(idx))
                            .width(Length::Fill)
                            .padding([6, 12]),
                        button("Paste Layout")
                            .on_press(Message::PasteLayout)
                            .width(Length::Fill)
                            .padding([6, 12]),
                    ]
                    .spacing(2)
                    .padding(4)
                )
                .style(|_theme: &Theme| container::Style {
                    background: Some(Background::Color(Color::from_rgb(0.2, 0.2, 0.2))),
                    border: Border {
                        color: Color::from_rgb(0.4, 0.4, 0.4),
                        width: 1.0,
                        radius: 4.0.into(),
                    },
                    ..Default::default()
                })
                .into()
            });

            context_menu.into()
        })
        .collect();

    let job_list: Element<'_, Message> = if job_rows.is_empty() {
        container(
            column![
                text("No jobs in queue").size(16),
                Space::new().height(8),
                text("Click 'Add Job(s)...' to add jobs, or drag files here.").size(13),
            ]
            .align_x(Alignment::Center)
        )
        .padding(40)
        .width(Length::Fill)
        .center_x(Length::Fill)
        .into()
    } else {
        scrollable(column(job_rows).spacing(1))
            .height(Length::Fill)
            .into()
    };

    // Action buttons row
    let action_buttons = row![
        button("Add Job(s)...").on_press(Message::OpenAddJob),
        button("Remove Selected").on_press(Message::RemoveSelectedJobs),
        Space::new().width(16),
        button("↑ Move Up").on_press(Message::MoveJobsUp),
        button("↓ Move Down").on_press(Message::MoveJobsDown),
    ]
    .spacing(8);

    // Status text
    let status_text = if app.job_queue_status.is_empty() {
        text("Click to select, double-click or press Configure to set up track layout.").size(13)
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
            column![list_header, job_list].spacing(0)
        )
        .style(container::bordered_box)
        .height(Length::Fill),
        Space::new().height(8),
        status_text,
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
