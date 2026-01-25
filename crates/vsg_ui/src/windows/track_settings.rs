//! Track Settings dialog view.

use cosmic::iced::{Alignment, Length};
use cosmic::prelude::*;
use cosmic::{widget, Element};

use crate::app::{App, Message};

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

static LANGUAGE_NAMES: &[&str] = &[
    "Undetermined", "English", "Japanese", "Spanish", "French", "German", "Italian", "Portuguese",
    "Russian", "Chinese", "Korean", "Arabic", "Hindi", "Thai", "Vietnamese", "Polish",
    "Dutch", "Swedish", "Norwegian", "Danish", "Finnish", "Turkish", "Greek", "Hebrew",
    "Hungarian", "Czech", "Romanian", "Bulgarian", "Ukrainian",
];

pub fn view(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let is_subtitle = app.track_settings.track_type == "subtitles";

    let mut content = widget::column()
        .push(widget::text::title3("Track Settings"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_m.into())))
        .push(
            widget::row()
                .push(widget::text::body("Language:").width(Length::Fixed(120.0)))
                .push(
                    widget::dropdown(LANGUAGE_NAMES, Some(app.track_settings.selected_language_idx), Message::TrackLanguageChanged)
                )
                .spacing(spacing.space_s)
                .align_y(Alignment::Center)
        )
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::row()
                .push(widget::text::body("Custom Name:").width(Length::Fixed(120.0)))
                .push(
                    widget::text_input::text_input("", &app.track_settings.custom_name)
                        .on_input(Message::TrackCustomNameChanged)
                        .width(Length::Fill)
                )
                .spacing(spacing.space_s)
                .align_y(Alignment::Center)
        )
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_l.into())));

    if is_subtitle {
        content = content
            .push(widget::text::title4("Subtitle Options"))
            .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
            .push(
                widget::checkbox("Perform OCR (image-based subtitles)", app.track_settings.perform_ocr)
                    .on_toggle(Message::TrackPerformOcrChanged)
            )
            .push(
                widget::checkbox("Convert to ASS format", app.track_settings.convert_to_ass)
                    .on_toggle(Message::TrackConvertToAssChanged)
            )
            .push(
                widget::row()
                    .push(
                        widget::checkbox("Rescale", app.track_settings.rescale)
                            .on_toggle(Message::TrackRescaleChanged)
                    )
                    .push(widget::horizontal_space().width(Length::Fixed(spacing.space_s.into())))
                    .push(widget::text::body("Size multiplier:"))
                    .push(
                        widget::text_input::text_input("100", app.track_settings.size_multiplier_pct.to_string())
                            .on_input(|v| Message::TrackSizeMultiplierChanged(v.parse().unwrap_or(100)))
                            .width(Length::Fixed(60.0))
                    )
                    .push(widget::text::body("%"))
                    .spacing(spacing.space_s)
                    .align_y(Alignment::Center)
            )
            .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
            .push(
                widget::button::standard("Configure Sync Exclusion...")
                    .on_press(Message::ConfigureSyncExclusion)
            );
    }

    content = content
        .push(widget::vertical_space())
        .push(
            widget::row()
                .push(widget::horizontal_space())
                .push(
                    widget::button::standard("Cancel")
                        .on_press(Message::CloseTrackSettings)
                )
                .push(
                    widget::button::suggested("OK")
                        .on_press(Message::AcceptTrackSettings)
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
