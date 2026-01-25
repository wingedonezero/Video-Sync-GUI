//! Job queue window view (stub).
//!
//! This window is not yet fully implemented for the iced migration test.

use iced::widget::{button, column, container, row, text, Space};
use iced::{Element, Length};

use crate::app::{App, Message};

/// Build the job queue window view (stub).
pub fn view(_app: &App) -> Element<Message> {
    let content = column![
        text("Job Queue").size(24),
        text(""),
        text("This window is stubbed for the iced migration test."),
        text("Main and Settings windows are the focus of this test."),
        text(""),
        row![
            Space::new().width(Length::Fill),
            button("Close").on_press(Message::CloseJobQueue),
        ],
    ]
    .spacing(16)
    .padding(24);

    container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}
