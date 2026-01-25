//! Manual selection window view.
//!
//! Dialog for manually selecting and arranging tracks for a job's output.

use iced::widget::{button, checkbox, column, container, row, scrollable, text, Space};
use iced::{Alignment, Element, Length};

use crate::app::{App, Message};

/// Build the manual selection window view.
pub fn view(app: &App) -> Element<'_, Message> {
    // Header with job info
    let job_name = app.manual_selection_job_idx
        .and_then(|idx| {
            let q = app.job_queue.lock().unwrap();
            q.jobs().get(idx).map(|j| j.name.clone())
        })
        .unwrap_or_else(|| "Unknown Job".to_string());

    let header = row![
        text("Manual Track Selection").size(24),
        Space::new().width(Length::Fill),
        text(job_name).size(14),
    ]
    .align_y(Alignment::Center);

    // Info message
    let info_text: Element<'_, Message> = if app.manual_selection_info.is_empty() {
        text("Double-click tracks to add them to the final output.").size(13).into()
    } else {
        text(&app.manual_selection_info).size(13).into()
    };

    // Left pane: Source groups with tracks
    let source_groups: Vec<Element<'_, Message>> = app
        .source_groups
        .iter()
        .map(|group| {
            let group_header = text(&group.title).size(14);

            let tracks: Vec<Element<'_, Message>> = group
                .tracks
                .iter()
                .map(|track| {
                    let track_id = track.id;
                    let source_key = group.source_key.clone();

                    let icon = match track.track_type.as_str() {
                        "video" => "🎬",
                        "audio" => "🔊",
                        "subtitles" => "💬",
                        _ => "📄",
                    };

                    let track_row = row![
                        text(icon).width(24),
                        text(&track.summary).width(Length::Fill),
                        text(&track.badges).size(11),
                    ]
                    .spacing(4)
                    .align_y(Alignment::Center);

                    let track_btn = button(track_row)
                        .on_press(Message::SourceTrackDoubleClicked {
                            track_id,
                            source_key
                        })
                        .width(Length::Fill)
                        .padding([4, 8]);

                    if track.is_blocked {
                        container(track_btn)
                            .style(|_theme| container::Style {
                                text_color: Some(iced::Color::from_rgb(0.5, 0.5, 0.5)),
                                ..Default::default()
                            })
                            .into()
                    } else {
                        track_btn.into()
                    }
                })
                .collect();

            column![
                group_header,
                column(tracks).spacing(2),
            ]
            .spacing(4)
            .into()
        })
        .collect();

    let left_pane = column![
        text("Available Tracks").size(16),
        Space::new().height(8),
        scrollable(column(source_groups).spacing(12))
            .height(Length::Fill),
        Space::new().height(8),
        button("Add External Subtitle(s)...").on_press(Message::AddExternalSubtitles),
    ]
    .spacing(4)
    .width(Length::FillPortion(1));

    // Right pane: Final output
    let final_tracks: Vec<Element<'_, Message>> = app
        .final_tracks
        .iter()
        .enumerate()
        .map(|(idx, track)| {
            let icon = match track.track_type.as_str() {
                "video" => "🎬",
                "audio" => "🔊",
                "subtitles" => "💬",
                _ => "📄",
            };

            row![
                text(format!("{}.", idx + 1)).width(24),
                text(icon).width(24),
                text(&track.summary).width(Length::Fill),
                text(&track.source_key).size(11),
                checkbox(track.is_default)
                    .label("D")
                    .on_toggle(move |v| Message::FinalTrackDefaultChanged(idx, v)),
                checkbox(track.is_forced)
                    .label("F")
                    .on_toggle(move |v| Message::FinalTrackForcedChanged(idx, v)),
                button("⚙").on_press(Message::FinalTrackSettingsClicked(idx)),
                button("✕").on_press(Message::FinalTrackRemoved(idx)),
            ]
            .spacing(4)
            .align_y(Alignment::Center)
            .into()
        })
        .collect();

    let final_list: Element<'_, Message> = if final_tracks.is_empty() {
        container(text("No tracks added yet.").size(13))
            .padding(20)
            .center_x(Length::Fill)
            .into()
    } else {
        scrollable(column(final_tracks).spacing(4))
            .height(Length::Fill)
            .into()
    };

    // Attachments section
    let attachment_checks: Vec<Element<'_, Message>> = app
        .source_groups
        .iter()
        .map(|group| {
            let key = group.source_key.clone();
            let key_for_toggle = key.clone();
            let checked = app.attachment_sources.get(&key).copied().unwrap_or(false);
            checkbox(checked)
                .label(key)
                .on_toggle(move |v| Message::AttachmentToggled(key_for_toggle.clone(), v))
                .into()
        })
        .collect();

    let right_pane = column![
        text("Final Output").size(16),
        Space::new().height(8),
        container(final_list)
            .style(container::bordered_box)
            .height(Length::Fill),
        Space::new().height(8),
        text("Include Attachments From:").size(14),
        row(attachment_checks).spacing(12),
    ]
    .spacing(4)
    .width(Length::FillPortion(1));

    // Main content with two panes
    let panes = row![
        left_pane,
        Space::new().width(16),
        right_pane,
    ];

    // Dialog buttons
    let dialog_buttons = row![
        Space::new().width(Length::Fill),
        button("Accept Layout").on_press(Message::AcceptLayout),
        button("Cancel").on_press(Message::CloseManualSelection),
    ]
    .spacing(8);

    let content = column![
        header,
        Space::new().height(4),
        info_text,
        Space::new().height(12),
        panes,
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
