//! Track widget layout mirroring `python/vsg_qt/track_widget/ui.py`.

use cosmic::iced::Length;
use cosmic::widget::{self};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    SelectSyncSource(usize),
    ToggleDefault(bool),
    ToggleForced(bool),
    ToggleSetName(bool),
    OpenStyleEditor,
    OpenSettings,
}

#[derive(Clone, Debug)]
pub struct State {
    pub summary: String,
    pub source: String,
    pub badges: String,
    pub sync_sources: Vec<String>,
    pub selected_sync: Option<usize>,
    pub is_default: bool,
    pub is_forced: bool,
    pub set_name: bool,
}

impl Default for State {
    fn default() -> Self {
        Self {
            summary: "Track Summary".to_string(),
            source: "Source 1".to_string(),
            badges: String::new(),
            sync_sources: vec![
                "Source 1".to_string(),
                "Source 2".to_string(),
                "Source 3".to_string(),
            ],
            selected_sync: Some(0),
            is_default: false,
            is_forced: false,
            set_name: false,
        }
    }
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::SelectSyncSource(index) => self.selected_sync = Some(index),
            Message::ToggleDefault(value) => self.is_default = value,
            Message::ToggleForced(value) => self.is_forced = value,
            Message::ToggleSetName(value) => self.set_name = value,
            Message::OpenStyleEditor | Message::OpenSettings => {}
        }
    }
}

pub fn view(state: &State) -> Element<Message> {
    let top_row = widget::row()
        .spacing(12)
        .push(widget::text::body(&state.summary).width(Length::FillPortion(3)))
        .push(widget::text::caption(&state.badges))
        .push(widget::text::caption(&state.source));

    let bottom_row = widget::row()
        .spacing(12)
        .push(widget::horizontal_space(Length::Fill))
        .push(widget::text::body("Sync to Source:"))
        .push(common::dropdown(
            &["Source 1", "Source 2", "Source 3"],
            state.selected_sync,
            Message::SelectSyncSource,
        ))
        .push(common::checkbox("Default", state.is_default, Message::ToggleDefault))
        .push(common::checkbox("Forced", state.is_forced, Message::ToggleForced))
        .push(common::checkbox("Set Name", state.set_name, Message::ToggleSetName))
        .push(common::button("Style Editor...", Message::OpenStyleEditor))
        .push(common::button("Settings...", Message::OpenSettings));

    widget::column()
        .spacing(8)
        .padding(8)
        .push(top_row)
        .push(bottom_row)
        .into()
}
