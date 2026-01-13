//! Python runtime bootstrapper
//!
//! Downloads and sets up an isolated Python environment using python-build-standalone.
//! This solves the "system Python updated and broke everything" problem.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::fs;
use std::io::{self, Write};
use thiserror::Error;
use tracing::{info, warn, debug};

/// Target Python version - 3.13.x (latest stable in 3.13 series)
const PYTHON_VERSION: &str = "3.13";
const PYTHON_BUILD_STANDALONE_RELEASE: &str = "20251120";

#[derive(Error, Debug)]
pub enum PythonBootstrapError {
    #[error("Unsupported platform: {0}")]
    UnsupportedPlatform(String),

    #[error("Failed to create directory {path}: {source}")]
    CreateDir { path: PathBuf, source: io::Error },

    #[error("Failed to download Python: {0}")]
    Download(String),

    #[error("Failed to extract Python archive: {0}")]
    Extract(String),

    #[error("Failed to create virtual environment: {0}")]
    CreateVenv(String),

    #[error("Failed to install dependencies: {0}")]
    InstallDeps(String),

    #[error("IO error: {0}")]
    Io(#[from] io::Error),

    #[error("Network error: {0}")]
    Network(#[from] reqwest::Error),
}

/// Paths to the isolated Python runtime
#[derive(Debug, Clone)]
pub struct RuntimePaths {
    /// Root directory for all runtime files (e.g., ~/.local/share/video-sync-gui/runtime)
    pub root: PathBuf,
    /// Path to the Python installation
    pub python_dir: PathBuf,
    /// Path to the Python executable
    pub python_exe: PathBuf,
    /// Path to the virtual environment
    pub venv_dir: PathBuf,
    /// Path to the venv Python executable
    pub venv_python: PathBuf,
    /// Path to pip in the venv
    pub venv_pip: PathBuf,
}

impl RuntimePaths {
    pub fn new(data_dir: &Path) -> Self {
        let root = data_dir.join("runtime");
        let python_dir = root.join("python");

        #[cfg(unix)]
        let python_exe = python_dir.join("bin").join("python3");
        #[cfg(windows)]
        let python_exe = python_dir.join("python.exe");

        let venv_dir = root.join("venv");

        #[cfg(unix)]
        let (venv_python, venv_pip) = (
            venv_dir.join("bin").join("python"),
            venv_dir.join("bin").join("pip"),
        );
        #[cfg(windows)]
        let (venv_python, venv_pip) = (
            venv_dir.join("Scripts").join("python.exe"),
            venv_dir.join("Scripts").join("pip.exe"),
        );

        Self {
            root,
            python_dir,
            python_exe,
            venv_dir,
            venv_python,
            venv_pip,
        }
    }

    /// Check if the runtime is fully set up
    pub fn is_ready(&self) -> bool {
        self.venv_python.exists() && self.venv_pip.exists()
    }
}

/// Ensure the Python runtime is available, downloading and setting it up if needed
pub async fn ensure_python_runtime(
    data_dir: &Path,
    requirements_path: &Path,
    progress_callback: impl Fn(BootstrapProgress),
) -> Result<RuntimePaths, PythonBootstrapError> {
    let paths = RuntimePaths::new(data_dir);

    if paths.is_ready() {
        info!("Python runtime already available at {:?}", paths.venv_python);
        progress_callback(BootstrapProgress::Ready);
        return Ok(paths);
    }

    info!("Setting up isolated Python runtime...");

    // Create directories
    fs::create_dir_all(&paths.root).map_err(|e| PythonBootstrapError::CreateDir {
        path: paths.root.clone(),
        source: e,
    })?;

    // Step 1: Download Python if needed
    if !paths.python_exe.exists() {
        progress_callback(BootstrapProgress::Downloading { percent: 0 });
        download_python(&paths, |p| {
            progress_callback(BootstrapProgress::Downloading { percent: p });
        })
        .await?;
    }

    // Step 2: Create venv if needed
    if !paths.venv_dir.exists() {
        progress_callback(BootstrapProgress::CreatingVenv);
        create_venv(&paths)?;
    }

    // Step 3: Install dependencies
    progress_callback(BootstrapProgress::InstallingDeps);
    install_dependencies(&paths, requirements_path)?;

    progress_callback(BootstrapProgress::Ready);
    info!("Python runtime ready at {:?}", paths.venv_python);

    Ok(paths)
}

/// Progress updates during bootstrap
#[derive(Debug, Clone)]
pub enum BootstrapProgress {
    Downloading { percent: u8 },
    Extracting,
    CreatingVenv,
    InstallingDeps,
    Ready,
}

/// Get the download URL for python-build-standalone
fn get_download_url() -> Result<String, PythonBootstrapError> {
    let (os, arch, ext) = get_platform_info()?;

    // Format: cpython-{version}+{release}-{arch}-{os}-{variant}-install_only.tar.gz
    // We use install_only which is simpler and smaller
    let filename = format!(
        "cpython-{version}+{release}-{arch}-{os}-gnu-install_only.tar.gz",
        version = PYTHON_VERSION,
        release = PYTHON_BUILD_STANDALONE_RELEASE,
        arch = arch,
        os = os,
    );

    Ok(format!(
        "https://github.com/astral-sh/python-build-standalone/releases/download/{}/{filename}",
        PYTHON_BUILD_STANDALONE_RELEASE
    ))
}

fn get_platform_info() -> Result<(&'static str, &'static str, &'static str), PythonBootstrapError> {
    let os = if cfg!(target_os = "linux") {
        "unknown-linux"
    } else if cfg!(target_os = "macos") {
        "apple-darwin"
    } else if cfg!(target_os = "windows") {
        "pc-windows-msvc"
    } else {
        return Err(PythonBootstrapError::UnsupportedPlatform(
            std::env::consts::OS.to_string(),
        ));
    };

    let arch = if cfg!(target_arch = "x86_64") {
        "x86_64"
    } else if cfg!(target_arch = "aarch64") {
        "aarch64"
    } else {
        return Err(PythonBootstrapError::UnsupportedPlatform(
            std::env::consts::ARCH.to_string(),
        ));
    };

    let ext = if cfg!(windows) { "zip" } else { "tar.gz" };

    Ok((os, arch, ext))
}

async fn download_python(
    paths: &RuntimePaths,
    progress: impl Fn(u8),
) -> Result<(), PythonBootstrapError> {
    let url = get_download_url()?;
    info!("Downloading Python from: {}", url);

    let client = reqwest::Client::new();
    let response = client.get(&url).send().await?;

    if !response.status().is_success() {
        return Err(PythonBootstrapError::Download(format!(
            "HTTP {}: {}",
            response.status(),
            url
        )));
    }

    let total_size = response.content_length().unwrap_or(0);
    let archive_path = paths.root.join("python.tar.gz");

    // Download to file
    let mut file = fs::File::create(&archive_path)?;
    let mut downloaded: u64 = 0;

    let mut stream = response.bytes_stream();
    use futures_util::StreamExt;

    while let Some(chunk) = stream.next().await {
        let chunk = chunk?;
        file.write_all(&chunk)?;
        downloaded += chunk.len() as u64;

        if total_size > 0 {
            let percent = ((downloaded as f64 / total_size as f64) * 100.0) as u8;
            progress(percent);
        }
    }

    // Extract
    info!("Extracting Python archive...");
    extract_tarball(&archive_path, &paths.root)?;

    // The archive extracts to a 'python' subdirectory
    // Rename if needed
    let extracted_dir = paths.root.join("python");
    if extracted_dir != paths.python_dir && extracted_dir.exists() {
        if paths.python_dir.exists() {
            fs::remove_dir_all(&paths.python_dir)?;
        }
        fs::rename(&extracted_dir, &paths.python_dir)?;
    }

    // Cleanup archive
    fs::remove_file(&archive_path).ok();

    Ok(())
}

fn extract_tarball(archive_path: &Path, dest: &Path) -> Result<(), PythonBootstrapError> {
    use flate2::read::GzDecoder;
    use tar::Archive;

    let file = fs::File::open(archive_path)?;
    let decoder = GzDecoder::new(file);
    let mut archive = Archive::new(decoder);

    archive
        .unpack(dest)
        .map_err(|e| PythonBootstrapError::Extract(e.to_string()))?;

    Ok(())
}

fn create_venv(paths: &RuntimePaths) -> Result<(), PythonBootstrapError> {
    info!("Creating virtual environment at {:?}", paths.venv_dir);

    let output = Command::new(&paths.python_exe)
        .args(["-m", "venv", paths.venv_dir.to_str().unwrap()])
        .output()
        .map_err(|e| PythonBootstrapError::CreateVenv(e.to_string()))?;

    if !output.status.success() {
        return Err(PythonBootstrapError::CreateVenv(
            String::from_utf8_lossy(&output.stderr).to_string(),
        ));
    }

    Ok(())
}

fn install_dependencies(
    paths: &RuntimePaths,
    requirements_path: &Path,
) -> Result<(), PythonBootstrapError> {
    info!("Installing dependencies from {:?}", requirements_path);

    // First upgrade pip
    let output = Command::new(&paths.venv_python)
        .args(["-m", "pip", "install", "--upgrade", "pip"])
        .output()
        .map_err(|e| PythonBootstrapError::InstallDeps(e.to_string()))?;

    if !output.status.success() {
        warn!(
            "pip upgrade failed (non-fatal): {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    // Install from requirements.txt
    let output = Command::new(&paths.venv_pip)
        .args([
            "install",
            "-r",
            requirements_path.to_str().unwrap(),
            "--no-warn-script-location",
        ])
        .output()
        .map_err(|e| PythonBootstrapError::InstallDeps(e.to_string()))?;

    if !output.status.success() {
        return Err(PythonBootstrapError::InstallDeps(
            String::from_utf8_lossy(&output.stderr).to_string(),
        ));
    }

    debug!(
        "pip install output: {}",
        String::from_utf8_lossy(&output.stdout)
    );

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_runtime_paths() {
        let paths = RuntimePaths::new(Path::new("/tmp/test"));
        assert_eq!(paths.root, PathBuf::from("/tmp/test/runtime"));
        assert!(paths.python_dir.starts_with(&paths.root));
        assert!(paths.venv_dir.starts_with(&paths.root));
    }

    #[test]
    fn test_platform_info() {
        let result = get_platform_info();
        assert!(result.is_ok());
    }
}
