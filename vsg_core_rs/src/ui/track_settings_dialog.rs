//! Track settings dialog layout mirroring `python/vsg_qt/track_settings_dialog/ui.py`.

use cosmic::iced::Length;
use cosmic::widget::{self};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    SelectLanguage(usize),
    UpdateCustomName(String),
    ToggleOcr(bool),
    ToggleCleanup(bool),
    ToggleConvert(bool),
    ToggleRescale(bool),
    UpdateSizeMultiplier(String),
    ConfigureSyncExclusion,
    Confirm,
    Cancel,
}

#[derive(Clone, Debug)]
pub struct State {
    pub languages: Vec<String>,
    pub selected_language: Option<usize>,
    pub custom_name: String,
    pub perform_ocr: bool,
    pub perform_cleanup: bool,
    pub convert_to_ass: bool,
    pub rescale: bool,
    pub size_multiplier: String,
}

impl Default for State {
    fn default() -> Self {
        Self {
            languages: vec!["eng".to_string(), "jpn".to_string(), "und".to_string()],
            selected_language: Some(0),
            custom_name: String::new(),
            perform_ocr: false,
            perform_cleanup: false,
            convert_to_ass: false,
            rescale: false,
            size_multiplier: "1.0".to_string(),
        }
    }
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::SelectLanguage(index) => self.selected_language = Some(index),
            Message::UpdateCustomName(value) => self.custom_name = value,
            Message::ToggleOcr(value) => self.perform_ocr = value,
            Message::ToggleCleanup(value) => self.perform_cleanup = value,
            Message::ToggleConvert(value) => self.convert_to_ass = value,
            Message::ToggleRescale(value) => self.rescale = value,
            Message::UpdateSizeMultiplier(value) => self.size_multiplier = value,
            Message::ConfigureSyncExclusion | Message::Confirm | Message::Cancel => {}
        }
    }
}

pub fn view(state: &State) -> Element<Message> {
    let language = widget::column()
        .spacing(8)
        .push(common::form_row(
            "Language Code:",
            common::dropdown(
                &["eng", "jpn", "spa", "und"],
                state.selected_language,
                Message::SelectLanguage,
            ),
        ));

    let name = widget::column()
        .spacing(8)
        .push(common::form_row(
            "Custom Name:",
            common::text_input("Track name", &state.custom_name, Message::UpdateCustomName),
        ));

    let subtitle_options = widget::column()
        .spacing(8)
        .push(common::checkbox(
            "Perform OCR",
            state.perform_ocr,
            Message::ToggleOcr,
        ))
        .push(common::checkbox(
            "Perform Post-OCR Cleanup",
            state.perform_cleanup,
            Message::ToggleCleanup,
        ))
        .push(common::checkbox(
            "Convert to ASS (SRT only)",
            state.convert_to_ass,
            Message::ToggleConvert,
        ))
        .push(common::checkbox(
            "Rescale to video resolution",
            state.rescale,
            Message::ToggleRescale,
        ))
        .push(common::form_row(
            "Size multiplier:",
            common::numeric_input("x", &state.size_multiplier, Message::UpdateSizeMultiplier),
        ))
        .push(common::button(
            "Configure Frame Sync Exclusions...",
            Message::ConfigureSyncExclusion,
        ));

    let content = widget::column()
        .spacing(16)
        .push(common::subsection("Language Settings", language.into()))
        .push(common::subsection("Track Name", name.into()))
        .push(common::subsection("Subtitle Options", subtitle_options.into()));

    let buttons = widget::row()
        .spacing(12)
        .push(widget::horizontal_space(Length::Fill))
        .push(common::button("OK", Message::Confirm))
        .push(common::button("Cancel", Message::Cancel));

    widget::column()
        .spacing(16)
        .padding(16)
        .push(content)
        .push(buttons)
        .into()
}
