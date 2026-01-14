//! Result type definitions

use thiserror::Error;

/// Core error types
#[derive(Error, Debug)]
pub enum CoreError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("Command execution failed: {0}")]
    CommandFailed(String),

    #[error("Tool not found: {0}")]
    ToolNotFound(String),

    #[error("Parse error: {0}")]
    ParseError(String),

    #[error("Invalid configuration: {0}")]
    ConfigError(String),

    #[error("Analysis failed: {0}")]
    AnalysisError(String),

    #[error("Extraction failed: {0}")]
    ExtractionError(String),

    #[error("Merge failed: {0}")]
    MergeError(String),

    #[error("Subtitle processing failed: {0}")]
    SubtitleError(String),

    #[error("Chapter processing failed: {0}")]
    ChapterError(String),

    #[error("Invalid track: {0}")]
    InvalidTrack(String),

    #[error("File not found: {0}")]
    FileNotFound(String),

    #[error("Other error: {0}")]
    Other(String),
}

// Implement From<String> for CoreError to allow using ? with String errors
impl From<String> for CoreError {
    fn from(s: String) -> Self {
        CoreError::Other(s)
    }
}

impl From<&str> for CoreError {
    fn from(s: &str) -> Self {
        CoreError::Other(s.to_string())
    }
}

// Implement From<quick_xml::Error> for CoreError
impl From<quick_xml::Error> for CoreError {
    fn from(e: quick_xml::Error) -> Self {
        CoreError::ParseError(format!("XML error: {}", e))
    }
}

/// Core result type
pub type CoreResult<T> = Result<T, CoreError>;

/// Pipeline error types
#[derive(Error, Debug)]
pub enum PipelineError {
    #[error("Pipeline step failed: {0}")]
    StepFailed(String),

    #[error("Validation failed: {0}")]
    ValidationFailed(String),

    #[error("Context error: {0}")]
    ContextError(String),

    #[error("Core error: {0}")]
    Core(#[from] CoreError),
}

/// Pipeline result type
pub type PipelineResult<T> = Result<T, PipelineError>;
