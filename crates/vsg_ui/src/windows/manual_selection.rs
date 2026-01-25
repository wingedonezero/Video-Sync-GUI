//! Manual Selection dialog view.

use cosmic::iced::{Alignment, Length};
use cosmic::prelude::*;
use cosmic::{widget, Element};

use crate::app::{App, FinalTrackState, Message, SourceGroupState};

pub fn view(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let mut content = widget::column()
        .push(widget::text::title3("Manual Track Selection"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())));

    if !app.manual_selection_info.is_empty() {
        content = content.push(widget::text::body(&app.manual_selection_info));
    }

    content = content
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::row()
                .push(
                    widget::container(
                        widget::column()
                            .push(widget::text::title4("Available Tracks"))
                            .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
                            .push(
                                widget::scrollable(
                                    app.source_groups.iter().fold(
                                        widget::column().spacing(spacing.space_s),
                                        |col, group| col.push(source_group(group))
                                    )
                                )
                                .height(Length::Fill)
                            )
                            .spacing(spacing.space_xxs)
                    )
                    .width(Length::FillPortion(35))
                    .padding(spacing.space_s)
                )
                .push(
                    widget::container(
                        widget::column()
                            .push(widget::text::title4("Final Output Tracks"))
                            .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
                            .push(
                                widget::scrollable(
                                    app.final_tracks.iter().enumerate().fold(
                                        widget::column().spacing(spacing.space_xxs),
                                        |col, (idx, track)| {
                                            col.push(final_track_row(idx, track, &app.source_keys()))
                                        }
                                    )
                                )
                                .height(Length::Fill)
                            )
                            .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
                            .push(
                                widget::button::standard("+ Add External Subtitles")
                                    .on_press(Message::AddExternalSubtitles)
                            )
                            .spacing(spacing.space_xxs)
                    )
                    .width(Length::FillPortion(65))
                    .padding(spacing.space_s)
                )
                .height(Length::FillPortion(1))
        )
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(attachment_section(app))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_m.into())))
        .push(
            widget::row()
                .push(widget::horizontal_space())
                .push(
                    widget::button::standard("Cancel")
                        .on_press(Message::CloseManualSelection)
                )
                .push(
                    widget::button::suggested("Accept")
                        .on_press(Message::AcceptLayout)
                )
                .spacing(spacing.space_s)
        )
        .spacing(spacing.space_xxs)
        .padding(spacing.space_l);

    widget::container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}

fn source_group(group: &SourceGroupState) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let title = group.title.clone();
    let source_key = group.source_key.clone();

    let tracks_column = group.tracks.iter().fold(
        widget::column().spacing(2),
        |col, track| {
            let track_id = track.id;
            let source_key_clone = source_key.clone();
            let summary = track.summary.clone();
            let is_blocked = track.is_blocked;
            let type_char = track.track_type.chars().next().unwrap_or('?').to_ascii_uppercase();

            let track_label = format!("[{}] {}", type_char, summary);

            let mut track_button = widget::button::text(track_label)
                .width(Length::Fill);

            if !is_blocked {
                track_button = track_button.on_press(Message::SourceTrackDoubleClicked {
                    track_id,
                    source_key: source_key_clone,
                });
            }

            col.push(track_button)
        }
    );

    widget::column()
        .push(widget::text::body(title))
        .push(widget::container(tracks_column).padding([0, 0, 0, spacing.space_m]))
        .spacing(spacing.space_xxs)
        .into()
}

fn final_track_row(idx: usize, track: &FinalTrackState, _source_keys: &[String]) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let summary = track.summary.clone();
    let is_subtitle = track.track_type == "subtitles";
    let is_default = track.is_default;
    let is_forced = track.is_forced;
    let sync_to = track.sync_to_source.clone();

    let mut row = widget::row()
        .push(widget::text::body(format!("{}. {}", idx + 1, summary)).width(Length::FillPortion(1)));

    if is_subtitle {
        row = row.push(
            widget::checkbox("Default", is_default)
                .on_toggle(move |v| Message::FinalTrackDefaultChanged(idx, v))
        );
        row = row.push(
            widget::checkbox("Forced", is_forced)
                .on_toggle(move |v| Message::FinalTrackForcedChanged(idx, v))
        );

        // Show sync target as text instead of dropdown (to avoid lifetime issues)
        row = row.push(
            widget::text::caption(format!("Sync: {}", sync_to))
        );
    }

    row = row
        .push(
            widget::button::standard("...")
                .on_press(Message::FinalTrackSettingsClicked(idx))
        )
        .push(
            widget::button::standard("X")
                .on_press(Message::FinalTrackRemoved(idx))
        )
        .spacing(spacing.space_s)
        .align_y(Alignment::Center);

    row.into()
}

fn attachment_section(app: &App) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let checkboxes = app.source_groups.iter().fold(
        widget::row().spacing(spacing.space_m),
        |row, group| {
            let source_key = group.source_key.clone();
            let checked = app.attachment_sources.get(&source_key).copied().unwrap_or(false);
            let key_for_msg = source_key.clone();
            row.push(
                widget::checkbox(source_key, checked)
                    .on_toggle(move |v| Message::AttachmentToggled(key_for_msg.clone(), v))
            )
        }
    );

    widget::column()
        .push(widget::text::body("Include Attachments From:"))
        .push(checkboxes)
        .spacing(spacing.space_xxs)
        .into()
}
