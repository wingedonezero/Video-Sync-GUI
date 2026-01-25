//! Job Queue Dialog logic controller.
//!
//! Manages the job queue display, add/remove/reorder operations,
//! and launching job configuration and processing.

use std::sync::{Arc, Mutex};

use slint::{ComponentHandle, Model, ModelRc, SharedString, VecModel};
use vsg_core::jobs::{JobQueue, JobQueueStatus};

use crate::ui::{AddJobDialog, JobQueueDialog, JobRowData, ManualSelectionDialog};
use crate::windows::add_job_dialog::setup_add_job_dialog;
use crate::windows::manual_selection_dialog::setup_manual_selection_dialog;

/// Set up all callbacks for the JobQueueDialog.
pub fn setup_job_queue_dialog(dialog: &JobQueueDialog, queue: Arc<Mutex<JobQueue>>) {
    setup_add_jobs_button(dialog, Arc::clone(&queue));
    setup_row_selection(dialog, Arc::clone(&queue));
    setup_row_double_click(dialog, Arc::clone(&queue));
    setup_configure_job(dialog, Arc::clone(&queue));
    setup_remove_selected(dialog, Arc::clone(&queue));
    setup_move_buttons(dialog, Arc::clone(&queue));
    setup_copy_paste_layout(dialog, Arc::clone(&queue));
    setup_start_processing(dialog, Arc::clone(&queue));
    setup_cancel_button(dialog);
    setup_files_dropped(dialog, Arc::clone(&queue));

    // Initial populate
    refresh_job_table(dialog, &queue.lock().unwrap());
}

/// Refresh the job table from queue state.
pub fn refresh_job_table(dialog: &JobQueueDialog, queue: &JobQueue) {
    let jobs: Vec<JobRowData> = queue
        .jobs()
        .iter()
        .map(|job| JobRowData {
            id: job.id.clone().into(),
            name: job.name.clone().into(),
            source1: job.source_display("Source 1", 40).into(),
            source2: job.source_display("Source 2", 40).into(),
            source3: job.source_display("Source 3", 30).into(),
            source4: job.source_display("Source 4", 30).into(),
            status: job.status.as_str().into(),
            is_selected: false,
        })
        .collect();

    let model = std::rc::Rc::new(VecModel::from(jobs));
    dialog.set_jobs(ModelRc::from(model));
    dialog.set_has_clipboard(queue.has_clipboard());
}

/// Set up Add Jobs button.
fn setup_add_jobs_button(dialog: &JobQueueDialog, queue: Arc<Mutex<JobQueue>>) {
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);

    dialog.on_add_jobs(move || {
        let Some(parent_dialog) = dialog_weak.upgrade() else {
            return;
        };

        // Create and show AddJobDialog
        match AddJobDialog::new() {
            Ok(add_dialog) => {
                let parent_weak = parent_dialog.as_weak();
                let queue_for_add = Arc::clone(&queue_clone);
                let queue_for_callback = Arc::clone(&queue_clone);

                // Set up the add job dialog
                setup_add_job_dialog(&add_dialog, queue_for_add, move |jobs_added| {
                    // Callback when jobs are added
                    if jobs_added > 0 {
                        if let Some(parent) = parent_weak.upgrade() {
                            let q = queue_for_callback.lock().unwrap();
                            refresh_job_table(&parent, &q);
                            parent.set_status_message(
                                format!("Added {} job(s) to queue", jobs_added).into(),
                            );
                        }
                    }
                });

                if let Err(e) = add_dialog.show() {
                    parent_dialog.set_status_message(
                        format!("Failed to show Add Job dialog: {}", e).into(),
                    );
                }
            }
            Err(e) => {
                parent_dialog
                    .set_status_message(format!("Failed to create Add Job dialog: {}", e).into());
            }
        }
    });
}

/// Set up row selection handling.
fn setup_row_selection(dialog: &JobQueueDialog, _queue: Arc<Mutex<JobQueue>>) {
    let dialog_weak = dialog.as_weak();

    dialog.on_row_selected(move |row_idx, is_selected| {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        // Update the is_selected flag in the jobs model
        let jobs = dialog.get_jobs();
        if let Some(model) = jobs.as_any().downcast_ref::<VecModel<JobRowData>>() {
            if let Some(mut job) = model.row_data(row_idx as usize) {
                job.is_selected = is_selected;
                model.set_row_data(row_idx as usize, job);
            }
        }

        // Update selected indices
        update_selected_indices(&dialog);
    });
}

/// Update the selected_indices property from jobs model.
fn update_selected_indices(dialog: &JobQueueDialog) {
    let jobs = dialog.get_jobs();
    let mut indices: Vec<i32> = Vec::new();

    for i in 0..jobs.row_count() {
        if let Some(job) = jobs.row_data(i) {
            if job.is_selected {
                indices.push(i as i32);
            }
        }
    }

    let model = std::rc::Rc::new(VecModel::from(indices));
    dialog.set_selected_indices(ModelRc::from(model));
}

/// Set up row double-click to configure job.
fn setup_row_double_click(dialog: &JobQueueDialog, queue: Arc<Mutex<JobQueue>>) {
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);

    dialog.on_row_double_clicked(move |row_idx| {
        open_manual_selection(dialog_weak.clone(), Arc::clone(&queue_clone), row_idx as usize);
    });
}

/// Set up configure job button/callback.
fn setup_configure_job(dialog: &JobQueueDialog, queue: Arc<Mutex<JobQueue>>) {
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);

    dialog.on_configure_job(move |row_idx| {
        open_manual_selection(dialog_weak.clone(), Arc::clone(&queue_clone), row_idx as usize);
    });
}

/// Open ManualSelectionDialog for a job.
fn open_manual_selection(
    dialog_weak: slint::Weak<JobQueueDialog>,
    queue: Arc<Mutex<JobQueue>>,
    job_idx: usize,
) {
    let Some(parent_dialog) = dialog_weak.upgrade() else {
        return;
    };

    // Get job info
    let (job_id, job_name, sources) = {
        let q = queue.lock().unwrap();
        match q.get(job_idx) {
            Some(job) => (job.id.clone(), job.name.clone(), job.sources.clone()),
            None => {
                parent_dialog.set_status_message("Job not found".into());
                return;
            }
        }
    };

    // Create and show ManualSelectionDialog
    match ManualSelectionDialog::new() {
        Ok(selection_dialog) => {
            let parent_weak = parent_dialog.as_weak();
            let queue_for_save = Arc::clone(&queue);
            let job_id_for_save = job_id.clone();

            setup_manual_selection_dialog(
                &selection_dialog,
                &job_name,
                &sources,
                move |layout| {
                    // Callback when layout is accepted
                    if let Some(layout) = layout {
                        let mut q = queue_for_save.lock().unwrap();
                        q.set_layout(job_idx, layout);
                        if let Err(e) = q.save() {
                            tracing::warn!("Failed to save queue: {}", e);
                        }

                        if let Some(parent) = parent_weak.upgrade() {
                            refresh_job_table(&parent, &q);
                            parent.set_status_message("Job configured".into());
                        }
                    }
                },
            );

            // Note: Window title is set at compile time in Slint, can't be changed dynamically
            // The job_name is passed to setup_manual_selection_dialog for use in the UI

            if let Err(e) = selection_dialog.show() {
                parent_dialog.set_status_message(
                    format!("Failed to show selection dialog: {}", e).into(),
                );
            }
        }
        Err(e) => {
            parent_dialog
                .set_status_message(format!("Failed to create selection dialog: {}", e).into());
        }
    }
}

/// Set up remove selected button.
fn setup_remove_selected(dialog: &JobQueueDialog, queue: Arc<Mutex<JobQueue>>) {
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);

    dialog.on_remove_selected(move || {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let selected = dialog.get_selected_indices();
        let indices: Vec<usize> = (0..selected.row_count())
            .filter_map(|i| selected.row_data(i).map(|idx| idx as usize))
            .collect();

        if indices.is_empty() {
            return;
        }

        let count = indices.len();
        {
            let mut q = queue_clone.lock().unwrap();
            q.remove_indices(indices);
            if let Err(e) = q.save() {
                tracing::warn!("Failed to save queue: {}", e);
            }
            refresh_job_table(&dialog, &q);
        }

        dialog.set_status_message(format!("Removed {} job(s)", count).into());
    });
}

/// Set up move up/down buttons.
fn setup_move_buttons(dialog: &JobQueueDialog, queue: Arc<Mutex<JobQueue>>) {
    // Move up
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);

    dialog.on_move_up(move || {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let selected = dialog.get_selected_indices();
        let indices: Vec<usize> = (0..selected.row_count())
            .filter_map(|i| selected.row_data(i).map(|idx| idx as usize))
            .collect();

        if indices.is_empty() {
            return;
        }

        {
            let mut q = queue_clone.lock().unwrap();
            q.move_up(&indices);
            if let Err(e) = q.save() {
                tracing::warn!("Failed to save queue: {}", e);
            }
            refresh_job_table(&dialog, &q);
        }

        // Re-select the moved items (now at idx-1)
        // TODO: Maintain selection after move
    });

    // Move down
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);

    dialog.on_move_down(move || {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let selected = dialog.get_selected_indices();
        let indices: Vec<usize> = (0..selected.row_count())
            .filter_map(|i| selected.row_data(i).map(|idx| idx as usize))
            .collect();

        if indices.is_empty() {
            return;
        }

        {
            let mut q = queue_clone.lock().unwrap();
            q.move_down(&indices);
            if let Err(e) = q.save() {
                tracing::warn!("Failed to save queue: {}", e);
            }
            refresh_job_table(&dialog, &q);
        }
    });
}

/// Set up copy/paste layout buttons.
fn setup_copy_paste_layout(dialog: &JobQueueDialog, queue: Arc<Mutex<JobQueue>>) {
    // Copy layout
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);

    dialog.on_copy_layout(move |row_idx| {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let mut q = queue_clone.lock().unwrap();
        if q.copy_layout(row_idx as usize) {
            dialog.set_has_clipboard(true);
            dialog.set_status_message("Layout copied to clipboard".into());
        } else {
            dialog.set_status_message("No layout to copy (job not configured)".into());
        }
    });

    // Paste layout
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);

    dialog.on_paste_layout(move || {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let selected = dialog.get_selected_indices();
        let indices: Vec<usize> = (0..selected.row_count())
            .filter_map(|i| selected.row_data(i).map(|idx| idx as usize))
            .collect();

        if indices.is_empty() {
            dialog.set_status_message("No jobs selected for paste".into());
            return;
        }

        let mut q = queue_clone.lock().unwrap();
        let count = q.paste_layout(&indices);

        if count > 0 {
            if let Err(e) = q.save() {
                tracing::warn!("Failed to save queue: {}", e);
            }
            refresh_job_table(&dialog, &q);
            dialog.set_status_message(format!("Pasted layout to {} job(s)", count).into());
        } else {
            dialog.set_status_message("No layout in clipboard".into());
        }
    });
}

/// Set up start processing button.
fn setup_start_processing(dialog: &JobQueueDialog, queue: Arc<Mutex<JobQueue>>) {
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);

    dialog.on_start_processing(move || {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        let q = queue_clone.lock().unwrap();
        let ready_count = q.jobs_ready().len();

        if ready_count == 0 {
            dialog.set_status_message(
                "No configured jobs to process. Double-click jobs to configure them.".into(),
            );
            return;
        }

        // TODO: Implement actual processing
        // For now, just show message
        dialog.set_status_message(
            format!(
                "{} job(s) ready for processing. Processing not yet implemented.",
                ready_count
            )
            .into(),
        );

        // Future implementation will:
        // 1. Set is_processing = true
        // 2. Spawn background thread
        // 3. Run pipeline for each job
        // 4. Update status as jobs complete
        // 5. Set is_processing = false when done
    });
}

/// Set up cancel button.
fn setup_cancel_button(dialog: &JobQueueDialog) {
    let dialog_weak = dialog.as_weak();

    dialog.on_cancel(move || {
        if let Some(dialog) = dialog_weak.upgrade() {
            dialog.hide().ok();
        }
    });
}

/// Set up file drop handling.
fn setup_files_dropped(dialog: &JobQueueDialog, queue: Arc<Mutex<JobQueue>>) {
    let dialog_weak = dialog.as_weak();
    let queue_clone = Arc::clone(&queue);

    dialog.on_files_dropped(move |paths| {
        let Some(dialog) = dialog_weak.upgrade() else {
            return;
        };

        // Parse URIs from dropped data
        // For now, just show message - real implementation would open AddJobDialog
        // with paths pre-populated
        let path_count = paths.row_count();
        if path_count > 0 {
            dialog.set_status_message(
                format!(
                    "Dropped {} file(s). Use 'Add Job(s)...' to add them.",
                    path_count
                )
                .into(),
            );
        }
    });
}
