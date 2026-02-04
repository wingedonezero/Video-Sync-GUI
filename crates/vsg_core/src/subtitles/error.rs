//! Subtitle error types.

use std::path::PathBuf;

/// Errors that can occur during subtitle operations.
#[derive(Debug, thiserror::Error)]
pub enum SubtitleError {
    /// Failed to read subtitle file.
    #[error("Failed to read file '{path}': {source}")]
    ReadError {
        path: PathBuf,
        source: std::io::Error,
    },

    /// Failed to write subtitle file.
    #[error("Failed to write file '{path}': {source}")]
    WriteError {
        path: PathBuf,
        source: std::io::Error,
    },

    /// Unknown or unsupported subtitle format.
    #[error("Unknown subtitle format for file '{0}'")]
    UnknownFormat(PathBuf),

    /// Parse error.
    #[error("Parse error: {0}")]
    ParseError(#[from] ParseError),

    /// Sync error.
    #[error("Sync error: {0}")]
    SyncError(#[from] SyncError),

    /// Frame utilities error.
    #[error("Frame error: {0}")]
    FrameError(#[from] FrameError),
}

/// Errors that can occur during subtitle parsing.
#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    /// Invalid or malformed time format.
    #[error("Invalid time format at line {line}: '{value}'")]
    InvalidTime { line: usize, value: String },

    /// Missing required section.
    #[error("Missing required section: {0}")]
    MissingSection(String),

    /// Invalid section format.
    #[error("Invalid section format at line {line}: {message}")]
    InvalidSection { line: usize, message: String },

    /// Invalid style definition.
    #[error("Invalid style at line {line}: {message}")]
    InvalidStyle { line: usize, message: String },

    /// Invalid event/dialogue line.
    #[error("Invalid event at line {line}: {message}")]
    InvalidEvent { line: usize, message: String },

    /// Invalid color format.
    #[error("Invalid color format: '{0}'")]
    InvalidColor(String),

    /// Encoding error.
    #[error("Encoding error: {0}")]
    EncodingError(String),

    /// Generic parse error.
    #[error("Parse error at line {line}: {message}")]
    Generic { line: usize, message: String },
}

/// Errors that can occur during sync operations.
#[derive(Debug, thiserror::Error)]
pub enum SyncError {
    /// Missing required video file.
    #[error("Missing video file: {0}")]
    MissingVideo(String),

    /// Frame matching failed.
    #[error("Frame matching failed: {0}")]
    FrameMatchFailed(String),

    /// No events to sync.
    #[error("No subtitle events to sync")]
    NoEvents,

    /// Invalid sync configuration.
    #[error("Invalid sync config: {0}")]
    InvalidConfig(String),

    /// Sync mode not available.
    #[error("Sync mode '{0}' is not available")]
    ModeNotAvailable(String),
}

/// Errors that can occur during frame operations.
#[derive(Debug, thiserror::Error)]
pub enum FrameError {
    /// Failed to open video file.
    #[error("Failed to open video '{path}': {message}")]
    OpenFailed { path: PathBuf, message: String },

    /// Failed to extract frame.
    #[error("Failed to extract frame at {time_ms}ms: {message}")]
    ExtractionFailed { time_ms: f64, message: String },

    /// FFmpeg not available.
    #[error("FFmpeg not found or not executable")]
    FfmpegNotFound,

    /// Invalid frame data.
    #[error("Invalid frame data: {0}")]
    InvalidData(String),

    /// Video properties detection failed.
    #[error("Failed to detect video properties: {0}")]
    PropertiesFailed(String),
}

impl SubtitleError {
    /// Create a read error.
    pub fn read(path: impl Into<PathBuf>, source: std::io::Error) -> Self {
        Self::ReadError {
            path: path.into(),
            source,
        }
    }

    /// Create a write error.
    pub fn write(path: impl Into<PathBuf>, source: std::io::Error) -> Self {
        Self::WriteError {
            path: path.into(),
            source,
        }
    }
}

impl ParseError {
    /// Create a generic parse error.
    pub fn at_line(line: usize, message: impl Into<String>) -> Self {
        Self::Generic {
            line,
            message: message.into(),
        }
    }

    /// Create an invalid time error.
    pub fn invalid_time(line: usize, value: impl Into<String>) -> Self {
        Self::InvalidTime {
            line,
            value: value.into(),
        }
    }

    /// Create an invalid event error.
    pub fn invalid_event(line: usize, message: impl Into<String>) -> Self {
        Self::InvalidEvent {
            line,
            message: message.into(),
        }
    }

    /// Create an invalid style error.
    pub fn invalid_style(line: usize, message: impl Into<String>) -> Self {
        Self::InvalidStyle {
            line,
            message: message.into(),
        }
    }
}
