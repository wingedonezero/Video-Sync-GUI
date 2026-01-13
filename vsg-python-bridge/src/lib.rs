//! Python Bridge for Video Sync GUI
//!
//! This crate handles:
//! 1. Bootstrapping an isolated Python environment (downloading python-build-standalone)
//! 2. Installing dependencies into an isolated venv
//! 3. Providing PyO3 bindings to call the existing Python vsg_core code

mod bootstrap;
mod runtime;

pub use bootstrap::{ensure_python_runtime, PythonBootstrapError, RuntimePaths};
pub use runtime::{PythonRuntime, PythonRuntimeError};

/// Re-export pyo3 for consumers
pub use pyo3;
