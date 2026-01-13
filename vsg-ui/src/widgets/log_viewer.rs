//! Log viewer widget
//!
//! A scrollable text area for displaying log messages

use cosmic::iced::Length;
use cosmic::widget::{column, container, scrollable, text};
use cosmic::Element;

/// Log viewer component
pub struct LogViewer<'a> {
    content: &'a str,
    max_lines: Option<usize>,
}

impl<'a> LogViewer<'a> {
    pub fn new(content: &'a str) -> Self {
        Self {
            content,
            max_lines: None,
        }
    }

    pub fn max_lines(mut self, lines: usize) -> Self {
        self.max_lines = Some(lines);
        self
    }

    pub fn view<M: 'a>(self) -> Element<'a, M> {
        let lines: Vec<&str> = self.content.lines().collect();

        let display_lines = if let Some(max) = self.max_lines {
            let start = lines.len().saturating_sub(max);
            &lines[start..]
        } else {
            &lines[..]
        };

        let log_elements: Vec<Element<'a, M>> = display_lines
            .iter()
            .map(|line| text(*line).size(12).into())
            .collect();

        let log_column = column(log_elements).spacing(2);

        container(
            scrollable(log_column)
                .height(Length::Fill)
        )
        .width(Length::Fill)
        .height(Length::Fill)
        .padding(8)
        .into()
    }
}
