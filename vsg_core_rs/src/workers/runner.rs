//! Worker runner core.
//!
//! Rust-first worker runner that emits optional callbacks without depending on
//! Python UI modules.

use std::path::Path;

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyAnyMethods, PyDict, PyIterator, PyList};

use crate::pipeline::job_pipeline::JobPipeline;
use crate::workers::signals::WorkerSignals;

#[pyclass]
struct LogCallback {
    signals: Py<WorkerSignals>,
}

#[pymethods]
impl LogCallback {
    fn __call__(&self, py: Python<'_>, message: String) -> PyResult<()> {
        self.signals.borrow(py).emit_log(py, &message)
    }
}

#[pyclass]
struct ProgressCallback {
    signals: Py<WorkerSignals>,
}

#[pymethods]
impl ProgressCallback {
    fn __call__(&self, py: Python<'_>, value: f32) -> PyResult<()> {
        self.signals.borrow(py).emit_progress(py, value)
    }
}

#[pyclass]
pub struct JobWorker {
    config: Py<PyAny>,
    jobs: Py<PyAny>,
    and_merge: bool,
    output_dir: String,
    signals: Py<WorkerSignals>,
    cancelled: bool,
}

#[pymethods]
impl JobWorker {
    #[new]
    pub fn new(
        py: Python<'_>,
        config: PyObject,
        jobs: PyObject,
        and_merge: bool,
        output_dir: String,
    ) -> PyResult<Self> {
        let signals = Py::new(py, WorkerSignals::new())?;
        Ok(Self {
            config: config.into(),
            jobs: jobs.into(),
            and_merge,
            output_dir,
            signals,
            cancelled: false,
        })
    }

    pub fn cancel(&mut self) {
        self.cancelled = true;
    }

    #[getter]
    pub fn signals(&self, py: Python<'_>) -> PyObject {
        self.signals.clone_ref(py).into()
    }

    pub fn run(mut slf: PyRefMut<'_, Self>, py: Python<'_>) -> PyResult<()> {
        let log_callback: Py<PyAny> = Py::new(
            py,
            LogCallback {
                signals: slf.signals.clone_ref(py),
            },
        )?
        .into();
        let progress_callback: Py<PyAny> = Py::new(
            py,
            ProgressCallback {
                signals: slf.signals.clone_ref(py),
            },
        )?
        .into();

        let mut pipeline = JobPipeline::new(
            slf.config.clone_ref(py).into(),
            log_callback,
            progress_callback,
        );

        let jobs = slf.jobs.bind(py);
        let jobs_iter = PyIterator::from_object(jobs)?;
        let total_jobs = jobs.len()? as i32;

        let mut all_results: Vec<PyObject> = Vec::new();

        for (index, job_any) in jobs_iter.enumerate() {
            let job_data = job_any?;
            let job_index = (index + 1) as i32;

            if slf.cancelled {
                slf._safe_log(py, &format!(
                    "[WORKER] Cancelled by user, stopping at job {job_index}/{total_jobs}"
                ))?;
                break;
            }

            let sources_obj: Py<PyAny> = match job_data.get_item("sources") {
                Ok(value) if !value.is_none() => value.into(),
                _ => PyDict::new(py).into(),
            };
            let sources = sources_obj.bind(py);
            let source1_file = sources.get_item("Source 1")?;
            if source1_file.is_none() {
                slf._safe_log(
                    py,
                    &format!(
                        "[FATAL WORKER ERROR] Job {job_index} is missing 'Source 1'. Skipping."
                    ),
                )?;
                continue;
            }

            let source1_path: String = source1_file.extract()?;

            job_data.set_item("ref_path_for_batch_check", &source1_path)?;

            slf._safe_status(
                py,
                &format!(
                    "Processing {job_index}/{total_jobs}: {}",
                    Path::new(&source1_path)
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("source1")
                ),
            )?;

            let manual_layout = match job_data.get_item("manual_layout") {
                Ok(value) if !value.is_none() => Some(value.into()),
                _ => None,
            };
            let attachment_sources = match job_data.get_item("attachment_sources") {
                Ok(value) if !value.is_none() => Some(value.into()),
                _ => None,
            };

            let result = pipeline.run_job(
                py,
                sources_obj,
                slf.and_merge,
                slf.output_dir.clone(),
                manual_layout,
                attachment_sources,
            )?;

            let result_any = result.bind(py);
            result_any.set_item("job_data_for_batch_check", job_data)?;

            slf._safe_finished_job(py, result.clone_ref(py))?;
            all_results.push(result);
        }

        let all_results_list = PyList::new(py, all_results)?;
        slf._safe_finished_all(py, all_results_list.into())?;
        Ok(())
    }

    fn _safe_log(&self, py: Python<'_>, msg: &str) -> PyResult<()> {
        self.signals.borrow(py).emit_log(py, msg)
    }

    fn _safe_progress(&self, py: Python<'_>, value: f32) -> PyResult<()> {
        self.signals.borrow(py).emit_progress(py, value)
    }

    fn _safe_status(&self, py: Python<'_>, msg: &str) -> PyResult<()> {
        self.signals.borrow(py).emit_status(py, msg)
    }

    fn _safe_finished_job(&self, py: Python<'_>, result: PyObject) -> PyResult<()> {
        self.signals.borrow(py).emit_finished_job(py, result)
    }

    fn _safe_finished_all(&self, py: Python<'_>, results: PyObject) -> PyResult<()> {
        self.signals.borrow(py).emit_finished_all(py, results)
    }
}
