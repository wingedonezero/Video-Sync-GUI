//! Text input with paste button for clipboard functionality.
//!
//! Provides a text input with a small paste button for easy pasting.

use iced::widget::{button, container, row, text, text_input};
use iced::{Alignment, Background, Border, Color, Element, Length, Theme};

use crate::app::Message;

/// Create a text input with a paste button.
///
/// # Arguments
/// * `placeholder` - Placeholder text when empty
/// * `value` - Current value of the input
/// * `on_input` - Message to send when text changes
/// * `paste_message` - Message to send when Paste button is clicked
pub fn text_input_with_paste<'a>(
    placeholder: &'a str,
    value: &'a str,
    on_input: impl Fn(String) -> Message + 'a,
    paste_message: Message,
) -> Element<'a, Message> {
    let input = text_input(placeholder, value)
        .on_input(on_input)
        .width(Length::Fill);

    // Small paste button with clipboard icon
    let paste_btn = button(
        container(text("📋").size(14))
            .center_x(Length::Fill)
            .center_y(Length::Fill)
    )
    .on_press(paste_message)
    .width(28)
    .height(28)
    .style(|theme: &Theme, status| {
        let palette = theme.palette();
        button::Style {
            background: match status {
                button::Status::Hovered => Some(Background::Color(Color::from_rgb(0.25, 0.30, 0.35))),
                button::Status::Pressed => Some(Background::Color(Color::from_rgb(0.20, 0.25, 0.30))),
                _ => Some(Background::Color(Color::from_rgb(0.20, 0.20, 0.20))),
            },
            text_color: palette.text,
            border: Border {
                color: Color::from_rgb(0.3, 0.3, 0.3),
                width: 1.0,
                radius: 4.0.into(),
            },
            ..Default::default()
        }
    });

    row![input, paste_btn]
        .spacing(4)
        .align_y(Alignment::Center)
        .into()
}
