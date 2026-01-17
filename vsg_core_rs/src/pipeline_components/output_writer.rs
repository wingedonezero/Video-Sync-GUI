//! Output writer component shell.
//!
//! Rust shell counterpart to `python/vsg_core/pipeline_components/output_writer.py`.
//! Delegates mkvmerge options generation to embedded Python.

use pyo3::prelude::*;

pub struct OutputWriter;

impl OutputWriter {
    pub fn write_mkvmerge_options(
        py: Python<'_>,
        tokens: &PyAny,
        temp_dir: &PyAny,
        config: &PyAny,
        runner: &PyAny,
    ) -> PyResult<String> {
        let module = py.import("vsg_core.pipeline_components.output_writer")?;
        let class = module.getattr("OutputWriter")?;
        class
            .call_method1("write_mkvmerge_options", (tokens, temp_dir, config, runner))?
            .extract::<String>()
    }

    pub fn prepare_output_path(
        py: Python<'_>,
        output_dir: &PyAny,
        source1_filename: &str,
    ) -> PyResult<PyObject> {
        let module = py.import("vsg_core.pipeline_components.output_writer")?;
        let class = module.getattr("OutputWriter")?;
        let result = class.call_method1("prepare_output_path", (output_dir, source1_filename))?;
        Ok(result.into_py(py))
    }
}
