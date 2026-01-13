//! File input widget
//!
//! A text input with browse button for file/directory selection

use cosmic::iced::{Alignment, Length};
use cosmic::widget::{self as widget, row, text, text_input};
use cosmic::Element;

/// File input component
pub struct FileInput<'a, M> {
    label: &'a str,
    value: &'a str,
    on_change: Box<dyn Fn(String) -> M + 'a>,
    on_browse: M,
    placeholder: &'a str,
}

impl<'a, M: Clone + 'a> FileInput<'a, M> {
    pub fn new(
        label: &'a str,
        value: &'a str,
        on_change: impl Fn(String) -> M + 'a,
        on_browse: M,
    ) -> Self {
        Self {
            label,
            value,
            on_change: Box::new(on_change),
            on_browse,
            placeholder: "",
        }
    }

    pub fn placeholder(mut self, placeholder: &'a str) -> Self {
        self.placeholder = placeholder;
        self
    }

    pub fn view(self) -> Element<'a, M> {
        row![
            text(self.label).width(Length::Fixed(150.0)),
            text_input(self.placeholder, self.value)
                .on_input(self.on_change)
                .width(Length::Fill),
            widget::button(text("Browse..."))
                .on_press(self.on_browse),
        ]
        .spacing(8)
        .align_y(Alignment::Center)
        .into()
    }
}
