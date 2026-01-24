//! Logging infrastructure for Video Sync GUI.
//!
//! This module provides:
//! - Per-job loggers with file + GUI callback dual output
//! - Compact mode with progress filtering
//! - Tail buffer for error diagnosis
//! - Integration with the `tracing` ecosystem
//!
//! # Example
//!
//! ```no_run
//! use vsg_core::logging::{JobLogger, LogConfig, LogLevel};
//!
//! // Create a job logger
//! let logger = JobLogger::new(
//!     "my_job",
//!     "/path/to/logs",
//!     LogConfig::default(),
//!     None,
//! ).unwrap();
//!
//! // Log messages at various levels
//! logger.info("Starting job");
//! logger.phase("Extraction");
//! logger.command("ffmpeg -i input.mkv ...");
//! logger.progress(50);
//! logger.success("Job completed");
//! ```

mod job_logger;
mod types;

pub use job_logger::{JobLogger, JobLoggerBuilder};
pub use types::{GuiLogCallback, LogConfig, LogLevel, MessagePrefix};

use tracing_subscriber::{fmt, prelude::*, EnvFilter};

/// Initialize global tracing subscriber for application-wide logging.
///
/// This sets up a subscriber that:
/// - Respects RUST_LOG environment variable
/// - Falls back to the provided default level
/// - Outputs to stderr with timestamps
///
/// Should be called once at application startup.
pub fn init_tracing(default_level: LogLevel) {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new(level_to_filter_str(default_level)));

    tracing_subscriber::registry()
        .with(fmt::layer().with_target(true).with_thread_ids(false))
        .with(filter)
        .init();
}

/// Initialize tracing for tests (only logs warnings and above).
#[cfg(test)]
pub fn init_test_tracing() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter("warn")
        .with_test_writer()
        .try_init();
}

/// Convert LogLevel to filter string.
fn level_to_filter_str(level: LogLevel) -> &'static str {
    match level {
        LogLevel::Trace => "trace",
        LogLevel::Debug => "debug",
        LogLevel::Info => "info",
        LogLevel::Warn => "warn",
        LogLevel::Error => "error",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn level_to_filter_works() {
        assert_eq!(level_to_filter_str(LogLevel::Debug), "debug");
        assert_eq!(level_to_filter_str(LogLevel::Info), "info");
    }
}
