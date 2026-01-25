//! Add Job dialog view.

use cosmic::iced::{Alignment, Length};
use cosmic::prelude::*;
use cosmic::{widget, Element};

use crate::app::{App, Message};

pub fn view(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let mut content = widget::column()
        .push(widget::text::title3("Add Job(s)"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())));

    if !app.add_job_error.is_empty() {
        content = content.push(widget::text::body(&app.add_job_error));
    }

    content = content
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::scrollable(
                app.add_job_sources.iter().enumerate().fold(
                    widget::column().spacing(spacing.space_s),
                    |col, (idx, path)| {
                        col.push(source_input_row(idx, path, !app.is_finding_jobs))
                    }
                )
            )
            .height(Length::Fill)
        )
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())));

    let mut add_source_btn = widget::button::standard("+ Add Source");
    if !app.is_finding_jobs && app.add_job_sources.len() < 10 {
        add_source_btn = add_source_btn.on_press(Message::AddSource);
    }

    content = content
        .push(
            widget::row()
                .push(add_source_btn)
                .push(widget::horizontal_space())
        )
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_m.into())));

    let mut cancel_btn = widget::button::standard("Cancel");
    if !app.is_finding_jobs {
        cancel_btn = cancel_btn.on_press(Message::CloseAddJob);
    }

    let find_label = if app.is_finding_jobs { "Finding..." } else { "Find and Add Jobs" };
    let mut find_btn = widget::button::suggested(find_label);
    if !app.is_finding_jobs {
        find_btn = find_btn.on_press(Message::FindAndAddJobs);
    }

    content = content
        .push(
            widget::row()
                .push(widget::horizontal_space())
                .push(cancel_btn)
                .push(find_btn)
                .spacing(spacing.space_s)
        )
        .spacing(spacing.space_xxs)
        .padding(spacing.space_l);

    widget::container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}

fn source_input_row(idx: usize, path: &str, enabled: bool) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let label = if idx == 0 {
        "Source 1 (Reference):".to_string()
    } else {
        format!("Source {}:", idx + 1)
    };
    let path_owned = path.to_string();

    let mut browse_btn = widget::button::standard("Browse");
    if enabled {
        browse_btn = browse_btn.on_press(Message::AddJobBrowseSource(idx));
    }

    let mut row = widget::row()
        .push(widget::text::body(label).width(Length::Fixed(150.0)))
        .push(
            widget::text_input::text_input("Drop file here or browse...", path_owned)
                .on_input(move |s| Message::AddJobSourceChanged(idx, s))
                .width(Length::Fill)
        )
        .push(browse_btn);

    if idx >= 2 {
        let mut remove_btn = widget::button::standard("X");
        if enabled {
            remove_btn = remove_btn.on_press(Message::RemoveSource(idx));
        }
        row = row.push(remove_btn);
    }

    row.spacing(spacing.space_s)
        .align_y(Alignment::Center)
        .into()
}
