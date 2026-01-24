//! VSG Core - Backend logic for Video Sync GUI
//!
//! This crate contains all business logic with zero UI dependencies.
//! It can be used by the GUI application or a CLI tool.

pub mod config;
pub mod logging;
pub mod models;

/// Returns the crate version.
pub fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_returns_value() {
        assert!(!version().is_empty());
    }
}
