//! Shared UI helpers for libcosmic layout scaffolding.
//!
//! These helpers keep the UI structure consistent with the Python Qt layout,
//! while we build out the full Rust UI in Phase 9.

use cosmic::iced::{Alignment, Length};
use cosmic::widget::{self, horizontal_space, vertical_space};
use cosmic::Element;

pub fn section<'a, Message: Clone + 'static>(
    title: &str,
    content: Element<'a, Message>,
) -> Element<'a, Message> {
    let layout = widget::column()
        .spacing(12)
        .push(widget::text::title4(title))
        .push(content);

    widget::container(layout)
        .padding(16)
        .width(Length::Fill)
        .into()
}

pub fn subsection<'a, Message: Clone + 'static>(
    title: &str,
    content: Element<'a, Message>,
) -> Element<'a, Message> {
    let layout = widget::column()
        .spacing(8)
        .push(widget::text::heading(title))
        .push(content);

    widget::container(layout)
        .padding(12)
        .width(Length::Fill)
        .into()
}

pub fn form_row<'a, Message: Clone + 'static>(
    label: &str,
    control: Element<'a, Message>,
) -> Element<'a, Message> {
    widget::row()
        .spacing(16)
        .align_items(Alignment::Center)
        .push(widget::text::body(label).width(Length::FillPortion(3)))
        .push(widget::container(control).width(Length::FillPortion(5)))
        .into()
}

pub fn spacer<Message: Clone + 'static>() -> Element<'static, Message> {
    vertical_space(Length::Units(8)).into()
}

pub fn button<'a, Message: Clone + 'static>(
    label: &str,
    on_press: Message,
) -> Element<'a, Message> {
    widget::button::standard(label).on_press(on_press).into()
}

pub fn text_input<'a, Message: Clone + 'static>(
    placeholder: &str,
    value: &str,
    on_input: impl Fn(String) -> Message + 'static,
) -> Element<'a, Message> {
    widget::text_input(placeholder, value).on_input(on_input).into()
}

pub fn numeric_input<'a, Message: Clone + 'static>(
    placeholder: &str,
    value: &str,
    on_input: impl Fn(String) -> Message + 'static,
) -> Element<'a, Message> {
    widget::text_input(placeholder, value).on_input(on_input).into()
}

pub fn checkbox<'a, Message: Clone + 'static>(
    label: &str,
    checked: bool,
    on_toggle: impl Fn(bool) -> Message + 'static,
) -> Element<'a, Message> {
    widget::checkbox(label, checked, on_toggle).into()
}

pub fn radio<'a, Message: Clone + 'static>(
    label: &str,
    value: &'static str,
    selected: Option<&'static str>,
    on_select: impl Fn(&'static str) -> Message + 'static,
) -> Element<'static, Message> {
    widget::radio(widget::text::body(label), value, selected, on_select).into()
}

pub fn dropdown<'a, Message: Clone + 'static>(
    options: &[&'static str],
    selected: Option<usize>,
    on_select: impl Fn(usize) -> Message + 'static,
) -> Element<'a, Message> {
    widget::dropdown(options, selected, on_select).into()
}

pub fn file_picker_input<'a, Message: Clone + 'static>(
    label: &str,
    value: &str,
    on_input: impl Fn(String) -> Message + 'static,
    on_browse: Message,
) -> Element<'a, Message> {
    form_row(
        label,
        widget::row()
            .spacing(8)
            .push(text_input("", value, on_input))
            .push(button("Browse…", on_browse))
            .into(),
    )
}

pub fn table_placeholder<Message: Clone + 'static>(title: &str) -> Element<'static, Message> {
    widget::container(
        widget::column()
            .spacing(8)
            .push(widget::text::body(title))
            .push(widget::container(widget::text::caption("Table rows appear here")))
            .push(horizontal_space(Length::Fill)),
    )
    .padding(12)
    .width(Length::Fill)
    .height(Length::Units(220))
    .into()
}

pub fn table_placeholder_with_headers<Message: Clone + 'static>(
    title: &str,
    headers: &[&str],
) -> Element<'static, Message> {
    let header_row = headers.iter().fold(widget::row().spacing(12), |row, label| {
        row.push(widget::text::caption(*label))
    });

    widget::container(
        widget::column()
            .spacing(8)
            .push(widget::text::body(title))
            .push(header_row)
            .push(widget::container(widget::text::caption("Table rows appear here")))
            .push(horizontal_space(Length::Fill)),
    )
    .padding(12)
    .width(Length::Fill)
    .height(Length::Units(220))
    .into()
}
