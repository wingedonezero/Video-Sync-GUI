//! Job pipeline shell.
//!
//! Rust counterpart to `python/vsg_core/pipeline.py`.
//! The pipeline owns orchestration flow while embedding Python for unported
//! components, preserving logging and mkvmerge behaviors.

use std::path::{Path, PathBuf};

use pyo3::exceptions::{PyFileNotFoundError, PyImportError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};

use crate::pipeline_components::{
    log_manager::LogManager, output_writer::OutputWriter, result_auditor::ResultAuditor,
    sync_executor::SyncExecutor, sync_planner::SyncPlanner, tool_validator::ToolValidator,
};

#[pyclass]
pub struct JobPipeline {
    config: Py<PyAny>,
    gui_log_callback: Py<PyAny>,
    progress_callback: Py<PyAny>,
    tool_paths: Option<Py<PyAny>>,
}

impl JobPipeline {
    fn path_from_str(py: Python<'_>, path: &Path) -> PyResult<PyObject> {
        let pathlib = py.import("pathlib")?;
        let py_path = pathlib.getattr("Path")?;
        let path_obj = py_path.call1((path.to_string_lossy().to_string(),))?;
        Ok(path_obj.into_py(py))
    }
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

        let log_dir = Self::path_from_str(py, &output_dir)?;
        let (logger, handler, log_to_all) = LogManager::setup_job_log(
            py,
            job_name,
            log_dir.as_ref(py),
            self.gui_log_callback.as_ref(py),
        )?;

        let runner_module = py.import("vsg_core.io.runner")?;
        let runner = runner_module.getattr("CommandRunner")?.call1((
            self.config.clone_ref(py),
            log_to_all.clone_ref(py),
        ))?;

        let mut ctx_temp_dir: Option<PathBuf> = None;
        let manual_layout_missing = manual_layout.is_none();
        let manual_layout = manual_layout.unwrap_or_else(|| PyList::empty(py).into_py(py));
        let attachment_sources =
            attachment_sources.unwrap_or_else(|| PyList::empty(py).into_py(py));

        let result = (|| -> PyResult<PyObject> {
            let tool_paths = match ToolValidator::validate_tools(py) {
                Ok(paths) => paths,
                Err(err) => {
                    if err.is_instance(py, PyFileNotFoundError::type_object(py))? {
                        log_to_all.call1(py, (format!("[ERROR] {err}"),))?;
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
                        return Ok(response.into_py(py));
                    }
                    return Err(err);
                }
            };

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
            self.progress_callback
                .as_ref(py)
                .call1((0.0f32,))?;

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
                tool_paths.as_ref(py),
                log_to_all.as_ref(py),
                self.progress_callback.as_ref(py),
                sources.as_ref(py),
                and_merge,
                &output_dir_str,
                manual_layout.as_ref(py),
                attachment_sources.as_ref(py),
            )?;

            let ctx_temp: String = ctx.getattr(py, "temp_dir")?.str()?.extract()?;
            ctx_temp_dir = Some(PathBuf::from(ctx_temp));

            if !and_merge {
                log_to_all.call1(py, ("--- Analysis Complete (No Merge) ---",))?;
                self.progress_callback
                    .as_ref(py)
                    .call1((1.0f32,))?;

                let response = PyDict::new(py);
                response.set_item("status", "Analyzed")?;
                let delays = ctx.getattr(py, "delays")?;
                let delays_dict = if delays.is_none(py) {
                    PyDict::new(py).into_py(py)
                } else {
                    delays.getattr(py, "source_delays_ms")?.into_py(py)
                };
                response.set_item("delays", delays_dict)?;
                response.set_item(
                    "name",
                    Path::new(&source1_path)
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("source1"),
                )?;
                response.set_item("issues", 0)?;
                response.set_item("stepping_sources", ctx.getattr(py, "stepping_sources")?)?;
                response.set_item(
                    "stepping_detected_disabled",
                    ctx.getattr(py, "stepping_detected_disabled")?,
                )?;
                return Ok(response.into_py(py));
            }

            let tokens = ctx.getattr(py, "tokens")?;
            if tokens.is_none(py) {
                return Err(PyRuntimeError::new_err(
                    "Internal error: mkvmerge tokens were not generated.",
                ));
            }

            let output_dir_path = Self::path_from_str(py, &output_dir)?;
            let final_output_path = OutputWriter::prepare_output_path(
                py,
                output_dir_path.as_ref(py),
                Path::new(&source1_path)
                    .file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("source1"),
            )?;

            let final_output_name: String = final_output_path
                .as_ref(py)
                .getattr("name")?
                .extract()?;

            let temp_dir = ctx.getattr(py, "temp_dir")?;
            let mkvmerge_output_path = temp_dir.call_method1(
                py,
                "joinpath",
                (format!("temp_{final_output_name}"),),
            )?;
            let mkvmerge_output_path_str: String = mkvmerge_output_path.str()?.extract()?;

            tokens.call_method1(py, "insert", (0, mkvmerge_output_path_str))?;
            tokens.call_method1(py, "insert", (0, "--output"))?;

            let opts_path = OutputWriter::write_mkvmerge_options(
                py,
                tokens,
                temp_dir,
                self.config.as_ref(py),
                runner,
            )?;

            let merge_ok = SyncExecutor::execute_merge(
                py,
                &opts_path,
                tool_paths.as_ref(py),
                runner,
            )?;
            if !merge_ok {
                return Err(PyRuntimeError::new_err("mkvmerge execution failed."));
            }

            SyncExecutor::finalize_output(
                py,
                mkvmerge_output_path,
                final_output_path.as_ref(py),
                self.config.as_ref(py),
                tool_paths.as_ref(py),
                runner,
            )?;

            log_to_all.call1(
                py,
                (format!(
                    "[SUCCESS] Output file created: {}",
                    final_output_path.as_ref(py).str()?.extract::<String>()?
                ),),
            )?;

            let issues = ResultAuditor::audit_output(
                py,
                final_output_path.as_ref(py),
                ctx,
                runner,
                log_to_all.as_ref(py),
            )?;

            self.progress_callback
                .as_ref(py)
                .call1((1.0f32,))?;

            let response = PyDict::new(py);
            response.set_item("status", "Merged")?;
            response.set_item("output", final_output_path.as_ref(py).str()?.extract::<String>()?)?;
            let delays = ctx.getattr(py, "delays")?;
            let delays_dict = if delays.is_none(py) {
                PyDict::new(py).into_py(py)
            } else {
                delays.getattr(py, "source_delays_ms")?.into_py(py)
            };
            response.set_item("delays", delays_dict)?;
            response.set_item(
                "name",
                Path::new(&source1_path)
                    .file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("source1"),
            )?;
            response.set_item("issues", issues)?;
            response.set_item("stepping_sources", ctx.getattr(py, "stepping_sources")?)?;
            response.set_item(
                "stepping_detected_disabled",
                ctx.getattr(py, "stepping_detected_disabled")?,
            )?;
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
                response.set_item("stepping_detected_disabled", PyList::empty(py))?;
                response.into_py(py)
            }
        };

        if let Some(temp_dir) = ctx_temp_dir {
            let _ = std::fs::remove_dir_all(temp_dir);
        }

        match py.import("vsg_core.subtitles.frame_utils") {
            Ok(module) => {
                let _ = module.call_method0("clear_vfr_cache");
            }
            Err(err) => {
                if !err.is_instance(py, PyImportError::type_object(py))? {
                    err.restore(py);
                }
            }
        }

        log_to_all.call1(py, ("=== Job Finished ===",))?;
        LogManager::cleanup_log(py, logger.as_ref(py), handler.as_ref(py))?;

        Ok(final_result)
    }
}
