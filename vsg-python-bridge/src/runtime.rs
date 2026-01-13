//! Python runtime wrapper using subprocess
//!
//! Calls existing vsg_core Python code via subprocess.
//! This approach avoids build-time Python version conflicts.

use std::path::{Path, PathBuf};
use std::process::Stdio;
use tokio::process::Command;
use tokio::io::{AsyncBufReadExt, BufReader};
use thiserror::Error;
use tracing::{info, debug, error};
use serde::{Deserialize, Serialize};

use crate::RuntimePaths;

#[derive(Error, Debug)]
pub enum PythonRuntimeError {
    #[error("Python not initialized")]
    NotInitialized,

    #[error("Python process failed: {0}")]
    ProcessError(String),

    #[error("Failed to parse Python output: {0}")]
    ParseError(String),

    #[error("Python script error: {0}")]
    ScriptError(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

/// Wrapper around the Python runtime using subprocess calls
pub struct PythonRuntime {
    paths: RuntimePaths,
    vsg_core_path: PathBuf,
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
        }
    }

    /// Check if the runtime is ready
    pub fn is_ready(&self) -> bool {
        self.paths.is_ready()
    }

    /// Run a Python script and return its JSON output
    async fn run_python_script(&self, script: &str) -> Result<String, PythonRuntimeError> {
        if !self.is_ready() {
            return Err(PythonRuntimeError::NotInitialized);
        }

        let vsg_parent = self
            .vsg_core_path
            .parent()
            .unwrap_or(&self.vsg_core_path);

        let mut cmd = Command::new(&self.paths.venv_python);
        cmd.arg("-c")
            .arg(script)
            .env("PYTHONPATH", vsg_parent)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        debug!("Running Python: {:?}", cmd);

        let output = cmd.output().await?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(PythonRuntimeError::ScriptError(stderr.to_string()));
        }

        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }

    /// Load and return the AppConfig from vsg_core.config
    pub async fn load_config(&self) -> Result<serde_json::Value, PythonRuntimeError> {
        let script = r#"
import json
from vsg_core.config import AppConfig
config = AppConfig()
print(json.dumps(config.as_dict()))
"#;

        let output = self.run_python_script(script).await?;
        serde_json::from_str(&output).map_err(|e| PythonRuntimeError::ParseError(e.to_string()))
    }

    /// Save configuration back to vsg_core.config
    pub async fn save_config(&self, config_json: &serde_json::Value) -> Result<(), PythonRuntimeError> {
        let config_str = serde_json::to_string(config_json)?;
        let script = format!(
            r#"
import json
from vsg_core.config import AppConfig
config = AppConfig()
data = json.loads('''{}''')
config.from_dict(data)
config.save()
print("ok")
"#,
            config_str.replace('\'', "\\'")
        );

        self.run_python_script(&script).await?;
        Ok(())
    }

    /// Run audio correlation analysis between two files
    pub async fn analyze_audio_correlation(
        &self,
        reference_path: &Path,
        secondary_path: &Path,
    ) -> Result<AnalysisResult, PythonRuntimeError> {
        let script = format!(
            r#"
import json
from vsg_core.analysis.audio_corr import correlate_audio
result = correlate_audio("{}", "{}")
print(json.dumps({{"delay_ms": result.delay_ms, "confidence": result.confidence}}))
"#,
            reference_path.display(),
            secondary_path.display()
        );

        let output = self.run_python_script(&script).await?;
        let result: AnalysisResultJson = serde_json::from_str(&output)?;

        Ok(AnalysisResult {
            delay_ms: result.delay_ms,
            confidence: result.confidence,
        })
    }

    /// Run a full job pipeline with progress streaming
    pub async fn run_job(
        &self,
        job_config: &serde_json::Value,
        mut progress_callback: impl FnMut(JobProgress),
    ) -> Result<JobResult, PythonRuntimeError> {
        if !self.is_ready() {
            return Err(PythonRuntimeError::NotInitialized);
        }

        let config_str = serde_json::to_string(job_config)?;
        let vsg_parent = self
            .vsg_core_path
            .parent()
            .unwrap_or(&self.vsg_core_path);

        // Create a Python script that streams progress
        let script = format!(
            r#"
import json
import sys
from vsg_core.pipeline import JobPipeline

def progress_callback(stage, percent, message):
    print(json.dumps({{"stage": stage, "percent": percent, "message": message}}), flush=True)

config = json.loads('''{}''')
pipeline = JobPipeline(config, progress_callback=progress_callback)
result = pipeline.run()
print(json.dumps({{"success": result.success, "output_path": str(result.output_path) if result.output_path else None, "error_message": result.error_message}}))
"#,
            config_str.replace('\'', "\\'")
        );

        let mut cmd = Command::new(&self.paths.venv_python);
        cmd.arg("-c")
            .arg(&script)
            .env("PYTHONPATH", vsg_parent)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        let mut child = cmd.spawn()?;

        // Stream stdout for progress
        let stdout = child.stdout.take().expect("Failed to capture stdout");
        let mut reader = BufReader::new(stdout).lines();

        let mut last_line = String::new();
        while let Some(line) = reader.next_line().await? {
            last_line = line.clone();

            // Try to parse as progress update
            if let Ok(progress) = serde_json::from_str::<ProgressUpdate>(&line) {
                let job_progress = match progress.stage.as_str() {
                    "analyzing" => JobProgress::Analyzing { percent: progress.percent },
                    "extracting" => JobProgress::Extracting { percent: progress.percent },
                    "processing" => JobProgress::Processing { percent: progress.percent },
                    "merging" => JobProgress::Merging { percent: progress.percent },
                    _ => JobProgress::Processing { percent: progress.percent },
                };
                progress_callback(job_progress);
            }
        }

        let status = child.wait().await?;
        progress_callback(JobProgress::Done);

        // Parse the final result from last line
        if !status.success() {
            return Err(PythonRuntimeError::ProcessError(format!(
                "Python process exited with status: {}",
                status
            )));
        }

        let result: JobResultJson = serde_json::from_str(&last_line)
            .map_err(|e| PythonRuntimeError::ParseError(format!("{}: {}", e, last_line)))?;

        Ok(JobResult {
            success: result.success,
            output_path: result.output_path,
            error_message: result.error_message,
        })
    }

    /// Get probe information for a media file using ffprobe
    pub async fn probe_file(&self, path: &Path) -> Result<MediaInfo, PythonRuntimeError> {
        // Use ffprobe directly - no need for Python here
        let output = Command::new("ffprobe")
            .args([
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                path.to_str().unwrap(),
            ])
            .output()
            .await?;

        if !output.status.success() {
            return Err(PythonRuntimeError::ProcessError(
                String::from_utf8_lossy(&output.stderr).to_string()
            ));
        }

        let probe_data: FFProbeOutput = serde_json::from_slice(&output.stdout)?;

        let mut video_tracks = Vec::new();
        let mut audio_tracks = Vec::new();
        let mut subtitle_tracks = Vec::new();

        for stream in &probe_data.streams {
            match stream.codec_type.as_str() {
                "video" => video_tracks.push(stream.index),
                "audio" => audio_tracks.push(stream.index),
                "subtitle" => subtitle_tracks.push(stream.index),
                _ => {}
            }
        }

        let duration = probe_data
            .format
            .duration
            .as_ref()
            .and_then(|d| d.parse::<f64>().ok());

        Ok(MediaInfo {
            path: PathBuf::from(&probe_data.format.filename),
            duration,
            video_tracks,
            audio_tracks,
            subtitle_tracks,
        })
    }
}

// JSON helper structs
#[derive(Deserialize)]
struct AnalysisResultJson {
    delay_ms: f64,
    confidence: f64,
}

#[derive(Deserialize)]
struct ProgressUpdate {
    stage: String,
    percent: u8,
    #[allow(dead_code)]
    message: String,
}

#[derive(Deserialize)]
struct JobResultJson {
    success: bool,
    output_path: Option<String>,
    error_message: Option<String>,
}

#[derive(Deserialize)]
struct FFProbeOutput {
    streams: Vec<FFProbeStream>,
    format: FFProbeFormat,
}

#[derive(Deserialize)]
struct FFProbeStream {
    index: u32,
    codec_type: String,
}

#[derive(Deserialize)]
struct FFProbeFormat {
    filename: String,
    duration: Option<String>,
}

/// Result from audio correlation analysis
#[derive(Debug, Clone, Serialize, Deserialize)]
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
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobResult {
    pub success: bool,
    pub output_path: Option<String>,
    pub error_message: Option<String>,
}

/// Media file information from probing
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MediaInfo {
    pub path: PathBuf,
    pub duration: Option<f64>,
    pub video_tracks: Vec<u32>,
    pub audio_tracks: Vec<u32>,
    pub subtitle_tracks: Vec<u32>,
}
