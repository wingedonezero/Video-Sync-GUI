//! Style editor dialog layout mirroring `python/vsg_qt/style_editor_dialog/ui.py`.

use cosmic::iced::Length;
use cosmic::widget::{self, scrollable};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    TogglePlayback,
    SeekChanged(String),
    SelectStyle(usize),
    ResetStyle,
    StripTags,
    Resample,
    UpdateFontName(String),
    UpdateFontSize(String),
    PickPrimaryColor,
    PickSecondaryColor,
    PickOutlineColor,
    PickShadowColor,
    ToggleBold(bool),
    ToggleItalic(bool),
    ToggleUnderline(bool),
    ToggleStrikeout(bool),
    UpdateOutline(String),
    UpdateShadow(String),
    UpdateMarginLeft(String),
    UpdateMarginRight(String),
    UpdateMarginVertical(String),
    Confirm,
    Cancel,
}

#[derive(Clone, Debug)]
pub struct State {
    pub is_playing: bool,
    pub seek_value: String,
    pub styles: Vec<String>,
    pub selected_style: Option<usize>,
    pub font_name: String,
    pub font_size: String,
    pub bold: bool,
    pub italic: bool,
    pub underline: bool,
    pub strikeout: bool,
    pub outline: String,
    pub shadow: String,
    pub margin_left: String,
    pub margin_right: String,
    pub margin_vertical: String,
}

impl Default for State {
    fn default() -> Self {
        Self {
            is_playing: true,
            seek_value: String::new(),
            styles: vec!["Default".to_string(), "Alt Style".to_string()],
            selected_style: Some(0),
            font_name: String::new(),
            font_size: String::new(),
            bold: false,
            italic: false,
            underline: false,
            strikeout: false,
            outline: String::new(),
            shadow: String::new(),
            margin_left: String::new(),
            margin_right: String::new(),
            margin_vertical: String::new(),
        }
    }
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::TogglePlayback => self.is_playing = !self.is_playing,
            Message::SeekChanged(value) => self.seek_value = value,
            Message::SelectStyle(index) => self.selected_style = Some(index),
            Message::ResetStyle => {}
            Message::StripTags | Message::Resample => {}
            Message::UpdateFontName(value) => self.font_name = value,
            Message::UpdateFontSize(value) => self.font_size = value,
            Message::PickPrimaryColor
            | Message::PickSecondaryColor
            | Message::PickOutlineColor
            | Message::PickShadowColor => {}
            Message::ToggleBold(value) => self.bold = value,
            Message::ToggleItalic(value) => self.italic = value,
            Message::ToggleUnderline(value) => self.underline = value,
            Message::ToggleStrikeout(value) => self.strikeout = value,
            Message::UpdateOutline(value) => self.outline = value,
            Message::UpdateShadow(value) => self.shadow = value,
            Message::UpdateMarginLeft(value) => self.margin_left = value,
            Message::UpdateMarginRight(value) => self.margin_right = value,
            Message::UpdateMarginVertical(value) => self.margin_vertical = value,
            Message::Confirm | Message::Cancel => {}
        }
    }
}

pub fn view(state: &State) -> Element<Message> {
    let video_panel = widget::column()
        .spacing(12)
        .push(
            widget::container(widget::text::body("Video Preview"))
                .height(Length::Units(300))
                .width(Length::Fill),
        )
        .push(
            widget::row()
                .spacing(12)
                .push(common::button(
                    if state.is_playing { "Pause" } else { "Play" },
                    Message::TogglePlayback,
                ))
                .push(
                    widget::container(common::text_input(
                        "Seek position (ms)",
                        &state.seek_value,
                        Message::SeekChanged,
                    ))
                    .width(Length::Fill),
                ),
        )
        .push(common::table_placeholder_with_headers(
            "Subtitle Events",
            &["#", "Start", "End", "Style", "Text"],
        ));

    let style_controls = widget::column()
        .spacing(12)
        .push(
            widget::row()
                .spacing(12)
                .push(common::dropdown(
                    &["Default", "Alt Style"],
                    state.selected_style,
                    Message::SelectStyle,
                ))
                .push(common::button("Reset Style", Message::ResetStyle)),
        )
        .push(
            widget::row()
                .spacing(12)
                .push(common::button("Strip Tags from Line(s)", Message::StripTags))
                .push(common::button("Resample...", Message::Resample))
                .push(widget::horizontal_space(Length::Fill)),
        )
        .push(widget::text::caption("Tag warning messages appear here."))
        .push(scrollable(
            widget::column()
                .spacing(8)
                .push(common::form_row(
                    "Font Name:",
                    common::text_input("Font", &state.font_name, Message::UpdateFontName),
                ))
                .push(common::form_row(
                    "Font Size:",
                    common::numeric_input("size", &state.font_size, Message::UpdateFontSize),
                ))
                .push(common::form_row(
                    "Primary Color:",
                    common::button("Pick...", Message::PickPrimaryColor),
                ))
                .push(common::form_row(
                    "Secondary Color:",
                    common::button("Pick...", Message::PickSecondaryColor),
                ))
                .push(common::form_row(
                    "Outline Color:",
                    common::button("Pick...", Message::PickOutlineColor),
                ))
                .push(common::form_row(
                    "Shadow Color:",
                    common::button("Pick...", Message::PickShadowColor),
                ))
                .push(common::form_row(
                    "Bold:",
                    common::checkbox("", state.bold, Message::ToggleBold),
                ))
                .push(common::form_row(
                    "Italic:",
                    common::checkbox("", state.italic, Message::ToggleItalic),
                ))
                .push(common::form_row(
                    "Underline:",
                    common::checkbox("", state.underline, Message::ToggleUnderline),
                ))
                .push(common::form_row(
                    "Strikeout:",
                    common::checkbox("", state.strikeout, Message::ToggleStrikeout),
                ))
                .push(common::form_row(
                    "Outline:",
                    common::numeric_input("px", &state.outline, Message::UpdateOutline),
                ))
                .push(common::form_row(
                    "Shadow:",
                    common::numeric_input("px", &state.shadow, Message::UpdateShadow),
                ))
                .push(common::form_row(
                    "Margin Left:",
                    common::numeric_input("px", &state.margin_left, Message::UpdateMarginLeft),
                ))
                .push(common::form_row(
                    "Margin Right:",
                    common::numeric_input("px", &state.margin_right, Message::UpdateMarginRight),
                ))
                .push(common::form_row(
                    "Margin Vertical:",
                    common::numeric_input(
                        "px",
                        &state.margin_vertical,
                        Message::UpdateMarginVertical,
                    ),
                )),
        ))
        .push(
            widget::row()
                .spacing(12)
                .push(widget::horizontal_space(Length::Fill))
                .push(common::button("OK", Message::Confirm))
                .push(common::button("Cancel", Message::Cancel)),
        );

    widget::row()
        .spacing(16)
        .padding(16)
        .push(widget::container(video_panel).width(Length::FillPortion(3)))
        .push(widget::container(style_controls).width(Length::FillPortion(2)))
        .into()
}
