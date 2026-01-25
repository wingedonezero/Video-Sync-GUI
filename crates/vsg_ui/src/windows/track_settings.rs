//! Track Settings dialog view.

use cosmic::iced::alignment::Vertical;
use cosmic::iced::Length;
use cosmic::widget::{self, button, checkbox, column, container, dropdown, horizontal_space, row, spin_button, text, text_input, vertical_space};
use cosmic::Element;

use crate::app::{App, Message};
use crate::theme::{font, spacing};

const LANGUAGE_OPTIONS: &[(&str, &str)] = &[
    ("und", "Undetermined"), ("eng", "English"), ("jpn", "Japanese"), ("spa", "Spanish"),
    ("fre", "French"), ("ger", "German"), ("ita", "Italian"), ("por", "Portuguese"),
    ("rus", "Russian"), ("chi", "Chinese"), ("kor", "Korean"), ("ara", "Arabic"),
    ("hin", "Hindi"), ("tha", "Thai"), ("vie", "Vietnamese"), ("pol", "Polish"),
    ("dut", "Dutch"), ("swe", "Swedish"), ("nor", "Norwegian"), ("dan", "Danish"),
    ("fin", "Finnish"), ("tur", "Turkish"), ("gre", "Greek"), ("heb", "Hebrew"),
    ("hun", "Hungarian"), ("cze", "Czech"), ("rum", "Romanian"), ("bul", "Bulgarian"),
    ("ukr", "Ukrainian"),
];

pub fn view(app: &App) -> Element<Message> {
    let is_subtitle = app.track_settings.track_type == "subtitles";
    let language_names: Vec<&str> = LANGUAGE_OPTIONS.iter().map(|(_, name)| *name).collect();

    let content = column![
        text("Track Settings").size(font::HEADER),
        vertical_space().height(spacing::MD),
        row![
            text("Language:").size(font::NORMAL).width(Length::Fixed(120.0)),
            dropdown(&language_names, Some(app.track_settings.selected_language_idx), Message::TrackLanguageChanged),
        ].spacing(spacing::SM).align_y(Vertical::Center),
        vertical_space().height(spacing::SM),
        row![
            text("Custom Name:").size(font::NORMAL).width(Length::Fixed(120.0)),
            text_input("", &app.track_settings.custom_name)
                .on_input(Message::TrackCustomNameChanged)
                .width(Length::Fill).size(font::NORMAL),
        ].spacing(spacing::SM).align_y(Vertical::Center),
        vertical_space().height(spacing::LG),
        if is_subtitle {
            column![
                text("Subtitle Options").size(font::MD),
                vertical_space().height(spacing::SM),
                checkbox("Perform OCR (image-based subtitles)", app.track_settings.perform_ocr)
                    .on_toggle(Message::TrackPerformOcrChanged).text_size(font::NORMAL),
                checkbox("Convert to ASS format", app.track_settings.convert_to_ass)
                    .on_toggle(Message::TrackConvertToAssChanged).text_size(font::NORMAL),
                row![
                    checkbox("Rescale", app.track_settings.rescale)
                        .on_toggle(Message::TrackRescaleChanged).text_size(font::NORMAL),
                    horizontal_space().width(spacing::SM),
                    text("Size multiplier:").size(font::NORMAL),
                    spin_button("", app.track_settings.size_multiplier_pct)
                        .on_change(Message::TrackSizeMultiplierChanged).min(50).max(200).step(5),
                    text("%").size(font::NORMAL),
                ].spacing(spacing::SM).align_y(Vertical::Center),
                vertical_space().height(spacing::SM),
                button(text("Configure Sync Exclusion...").size(font::NORMAL))
                    .on_press(Message::ConfigureSyncExclusion)
                    .padding([spacing::SM, spacing::MD]),
            ].spacing(spacing::XS).into()
        } else { container(text("")).into() },
        vertical_space(),
        row![
            horizontal_space(),
            button(text("Cancel").size(font::NORMAL))
                .on_press(Message::CloseTrackSettings)
                .padding([spacing::SM, spacing::LG]),
            button(text("OK").size(font::NORMAL))
                .on_press(Message::AcceptTrackSettings)
                .padding([spacing::SM, spacing::LG]),
        ].spacing(spacing::SM),
    ].spacing(spacing::XS).padding(spacing::LG);

    container(content).width(Length::Fill).height(Length::Fill).into()
}
