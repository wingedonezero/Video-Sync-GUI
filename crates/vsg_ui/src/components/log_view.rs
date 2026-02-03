//! Scrollable log view component with monospace font

use gtk4::prelude::*;
use relm4::prelude::*;

/// Input message for LogView
#[derive(Debug)]
pub enum LogViewMsg {
    /// Append text to the log
    Append(String),
    /// Clear all log text
    Clear,
}

/// Log view component model
pub struct LogView {
    buffer: gtk4::TextBuffer,
}

#[relm4::component(pub)]
impl Component for LogView {
    type Init = ();
    type Input = LogViewMsg;
    type Output = ();
    type CommandOutput = ();

    view! {
        gtk4::ScrolledWindow {
            set_vexpand: true,
            set_hexpand: true,
            set_min_content_height: 150,

            #[name = "text_view"]
            gtk4::TextView {
                set_buffer: Some(&model.buffer),
                set_editable: false,
                set_cursor_visible: false,
                set_monospace: true,
                set_wrap_mode: gtk4::WrapMode::WordChar,
                set_left_margin: 8,
                set_right_margin: 8,
                set_top_margin: 4,
                set_bottom_margin: 4,
            },
        }
    }

    fn init(
        _init: Self::Init,
        root: Self::Root,
        _sender: ComponentSender<Self>,
    ) -> ComponentParts<Self> {
        let buffer = gtk4::TextBuffer::new(None::<&gtk4::TextTagTable>);

        let model = LogView { buffer };

        let widgets = view_output!();

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, _sender: ComponentSender<Self>, root: &Self::Root) {
        match msg {
            LogViewMsg::Append(text) => {
                let mut end_iter = self.buffer.end_iter();
                self.buffer.insert(&mut end_iter, &text);
                self.buffer.insert(&mut end_iter, "\n");

                // Auto-scroll to bottom
                if let Some(text_view) = root
                    .child()
                    .and_then(|c| c.downcast::<gtk4::TextView>().ok())
                {
                    let mark = self
                        .buffer
                        .create_mark(None, &self.buffer.end_iter(), false);
                    text_view.scroll_to_mark(&mark, 0.0, false, 0.0, 0.0);
                    self.buffer.delete_mark(&mark);
                }
            }
            LogViewMsg::Clear => {
                self.buffer.set_text("");
            }
        }
    }
}
