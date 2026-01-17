//! Job pipeline core.
//!
//! Rust-first counterpart to `python/vsg_core/pipeline.py`.
//! This owns orchestration flow while leaving hooks for optional Python-backed
//! dependency calls when required.

use std::path::{Path, PathBuf};

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};

use crate::pipeline_components::{
    log_manager::LogManager, sync_planner::SyncPlanner, tool_validator::ToolValidator,
};

#[pyclass]
pub struct JobPipeline {
    config: Py<PyAny>,
    gui_log_callback: Py<PyAny>,
    progress_callback: Py<PyAny>,
    tool_paths: Option<Py<PyAny>>,
}

#[pymethods]
impl JobPipeline {
    #[new]
    pub fn new(config: PyObject, log_callback: PyObject, progress_callback: PyObject) -> Self {
        Self {
            config: config.into(),
            gui_log_callback: log_callback.into(),
            progress_callback: progress_callback.into(),
            tool_paths: None,
        }
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        sources,
        and_merge,
        output_dir_str,
        manual_layout=None,
        attachment_sources=None
    ))]
    pub fn run_job(
        &mut self,
        py: Python<'_>,
        sources: PyObject,
        and_merge: bool,
        output_dir_str: String,
        manual_layout: Option<PyObject>,
        attachment_sources: Option<PyObject>,
    ) -> PyResult<PyObject> {
        let sources_any = sources.as_ref(py);
        let source1_file = sources_any
            .get_item("Source 1")?
            .ok_or_else(|| PyValueError::new_err("Job is missing Source 1 (Reference)."))?;
        let source1_path: String = source1_file.extract()?;

        let output_dir = PathBuf::from(&output_dir_str);
        std::fs::create_dir_all(&output_dir)?;

        let job_name = Path::new(&source1_path)
            .file_stem()
            .and_then(|stem| stem.to_str())
            .unwrap_or("job");

        let log_dir = PyList::empty(py);
        let (logger, handler, log_to_all) = LogManager::setup_job_log(
            py,
            job_name,
            log_dir,
            self.gui_log_callback.as_ref(py),
        )?;

        let mut ctx_temp_dir: Option<PathBuf> = None;
        let manual_layout_missing = manual_layout.is_none();
        let manual_layout = manual_layout.unwrap_or_else(|| PyList::empty(py).into_py(py));
        let attachment_sources =
            attachment_sources.unwrap_or_else(|| PyList::empty(py).into_py(py));

        let result = (|| -> PyResult<PyObject> {
            let tool_paths = ToolValidator::validate_tools(py)?;
            self.tool_paths = Some(tool_paths.into_py(py));

            log_to_all.call1(
                py,
                (format!(
                    "=== Starting Job: {} ===",
                    Path::new(&source1_path)
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("source1")
                ),),
            )?;
            self.progress_callback.as_ref(py).call1((0.0f32,))?;

            if and_merge && manual_layout_missing {
                let err_msg = "Manual layout required for merge.";
                log_to_all.call1(py, (format!("[ERROR] {err_msg}"),))?;
                let response = PyDict::new(py);
                response.set_item("status", "Failed")?;
                response.set_item("error", err_msg)?;
                response.set_item(
                    "name",
                    Path::new(&source1_path)
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("source1"),
                )?;
                return Ok(response.into_py(py));
            }

            let ctx = SyncPlanner::plan_sync(
                py,
                self.config.as_ref(py),
                self.tool_paths.as_ref().unwrap().as_ref(py),
                log_to_all.as_ref(py),
                self.progress_callback.as_ref(py),
                sources.as_ref(py),
                and_merge,
                &output_dir_str,
                manual_layout.as_ref(py),
                attachment_sources.as_ref(py),
            )?;

            ctx_temp_dir = Some(ctx.temp_dir.clone());

            if !and_merge {
                log_to_all.call1(py, ("--- Analysis Complete (No Merge) ---",))?;
                self.progress_callback.as_ref(py).call1((1.0f32,))?;

                let response = PyDict::new(py);
                response.set_item("status", "Analyzed")?;
                let delays_dict = PyDict::new(py);
                for (key, value) in ctx.delays.iter() {
                    delays_dict.set_item(key, *value)?;
                }
                response.set_item("delays", delays_dict)?;
                response.set_item(
                    "name",
                    Path::new(&source1_path)
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("source1"),
                )?;
                response.set_item("issues", 0)?;
                response.set_item("stepping_sources", PyList::new(py, &ctx.stepping_sources))?;
                response.set_item("stepping_detected_disabled", ctx.stepping_detected_disabled)?;
                return Ok(response.into_py(py));
            }

            log_to_all.call1(
                py,
                ("[ERROR] Merge pipeline not implemented in Rust core yet.",),
            )?;

            let response = PyDict::new(py);
            response.set_item("status", "Failed")?;
            response.set_item("error", "Merge pipeline not implemented yet.")?;
            response.set_item(
                "name",
                Path::new(&source1_path)
                    .file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("source1"),
            )?;
            response.set_item("issues", 0)?;
            response.set_item("stepping_sources", PyList::new(py, &ctx.stepping_sources))?;
            response.set_item("stepping_detected_disabled", ctx.stepping_detected_disabled)?;
            Ok(response.into_py(py))
        })();

        let final_result = match result {
            Ok(value) => value,
            Err(err) => {
                log_to_all
                    .call1(py, (format!("[FATAL ERROR] Job failed: {err}"),))
                    .ok();
                let response = PyDict::new(py);
                response.set_item("status", "Failed")?;
                response.set_item("error", err.to_string())?;
                response.set_item(
                    "name",
                    Path::new(&source1_path)
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("source1"),
                )?;
                response.set_item("issues", 0)?;
                response.set_item("stepping_sources", PyList::empty(py))?;
                response.set_item("stepping_detected_disabled", false)?;
                response.into_py(py)
            }
        };

        if let Some(temp_dir) = ctx_temp_dir {
            let _ = std::fs::remove_dir_all(temp_dir);
        }

        log_to_all.call1(py, ("=== Job Finished ===",))?;
        LogManager::cleanup_log(py, logger.as_ref(py), handler.as_ref(py))?;

        Ok(final_result)
    }
}
