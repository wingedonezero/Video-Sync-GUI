//! Video Sync GUI - Main entry point

// Include the Slint-generated code
slint::include_modules!();

fn main() -> Result<(), slint::PlatformError> {
    // Create the main window
    let main_window = MainWindow::new()?;

    // Log that we're starting
    let version_info = format!(
        "Video Sync GUI started.\nCore version: {}\n",
        vsg_core::version()
    );
    main_window.set_log_text(version_info.into());

    // Settings button
    let window_weak = main_window.as_weak();
    main_window.on_settings_clicked(move || {
        if let Some(window) = window_weak.upgrade() {
            append_log(&window, "Opening settings...");
            // Settings window would be shown here
            // For now just log
            append_log(&window, "Settings dialog not yet wired up");
        }
    });

    // Queue Jobs button
    let window_weak = main_window.as_weak();
    main_window.on_queue_jobs_clicked(move || {
        if let Some(window) = window_weak.upgrade() {
            append_log(&window, "Opening job queue...");
            append_log(&window, "Job queue dialog not yet implemented");
        }
    });

    // Browse Source 1
    let window_weak = main_window.as_weak();
    main_window.on_browse_source1(move || {
        if let Some(window) = window_weak.upgrade() {
            append_log(&window, "Browse Source 1 clicked (file dialog not yet implemented)");
        }
    });

    // Browse Source 2
    let window_weak = main_window.as_weak();
    main_window.on_browse_source2(move || {
        if let Some(window) = window_weak.upgrade() {
            append_log(&window, "Browse Source 2 clicked (file dialog not yet implemented)");
        }
    });

    // Browse Source 3
    let window_weak = main_window.as_weak();
    main_window.on_browse_source3(move || {
        if let Some(window) = window_weak.upgrade() {
            append_log(&window, "Browse Source 3 clicked (file dialog not yet implemented)");
        }
    });

    // Analyze Only button
    let window_weak = main_window.as_weak();
    main_window.on_analyze_only_clicked(move || {
        if let Some(window) = window_weak.upgrade() {
            let source1 = window.get_source1_path();
            let source2 = window.get_source2_path();

            if source1.is_empty() || source2.is_empty() {
                append_log(&window, "[WARNING] Please select at least Source 1 and Source 2");
                return;
            }

            window.set_status_text("Analyzing...".into());
            window.set_progress_value(0.0);

            append_log(&window, "=== Starting Analysis ===");
            append_log(&window, &format!("Source 1: {}", source1));
            append_log(&window, &format!("Source 2: {}", source2));

            let source3 = window.get_source3_path();
            if !source3.is_empty() {
                append_log(&window, &format!("Source 3: {}", source3));
            }

            // Simulate progress
            window.set_progress_value(50.0);
            append_log(&window, "Analysis step not yet implemented - using stub");

            // Show stub results
            window.set_delay_source2("0 ms".into());
            if !source3.is_empty() {
                window.set_delay_source3("0 ms".into());
            }

            window.set_progress_value(100.0);
            window.set_status_text("Ready".into());
            append_log(&window, "=== Analysis Complete ===");
        }
    });

    // Run the event loop
    main_window.run()
}

/// Helper to append text to the log
fn append_log(window: &MainWindow, message: &str) {
    let current = window.get_log_text();
    let new_text = format!("{}{}\n", current, message);
    window.set_log_text(new_text.into());
}
