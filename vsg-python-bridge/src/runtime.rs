//! Python runtime wrapper using PyO3
//!
//! Provides safe interface to call existing vsg_core Python code.

use std::path::{Path, PathBuf};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule};
use thiserror::Error;
use tracing::{info, debug, error};

use crate::RuntimePaths;

#[derive(Error, Debug)]
pub enum PythonRuntimeError {
    #[error("Python not initialized")]
    NotInitialized,

    #[error("Python error: {0}")]
    Python(#[from] PyErr),

    #[error("Failed to import module {module}: {error}")]
    ImportError { module: String, error: String },

    #[error("Failed to call function {function}: {error}")]
    CallError { function: String, error: String },

    #[error("Invalid configuration: {0}")]
    ConfigError(String),
}

/// Wrapper around the Python runtime and vsg_core modules
pub struct PythonRuntime {
    paths: RuntimePaths,
    vsg_core_path: PathBuf,
    initialized: bool,
}

impl PythonRuntime {
    /// Create a new Python runtime wrapper
    ///
    /// # Arguments
    /// * `paths` - The runtime paths from bootstrap
    /// * `vsg_core_path` - Path to the vsg_core Python package directory
    pub fn new(paths: RuntimePaths, vsg_core_path: PathBuf) -> Self {
        Self {
            paths,
            vsg_core_path,
            initialized: false,
        }
    }

    /// Initialize the Python interpreter with the correct paths
    pub fn initialize(&mut self) -> Result<(), PythonRuntimeError> {
        if self.initialized {
            return Ok(());
        }

        info!("Initializing Python runtime...");

        // Set PYTHONHOME to our isolated Python
        std::env::set_var("PYTHONHOME", &self.paths.python_dir);

        // Set up the Python path to include:
        // 1. The venv site-packages
        // 2. The vsg_core parent directory (so `import vsg_core` works)
        let site_packages = self.paths.venv_dir.join("lib");

        // Find the actual site-packages directory (it includes Python version)
        let site_packages = find_site_packages(&site_packages)
            .unwrap_or_else(|| site_packages.join("python3.13").join("site-packages"));

        let vsg_parent = self
            .vsg_core_path
            .parent()
            .unwrap_or(&self.vsg_core_path)
            .to_path_buf();

        // Build PYTHONPATH
        let python_path = format!(
            "{}:{}",
            site_packages.display(),
            vsg_parent.display()
        );
        std::env::set_var("PYTHONPATH", &python_path);

        debug!("PYTHONHOME={}", self.paths.python_dir.display());
        debug!("PYTHONPATH={}", python_path);

        // Initialize Python
        pyo3::prepare_freethreaded_python();

        self.initialized = true;
        info!("Python runtime initialized successfully");

        Ok(())
    }

    /// Load and return the AppConfig from vsg_core.config
    pub fn load_config(&self) -> Result<serde_json::Value, PythonRuntimeError> {
        if !self.initialized {
            return Err(PythonRuntimeError::NotInitialized);
        }

        Python::with_gil(|py| {
            // Import vsg_core.config
            let config_module = PyModule::import(py, "vsg_core.config")
                .map_err(|e| PythonRuntimeError::ImportError {
                    module: "vsg_core.config".to_string(),
                    error: e.to_string(),
                })?;

            // Get AppConfig class and instantiate
            let app_config_class = config_module.getattr("AppConfig")?;
            let config_instance = app_config_class.call0()?;

            // Convert to dict and then to JSON
            let as_dict_method = config_instance.getattr("as_dict")?;
            let config_dict = as_dict_method.call0()?;

            // Use Python's json module to serialize
            let json_module = PyModule::import(py, "json")?;
            let dumps = json_module.getattr("dumps")?;
            let json_str: String = dumps.call1((config_dict,))?.extract()?;

            serde_json::from_str(&json_str)
                .map_err(|e| PythonRuntimeError::ConfigError(e.to_string()))
        })
    }

    /// Save configuration back to vsg_core.config
    pub fn save_config(&self, config_json: &serde_json::Value) -> Result<(), PythonRuntimeError> {
        if !self.initialized {
            return Err(PythonRuntimeError::NotInitialized);
        }

        Python::with_gil(|py| {
            let config_module = PyModule::import(py, "vsg_core.config")
                .map_err(|e| PythonRuntimeError::ImportError {
                    module: "vsg_core.config".to_string(),
                    error: e.to_string(),
                })?;

            let app_config_class = config_module.getattr("AppConfig")?;
            let config_instance = app_config_class.call0()?;

            // Convert JSON to Python dict
            let json_module = PyModule::import(py, "json")?;
            let loads = json_module.getattr("loads")?;
            let json_str = serde_json::to_string(config_json)
                .map_err(|e| PythonRuntimeError::ConfigError(e.to_string()))?;
            let config_dict = loads.call1((json_str,))?;

            // Update config from dict
            let from_dict_method = config_instance.getattr("from_dict")?;
            from_dict_method.call1((config_dict,))?;

            // Save
            let save_method = config_instance.getattr("save")?;
            save_method.call0()?;

            Ok(())
        })
    }

    /// Run audio correlation analysis between two files
    pub fn analyze_audio_correlation(
        &self,
        reference_path: &Path,
        secondary_path: &Path,
    ) -> Result<AnalysisResult, PythonRuntimeError> {
        if !self.initialized {
            return Err(PythonRuntimeError::NotInitialized);
        }

        Python::with_gil(|py| {
            let analysis_module = PyModule::import(py, "vsg_core.analysis.audio_corr")
                .map_err(|e| PythonRuntimeError::ImportError {
                    module: "vsg_core.analysis.audio_corr".to_string(),
                    error: e.to_string(),
                })?;

            // Get the correlation function
            let correlate_fn = analysis_module.getattr("correlate_audio")?;

            // Call the function
            let result = correlate_fn
                .call1((
                    reference_path.to_str().unwrap(),
                    secondary_path.to_str().unwrap(),
                ))
                .map_err(|e| PythonRuntimeError::CallError {
                    function: "correlate_audio".to_string(),
                    error: e.to_string(),
                })?;

            // Extract result
            let delay_ms: f64 = result.getattr("delay_ms")?.extract()?;
            let confidence: f64 = result.getattr("confidence")?.extract()?;

            Ok(AnalysisResult {
                delay_ms,
                confidence,
            })
        })
    }

    /// Run a full job pipeline
    pub fn run_job(
        &self,
        job_config: &serde_json::Value,
        progress_callback: impl Fn(JobProgress) + Send + 'static,
    ) -> Result<JobResult, PythonRuntimeError> {
        if !self.initialized {
            return Err(PythonRuntimeError::NotInitialized);
        }

        Python::with_gil(|py| {
            let pipeline_module = PyModule::import(py, "vsg_core.pipeline")
                .map_err(|e| PythonRuntimeError::ImportError {
                    module: "vsg_core.pipeline".to_string(),
                    error: e.to_string(),
                })?;

            // Convert job config to Python dict
            let json_module = PyModule::import(py, "json")?;
            let loads = json_module.getattr("loads")?;
            let job_config_str = serde_json::to_string(job_config)
                .map_err(|e| PythonRuntimeError::ConfigError(e.to_string()))?;
            let job_dict = loads.call1((job_config_str,))?;

            // Get JobPipeline class
            let job_pipeline_class = pipeline_module.getattr("JobPipeline")?;

            // Create and run pipeline
            let pipeline = job_pipeline_class.call1((job_dict,))?;
            let run_method = pipeline.getattr("run")?;

            // Run the pipeline
            let result = run_method
                .call0()
                .map_err(|e| PythonRuntimeError::CallError {
                    function: "JobPipeline.run".to_string(),
                    error: e.to_string(),
                })?;

            // Extract results
            let success: bool = result.getattr("success")?.extract()?;
            let output_path: Option<String> = result
                .getattr("output_path")
                .ok()
                .and_then(|p| p.extract().ok());
            let error_message: Option<String> = result
                .getattr("error_message")
                .ok()
                .and_then(|m| m.extract().ok());

            Ok(JobResult {
                success,
                output_path,
                error_message,
            })
        })
    }

    /// Get probe information for a media file
    pub fn probe_file(&self, path: &Path) -> Result<MediaInfo, PythonRuntimeError> {
        if !self.initialized {
            return Err(PythonRuntimeError::NotInitialized);
        }

        Python::with_gil(|py| {
            // We'll use ffprobe via subprocess for now
            // Later this can be moved to a native Rust implementation
            let subprocess = PyModule::import(py, "subprocess")?;
            let json_module = PyModule::import(py, "json")?;

            let cmd = vec![
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path.to_str().unwrap(),
            ];

            let result = subprocess
                .getattr("run")?
                .call1((
                    cmd,
                    PyDict::new(py)
                        .set_item("capture_output", true)
                        .and_then(|_| Ok(PyDict::new(py)))?,
                ))
                .map_err(|e| PythonRuntimeError::CallError {
                    function: "ffprobe".to_string(),
                    error: e.to_string(),
                })?;

            let stdout = result.getattr("stdout")?;
            let stdout_str: String = stdout.call_method0("decode")?.extract()?;

            let probe_data = json_module.getattr("loads")?.call1((stdout_str,))?;

            // Parse streams
            let streams_list = probe_data.getattr("streams")?;
            let mut video_tracks = Vec::new();
            let mut audio_tracks = Vec::new();
            let mut subtitle_tracks = Vec::new();

            if let Ok(streams) = streams_list.downcast::<PyList>() {
                for stream in streams.iter() {
                    let codec_type: String =
                        stream.get_item("codec_type")?.extract()?;
                    let index: u32 = stream.get_item("index")?.extract()?;

                    match codec_type.as_str() {
                        "video" => video_tracks.push(index),
                        "audio" => audio_tracks.push(index),
                        "subtitle" => subtitle_tracks.push(index),
                        _ => {}
                    }
                }
            }

            // Get format info
            let format_info = probe_data.getattr("format")?;
            let duration: Option<f64> = format_info
                .get_item("duration")
                .ok()
                .and_then(|d| d.extract().ok());
            let filename: String = format_info.get_item("filename")?.extract()?;

            Ok(MediaInfo {
                path: PathBuf::from(filename),
                duration,
                video_tracks,
                audio_tracks,
                subtitle_tracks,
            })
        })
    }
}

/// Find the site-packages directory (handles version-specific paths)
fn find_site_packages(lib_dir: &Path) -> Option<PathBuf> {
    if let Ok(entries) = std::fs::read_dir(lib_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                let site_packages = path.join("site-packages");
                if site_packages.exists() {
                    return Some(site_packages);
                }
            }
        }
    }
    None
}

/// Result from audio correlation analysis
#[derive(Debug, Clone)]
pub struct AnalysisResult {
    pub delay_ms: f64,
    pub confidence: f64,
}

/// Progress updates during job execution
#[derive(Debug, Clone)]
pub enum JobProgress {
    Analyzing { percent: u8 },
    Extracting { percent: u8 },
    Processing { percent: u8 },
    Merging { percent: u8 },
    Done,
}

/// Result from running a job
#[derive(Debug, Clone)]
pub struct JobResult {
    pub success: bool,
    pub output_path: Option<String>,
    pub error_message: Option<String>,
}

/// Media file information from probing
#[derive(Debug, Clone)]
pub struct MediaInfo {
    pub path: PathBuf,
    pub duration: Option<f64>,
    pub video_tracks: Vec<u32>,
    pub audio_tracks: Vec<u32>,
    pub subtitle_tracks: Vec<u32>,
}
