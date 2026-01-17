//! Manual selection dialog layout mirroring `python/vsg_qt/manual_selection_dialog/ui.py`.

use cosmic::iced::Length;
use cosmic::widget::{self, scrollable};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    ToggleAttachment(usize, bool),
    AddExternalSubtitles,
    Confirm,
    Cancel,
}

#[derive(Clone, Debug)]
pub struct State {
    pub sources: Vec<String>,
    pub attachment_sources: Vec<String>,
    pub attachment_selected: Vec<bool>,
}

impl Default for State {
    fn default() -> Self {
        let sources = vec!["Source 1".to_string(), "Source 2".to_string(), "Source 3".to_string()];
        Self {
            attachment_sources: sources.clone(),
            sources,
            attachment_selected: vec![false, false, false],
        }
    }
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::ToggleAttachment(index, value) => {
                if let Some(entry) = self.attachment_selected.get_mut(index) {
                    *entry = value;
                }
            }
            Message::AddExternalSubtitles | Message::Confirm | Message::Cancel => {}
        }
    }
}

fn source_group<Message: Clone + 'static>(title: &str) -> Element<'static, Message> {
    let list = widget::container(widget::text::body("Tracks list"))
        .height(Length::Units(160))
        .width(Length::Fill);

    common::subsection(title, list.into())
}

pub fn view(state: &State) -> Element<Message> {
    let left_sources = state
        .sources
        .iter()
        .enumerate()
        .fold(widget::column().spacing(12), |column, (idx, source)| {
            let title = if idx == 0 {
                format!("{source} (Reference) Tracks")
            } else {
                format!("{source} Tracks")
            };
            column.push(source_group(&title))
        })
        .push(source_group("External Subtitles"));

    let left_panel = widget::column()
        .spacing(12)
        .push(scrollable(left_sources).height(Length::FillPortion(4)))
        .push(common::button(
            "Add External Subtitle(s)...",
            Message::AddExternalSubtitles,
        ));

    let final_output = widget::column()
        .spacing(12)
        .push(
            widget::container(widget::text::body("Final Output (Drag to reorder)"))
                .height(Length::Units(260))
                .width(Length::Fill),
        )
        .push(
            state
                .attachment_sources
                .iter()
                .enumerate()
                .fold(
                    widget::row()
                        .spacing(8)
                        .push(widget::text::body("Include attachments from:")),
                    |row, (idx, label)| {
                        row.push(common::checkbox(
                            label,
                            *state.attachment_selected.get(idx).unwrap_or(&false),
                            move |value| Message::ToggleAttachment(idx, value),
                        ))
                    },
                )
                .push(widget::horizontal_space(Length::Fill)),
        );

    let body = widget::row()
        .spacing(16)
        .push(widget::container(left_panel).width(Length::FillPortion(2)))
        .push(widget::container(final_output).width(Length::FillPortion(3)));

    let buttons = widget::row()
        .spacing(12)
        .push(widget::horizontal_space(Length::Fill))
        .push(common::button("OK", Message::Confirm))
        .push(common::button("Cancel", Message::Cancel));

    widget::column()
        .spacing(16)
        .padding(16)
        .push(body)
        .push(buttons)
        .into()
}
