//! Application settings model
//!
//! This module is a placeholder - the full implementation will be in config.rs
//! which handles both the model and persistence logic.

use serde::{Deserialize, Serialize};

/// Application settings
///
/// Note: The actual settings structure is defined in config.rs.
/// This is just a placeholder type alias for now.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppSettings {
    // Placeholder - will be expanded when config module is implemented
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {}
    }
}
