//! Manual selection window view.
//!
//! Dialog for manually selecting and arranging tracks for a job's output.
//! Left pane shows available tracks from sources, right pane shows final output.

use iced::widget::{button, checkbox, column, container, row, scrollable, text, Space};
use iced::{Alignment, Background, Border, Color, Element, Length, Theme};

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
        text("Click tracks to add them to the final output. Use ↑/↓ to reorder.").size(13).into()
    } else {
        text(&app.manual_selection_info).size(13).into()
    };

    // =========================================================================
    // LEFT PANE: Source groups with tracks
    // =========================================================================
    let source_groups: Vec<Element<'_, Message>> = app
        .source_groups
        .iter()
        .map(|group| {
            // Group header with source name
            let group_header = container(
                text(&group.title).size(14)
            )
            .padding([6, 8])
            .width(Length::Fill)
            .style(|_theme: &Theme| container::Style {
                background: Some(Background::Color(Color::from_rgb(0.18, 0.18, 0.18))),
                ..Default::default()
            });

            // Track rows - 2 lines per track
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

                    // Line 1: icon + main summary + badges
                    let line1 = row![
                        text(icon).width(20),
                        text(&track.summary).width(Length::Fill),
                        text(&track.badges).size(10),
                    ]
                    .spacing(4)
                    .align_y(Alignment::Center);

                    // Line 2: codec details
                    let line2 = row![
                        Space::new().width(20),
                        text(&track.codec_id).size(11).color(Color::from_rgb(0.6, 0.6, 0.6)),
                    ]
                    .spacing(4);

                    let track_content = column![line1, line2].spacing(2);

                    let track_btn = button(track_content)
                        .on_press(Message::SourceTrackDoubleClicked {
                            track_id,
                            source_key
                        })
                        .width(Length::Fill)
                        .padding([6, 8])
                        .style(move |_theme, _status| {
                            button::Style {
                                background: Some(Background::Color(Color::TRANSPARENT)),
                                text_color: Color::from_rgb(0.9, 0.9, 0.9),
                                border: Border::default(),
                                ..Default::default()
                            }
                        });

                    if track.is_blocked {
                        container(track_btn)
                            .style(|_theme| container::Style {
                                text_color: Some(Color::from_rgb(0.5, 0.5, 0.5)),
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
                column(tracks).spacing(1),
            ]
            .spacing(0)
            .into()
        })
        .collect();

    // External subtitles section (if any)
    let external_section: Element<'_, Message> = if app.external_subtitles.is_empty() {
        Space::new().height(0).into()
    } else {
        let ext_items: Vec<Element<'_, Message>> = app.external_subtitles
            .iter()
            .enumerate()
            .map(|(idx, path)| {
                let filename = path.file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_else(|| path.to_string_lossy().to_string());
                row![
                    text("💬").width(20),
                    text(filename).width(Length::Fill).size(13),
                    button("✕").on_press(Message::FinalTrackRemoved(idx)), // TODO: proper external sub removal
                ]
                .spacing(4)
                .padding([4, 8])
                .into()
            })
            .collect();

        column![
            container(text("External Subtitles").size(14))
                .padding([6, 8])
                .width(Length::Fill)
                .style(|_theme: &Theme| container::Style {
                    background: Some(Background::Color(Color::from_rgb(0.18, 0.18, 0.18))),
                    ..Default::default()
                }),
            column(ext_items).spacing(1),
        ]
        .spacing(0)
        .into()
    };

    let left_pane = column![
        text("Available Tracks").size(16),
        Space::new().height(8),
        container(
            scrollable(
                column![
                    column(source_groups).spacing(8),
                    external_section,
                ]
                .spacing(12)
            )
            .height(Length::Fill)
        )
        .style(container::bordered_box)
        .height(Length::Fill),
        Space::new().height(8),
        button("Add External Subtitle(s)...").on_press(Message::AddExternalSubtitles),
    ]
    .spacing(4)
    .width(Length::FillPortion(1))
    .height(Length::Fill);

    // =========================================================================
    // RIGHT PANE: Final output + attachments
    // =========================================================================
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

            let track_count = app.final_tracks.len();
            let can_move_up = idx > 0;
            let can_move_down = idx < track_count.saturating_sub(1);

            // Line 1: index + icon + summary + source tag
            let line1 = row![
                text(format!("{}.", idx + 1)).width(24),
                text(icon).width(20),
                text(&track.summary).width(Length::Fill).size(13),
                container(text(&track.source_key).size(10))
                    .padding([2, 6])
                    .style(|_theme: &Theme| container::Style {
                        background: Some(Background::Color(Color::from_rgb(0.25, 0.25, 0.25))),
                        border: Border {
                            radius: 3.0.into(),
                            ..Default::default()
                        },
                        ..Default::default()
                    }),
            ]
            .spacing(4)
            .align_y(Alignment::Center);

            // Line 2: controls (D/F checkboxes, move, settings, delete)
            let move_up_btn = if can_move_up {
                button("↑").on_press(Message::FinalTrackMoved(idx, idx - 1)).width(28)
            } else {
                button("↑").width(28)
            };

            let move_down_btn = if can_move_down {
                button("↓").on_press(Message::FinalTrackMoved(idx, idx + 1)).width(28)
            } else {
                button("↓").width(28)
            };

            let line2 = row![
                Space::new().width(44), // align with icon column
                checkbox(track.is_default)
                    .label("Default")
                    .on_toggle(move |v| Message::FinalTrackDefaultChanged(idx, v)),
                checkbox(track.is_forced)
                    .label("Forced")
                    .on_toggle(move |v| Message::FinalTrackForcedChanged(idx, v)),
                Space::new().width(Length::Fill),
                move_up_btn,
                move_down_btn,
                button("⚙").on_press(Message::FinalTrackSettingsClicked(idx)).width(28),
                button("✕").on_press(Message::FinalTrackRemoved(idx)).width(28),
            ]
            .spacing(4)
            .align_y(Alignment::Center);

            container(
                column![line1, line2].spacing(4)
            )
            .padding([8, 8])
            .width(Length::Fill)
            .style(|_theme: &Theme| container::Style {
                background: Some(Background::Color(Color::from_rgb(0.12, 0.12, 0.12))),
                border: Border {
                    radius: 4.0.into(),
                    ..Default::default()
                },
                ..Default::default()
            })
            .into()
        })
        .collect();

    let final_list: Element<'_, Message> = if final_tracks.is_empty() {
        container(
            column![
                text("No tracks added yet").size(14),
                Space::new().height(4),
                text("Click tracks on the left to add them here.").size(12).color(Color::from_rgb(0.6, 0.6, 0.6)),
            ]
            .align_x(Alignment::Center)
        )
        .padding(30)
        .width(Length::Fill)
        .center_x(Length::Fill)
        .into()
    } else {
        scrollable(column(final_tracks).spacing(4).width(Length::Fill))
            .height(Length::Fill)
            .into()
    };

    // Attachments section (pinned at bottom)
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
            .height(Length::FillPortion(1)),
        Space::new().height(12),
        text("Include Attachments From:").size(14),
        Space::new().height(4),
        row(attachment_checks).spacing(16),
    ]
    .spacing(4)
    .width(Length::FillPortion(2))  // Right pane is wider
    .height(Length::Fill);

    // =========================================================================
    // MAIN LAYOUT
    // =========================================================================
    let panes = row![
        left_pane,
        Space::new().width(16),
        right_pane,
    ]
    .height(Length::Fill);

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
    .padding(16)
    .height(Length::Fill);

    container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}
