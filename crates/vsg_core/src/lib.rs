//! VSG Core - Backend logic for Video Sync GUI
//!
//! This crate contains all business logic with zero UI dependencies.
//! It can be used by the GUI application or a CLI tool.

pub mod analysis;
pub mod chapters;
pub mod config;
pub mod extraction;
pub mod jobs;
pub mod logging;
pub mod models;
pub mod mux;
pub mod orchestrator;

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
