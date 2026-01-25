//! Theme configuration for Video Sync GUI.
//!
//! This module provides theming for iced and custom colors.

use iced::Color;

/// Application theme colors (dark theme to match original).
pub mod colors {
    use super::Color;

    /// Background color
    pub const BACKGROUND: Color = Color::from_rgb(0.12, 0.12, 0.12);

    /// Surface color (slightly lighter)
    pub const SURFACE: Color = Color::from_rgb(0.16, 0.16, 0.16);

    /// Card/panel background
    pub const CARD: Color = Color::from_rgb(0.14, 0.14, 0.14);

    /// Primary accent color
    pub const PRIMARY: Color = Color::from_rgb(0.24, 0.35, 0.50);

    /// Primary accent hover
    pub const PRIMARY_HOVER: Color = Color::from_rgb(0.30, 0.42, 0.58);

    /// Success color (for configured status)
    pub const SUCCESS: Color = Color::from_rgb(0.18, 0.35, 0.18);

    /// Warning color (for processing status)
    pub const WARNING: Color = Color::from_rgb(0.35, 0.35, 0.18);

    /// Error color
    pub const ERROR: Color = Color::from_rgb(0.35, 0.18, 0.18);

    /// Info color
    pub const INFO: Color = Color::from_rgb(0.18, 0.35, 0.35);

    /// Text primary
    pub const TEXT_PRIMARY: Color = Color::from_rgb(0.93, 0.93, 0.93);

    /// Text secondary
    pub const TEXT_SECONDARY: Color = Color::from_rgb(0.53, 0.53, 0.53);

    /// Text muted
    pub const TEXT_MUTED: Color = Color::from_rgb(0.40, 0.40, 0.40);

    /// Border color
    pub const BORDER: Color = Color::from_rgb(0.25, 0.25, 0.25);

    /// Selected row background
    pub const SELECTED: Color = Color::from_rgb(0.24, 0.35, 0.50);

    /// Hover row background
    pub const HOVER: Color = Color::from_rgb(0.23, 0.23, 0.23);

    /// Badge background
    pub const BADGE_BG: Color = Color::from_rgb(0.20, 0.20, 0.20);
}

/// Status colors for job status badges.
pub mod status {
    use super::Color;

    pub fn for_status(status: &str) -> Color {
        match status {
            "Configured" => Color::from_rgb(0.18, 0.35, 0.18),
            "Processing" => Color::from_rgb(0.35, 0.35, 0.18),
            "Complete" | "Merged" | "Analyzed" => Color::from_rgb(0.18, 0.35, 0.35),
            "Error" | "Failed" => Color::from_rgb(0.35, 0.18, 0.18),
            _ => Color::from_rgb(0.20, 0.20, 0.20),
        }
    }
}

/// Spacing constants.
pub mod spacing {
    /// Extra small spacing (4px)
    pub const XS: u16 = 4;
    /// Small spacing (8px)
    pub const SM: u16 = 8;
    /// Medium spacing (12px)
    pub const MD: u16 = 12;
    /// Large spacing (16px)
    pub const LG: u16 = 16;
    /// Extra large spacing (24px)
    pub const XL: u16 = 24;
}

/// Font sizes.
pub mod font {
    /// Small font size
    pub const SM: u16 = 11;
    /// Normal font size
    pub const NORMAL: u16 = 13;
    /// Medium font size
    pub const MD: u16 = 14;
    /// Large font size
    pub const LG: u16 = 16;
    /// Header font size
    pub const HEADER: u16 = 18;
}
