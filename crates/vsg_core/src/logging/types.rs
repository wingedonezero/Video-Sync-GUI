//! Logging types and configuration.

use serde::{Deserialize, Serialize};

/// Log level for filtering messages.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Default, Serialize, Deserialize)]
pub enum LogLevel {
    /// Trace-level debugging (very verbose).
    Trace,
    /// Debug information.
    Debug,
    /// General information.
    #[default]
    Info,
    /// Warnings.
    Warn,
    /// Errors.
    Error,
}

impl LogLevel {
    /// Convert to tracing level.
    pub fn to_tracing_level(&self) -> tracing::Level {
        match self {
            LogLevel::Trace => tracing::Level::TRACE,
            LogLevel::Debug => tracing::Level::DEBUG,
            LogLevel::Info => tracing::Level::INFO,
            LogLevel::Warn => tracing::Level::WARN,
            LogLevel::Error => tracing::Level::ERROR,
        }
    }
}

/// Configuration for logging behavior.
#[derive(Debug, Clone)]
pub struct LogConfig {
    /// Minimum log level to output.
    pub level: LogLevel,
    /// Use compact mode (filter progress, show tail on error).
    pub compact: bool,
    /// Progress update step percentage (only log progress at these intervals).
    pub progress_step: u32,
    /// Number of lines to show on error (tail).
    pub error_tail: usize,
    /// Show timestamps in log output.
    pub show_timestamps: bool,
}

impl Default for LogConfig {
    fn default() -> Self {
        Self {
            level: LogLevel::Info,
            compact: true,
            progress_step: 20,
            error_tail: 20,
            show_timestamps: true,
        }
    }
}

impl LogConfig {
    /// Create a debug configuration (verbose, no compact).
    pub fn debug() -> Self {
        Self {
            level: LogLevel::Debug,
            compact: false,
            progress_step: 10,
            error_tail: 50,
            show_timestamps: true,
        }
    }

    /// Create a trace configuration (very verbose).
    pub fn trace() -> Self {
        Self {
            level: LogLevel::Trace,
            compact: false,
            progress_step: 5,
            error_tail: 100,
            show_timestamps: true,
        }
    }
}

/// Type alias for GUI log callback function.
///
/// The callback receives each log message as a string.
pub type GuiLogCallback = Box<dyn Fn(&str) + Send + Sync>;

/// Message prefix types for consistent formatting.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MessagePrefix {
    /// Shell command: `$ command`
    Command,
    /// Phase marker: `=== Phase ===`
    Phase,
    /// Section marker: `--- Section ---`
    Section,
    /// Validation: `[Validation]`
    Validation,
    /// Success: `[SUCCESS]`
    Success,
    /// Warning: `[WARNING]`
    Warning,
    /// Error: `[ERROR]`
    Error,
    /// Debug: `[DEBUG]`
    Debug,
    /// No prefix
    None,
}

impl MessagePrefix {
    /// Format a message with this prefix.
    pub fn format(&self, message: &str) -> String {
        match self {
            MessagePrefix::Command => format!("$ {}", message),
            MessagePrefix::Phase => format!("=== {} ===", message),
            MessagePrefix::Section => format!("--- {} ---", message),
            MessagePrefix::Validation => format!("[Validation] {}", message),
            MessagePrefix::Success => format!("[SUCCESS] {}", message),
            MessagePrefix::Warning => format!("[WARNING] {}", message),
            MessagePrefix::Error => format!("[ERROR] {}", message),
            MessagePrefix::Debug => format!("[DEBUG] {}", message),
            MessagePrefix::None => message.to_string(),
        }
    }
}
