//! Resample dialog layout mirroring `python/vsg_qt/resample_dialog/ui.py`.

use cosmic::iced::Length;
use cosmic::widget::{self};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    UpdateDestWidth(String),
    UpdateDestHeight(String),
    FromVideo,
    Confirm,
    Cancel,
}

#[derive(Clone, Debug)]
pub struct State {
    pub src_width: String,
    pub src_height: String,
    pub dest_width: String,
    pub dest_height: String,
}

impl Default for State {
    fn default() -> Self {
        Self {
            src_width: "1920".to_string(),
            src_height: "1080".to_string(),
            dest_width: "1920".to_string(),
            dest_height: "1080".to_string(),
        }
    }
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::UpdateDestWidth(value) => self.dest_width = value,
            Message::UpdateDestHeight(value) => self.dest_height = value,
            Message::FromVideo | Message::Confirm | Message::Cancel => {}
        }
    }
}

pub fn view(state: &State) -> Element<Message> {
    let source = widget::column()
        .spacing(8)
        .push(common::form_row(
            "Width (X):",
            widget::text::body(&state.src_width).into(),
        ))
        .push(common::form_row(
            "Height (Y):",
            widget::text::body(&state.src_height).into(),
        ));

    let dest = widget::column()
        .spacing(8)
        .push(common::form_row(
            "Width (X):",
            common::numeric_input("px", &state.dest_width, Message::UpdateDestWidth),
        ))
        .push(common::form_row(
            "Height (Y):",
            common::numeric_input("px", &state.dest_height, Message::UpdateDestHeight),
        ))
        .push(common::button("From Video", Message::FromVideo));

    let buttons = widget::row()
        .spacing(12)
        .push(widget::horizontal_space(Length::Fill))
        .push(common::button("OK", Message::Confirm))
        .push(common::button("Cancel", Message::Cancel));

    widget::column()
        .spacing(16)
        .padding(16)
        .push(common::subsection("Source Resolution (from Script)", source.into()))
        .push(common::subsection("Destination Resolution", dest.into()))
        .push(buttons)
        .into()
}
