//! Track settings window view.
//!
//! Dialog for configuring individual track settings like language, name, and subtitle options.
//! Shows/hides options based on codec compatibility (like Qt reference implementation).

use iced::widget::{button, checkbox, column, container, pick_list, row, text, text_input, Space};
use iced::{Alignment, Color, Element, Length, Theme};

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

/// Check if codec is OCR-compatible (image-based subtitles).
fn is_ocr_compatible(codec_id: &str) -> bool {
    let codec_upper = codec_id.to_uppercase();
    codec_upper.contains("VOBSUB") || codec_upper.contains("PGS")
}

/// Check if codec can be converted to ASS (SRT subtitles).
fn is_convert_to_ass_compatible(codec_id: &str) -> bool {
    codec_id.to_uppercase().contains("S_TEXT/UTF8")
}

/// Check if codec supports style editing (ASS/SSA subtitles).
fn is_style_editable(codec_id: &str) -> bool {
    let codec_upper = codec_id.to_uppercase();
    codec_upper.contains("S_TEXT/ASS") || codec_upper.contains("S_TEXT/SSA")
}

/// Build the track settings window view.
pub fn view(app: &App) -> Element<'_, Message> {
    let track_type = &app.track_settings.track_type;
    let codec_id = &app.track_settings.codec_id;
    let is_subtitle = track_type == "subtitles";

    // Codec compatibility checks
    let can_ocr = is_ocr_compatible(codec_id);
    let can_convert_to_ass = is_convert_to_ass_compatible(codec_id);
    let can_style_edit = is_style_editable(codec_id);

    // Header
    let header = text("Track Settings").size(24);

    // Track info with codec
    let track_type_display = match track_type.as_str() {
        "video" => "Video",
        "audio" => "Audio",
        "subtitles" => "Subtitle",
        _ => "Unknown",
    };

    let track_info: Element<'_, Message> = if !codec_id.is_empty() {
        column![
            text(format!("Configuring {} track", track_type_display)).size(13),
            text(format!("Codec: {}", codec_id)).size(11).color(Color::from_rgb(0.6, 0.6, 0.6)),
        ]
        .spacing(2)
        .into()
    } else {
        text(format!("Configuring {} track", track_type_display)).size(13).into()
    };

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
    let custom_name_str = app.track_settings.custom_name.as_deref().unwrap_or("");
    let name_row = row![
        text("Custom Name:").width(140),
        text_input("Leave empty for default", custom_name_str)
            .on_input(|s| Message::TrackCustomNameChanged(s))
            .width(Length::Fill),
    ]
    .spacing(8)
    .align_y(Alignment::Center);

    // Subtitle-specific options with codec-aware enabling/disabling
    let subtitle_options: Element<'_, Message> = if is_subtitle {
        let mut options = column![
            Space::new().height(8),
            text("Subtitle Options").size(16),
            Space::new().height(8),
        ]
        .spacing(4);

        // OCR checkbox - only enabled for VOBSUB/PGS
        if can_ocr {
            options = options.push(
                checkbox(app.track_settings.perform_ocr)
                    .label("Perform OCR (image-based subtitle)")
                    .on_toggle(Message::TrackPerformOcrChanged)
            );
        } else {
            options = options.push(
                container(
                    row![
                        checkbox(app.track_settings.perform_ocr).label("Perform OCR"),
                        text(" (requires VOBSUB/PGS)").size(11).color(Color::from_rgb(0.5, 0.5, 0.5)),
                    ]
                    .align_y(Alignment::Center)
                )
                .style(|_theme: &Theme| container::Style {
                    text_color: Some(Color::from_rgb(0.4, 0.4, 0.4)),
                    ..Default::default()
                })
            );
        }

        // Convert to ASS checkbox - only enabled for SRT
        if can_convert_to_ass {
            options = options.push(
                checkbox(app.track_settings.convert_to_ass)
                    .label("Convert to ASS format")
                    .on_toggle(Message::TrackConvertToAssChanged)
            );
        } else {
            options = options.push(
                container(
                    row![
                        checkbox(app.track_settings.convert_to_ass).label("Convert to ASS"),
                        text(" (requires SRT)").size(11).color(Color::from_rgb(0.5, 0.5, 0.5)),
                    ]
                    .align_y(Alignment::Center)
                )
                .style(|_theme: &Theme| container::Style {
                    text_color: Some(Color::from_rgb(0.4, 0.4, 0.4)),
                    ..Default::default()
                })
            );
        }

        // Rescale checkbox - always available for subtitles
        options = options.push(
            checkbox(app.track_settings.rescale)
                .label("Rescale to video resolution")
                .on_toggle(Message::TrackRescaleChanged)
        );

        // Size multiplier
        options = options.push(
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
            .align_y(Alignment::Center)
        );

        options = options.push(Space::new().height(8));

        // Sync Exclusion button - only for ASS/SSA
        if can_style_edit {
            let exclusion_info = if app.track_settings.sync_exclusion_styles.is_empty() {
                "No styles excluded".to_string()
            } else {
                format!("{} style(s) excluded", app.track_settings.sync_exclusion_styles.len())
            };

            options = options.push(
                row![
                    button("Configure Sync Exclusions...").on_press(Message::ConfigureSyncExclusion),
                    Space::new().width(8),
                    text(exclusion_info).size(11).color(Color::from_rgb(0.6, 0.6, 0.6)),
                ]
                .align_y(Alignment::Center)
            );

            // Style editor button
            options = options.push(Space::new().height(4));
            options = options.push(
                button("Edit Styles...").on_press(Message::OpenStyleEditor(
                    app.track_settings_idx.unwrap_or(0)
                ))
            );
        } else {
            options = options.push(
                container(
                    text("Sync Exclusion and Style Editing require ASS/SSA subtitles")
                        .size(11)
                        .color(Color::from_rgb(0.5, 0.5, 0.5))
                )
                .padding([8, 0])
            );
        }

        options.into()
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
