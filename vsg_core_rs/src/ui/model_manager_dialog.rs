//! Model manager dialog layout mirroring `python/vsg_qt/options_dialog/model_manager_dialog.py`.

use cosmic::iced::Length;
use cosmic::widget::{self};
use cosmic::Element;

use super::common;

#[derive(Clone, Debug)]
pub enum Message {
    UpdateTypeFilter(usize),
    UpdateStatusFilter(usize),
    UpdateSearch(String),
    Refresh,
    Close,
}

#[derive(Clone, Debug)]
pub struct State {
    pub type_filter: Option<usize>,
    pub status_filter: Option<usize>,
    pub search: String,
}

impl Default for State {
    fn default() -> Self {
        Self {
            type_filter: Some(0),
            status_filter: Some(0),
            search: String::new(),
        }
    }
}

impl State {
    pub fn update(&mut self, message: Message) {
        match message {
            Message::UpdateTypeFilter(value) => self.type_filter = Some(value),
            Message::UpdateStatusFilter(value) => self.status_filter = Some(value),
            Message::UpdateSearch(value) => self.search = value,
            Message::Refresh | Message::Close => {}
        }
    }
}

pub fn view(state: &State) -> Element<Message> {
    let filters = widget::row()
        .spacing(12)
        .push(widget::text::body("Filter by Type:"))
        .push(common::dropdown(
            &[
                "All Types",
                "Demucs v4",
                "BS-Roformer",
                "MelBand Roformer",
                "MDX-Net",
                "VR Arch",
            ],
            state.type_filter,
            Message::UpdateTypeFilter,
        ))
        .push(widget::text::body("Status:"))
        .push(common::dropdown(
            &["All", "Installed", "Available"],
            state.status_filter,
            Message::UpdateStatusFilter,
        ))
        .push(widget::text::body("Search:"))
        .push(
            widget::container(common::text_input(
                "Filter by name...",
                &state.search,
                Message::UpdateSearch,
            ))
                .width(Length::Fill),
        );

    let table = common::table_placeholder_with_headers(
        "Available Models",
        &[
            "Name",
            "Quality",
            "Type",
            "SDR (V/I)",
            "Stems",
            "Status",
            "Action",
        ],
    );

    let progress = widget::column()
        .spacing(4)
        .push(widget::text::caption("Download progress"))
        .push(widget::container(widget::text::body("Progress Bar")));

    let info = widget::container(widget::text::body("Model information details..."))
        .padding(12)
        .height(Length::Units(120));

    let buttons = widget::row()
        .spacing(12)
        .push(common::button("Refresh List", Message::Refresh))
        .push(widget::horizontal_space(Length::Fill))
        .push(common::button("Close", Message::Close));

    widget::column()
        .spacing(16)
        .padding(16)
        .push(filters)
        .push(table)
        .push(progress)
        .push(common::subsection("Model Information", info.into()))
        .push(buttons)
        .into()
}
