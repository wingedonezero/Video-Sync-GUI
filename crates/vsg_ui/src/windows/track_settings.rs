//! Track settings dialog component.
//!
//! Dialog for configuring individual track settings.

use gtk::glib;
use gtk::prelude::*;
use libadwaita::prelude::*;
use relm4::prelude::*;
use relm4::{Component, ComponentParts, ComponentSender};

use crate::types::{FinalTrackState, SyncExclusionMode, LANGUAGE_CODES};

/// Output messages from the track settings dialog.
#[derive(Debug)]
pub enum TrackSettingsOutput {
    Accepted(FinalTrackState),
    Cancelled,
}

/// Input messages for the track settings dialog.
#[derive(Debug)]
pub enum TrackSettingsMsg {
    // Language
    LanguageChanged(u32),
    CustomNameChanged(String),

    // Subtitle options
    PerformOcrChanged(bool),
    ConvertToAssChanged(bool),
    RescaleChanged(bool),
    SizeMultiplierChanged(String),

    // Style editing
    OpenStyleEditor,
    OpenFontReplacements,

    // Sync exclusion
    OpenSyncExclusion,

    // Dialog actions
    Accept,
    Cancel,
}

/// Track settings dialog state.
pub struct TrackSettingsDialog {
    track: FinalTrackState,
    selected_lang_idx: u32,
}

#[relm4::component(pub)]
impl Component for TrackSettingsDialog {
    type Init = FinalTrackState;
    type Input = TrackSettingsMsg;
    type Output = TrackSettingsOutput;
    type CommandOutput = ();

    view! {
        adw::Window {
            set_title: Some("Track Settings"),
            set_default_width: 500,
            set_default_height: 500,
            set_modal: true,

            #[wrap(Some)]
            set_content = &gtk::Box {
                set_orientation: gtk::Orientation::Vertical,

                adw::HeaderBar {
                    #[wrap(Some)]
                    set_title_widget = &gtk::Label {
                        set_label: "Track Settings",
                    },
                },

                gtk::Box {
                    set_orientation: gtk::Orientation::Vertical,
                    set_spacing: 16,
                    set_margin_all: 16,
                    set_vexpand: true,

                    // Track info
                    gtk::Frame {
                        gtk::Box {
                            set_orientation: gtk::Orientation::Vertical,
                            set_spacing: 8,
                            set_margin_all: 12,

                            gtk::Label {
                                #[watch]
                                set_label: &model.track.summary,
                                set_xalign: 0.0,
                                add_css_class: "title-3",
                            },

                            gtk::Label {
                                #[watch]
                                set_label: &format!("{} | {}", model.track.track_type, model.track.codec_id),
                                set_xalign: 0.0,
                            },
                        },
                    },

                    // Language settings
                    gtk::Frame {
                        set_label: Some("Language"),

                        gtk::Box {
                            set_orientation: gtk::Orientation::Vertical,
                            set_spacing: 8,
                            set_margin_all: 12,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Horizontal,
                                set_spacing: 8,

                                gtk::Label {
                                    set_label: "Language:",
                                    set_width_chars: 14,
                                    set_xalign: 0.0,
                                },

                                #[name = "lang_dropdown"]
                                gtk::DropDown {
                                    set_model: Some(&gtk::StringList::new(LANGUAGE_CODES)),
                                    #[watch]
                                    set_selected: model.selected_lang_idx,
                                    connect_selected_notify[sender] => move |dropdown| {
                                        sender.input(TrackSettingsMsg::LanguageChanged(dropdown.selected()));
                                    },
                                },
                            },

                            gtk::Box {
                                set_orientation: gtk::Orientation::Horizontal,
                                set_spacing: 8,

                                gtk::Label {
                                    set_label: "Custom Name:",
                                    set_width_chars: 14,
                                    set_xalign: 0.0,
                                },

                                gtk::Entry {
                                    set_hexpand: true,
                                    set_placeholder_text: Some("Optional track name"),
                                    #[watch]
                                    set_text: model.track.custom_name.as_deref().unwrap_or(""),
                                    connect_changed[sender] => move |entry| {
                                        sender.input(TrackSettingsMsg::CustomNameChanged(entry.text().to_string()));
                                    },
                                },
                            },
                        },
                    },

                    // Subtitle options (only for subtitle tracks)
                    gtk::Frame {
                        set_label: Some("Subtitle Options"),
                        #[watch]
                        set_visible: model.track.track_type == "Subtitle",

                        gtk::Box {
                            set_orientation: gtk::Orientation::Vertical,
                            set_spacing: 8,
                            set_margin_all: 12,

                            gtk::CheckButton {
                                set_label: Some("Perform OCR (image-based subtitles)"),
                                #[watch]
                                set_active: model.track.perform_ocr,
                                #[watch]
                                set_sensitive: model.track.is_ocr_compatible(),
                                connect_toggled[sender] => move |btn| {
                                    sender.input(TrackSettingsMsg::PerformOcrChanged(btn.is_active()));
                                },
                            },

                            gtk::CheckButton {
                                set_label: Some("Convert to ASS (SRT subtitles)"),
                                #[watch]
                                set_active: model.track.convert_to_ass,
                                #[watch]
                                set_sensitive: model.track.is_convert_to_ass_compatible(),
                                connect_toggled[sender] => move |btn| {
                                    sender.input(TrackSettingsMsg::ConvertToAssChanged(btn.is_active()));
                                },
                            },

                            gtk::CheckButton {
                                set_label: Some("Rescale timing"),
                                #[watch]
                                set_active: model.track.rescale,
                                connect_toggled[sender] => move |btn| {
                                    sender.input(TrackSettingsMsg::RescaleChanged(btn.is_active()));
                                },
                            },

                            gtk::Box {
                                set_orientation: gtk::Orientation::Horizontal,
                                set_spacing: 8,

                                gtk::Label {
                                    set_label: "Size Multiplier (%):",
                                    set_width_chars: 18,
                                    set_xalign: 0.0,
                                },

                                gtk::Entry {
                                    set_width_chars: 6,
                                    #[watch]
                                    set_text: &model.track.size_multiplier_pct.to_string(),
                                    connect_changed[sender] => move |entry| {
                                        sender.input(TrackSettingsMsg::SizeMultiplierChanged(entry.text().to_string()));
                                    },
                                },
                            },
                        },
                    },

                    // Style editing (only for ASS/SSA)
                    gtk::Frame {
                        set_label: Some("Style Editing"),
                        #[watch]
                        set_visible: model.track.is_style_editable(),

                        gtk::Box {
                            set_orientation: gtk::Orientation::Vertical,
                            set_spacing: 8,
                            set_margin_all: 12,

                            gtk::Button {
                                set_label: "Edit Styles...",
                                connect_clicked => TrackSettingsMsg::OpenStyleEditor,
                            },

                            gtk::Button {
                                set_label: "Font Replacements...",
                                connect_clicked => TrackSettingsMsg::OpenFontReplacements,
                            },

                            gtk::Button {
                                set_label: "Sync Exclusion...",
                                connect_clicked => TrackSettingsMsg::OpenSyncExclusion,
                            },
                        },
                    },

                    // Spacer
                    gtk::Box {
                        set_vexpand: true,
                    },

                    // Dialog buttons
                    gtk::Box {
                        set_orientation: gtk::Orientation::Horizontal,
                        set_spacing: 8,
                        set_halign: gtk::Align::End,

                        #[name = "accept_btn"]
                        gtk::Button {
                            set_label: "Accept",
                            add_css_class: "suggested-action",
                            // Connected manually in init to avoid panic
                        },

                        #[name = "cancel_btn"]
                        gtk::Button {
                            set_label: "Cancel",
                            // Connected manually in init to avoid panic
                        },
                    },
                },
            },
        }
    }

    fn init(
        init: Self::Init,
        root: Self::Root,
        sender: ComponentSender<Self>,
    ) -> ComponentParts<Self> {
        // Find the index of the current language
        let current_lang = init.custom_lang.as_deref()
            .or(init.original_lang.as_deref())
            .unwrap_or("und");

        let selected_lang_idx = LANGUAGE_CODES
            .iter()
            .position(|&l| l == current_lang)
            .unwrap_or(0) as u32;

        let model = TrackSettingsDialog {
            track: init,
            selected_lang_idx,
        };

        let widgets = view_output!();

        // Manually connect buttons to avoid panic if component is destroyed
        // Accept button - needs to go through message to get current track state
        let input_sender = sender.input_sender().clone();
        widgets.accept_btn.connect_clicked(move |_| {
            let _ = input_sender.send(TrackSettingsMsg::Accept);
        });

        // Cancel button - sends output directly
        let output_sender = sender.output_sender().clone();
        widgets.cancel_btn.connect_clicked(move |_| {
            let _ = output_sender.send(TrackSettingsOutput::Cancelled);
        });

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, root: &Self::Root) {
        match msg {
            TrackSettingsMsg::LanguageChanged(idx) => {
                self.selected_lang_idx = idx;
                if let Some(lang) = LANGUAGE_CODES.get(idx as usize) {
                    self.track.custom_lang = Some(lang.to_string());
                }
            }

            TrackSettingsMsg::CustomNameChanged(name) => {
                self.track.custom_name = if name.is_empty() { None } else { Some(name) };
            }

            TrackSettingsMsg::PerformOcrChanged(value) => {
                self.track.perform_ocr = value;
            }

            TrackSettingsMsg::ConvertToAssChanged(value) => {
                self.track.convert_to_ass = value;
            }

            TrackSettingsMsg::RescaleChanged(value) => {
                self.track.rescale = value;
            }

            TrackSettingsMsg::SizeMultiplierChanged(value) => {
                if let Ok(pct) = value.parse() {
                    self.track.size_multiplier_pct = pct;
                }
            }

            TrackSettingsMsg::OpenStyleEditor => {
                // TODO: Open style editor dialog
            }

            TrackSettingsMsg::OpenFontReplacements => {
                // TODO: Open font replacements dialog
            }

            TrackSettingsMsg::OpenSyncExclusion => {
                // TODO: Open sync exclusion dialog
            }

            TrackSettingsMsg::Accept => {
                // Defer output to avoid panic when controller is dropped while in click handler
                let track = self.track.clone();
                let output_sender = sender.output_sender().clone();
                glib::idle_add_local_once(move || {
                    let _ = output_sender.send(TrackSettingsOutput::Accepted(track));
                });
            }

            TrackSettingsMsg::Cancel => {
                // Note: Cancel button is now connected directly in init to avoid panic
                // This handler is kept for completeness but should not be called
            }
        }
    }
}
