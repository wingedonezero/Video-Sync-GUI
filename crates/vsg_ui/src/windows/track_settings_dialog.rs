//! Track Settings Dialog logic controller.
//!
//! Handles per-track configuration: language, name, subtitle options.

use slint::{ComponentHandle, Model, ModelRc, SharedString, VecModel};
use vsg_core::jobs::TrackConfig;

use crate::ui::TrackSettingsDialog;

/// Common language options.
const LANGUAGE_OPTIONS: &[(&str, &str)] = &[
    ("und", "Undetermined"),
    ("eng", "English"),
    ("jpn", "Japanese"),
    ("spa", "Spanish"),
    ("fre", "French"),
    ("ger", "German"),
    ("ita", "Italian"),
    ("por", "Portuguese"),
    ("rus", "Russian"),
    ("chi", "Chinese"),
    ("kor", "Korean"),
    ("ara", "Arabic"),
    ("hin", "Hindi"),
    ("tha", "Thai"),
    ("vie", "Vietnamese"),
    ("pol", "Polish"),
    ("dut", "Dutch"),
    ("swe", "Swedish"),
    ("nor", "Norwegian"),
    ("dan", "Danish"),
    ("fin", "Finnish"),
    ("tur", "Turkish"),
    ("gre", "Greek"),
    ("heb", "Hebrew"),
    ("hun", "Hungarian"),
    ("cze", "Czech"),
    ("rum", "Romanian"),
    ("bul", "Bulgarian"),
    ("ukr", "Ukrainian"),
];

/// Set up all callbacks for TrackSettingsDialog.
///
/// The `on_accept` callback is called when the user accepts,
/// with the TrackConfig (or None if cancelled).
pub fn setup_track_settings_dialog<F>(
    dialog: &TrackSettingsDialog,
    track_type: &str,
    codec_id: &str,
    current_config: TrackConfig,
    on_accept: F,
) where
    F: Fn(Option<TrackConfig>) + Clone + 'static,
{
    // Set track info for conditional UI
    dialog.set_track_type(track_type.into());
    dialog.set_codec_id(codec_id.into());

    // Populate language dropdown
    populate_languages(dialog, current_config.custom_lang.as_deref());

    // Apply current config values
    apply_config_to_ui(dialog, &current_config);

    // Set up callbacks
    setup_sync_exclusion_button(dialog);
    setup_accept_cancel(dialog, on_accept);
}

/// Populate language dropdown options.
fn populate_languages(dialog: &TrackSettingsDialog, selected_lang: Option<&str>) {
    let display_names: Vec<SharedString> = LANGUAGE_OPTIONS
        .iter()
        .map(|(_, display)| (*display).into())
        .collect();

    let model = std::rc::Rc::new(VecModel::from(display_names));
    dialog.set_language_display_names(ModelRc::from(model));

    // Find index of selected language
    let selected_idx = selected_lang
        .and_then(|lang| {
            LANGUAGE_OPTIONS
                .iter()
                .position(|(code, _)| *code == lang)
        })
        .unwrap_or(0); // Default to "Undetermined"

    dialog.set_selected_language_index(selected_idx as i32);
}

/// Apply config values to dialog UI.
fn apply_config_to_ui(dialog: &TrackSettingsDialog, config: &TrackConfig) {
    dialog.set_custom_name(
        config
            .custom_name
            .as_ref()
            .map(|s| s.as_str().into())
            .unwrap_or_default(),
    );

    dialog.set_perform_ocr(config.perform_ocr);
    dialog.set_convert_to_ass(config.convert_to_ass);
    dialog.set_rescale(config.rescale);
    dialog.set_size_multiplier_pct((config.size_multiplier * 100.0) as i32);
}

/// Read config values from dialog UI.
fn read_config_from_ui(dialog: &TrackSettingsDialog) -> TrackConfig {
    let selected_idx = dialog.get_selected_language_index() as usize;
    let custom_lang = if selected_idx > 0 && selected_idx < LANGUAGE_OPTIONS.len() {
        Some(LANGUAGE_OPTIONS[selected_idx].0.to_string())
    } else {
        None // "Undetermined" = no override
    };

    let custom_name_str = dialog.get_custom_name().to_string();
    let custom_name = if custom_name_str.is_empty() {
        None
    } else {
        Some(custom_name_str)
    };

    TrackConfig {
        sync_to_source: None, // Not editable in this dialog
        is_default: false,     // Not editable in this dialog
        is_forced: false,      // Not editable in this dialog
        custom_name,
        custom_lang,
        perform_ocr: dialog.get_perform_ocr(),
        convert_to_ass: dialog.get_convert_to_ass(),
        rescale: dialog.get_rescale(),
        size_multiplier: dialog.get_size_multiplier_pct() as f32 / 100.0,
        sync_exclusion_styles: Vec::new(), // TODO: From SyncExclusionDialog
    }
}

/// Set up sync exclusion button (stub - opens placeholder dialog).
fn setup_sync_exclusion_button(dialog: &TrackSettingsDialog) {
    let _dialog_weak = dialog.as_weak();

    dialog.on_configure_sync_exclusion(move || {
        // TODO: Open SyncExclusionDialog
        tracing::info!("Sync exclusion dialog not yet implemented");
    });
}

/// Set up accept/cancel buttons.
fn setup_accept_cancel<F>(dialog: &TrackSettingsDialog, on_accept: F)
where
    F: Fn(Option<TrackConfig>) + Clone + 'static,
{
    // Accept
    let dialog_weak = dialog.as_weak();
    let callback = on_accept.clone();

    dialog.on_accept(move || {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let config = read_config_from_ui(&dialog);
        callback(Some(config));
        dialog.hide().ok();
    });

    // Cancel
    let dialog_weak = dialog.as_weak();
    let callback = on_accept;

    dialog.on_cancel(move || {
        if let Some(dialog) = dialog_weak.upgrade() {
            callback(None);
            dialog.hide().ok();
        }
    });
}
