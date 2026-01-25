//! Add Job Dialog logic controller.
//!
//! Handles source file selection, validation, and job discovery.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use slint::{ComponentHandle, Model, ModelRc, SharedString, VecModel};
use vsg_core::jobs::{discover_jobs, JobQueue};

use crate::ui::{AddJobDialog, SourceInputData};

/// Set up all callbacks for AddJobDialog.
///
/// The `on_jobs_added` callback is called when jobs are successfully added,
/// with the count of jobs added.
pub fn setup_add_job_dialog<F>(
    dialog: &AddJobDialog,
    queue: Arc<Mutex<JobQueue>>,
    on_jobs_added: F,
) where
    F: Fn(usize) + Clone + 'static,
{
    setup_source_management(dialog);
    setup_browse_buttons(dialog);
    setup_path_changed(dialog);
    setup_find_and_add(dialog, queue, on_jobs_added);
    setup_cancel_button(dialog);

    // Initialize with default sources
    initialize_sources(dialog);
}

/// Initialize default source inputs.
fn initialize_sources(dialog: &AddJobDialog) {
    let sources = vec![
        SourceInputData {
            index: 1,
            path: SharedString::new(),
            is_reference: true,
        },
        SourceInputData {
            index: 2,
            path: SharedString::new(),
            is_reference: false,
        },
    ];

    let model = std::rc::Rc::new(VecModel::from(sources));
    dialog.set_sources(ModelRc::from(model));
}

/// Set up add/remove source management.
fn setup_source_management(dialog: &AddJobDialog) {
    // Add source
    let dialog_weak = dialog.as_weak();

    dialog.on_add_source(move || {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let sources = dialog.get_sources();
        let current_count = sources.row_count();

        if current_count >= 10 {
            return; // Max limit
        }

        // Get the model and add new source
        if let Some(model) = sources.as_any().downcast_ref::<VecModel<SourceInputData>>() {
            let new_source = SourceInputData {
                index: (current_count + 1) as i32,
                path: SharedString::new(),
                is_reference: false,
            };
            model.push(new_source);
        }
    });

    // Remove source
    let dialog_weak = dialog.as_weak();

    dialog.on_remove_source(move |source_index| {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let sources = dialog.get_sources();

        // Find and remove the source with this index
        if let Some(model) = sources.as_any().downcast_ref::<VecModel<SourceInputData>>() {
            let count = model.row_count();

            // Don't allow removal if only 2 sources remain
            if count <= 2 {
                return;
            }

            // Find the source to remove
            for i in 0..count {
                if let Some(source) = model.row_data(i) {
                    if source.index == source_index && !source.is_reference {
                        model.remove(i);
                        // Renumber remaining sources
                        renumber_sources(&dialog);
                        break;
                    }
                }
            }
        }
    });
}

/// Renumber sources after removal.
fn renumber_sources(dialog: &AddJobDialog) {
    let sources = dialog.get_sources();

    if let Some(model) = sources.as_any().downcast_ref::<VecModel<SourceInputData>>() {
        for i in 0..model.row_count() {
            if let Some(mut source) = model.row_data(i) {
                source.index = (i + 1) as i32;
                source.is_reference = i == 0;
                model.set_row_data(i, source);
            }
        }
    }
}

/// Set up browse buttons for each source.
fn setup_browse_buttons(dialog: &AddJobDialog) {
    let dialog_weak = dialog.as_weak();

    dialog.on_browse_source(move |source_index| {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        // Open file picker
        let title = if source_index == 1 {
            "Select Source 1 (Reference)"
        } else {
            &format!("Select Source {}", source_index)
        };

        if let Some(path) = pick_video_file(title) {
            update_source_path(&dialog, source_index, path.to_string_lossy().to_string());
        }
    });
}

/// Set up path change handling (from drag-drop or manual edit).
fn setup_path_changed(dialog: &AddJobDialog) {
    let dialog_weak = dialog.as_weak();

    dialog.on_source_path_changed(move |source_index, path| {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        // Clean up file:// URL if present
        let clean_path = clean_file_url(&path);

        // Update if cleaned
        if clean_path != path.as_str() {
            update_source_path(&dialog, source_index, clean_path);
        }

        // Clear any previous error
        dialog.set_error_message(SharedString::new());
    });
}

/// Update a source path in the model.
fn update_source_path(dialog: &AddJobDialog, source_index: i32, path: String) {
    let sources = dialog.get_sources();

    if let Some(model) = sources.as_any().downcast_ref::<VecModel<SourceInputData>>() {
        for i in 0..model.row_count() {
            if let Some(mut source) = model.row_data(i) {
                if source.index == source_index {
                    source.path = path.into();
                    model.set_row_data(i, source);
                    break;
                }
            }
        }
    }
}

/// Set up Find & Add Jobs button.
fn setup_find_and_add<F>(dialog: &AddJobDialog, queue: Arc<Mutex<JobQueue>>, on_jobs_added: F)
where
    F: Fn(usize) + Clone + 'static,
{
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);
    let callback = on_jobs_added;

    dialog.on_find_and_add_jobs(move || {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        dialog.set_is_processing(true);
        dialog.set_error_message(SharedString::new());

        // Collect source paths
        let sources = collect_source_paths(&dialog);

        // Validate Source 1 is provided
        let source1 = sources.get("Source 1");
        if source1.map(|s| s.as_os_str().is_empty()).unwrap_or(true) {
            dialog.set_error_message("Source 1 (Reference) is required.".into());
            dialog.set_is_processing(false);
            return;
        }

        // Validate Source 2 is provided
        let source2 = sources.get("Source 2");
        if source2.map(|s| s.as_os_str().is_empty()).unwrap_or(true) {
            dialog.set_error_message("Source 2 is required.".into());
            dialog.set_is_processing(false);
            return;
        }

        // Discover jobs
        match discover_jobs(&sources) {
            Ok(jobs) if jobs.is_empty() => {
                dialog.set_error_message(
                    "No jobs could be discovered from the provided sources.".into(),
                );
                dialog.set_is_processing(false);
            }
            Ok(jobs) => {
                let count = jobs.len();

                // Add to queue
                {
                    let mut q = queue_clone.lock().unwrap();
                    q.add_all(jobs);
                    if let Err(e) = q.save() {
                        tracing::warn!("Failed to save queue: {}", e);
                    }
                }

                // Notify caller
                callback(count);

                // Close dialog
                dialog.set_is_processing(false);
                dialog.hide().ok();
            }
            Err(e) => {
                dialog.set_error_message(e.into());
                dialog.set_is_processing(false);
            }
        }
    });
}

/// Collect source paths from dialog into HashMap.
fn collect_source_paths(dialog: &AddJobDialog) -> HashMap<String, PathBuf> {
    let mut paths = HashMap::new();
    let sources = dialog.get_sources();

    for i in 0..sources.row_count() {
        if let Some(source) = sources.row_data(i) {
            let path = source.path.to_string();
            if !path.is_empty() {
                let key = format!("Source {}", source.index);
                paths.insert(key, PathBuf::from(path));
            }
        }
    }

    paths
}

/// Set up cancel button.
fn setup_cancel_button(dialog: &AddJobDialog) {
    let dialog_weak = dialog.as_weak();

    dialog.on_cancel(move || {
        if let Some(dialog) = dialog_weak.upgrade() {
            dialog.hide().ok();
        }
    });
}

/// Open a file picker for video files.
fn pick_video_file(title: &str) -> Option<PathBuf> {
    rfd::FileDialog::new()
        .set_title(title)
        .add_filter(
            "Video Files",
            &["mkv", "mp4", "avi", "mov", "webm", "m4v", "ts", "m2ts"],
        )
        .add_filter("All Files", &["*"])
        .pick_file()
}

/// Clean up a file URL (from drag-drop) to a regular path.
fn clean_file_url(url: &str) -> String {
    // text/uri-list can contain multiple URIs separated by \r\n or \n
    let first_uri = url
        .lines()
        .map(|line| line.trim())
        .find(|line| !line.is_empty() && !line.starts_with('#'))
        .unwrap_or("");

    let path = if first_uri.starts_with("file://") {
        let without_prefix = &first_uri[7..];
        percent_decode(without_prefix)
    } else {
        first_uri.to_string()
    };

    path.trim().to_string()
}

/// Simple percent decoding for file paths.
fn percent_decode(input: &str) -> String {
    let mut result = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();

    while let Some(c) = chars.next() {
        if c == '%' {
            let hex: String = chars.by_ref().take(2).collect();
            if hex.len() == 2 {
                if let Ok(byte) = u8::from_str_radix(&hex, 16) {
                    result.push(byte as char);
                    continue;
                }
            }
            result.push('%');
            result.push_str(&hex);
        } else {
            result.push(c);
        }
    }

    result
}
