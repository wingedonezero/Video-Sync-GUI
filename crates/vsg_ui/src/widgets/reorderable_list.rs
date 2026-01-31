//! Reorderable list widget for drag-and-drop reordering.
//!
//! A reusable widget that wraps a list of items and allows drag-and-drop reordering.
//! Uses mouse_area to detect press, move, and release events.

use iced::widget::{column, container, mouse_area, text, Space};
use iced::{Background, Border, Color, Element, Length, Theme};

use crate::app::{DragState, Message};

/// Row height for calculating drop targets (approximate)
const ROW_HEIGHT: f32 = 72.0;

/// Build a reorderable list view for final tracks.
///
/// # Arguments
/// * `items` - Slice of items to display
/// * `drag_state` - Current drag state
/// * `render_row` - Function to render each row's content (excluding drag wrapper)
///
/// # Returns
/// An Element containing the reorderable list
pub fn view<'a, T, F>(
    items: &'a [T],
    drag_state: &DragState,
    render_row: F,
) -> Element<'a, Message>
where
    T: 'a,
    F: Fn(&'a T, usize, bool, bool) -> Element<'a, Message>,
{
    if items.is_empty() {
        return container(
            column![
                text("No tracks added yet").size(14),
                Space::new().height(4),
                text("Click tracks on the left to add them here.")
                    .size(12)
                    .color(Color::from_rgb(0.6, 0.6, 0.6)),
            ]
            .align_x(iced::Alignment::Center),
        )
        .padding(30)
        .width(Length::Fill)
        .center_x(Length::Fill)
        .into();
    }

    let dragging_idx = drag_state.dragging_idx;
    let hover_idx = drag_state.hover_idx;

    let rows: Vec<Element<'a, Message>> = items
        .iter()
        .enumerate()
        .flat_map(|(idx, item)| {
            let is_dragging = dragging_idx == Some(idx);
            let is_drop_target = dragging_idx.is_some() && hover_idx == Some(idx) && !is_dragging;

            // Show drop indicator BEFORE this item if we're hovering and this is the target
            let mut elements: Vec<Element<'a, Message>> = Vec::new();

            // Drop indicator line (shown above the drop target)
            if is_drop_target && hover_idx < dragging_idx {
                elements.push(drop_indicator());
            }

            // The row content
            let row_content = render_row(item, idx, is_dragging, is_drop_target);

            // Wrap in drag-aware container
            let row_element = draggable_row(idx, row_content, is_dragging, dragging_idx.is_some());
            elements.push(row_element);

            // Drop indicator line (shown below the drop target when moving down)
            if is_drop_target && hover_idx > dragging_idx {
                elements.push(drop_indicator());
            }

            elements
        })
        .collect();

    column(rows).spacing(4).width(Length::Fill).into()
}

/// Create a draggable row wrapper.
fn draggable_row<'a>(
    idx: usize,
    content: Element<'a, Message>,
    is_dragging: bool,
    any_dragging: bool,
) -> Element<'a, Message> {
    // Style based on drag state
    let (bg_color, border_color, opacity) = if is_dragging {
        // Currently being dragged - highlight with blue border
        (
            Color::from_rgb(0.15, 0.18, 0.22),
            Color::from_rgb(0.3, 0.5, 0.8),
            0.7,
        )
    } else if any_dragging {
        // Another item is being dragged - potential drop target
        (
            Color::from_rgb(0.12, 0.12, 0.12),
            Color::from_rgb(0.2, 0.2, 0.2),
            1.0,
        )
    } else {
        // Normal state
        (
            Color::from_rgb(0.12, 0.12, 0.12),
            Color::TRANSPARENT,
            1.0,
        )
    };

    let styled_container = container(content)
        .padding([8, 8])
        .width(Length::Fill)
        .style(move |_theme: &Theme| container::Style {
            background: Some(Background::Color(Color {
                a: opacity,
                ..bg_color
            })),
            border: Border {
                color: border_color,
                width: if is_dragging { 2.0 } else { 0.0 },
                radius: 4.0.into(),
            },
            ..Default::default()
        });

    // Wrap in mouse_area for drag detection
    mouse_area(styled_container)
        .on_press(Message::DragStart(idx))
        .on_release(Message::DragEnd)
        .on_enter(Message::DragHover(idx))
        .into()
}

/// Create a drop indicator line.
fn drop_indicator<'a>() -> Element<'a, Message> {
    container(Space::new().width(Length::Fill).height(2))
        .width(Length::Fill)
        .style(|_theme: &Theme| container::Style {
            background: Some(Background::Color(Color::from_rgb(0.3, 0.6, 1.0))),
            border: Border {
                radius: 1.0.into(),
                ..Default::default()
            },
            ..Default::default()
        })
        .into()
}
