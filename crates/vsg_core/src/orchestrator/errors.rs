//! Error types for the orchestrator pipeline.
//!
//! Errors carry context that chains through layers:
//! Job → Step → Operation → Detail

use std::io;

use thiserror::Error;

/// Top-level pipeline error with job context.
#[derive(Error, Debug)]
pub enum PipelineError {
    /// A step failed during execution.
    #[error("Job '{job_name}' failed at step '{step_name}': {source}")]
    StepFailed {
        job_name: String,
        step_name: String,
        #[source]
        source: StepError,
    },

    /// Input validation failed before pipeline started.
    #[error("Job '{job_name}' failed validation: {message}")]
    ValidationFailed { job_name: String, message: String },

    /// Pipeline was cancelled.
    #[error("Job '{job_name}' was cancelled")]
    Cancelled { job_name: String },

    /// Failed to set up job (create directories, etc.).
    #[error("Job '{job_name}' setup failed: {message}")]
    SetupFailed { job_name: String, message: String },
}

impl PipelineError {
    /// Create a step failed error.
    pub fn step_failed(
        job_name: impl Into<String>,
        step_name: impl Into<String>,
        source: StepError,
    ) -> Self {
        Self::StepFailed {
            job_name: job_name.into(),
            step_name: step_name.into(),
            source,
        }
    }

    /// Create a validation failed error.
    pub fn validation_failed(job_name: impl Into<String>, message: impl Into<String>) -> Self {
        Self::ValidationFailed {
            job_name: job_name.into(),
            message: message.into(),
        }
    }

    /// Create a setup failed error.
    pub fn setup_failed(job_name: impl Into<String>, message: impl Into<String>) -> Self {
        Self::SetupFailed {
            job_name: job_name.into(),
            message: message.into(),
        }
    }

    /// Create a cancelled error.
    pub fn cancelled(job_name: impl Into<String>) -> Self {
        Self::Cancelled {
            job_name: job_name.into(),
        }
    }
}

/// Error from a pipeline step with operation context.
#[derive(Error, Debug)]
pub enum StepError {
    /// Input validation failed.
    #[error("Input validation failed: {0}")]
    InvalidInput(String),

    /// Output validation failed.
    #[error("Output validation failed: {0}")]
    InvalidOutput(String),

    /// An external command failed.
    #[error("{tool} failed with exit code {exit_code}: {message}")]
    CommandFailed {
        tool: String,
        exit_code: i32,
        message: String,
    },

    /// File I/O error.
    #[error("I/O error in {operation}: {source}")]
    IoError {
        operation: String,
        #[source]
        source: io::Error,
    },

    /// A required file was not found.
    #[error("Required file not found: {path}")]
    FileNotFound { path: String },

    /// Parsing error (e.g., JSON, timestamps).
    #[error("Failed to parse {what}: {message}")]
    ParseError { what: String, message: String },

    /// A precondition was not met.
    #[error("Precondition not met: {0}")]
    PreconditionFailed(String),

    /// Generic step error with message.
    #[error("{0}")]
    Other(String),
}

impl StepError {
    /// Create an invalid input error.
    pub fn invalid_input(message: impl Into<String>) -> Self {
        Self::InvalidInput(message.into())
    }

    /// Create an invalid output error.
    pub fn invalid_output(message: impl Into<String>) -> Self {
        Self::InvalidOutput(message.into())
    }

    /// Create a command failed error.
    pub fn command_failed(
        tool: impl Into<String>,
        exit_code: i32,
        message: impl Into<String>,
    ) -> Self {
        Self::CommandFailed {
            tool: tool.into(),
            exit_code,
            message: message.into(),
        }
    }

    /// Create an I/O error with context.
    pub fn io_error(operation: impl Into<String>, source: io::Error) -> Self {
        Self::IoError {
            operation: operation.into(),
            source,
        }
    }

    /// Create a file not found error.
    pub fn file_not_found(path: impl Into<String>) -> Self {
        Self::FileNotFound { path: path.into() }
    }

    /// Create a parse error.
    pub fn parse_error(what: impl Into<String>, message: impl Into<String>) -> Self {
        Self::ParseError {
            what: what.into(),
            message: message.into(),
        }
    }

    /// Create a precondition failed error.
    pub fn precondition_failed(message: impl Into<String>) -> Self {
        Self::PreconditionFailed(message.into())
    }

    /// Create a generic error.
    pub fn other(message: impl Into<String>) -> Self {
        Self::Other(message.into())
    }
}

/// Result type for step operations.
pub type StepResult<T> = Result<T, StepError>;

/// Result type for pipeline operations.
pub type PipelineResult<T> = Result<T, PipelineError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn step_error_displays_context() {
        let err = StepError::command_failed("mkvmerge", 2, "Invalid track ID");
        let msg = err.to_string();
        assert!(msg.contains("mkvmerge"));
        assert!(msg.contains("exit code 2"));
        assert!(msg.contains("Invalid track ID"));
    }

    #[test]
    fn pipeline_error_chains_context() {
        let step_err = StepError::file_not_found("/path/to/audio.flac");
        let pipeline_err = PipelineError::step_failed("movie_xyz", "Extract", step_err);

        let msg = pipeline_err.to_string();
        assert!(msg.contains("movie_xyz"));
        assert!(msg.contains("Extract"));
    }
}
