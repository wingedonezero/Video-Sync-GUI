//! Python Bridge for Video Sync GUI
//!
//! This crate handles:
//! 1. Bootstrapping an isolated Python environment (downloading python-build-standalone)
//! 2. Installing dependencies into an isolated venv
//! 3. Calling Python code via subprocess (avoiding build-time Python version conflicts)
//!
//! Note: We use subprocess instead of PyO3 to avoid requiring Python at compile time.
//! This is important because the system Python may be a version that PyO3 doesn't support.
//! Later, PyO3 can be added for performance-critical paths if needed.

mod bootstrap;
mod runtime;

pub use bootstrap::{
    ensure_python_runtime, BootstrapProgress, PythonBootstrapError, RuntimePaths,
};
pub use runtime::{
    AnalysisResult, JobProgress, JobResult, MediaInfo, PythonRuntime, PythonRuntimeError,
};
