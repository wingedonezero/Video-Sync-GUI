//! Job queue dialog layout mirroring `python/vsg_qt/job_queue_dialog/ui.py`.

use cosmic::iced::Length;
use cosmic::widget::{self};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    AddJob,
    RemoveSelected,
    MoveUp,
    MoveDown,
    StartQueue,
    Cancel,
}

#[derive(Clone, Debug, Default)]
pub struct State {
    pub rows: Vec<JobRow>,
}

#[derive(Clone, Debug, Default)]
pub struct JobRow {
    pub status: String,
    pub sources: String,
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::AddJob
            | Message::RemoveSelected
            | Message::MoveUp
            | Message::MoveDown
            | Message::StartQueue
            | Message::Cancel => {}
        }
    }
}

pub fn view(_state: &State) -> Element<Message> {
    let table = common::table_placeholder_with_headers(
        "Queued Jobs",
        &["#", "Status", "Sources"],
    );

    let controls = widget::row()
        .spacing(12)
        .push(common::button("Add Job(s)...", Message::AddJob))
        .push(widget::horizontal_space(Length::Fill))
        .push(common::button("Move Up", Message::MoveUp))
        .push(common::button("Move Down", Message::MoveDown))
        .push(common::button("Remove Selected", Message::RemoveSelected));

    let dialog_buttons = widget::row()
        .spacing(12)
        .push(widget::horizontal_space(Length::Fill))
        .push(common::button("Start Processing Queue", Message::StartQueue))
        .push(common::button("Cancel", Message::Cancel));

    widget::column()
        .spacing(16)
        .padding(16)
        .push(table)
        .push(controls)
        .push(dialog_buttons)
        .into()
}
