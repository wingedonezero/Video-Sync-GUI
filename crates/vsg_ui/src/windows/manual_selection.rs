//! Manual Selection dialog view.

use cosmic::iced::alignment::Vertical;
use cosmic::iced::Length;
use cosmic::widget::{self, button, checkbox, column, container, dropdown, horizontal_space, row, scrollable, text, vertical_space};
use cosmic::Element;

use crate::app::{App, Message};
use crate::theme::{font, spacing};

pub fn view(app: &App) -> Element<Message> {
    let content = column![
        text("Manual Track Selection").size(font::HEADER),
        vertical_space().height(spacing::SM),
        if !app.manual_selection_info.is_empty() {
            container(text(&app.manual_selection_info).size(font::NORMAL)).into()
        } else {
            container(text("")).into()
        },
        vertical_space().height(spacing::SM),
        row![
            container(
                column![
                    text("Available Tracks").size(font::MD),
                    vertical_space().height(spacing::SM),
                    scrollable(
                        column(
                            app.source_groups.iter().map(|group| source_group(group)).collect()
                        ).spacing(spacing::SM)
                    ).height(Length::Fill),
                ].spacing(spacing::XS)
            ).width(Length::FillPortion(35)).padding(spacing::SM),
            container(
                column![
                    text("Final Output Tracks").size(font::MD),
                    vertical_space().height(spacing::SM),
                    scrollable(
                        column(
                            app.final_tracks.iter().enumerate().map(|(idx, track)| {
                                final_track_row(idx, track, &app.source_keys())
                            }).collect()
                        ).spacing(spacing::XS)
                    ).height(Length::Fill),
                    vertical_space().height(spacing::SM),
                    button(text("+ Add External Subtitles").size(font::NORMAL))
                        .on_press(Message::AddExternalSubtitles)
                        .padding([spacing::SM, spacing::MD]),
                ].spacing(spacing::XS)
            ).width(Length::FillPortion(65)).padding(spacing::SM),
        ].height(Length::FillPortion(1)),
        vertical_space().height(spacing::SM),
        attachment_section(app),
        vertical_space().height(spacing::MD),
        row![
            horizontal_space(),
            button(text("Cancel").size(font::NORMAL))
                .on_press(Message::CloseManualSelection)
                .padding([spacing::SM, spacing::LG]),
            button(text("Accept").size(font::NORMAL))
                .on_press(Message::AcceptLayout)
                .padding([spacing::SM, spacing::LG]),
        ].spacing(spacing::SM),
    ].spacing(spacing::XS).padding(spacing::LG);

    container(content).width(Length::Fill).height(Length::Fill).into()
}

fn source_group(group: &crate::app::SourceGroupState) -> Element<'static, Message> {
    let title = group.title.clone();
    let source_key = group.source_key.clone();

    let tracks_column = column(
        group.tracks.iter().map(|track| {
            let track_id = track.id;
            let source_key_clone = source_key.clone();
            let summary = track.summary.clone();
            let is_blocked = track.is_blocked;
            let type_char = track.track_type.chars().next().unwrap_or('?').to_ascii_uppercase();

            let track_content = row![
                text(format!("[{}]", type_char)).size(font::SM).width(Length::Fixed(30.0)),
                text(summary).size(font::SM).width(Length::Fill),
            ].spacing(spacing::XS).align_y(Vertical::Center);

            let track_button = button(track_content)
                .on_press_maybe(if is_blocked { None } else {
                    Some(Message::SourceTrackDoubleClicked { track_id, source_key: source_key_clone })
                })
                .padding([spacing::XS, spacing::SM]).width(Length::Fill);

            container(track_button).width(Length::Fill).into()
        }).collect()
    ).spacing(2);

    column![
        text(title).size(font::NORMAL),
        container(tracks_column).padding([0, 0, 0, spacing::MD]),
    ].spacing(spacing::XS).into()
}

fn final_track_row(idx: usize, track: &crate::app::FinalTrackState, source_keys: &[String]) -> Element<'static, Message> {
    let summary = track.summary.clone();
    let is_subtitle = track.track_type == "subtitles";
    let is_default = track.is_default;
    let is_forced = track.is_forced;
    let sync_to = track.sync_to_source.clone();
    let sync_idx = source_keys.iter().position(|k| k == &sync_to).unwrap_or(0);
    let sync_options: Vec<String> = source_keys.to_vec();

    row![
        text(format!("{}. {}", idx + 1, summary)).size(font::NORMAL).width(Length::FillPortion(1)),
        if is_subtitle {
            checkbox("Default", is_default)
                .on_toggle(move |v| Message::FinalTrackDefaultChanged(idx, v))
                .text_size(font::SM).into()
        } else { horizontal_space().width(Length::Fixed(0.0)).into() },
        if is_subtitle {
            checkbox("Forced", is_forced)
                .on_toggle(move |v| Message::FinalTrackForcedChanged(idx, v))
                .text_size(font::SM).into()
        } else { horizontal_space().width(Length::Fixed(0.0)).into() },
        if is_subtitle {
            dropdown(&sync_options, Some(sync_idx), move |new_idx| {
                if new_idx < sync_options.len() {
                    Message::FinalTrackSyncChanged(idx, sync_options[new_idx].clone())
                } else { Message::Noop }
            }).into()
        } else { horizontal_space().width(Length::Fixed(0.0)).into() },
        button(text("...").size(font::SM))
            .on_press(Message::FinalTrackSettingsClicked(idx))
            .padding([spacing::XS, spacing::SM]),
        button(text("X").size(font::SM))
            .on_press(Message::FinalTrackRemoved(idx))
            .padding([spacing::XS, spacing::SM]),
    ].spacing(spacing::SM).align_y(Vertical::Center).into()
}

fn attachment_section(app: &App) -> Element<Message> {
    let checkboxes = row(
        app.source_groups.iter().map(|group| {
            let source_key = group.source_key.clone();
            let checked = app.attachment_sources.get(&source_key).copied().unwrap_or(false);
            let key_for_msg = source_key.clone();
            checkbox(source_key, checked)
                .on_toggle(move |v| Message::AttachmentToggled(key_for_msg.clone(), v))
                .text_size(font::NORMAL).into()
        }).collect()
    ).spacing(spacing::MD);

    column![
        text("Include Attachments From:").size(font::NORMAL),
        checkboxes,
    ].spacing(spacing::XS).into()
}
