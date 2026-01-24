//! Video Sync GUI - Main entry point

// Include the Slint-generated code
slint::include_modules!();

fn main() -> Result<(), slint::PlatformError> {
    // Create the main window
    let main_window = MainWindow::new()?;

    // Log that we're starting (demonstrates property setting)
    main_window.set_log_text("Video Sync GUI started.\nCore version: ".into());
    let version_info = format!(
        "Video Sync GUI started.\nCore version: {}\n",
        vsg_core::version()
    );
    main_window.set_log_text(version_info.into());

    // Set up callbacks
    let window_weak = main_window.as_weak();
    main_window.on_browse_source1(move || {
        if let Some(window) = window_weak.upgrade() {
            append_log(&window, "Browse Source 1 clicked (file dialog not yet implemented)");
        }
    });

    let window_weak = main_window.as_weak();
    main_window.on_browse_source2(move || {
        if let Some(window) = window_weak.upgrade() {
            append_log(&window, "Browse Source 2 clicked (file dialog not yet implemented)");
        }
    });

    let window_weak = main_window.as_weak();
    main_window.on_run_clicked(move || {
        if let Some(window) = window_weak.upgrade() {
            window.set_status_text("Running...".into());
            append_log(&window, "Run clicked - pipeline not yet implemented");
            window.set_status_text("Ready".into());
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
