//! Sync exclusion dialog layout mirroring `python/vsg_qt/sync_exclusion_dialog/ui.py`.

use cosmic::iced::Length;
use cosmic::widget::{self, scrollable};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    SetMode(ExclusionMode),
    ToggleStyle(usize, bool),
    SelectAll,
    DeselectAll,
    Confirm,
    Cancel,
}

#[derive(Clone, Debug)]
pub enum ExclusionMode {
    Exclude,
    IncludeOnly,
}

#[derive(Clone, Debug)]
pub struct StyleItem {
    pub name: String,
    pub count: usize,
    pub selected: bool,
}

#[derive(Clone, Debug)]
pub struct State {
    pub mode: ExclusionMode,
    pub styles: Vec<StyleItem>,
}

impl Default for State {
    fn default() -> Self {
        Self {
            mode: ExclusionMode::Exclude,
            styles: vec![
                StyleItem {
                    name: "Default".to_string(),
                    count: 123,
                    selected: false,
                },
                StyleItem {
                    name: "Signs".to_string(),
                    count: 45,
                    selected: false,
                },
                StyleItem {
                    name: "OP/ED".to_string(),
                    count: 12,
                    selected: false,
                },
            ],
        }
    }
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::SetMode(mode) => self.mode = mode,
            Message::ToggleStyle(index, selected) => {
                if let Some(style) = self.styles.get_mut(index) {
                    style.selected = selected;
                }
            }
            Message::SelectAll => {
                for style in &mut self.styles {
                    style.selected = true;
                }
            }
            Message::DeselectAll => {
                for style in &mut self.styles {
                    style.selected = false;
                }
            }
            Message::Confirm | Message::Cancel => {}
        }
    }
}

pub fn view(state: &State) -> Element<Message> {
    let info = widget::container(widget::text::body(
        "Configure which styles to exclude from frame matching:\nSource: Source 2\nTrack ID: 0\nDescription: Example",
    ))
    .padding(12);

    let help = widget::container(widget::text::body(
        "Excluded styles will use the corrected offset instead of frame matching.",
    ))
    .padding(12);

    let selected_mode = match state.mode {
        ExclusionMode::Exclude => Some("exclude"),
        ExclusionMode::IncludeOnly => Some("include"),
    };

    let mode = widget::column()
        .spacing(8)
        .push(common::radio(
            "Exclude selected styles from frame sync (use corrected offset)",
            "exclude",
            selected_mode,
            |_| Message::SetMode(ExclusionMode::Exclude),
        ))
        .push(common::radio(
            "Include only selected styles for frame sync (exclude others)",
            "include",
            selected_mode,
            |_| Message::SetMode(ExclusionMode::IncludeOnly),
        ));

    let styles = scrollable(
        state
            .styles
            .iter()
            .enumerate()
            .fold(widget::column().spacing(6), |column, (idx, style)| {
                let label = format!("{} ({} events)", style.name, style.count);
                column.push(common::checkbox(
                    &label,
                    style.selected,
                    move |value| Message::ToggleStyle(idx, value),
                ))
            }),
    )
    .height(Length::Units(200));

    let selection_buttons = widget::row()
        .spacing(8)
        .push(common::button("Select All", Message::SelectAll))
        .push(common::button("Deselect All", Message::DeselectAll));

    let preview = widget::container(widget::text::body("Preview of excluded styles."))
        .padding(8);

    let buttons = widget::row()
        .spacing(12)
        .push(widget::horizontal_space(Length::Fill))
        .push(common::button("OK", Message::Confirm))
        .push(common::button("Cancel", Message::Cancel));

    widget::column()
        .spacing(16)
        .padding(16)
        .push(info)
        .push(help)
        .push(common::subsection("Exclusion Mode", mode.into()))
        .push(common::subsection(
            "Select Styles",
            widget::column()
                .spacing(8)
                .push(widget::text::body(
                    "Check the styles you want to exclude/include from frame sync:",
                ))
                .push(styles)
                .push(selection_buttons)
                .into(),
        ))
        .push(preview)
        .push(buttons)
        .into()
}
