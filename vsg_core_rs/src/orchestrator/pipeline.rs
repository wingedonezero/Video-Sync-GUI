//! Orchestrator pipeline wiring.
//!
//! Rust shell counterpart to `python/vsg_core/orchestrator/pipeline.py`.
//! The orchestration flow is implemented in Rust while step execution and
//! validation are delegated to embedded Python until ported.

use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyList};

use crate::orchestrator::steps::{
    AnalysisStep, AudioCorrectionStep, AttachmentsStep, ChaptersStep, Context, ExtractStep,
    MuxStep, SubtitlesStep,
};
use crate::orchestrator::validation::StepValidator;

#[pyclass]
pub struct Orchestrator;

#[pymethods]
impl Orchestrator {
    #[new]
    pub fn new() -> Self {
        Self
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        settings_dict,
        tool_paths,
        log,
        progress,
        sources,
        and_merge,
        output_dir,
        manual_layout=None,
        attachment_sources=None
    ))]
    pub fn run(
        &self,
        py: Python<'_>,
        settings_dict: PyObject,
        tool_paths: PyObject,
        log: PyObject,
        progress: PyObject,
        sources: PyObject,
        and_merge: bool,
        output_dir: String,
        manual_layout: Option<PyObject>,
        attachment_sources: Option<PyObject>,
    ) -> PyResult<PyObject> {
        let settings_dict_any = settings_dict.as_ref(py);
        let sources_any = sources.as_ref(py);

        let source1_file = sources_any
            .get_item("Source 1")?
            .ok_or_else(|| PyValueError::new_err("Job is missing Source 1 (Reference)."))?;
        let source1_path: String = source1_file.extract()?;

        let settings_module = py.import("vsg_core.models.settings")?;
        let app_settings = settings_module
            .getattr("AppSettings")?
            .call_method1("from_config", (settings_dict.clone_ref(py),))?;

        let base_temp = match settings_dict_any.get_item("temp_root")? {
            Some(value) => PathBuf::from(value.extract::<String>()?),
            None => std::env::current_dir()?.join("temp_work"),
        };

        let source1_stem = Path::new(&source1_path)
            .file_stem()
            .and_then(|stem| stem.to_str())
            .unwrap_or("source1");
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        let job_temp = base_temp.join(format!("orch_{source1_stem}_{timestamp}"));
        std::fs::create_dir_all(&job_temp)?;

        let pathlib = py.import("pathlib")?;
        let py_path = pathlib.getattr("Path")?;
        let temp_dir_py = py_path.call1((job_temp.to_string_lossy().to_string(),))?;

        let runner_module = py.import("vsg_core.io.runner")?;
        let runner = runner_module
            .getattr("CommandRunner")?
            .call1((settings_dict.clone_ref(py), log.clone_ref(py)))?;

        let manual_layout = manual_layout.unwrap_or_else(|| PyList::empty(py).into_py(py));
        let attachment_sources =
            attachment_sources.unwrap_or_else(|| PyList::empty(py).into_py(py));

        let ctx = Context::new(
            py,
            app_settings,
            settings_dict.as_ref(py),
            tool_paths.as_ref(py),
            log.as_ref(py),
            progress.as_ref(py),
            &output_dir,
            temp_dir_py,
            sources.as_ref(py),
            and_merge,
            manual_layout.as_ref(py),
            attachment_sources.as_ref(py),
        )?;

        let validation_error = StepValidator::pipeline_validation_error(py)?;

        log.as_ref(py).call1(("--- Analysis Phase ---",))?;
        progress.as_ref(py).call1((0.10f32,))?;
        let mut ctx = match AnalysisStep::run(py, ctx.as_py(py), runner.as_ref(py)) {
            Ok(ctx) => ctx,
            Err(err) => {
                if err.is_instance(py, validation_error.as_ref(py))? {
                    log.as_ref(py)
                        .call1((format!("[FATAL] Analysis validation failed: {err}"),))?;
                    return Err(err);
                }
                log.as_ref(py)
                    .call1((format!("[FATAL] Analysis phase failed: {err}"),))?;
                return Err(PyRuntimeError::new_err(format!(
                    "Analysis phase failed: {err}"
                )));
            }
        };

        if let Err(err) = StepValidator::validate_analysis(py, ctx.as_ref(py)) {
            log.as_ref(py)
                .call1((format!("[FATAL] Analysis validation failed: {err}"),))?;
            return Err(err);
        }
        log.as_ref(py)
            .call1(("[Validation] Analysis phase validated successfully.",))?;

        if !and_merge {
            log.as_ref(py)
                .call1(("--- Analysis Complete (No Merge) ---",))?;
            progress.as_ref(py).call1((1.0f32,))?;
            return Ok(ctx);
        }

        log.as_ref(py).call1(("--- Extraction Phase ---",))?;
        progress.as_ref(py).call1((0.40f32,))?;
        ctx = match ExtractStep::run(py, ctx.as_ref(py), runner.as_ref(py)) {
            Ok(ctx) => ctx,
            Err(err) => {
                if err.is_instance(py, validation_error.as_ref(py))? {
                    log.as_ref(py)
                        .call1((format!("[FATAL] Extraction validation failed: {err}"),))?;
                    return Err(err);
                }
                log.as_ref(py)
                    .call1((format!("[FATAL] Extraction phase failed: {err}"),))?;
                return Err(PyRuntimeError::new_err(format!(
                    "Extraction phase failed: {err}"
                )));
            }
        };

        if let Err(err) = StepValidator::validate_extraction(py, ctx.as_ref(py)) {
            log.as_ref(py)
                .call1((format!("[FATAL] Extraction validation failed: {err}"),))?;
            return Err(err);
        }
        log.as_ref(py)
            .call1(("[Validation] Extraction phase validated successfully.",))?;

        let settings_dict_py = ctx.as_ref(py).getattr("settings_dict")?;
        let segmented_enabled = settings_dict_py
            .get_item("segmented_enabled")?
            .and_then(|value| value.extract::<bool>().ok())
            .unwrap_or(false);

        let segment_flags = ctx.as_ref(py).getattr("segment_flags")?;
        let pal_drift_flags = ctx.as_ref(py).getattr("pal_drift_flags")?;
        let linear_drift_flags = ctx.as_ref(py).getattr("linear_drift_flags")?;

        let has_audio_correction_flags = segment_flags.is_true()?
            || pal_drift_flags.is_true()?
            || linear_drift_flags.is_true()?;

        if segmented_enabled && has_audio_correction_flags {
            log.as_ref(py)
                .call1(("--- Advanced Audio Correction Phase ---",))?;
            progress.as_ref(py).call1((0.50f32,))?;
            ctx = match AudioCorrectionStep::run(py, ctx.as_ref(py), runner.as_ref(py)) {
                Ok(ctx) => ctx,
                Err(err) => {
                    if err.is_instance(py, validation_error.as_ref(py))? {
                        log.as_ref(py).call1((format!(
                            "[FATAL] Audio correction validation failed: {err}"
                        ),))?;
                        return Err(err);
                    }
                    log.as_ref(py)
                        .call1((format!("[FATAL] Audio correction phase failed: {err}"),))?;
                    return Err(PyRuntimeError::new_err(format!(
                        "Audio correction phase failed: {err}"
                    )));
                }
            };

            if let Err(err) = StepValidator::validate_correction(py, ctx.as_ref(py)) {
                log.as_ref(py)
                    .call1((format!("[FATAL] Audio correction validation failed: {err}"),))?;
                return Err(err);
            }
            log.as_ref(py).call1((
                "[Validation] Audio correction phase validated successfully.",
            ))?;
        }

        log.as_ref(py)
            .call1(("--- Subtitle Processing Phase ---",))?;
        ctx = match SubtitlesStep::run(py, ctx.as_ref(py), runner.as_ref(py)) {
            Ok(ctx) => ctx,
            Err(err) => {
                if err.is_instance(py, validation_error.as_ref(py))? {
                    log.as_ref(py).call1((format!(
                        "[FATAL] Subtitle processing validation failed: {err}"
                    ),))?;
                    return Err(err);
                }
                log.as_ref(py)
                    .call1((format!("[FATAL] Subtitle processing phase failed: {err}"),))?;
                return Err(PyRuntimeError::new_err(format!(
                    "Subtitle processing phase failed: {err}"
                )));
            }
        };

        if let Err(err) = StepValidator::validate_subtitles(py, ctx.as_ref(py)) {
            log.as_ref(py).call1((format!(
                "[FATAL] Subtitle processing validation failed: {err}"
            ),))?;
            return Err(err);
        }
        log.as_ref(py).call1((
            "[Validation] Subtitle processing phase validated successfully.",
        ))?;

        log.as_ref(py).call1(("--- Chapters Phase ---",))?;
        if let Err(err) = ChaptersStep::run(py, ctx.as_ref(py), runner.as_ref(py)) {
            log.as_ref(py)
                .call1((format!("[WARNING] Chapters phase had issues (non-fatal): {err}"),))?;
        } else {
            log.as_ref(py)
                .call1(("[Validation] Chapters phase completed.",))?;
        }

        log.as_ref(py).call1(("--- Attachments Phase ---",))?;
        progress.as_ref(py).call1((0.60f32,))?;
        if let Err(err) = AttachmentsStep::run(py, ctx.as_ref(py), runner.as_ref(py)) {
            log.as_ref(py)
                .call1((format!("[WARNING] Attachments phase had issues (non-fatal): {err}"),))?;
        } else {
            log.as_ref(py)
                .call1(("[Validation] Attachments phase completed.",))?;
        }

        log.as_ref(py).call1(("--- Merge Planning Phase ---",))?;
        progress.as_ref(py).call1((0.75f32,))?;
        ctx = match MuxStep::run(py, ctx.as_ref(py), runner.as_ref(py)) {
            Ok(ctx) => ctx,
            Err(err) => {
                if err.is_instance(py, validation_error.as_ref(py))? {
                    log.as_ref(py).call1((format!(
                        "[FATAL] Merge planning validation failed: {err}"
                    ),))?;
                    return Err(err);
                }
                log.as_ref(py)
                    .call1((format!("[FATAL] Merge planning phase failed: {err}"),))?;
                return Err(PyRuntimeError::new_err(format!(
                    "Merge planning phase failed: {err}"
                )));
            }
        };

        if let Err(err) = StepValidator::validate_mux(py, ctx.as_ref(py)) {
            log.as_ref(py)
                .call1((format!("[FATAL] Merge planning validation failed: {err}"),))?;
            return Err(err);
        }
        log.as_ref(py)
            .call1(("[Validation] Merge planning phase validated successfully.",))?;

        progress.as_ref(py).call1((0.80f32,))?;
        Ok(ctx)
    }
}
