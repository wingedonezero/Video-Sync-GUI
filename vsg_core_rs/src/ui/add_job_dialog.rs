//! Add job dialog layout mirroring `python/vsg_qt/add_job_dialog/ui.py`.

use cosmic::iced::Length;
use cosmic::widget::{self, scrollable};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    UpdateSource(usize, String),
    BrowseSource(usize),
    AddSource,
    Submit,
    Cancel,
}

#[derive(Clone, Debug)]
pub struct State {
    pub sources: Vec<String>,
}

impl Default for State {
    fn default() -> Self {
        Self {
            sources: vec![String::new(), String::new()],
        }
    }
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::UpdateSource(index, value) => {
                if let Some(entry) = self.sources.get_mut(index) {
                    *entry = value;
                }
            }
            Message::BrowseSource(_)
            | Message::AddSource
            | Message::Submit
            | Message::Cancel => {}
        }
    }
}

fn source_row(index: usize, label: &str, value: &str) -> Element<'static, Message> {
    widget::row()
        .spacing(12)
        .push(widget::text::body(label).width(Length::FillPortion(2)))
        .push(
            widget::container(common::text_input(
                "Select file or folder",
                value,
                move |text| Message::UpdateSource(index, text),
            ))
            .width(Length::FillPortion(6)),
        )
        .push(
            widget::container(common::button("Browse…", Message::BrowseSource(index)))
                .width(Length::FillPortion(2)),
        )
        .into()
}

pub fn view(state: &State) -> Element<Message> {
    let inputs = state
        .sources
        .iter()
        .enumerate()
        .fold(widget::column().spacing(12), |column, (idx, value)| {
            let label = if idx == 0 {
                "Source 1 (Reference):"
            } else {
                "Source:"
            };
            column.push(source_row(idx, label, value))
        });

    let scroll = scrollable(inputs).height(Length::FillPortion(5));

    let footer = widget::row()
        .spacing(12)
        .push(common::button("Add Another Source", Message::AddSource))
        .push(widget::horizontal_space(Length::Fill))
        .push(common::button("Find & Add Jobs", Message::Submit))
        .push(common::button("Cancel", Message::Cancel));

    widget::column()
        .spacing(16)
        .padding(16)
        .push(scroll)
        .push(footer)
        .into()
}
