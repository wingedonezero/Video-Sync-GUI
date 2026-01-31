//! Theme configuration for Video Sync GUI.
//!
//! This module provides theming constants for GTK4/libadwaita.
//! Note: libadwaita handles most theming automatically with its AdwStyleManager.

/// Application CSS styles.
pub const APP_CSS: &str = r#"
    .error {
        color: #e74c3c;
    }

    .success {
        color: #2ecc71;
    }

    .warning {
        color: #f39c12;
    }

    .info {
        color: #3498db;
    }

    .title-3 {
        font-weight: bold;
        font-size: 1.1em;
    }

    .title-4 {
        font-weight: 600;
        font-size: 1.05em;
    }

    .monospace {
        font-family: monospace;
    }

    row.selected {
        background-color: alpha(@accent_color, 0.2);
    }

    row.selected:hover {
        background-color: alpha(@accent_color, 0.3);
    }

    row.activatable.selected:active {
        background-color: alpha(@accent_color, 0.4);
    }
"#;

/// Spacing constants (in pixels).
pub mod spacing {
    /// Extra small spacing (4px)
    pub const XS: i32 = 4;
    /// Small spacing (8px)
    pub const SM: i32 = 8;
    /// Medium spacing (12px)
    pub const MD: i32 = 12;
    /// Large spacing (16px)
    pub const LG: i32 = 16;
    /// Extra large spacing (24px)
    pub const XL: i32 = 24;
}

/// Font sizes.
pub mod font {
    /// Small font size
    pub const SM: i32 = 11;
    /// Normal font size
    pub const NORMAL: i32 = 13;
    /// Medium font size
    pub const MD: i32 = 14;
    /// Large font size
    pub const LG: i32 = 16;
    /// Header font size
    pub const HEADER: i32 = 18;
}

/// Status colors for job status badges.
pub mod status {
    /// Get a CSS class name for a status.
    pub fn css_class_for_status(status: &str) -> &'static str {
        match status {
            "Configured" | "Complete" | "Merged" | "Analyzed" => "success",
            "Processing" => "warning",
            "Error" | "Failed" => "error",
            _ => "",
        }
    }
}

/// Initialize application-wide CSS.
pub fn init_css() {

    let provider = gtk::CssProvider::new();
    provider.load_from_string(APP_CSS);

    gtk::style_context_add_provider_for_display(
        &gtk::gdk::Display::default().expect("Could not get default display"),
        &provider,
        gtk::STYLE_PROVIDER_PRIORITY_APPLICATION,
    );
}
