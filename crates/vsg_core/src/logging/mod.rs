//! Logging infrastructure for Video Sync GUI.
//!
//! This module provides:
//! - Application-level logging with file output (app.log)
//! - Per-job loggers with file + GUI callback dual output
//! - Compact mode with progress filtering
//! - Tail buffer for error diagnosis
//! - Integration with the `tracing` ecosystem
//!
//! # Application Logging
//!
//! ```no_run
//! use std::path::Path;
//! use vsg_core::logging::{init_tracing_with_file, LogLevel};
//!
//! // Initialize app-level logging to logs/app.log
//! let _guard = init_tracing_with_file(LogLevel::Info, Path::new(".logs"));
//! // _guard must be kept alive for the duration of the program
//!
//! tracing::info!("Application started");
//! tracing::error!("Something went wrong: {}", "codec error");
//! ```
//!
//! # Job Logging
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

use std::path::Path;

pub use job_logger::{JobLogger, JobLoggerBuilder};
pub use types::{GuiLogCallback, LogConfig, LogLevel, MessagePrefix};

use tracing_appender::non_blocking::WorkerGuard;
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

/// Initialize global tracing subscriber for application-wide logging.
///
/// This sets up a subscriber that:
/// - Respects RUST_LOG environment variable
/// - Falls back to the provided default level
/// - Outputs to stderr with timestamps
///
/// Should be called once at application startup.
/// Note: This only logs to stderr. Use `init_tracing_with_file` for file logging.
pub fn init_tracing(default_level: LogLevel) {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new(level_to_filter_str(default_level)));

    tracing_subscriber::registry()
        .with(fmt::layer().with_target(true).with_thread_ids(false))
        .with(filter)
        .init();
}

/// Initialize global tracing with both stderr and file output.
///
/// This sets up a subscriber that logs to:
/// - stderr (for terminal/console viewing)
/// - `{logs_dir}/app.log` (for persistent application logs)
///
/// Returns a guard that must be kept alive for logging to work.
/// When the guard is dropped, any remaining logs are flushed.
///
/// # Arguments
/// * `default_level` - Default log level if RUST_LOG is not set
/// * `logs_dir` - Directory to write app.log to
///
/// # Example
/// ```no_run
/// use std::path::Path;
/// use vsg_core::logging::{init_tracing_with_file, LogLevel};
///
/// let _guard = init_tracing_with_file(LogLevel::Info, Path::new(".logs"));
/// tracing::info!("App started");
/// // _guard keeps logging active until dropped
/// ```
pub fn init_tracing_with_file(default_level: LogLevel, logs_dir: &Path) -> WorkerGuard {
    // Create logs directory if it doesn't exist
    if !logs_dir.exists() {
        let _ = std::fs::create_dir_all(logs_dir);
    }

    // Set up file appender (non-blocking for performance)
    let file_appender = tracing_appender::rolling::never(logs_dir, "app.log");
    let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);

    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new(level_to_filter_str(default_level)));

    // Create layers for stderr and file
    let stderr_layer = fmt::layer()
        .with_target(true)
        .with_thread_ids(false)
        .with_ansi(true);

    let file_layer = fmt::layer()
        .with_target(true)
        .with_thread_ids(false)
        .with_ansi(false) // No ANSI codes in file
        .with_writer(non_blocking);

    tracing_subscriber::registry()
        .with(filter)
        .with(stderr_layer)
        .with(file_layer)
        .init();

    guard
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
