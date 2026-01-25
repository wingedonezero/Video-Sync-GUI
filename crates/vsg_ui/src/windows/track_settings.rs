//! Track settings window view.
//!
//! Dialog for configuring individual track settings like language, name, and subtitle options.

use iced::widget::{button, checkbox, column, container, pick_list, row, text, text_input, Space};
use iced::{Alignment, Element, Length};

use crate::app::{App, Message};

/// Common language codes for the picker.
const LANGUAGES: &[&str] = &[
    "und (Undetermined)",
    "eng (English)",
    "jpn (Japanese)",
    "spa (Spanish)",
    "fre (French)",
    "ger (German)",
    "ita (Italian)",
    "por (Portuguese)",
    "rus (Russian)",
    "chi (Chinese)",
    "kor (Korean)",
    "ara (Arabic)",
];

/// Build the track settings window view.
pub fn view(app: &App) -> Element<'_, Message> {
    let track_type = &app.track_settings.track_type;
    let is_subtitle = track_type == "subtitles";

    // Header
    let header = text("Track Settings").size(24);

    let track_info = text(format!(
        "Configuring {} track",
        match track_type.as_str() {
            "video" => "Video",
            "audio" => "Audio",
            "subtitles" => "Subtitle",
            _ => "Unknown",
        }
    ))
    .size(13);

    // Language selector
    let selected_lang = LANGUAGES.get(app.track_settings.selected_language_idx).copied();

    let language_row = row![
        text("Language:").width(140),
        pick_list(
            LANGUAGES.to_vec(),
            selected_lang,
            |selected| {
                let idx = LANGUAGES.iter().position(|&l| l == selected).unwrap_or(0);
                Message::TrackLanguageChanged(idx)
            }
        )
        .width(Length::Fill),
    ]
    .spacing(8)
    .align_y(Alignment::Center);

    // Custom name input
    let name_row = row![
        text("Custom Name:").width(140),
        text_input("Leave empty for default", &app.track_settings.custom_name)
            .on_input(Message::TrackCustomNameChanged)
            .width(Length::Fill),
    ]
    .spacing(8)
    .align_y(Alignment::Center);

    // Subtitle-specific options
    let subtitle_options: Element<'_, Message> = if is_subtitle {
        column![
            Space::new().height(8),
            text("Subtitle Options").size(16),
            Space::new().height(8),
            checkbox(app.track_settings.perform_ocr)
                .label("Perform OCR (for image-based subtitles)")
                .on_toggle(Message::TrackPerformOcrChanged),
            checkbox(app.track_settings.convert_to_ass)
                .label("Convert to ASS (SRT only)")
                .on_toggle(Message::TrackConvertToAssChanged),
            checkbox(app.track_settings.rescale)
                .label("Rescale to video resolution")
                .on_toggle(Message::TrackRescaleChanged),
            row![
                text("Size Multiplier (%):").width(140),
                text_input(
                    "100",
                    &app.track_settings.size_multiplier_pct.to_string()
                )
                .on_input(|s| {
                    Message::TrackSizeMultiplierChanged(s.parse().unwrap_or(100))
                })
                .width(80),
            ]
            .spacing(8)
            .align_y(Alignment::Center),
            Space::new().height(8),
            button("Configure Sync Exclusions...").on_press(Message::ConfigureSyncExclusion),
        ]
        .spacing(4)
        .into()
    } else {
        Space::new().height(0).into()
    };

    // Dialog buttons
    let dialog_buttons = row![
        Space::new().width(Length::Fill),
        button("OK").on_press(Message::AcceptTrackSettings),
        button("Cancel").on_press(Message::CloseTrackSettings),
    ]
    .spacing(8);

    let content = column![
        header,
        Space::new().height(4),
        track_info,
        Space::new().height(16),
        language_row,
        Space::new().height(8),
        name_row,
        subtitle_options,
        Space::new().height(Length::Fill),
        dialog_buttons,
    ]
    .spacing(4)
    .padding(16);

    container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}
