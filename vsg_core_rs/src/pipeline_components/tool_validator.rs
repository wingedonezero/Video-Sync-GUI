//! Tool validation component core.
//!
//! Rust-first placeholder that will be populated with native tool checks.

use std::env;
use std::path::PathBuf;

use pyo3::exceptions::PyFileNotFoundError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub struct ToolValidator;

impl ToolValidator {
    pub fn validate_tools(py: Python<'_>) -> PyResult<PyObject> {
        let mut tool_paths = PyDict::new(py);
        let required = ["ffmpeg", "ffprobe", "mkvmerge", "mkvextract", "mkvpropedit"];
        let optional = ["videodiff"];

        for tool in required {
            let path = find_in_path(tool);
            if path.is_none() {
                return Err(PyFileNotFoundError::new_err(format!(
                    "Required tool '{tool}' not found in PATH."
                )));
            }
            tool_paths.set_item(tool, path.unwrap().to_string_lossy().to_string())?;
        }

        for tool in optional {
            let path = find_in_path(tool);
            tool_paths.set_item(
                tool,
                path.map(|p| p.to_string_lossy().to_string()),
            )?;
        }

        Ok(tool_paths.into())
    }
}

fn find_in_path(tool: &str) -> Option<PathBuf> {
    let path_var = env::var_os("PATH")?;
    for dir in env::split_paths(&path_var) {
        let full = dir.join(tool);
        if full.is_file() {
            return Some(full);
        }
        #[cfg(windows)]
        {
            let exe = dir.join(format!("{tool}.exe"));
            if exe.is_file() {
                return Some(exe);
            }
        }
    }
    None
}
