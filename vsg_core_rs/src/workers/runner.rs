//! Worker runner shell.
//!
//! Rust shell counterpart to `python/vsg_qt/worker/runner.py`.
//! Uses the Rust JobPipeline while emitting Python UI signals.

use std::path::Path;

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};

use crate::pipeline::job_pipeline::JobPipeline;
use crate::workers::signals::WorkerSignals;

#[pyclass]
pub struct JobWorker {
    config: Py<PyAny>,
    jobs: Py<PyAny>,
    and_merge: bool,
    output_dir: String,
    signals: WorkerSignals,
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
        Ok(Self {
            config: config.into(),
            jobs: jobs.into(),
            and_merge,
            output_dir,
            signals: WorkerSignals::new(py)?,
            cancelled: false,
        })
    }

    pub fn cancel(&mut self) {
        self.cancelled = true;
    }

    #[getter]
    pub fn signals(&self, py: Python<'_>) -> PyObject {
        self.signals.as_py(py).into_py(py)
    }

    pub fn run(mut slf: PyRefMut<'_, Self>, py: Python<'_>) -> PyResult<()> {
        let worker_obj = slf.to_object(py);
        let worker_ref = worker_obj.as_ref(py);
        let log_callback = worker_ref.getattr("_safe_log")?.into_py(py);
        let progress_callback = worker_ref.getattr("_safe_progress")?.into_py(py);

        let mut pipeline = JobPipeline::new(
            slf.config.clone_ref(py).into_py(py),
            log_callback,
            progress_callback,
        );

        let jobs_iter = slf.jobs.as_ref(py).iter()?;
        let total_jobs = slf.jobs.as_ref(py).len()? as i32;

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

            let sources_obj = job_data
                .get_item("sources")?
                .map(|value| value.into_py(py))
                .unwrap_or_else(|| PyDict::new(py).into_py(py));
            let sources = sources_obj.as_ref(py);
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

            let source1_path: String = source1_file.unwrap().extract()?;

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

            let result = pipeline.run_job(
                py,
                sources_obj,
                slf.and_merge,
                slf.output_dir.clone(),
                job_data.get_item("manual_layout").ok().flatten().map(|v| v.into_py(py)),
                job_data
                    .get_item("attachment_sources")
                    .ok()
                    .flatten()
                    .map(|v| v.into_py(py)),
            )?;

            let result_any = result.as_ref(py);
            result_any.set_item("job_data_for_batch_check", job_data)?;

            slf._safe_finished_job(py, result_any)?;
            all_results.push(result);
        }

        let all_results_list = PyList::new(py, all_results);
        slf._safe_finished_all(py, all_results_list)?;
        Ok(())
    }

    fn _safe_log(&self, py: Python<'_>, msg: &str) -> PyResult<()> {
        self.signals.emit_log(py, msg)
    }

    fn _safe_progress(&self, py: Python<'_>, value: f32) -> PyResult<()> {
        self.signals.emit_progress(py, value)
    }

    fn _safe_status(&self, py: Python<'_>, msg: &str) -> PyResult<()> {
        self.signals.emit_status(py, msg)
    }

    fn _safe_finished_job(&self, py: Python<'_>, result: &PyAny) -> PyResult<()> {
        self.signals.emit_finished_job(py, result)
    }

    fn _safe_finished_all(&self, py: Python<'_>, results: &PyAny) -> PyResult<()> {
        self.signals.emit_finished_all(py, results)
    }
}
