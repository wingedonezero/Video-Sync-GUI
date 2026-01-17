//! Tool validation component shell.
//!
//! Rust shell counterpart to `python/vsg_core/pipeline_components/tool_validator.py`.
//! Delegates PATH validation to embedded Python.

use pyo3::prelude::*;

pub struct ToolValidator;

impl ToolValidator {
    pub fn validate_tools(py: Python<'_>) -> PyResult<PyObject> {
        let module = py.import("vsg_core.pipeline_components.tool_validator")?;
        let class = module.getattr("ToolValidator")?;
        let result = class.call_method0("validate_tools")?;
        Ok(result.into_py(py))
    }
}
