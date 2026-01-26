//! Text input with right-click context menu for paste functionality.
//!
//! Wraps iced's text_input with iced_aw's context_menu to provide
//! a right-click paste option.

use iced::widget::{button, column, container, text_input};
use iced::{Background, Border, Color, Element, Length, Theme};
use iced_aw::ContextMenu;

use crate::app::Message;

/// Create a text input with right-click context menu for paste.
///
/// # Arguments
/// * `placeholder` - Placeholder text when empty
/// * `value` - Current value of the input
/// * `on_input` - Message to send when text changes (includes pasted text)
/// * `paste_message` - Message to send when Paste is clicked (should trigger clipboard read)
pub fn text_input_with_paste<'a>(
    placeholder: &'a str,
    value: &'a str,
    on_input: impl Fn(String) -> Message + 'a,
    paste_message: Message,
) -> Element<'a, Message> {
    let input = text_input(placeholder, value)
        .on_input(on_input)
        .width(Length::Fill);

    let menu_content = move || -> Element<'_, Message, Theme, iced::Renderer> {
        container(
            column![
                button("Paste")
                    .on_press(paste_message.clone())
                    .width(Length::Fill)
                    .style(|theme: &Theme, status| {
                        let palette = theme.palette();
                        button::Style {
                            background: match status {
                                button::Status::Hovered => Some(Background::Color(Color::from_rgb(0.25, 0.25, 0.25))),
                                _ => Some(Background::Color(Color::from_rgb(0.18, 0.18, 0.18))),
                            },
                            text_color: palette.text,
                            border: Border::default(),
                            ..Default::default()
                        }
                    }),
            ]
            .width(80)
        )
        .style(|_theme: &Theme| container::Style {
            background: Some(Background::Color(Color::from_rgb(0.15, 0.15, 0.15))),
            border: Border {
                color: Color::from_rgb(0.3, 0.3, 0.3),
                width: 1.0,
                radius: 4.0.into(),
            },
            ..Default::default()
        })
        .padding(4)
        .into()
    };

    ContextMenu::new(input, menu_content).into()
}
