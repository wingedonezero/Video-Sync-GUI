//! Application pages
//!
//! Each page represents a different view in the application

mod main_page;

pub use main_page::*;

/// Page identifiers
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PageId {
    /// Main application page with file inputs and job controls
    Main,
    /// Settings page (when not shown as dialog)
    Settings,
}
